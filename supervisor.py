"""
supervisor.py — long-running watchdog for the verification document crawler.

Lifecycle:
  1. Launch run_local.sh as a subprocess.
  2. Every 60 s check crawl.log — if the last line has not changed in
     10 minutes, treat the crawler as stalled: kill it and restart.
  3. After a clean exit, merge /tmp/results_local_run.csv into
     results_local.csv (deduplicating on query+url+local_path).
  4. Sleep for SLEEP_BETWEEN seconds, then go back to step 1.

Run with:
    .venv/bin/python3 supervisor.py &
"""

import csv
import os
import subprocess
import sys
import time
from datetime import datetime

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR       = os.path.dirname(os.path.abspath(__file__))
RUN_LOCAL_SH     = os.path.join(SCRIPT_DIR, "run_local.sh")
CRAWL_LOG        = os.path.join(SCRIPT_DIR, "crawl.log")
SUPERVISOR_LOG   = os.path.join(SCRIPT_DIR, "supervisor.log")
RESULTS_FINAL    = os.path.join(SCRIPT_DIR, "results_local.csv")
RESULTS_TMP      = "/tmp/results_local_run.csv"

# ---------------------------------------------------------------------------
# Tuning
# ---------------------------------------------------------------------------

STALL_TIMEOUT    = int(os.environ.get("STALL_TIMEOUT_SECONDS", 10 * 60))
POLL_INTERVAL    = int(os.environ.get("POLL_INTERVAL_SECONDS", 60))
SLEEP_BETWEEN    = int(os.environ.get("SLEEP_BETWEEN_SECONDS", 0))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _ts():
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def slog(msg):
    """Write a timestamped line to supervisor.log and stdout."""
    line = f"[{_ts()}] {msg}"
    print(line, flush=True)
    with open(SUPERVISOR_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ---------------------------------------------------------------------------
# crawl.log tail reader
# ---------------------------------------------------------------------------

def _last_log_line():
    """Return the last non-empty line of crawl.log, or '' if absent/empty."""
    try:
        with open(CRAWL_LOG, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if size == 0:
                return ""
            # Walk back up to 4 KB to find the last line
            chunk = min(size, 4096)
            f.seek(-chunk, 2)
            data = f.read(chunk).decode("utf-8", errors="replace")
        lines = [l for l in data.splitlines() if l.strip()]
        return lines[-1] if lines else ""
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# Result merging
# ---------------------------------------------------------------------------

def _load_seen_keys(path):
    """Return set of (query, url, local_path) tuples from an existing CSV."""
    seen = set()
    if not os.path.exists(path):
        return seen
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                q = row.get("query", "").strip()
                u = row.get("url", "").strip()
                p = row.get("local_path", "").strip()
                if q or u or p:
                    seen.add((q, u, p))
    except Exception as exc:
        slog(f"[warn] could not read existing results: {exc}")
    return seen


def merge_results(log_noop=False):
    """
    Append rows from RESULTS_TMP into RESULTS_FINAL, skipping any
    (query, url, local_path) tuple already present in RESULTS_FINAL.
    Returns number of new rows written.
    """
    if not os.path.exists(RESULTS_TMP):
        if log_noop:
            slog("[merge] /tmp/results_local_run.csv not found — nothing to merge")
        return 0

    seen = _load_seen_keys(RESULTS_FINAL)
    new_rows = []
    fieldnames = []

    try:
        with open(RESULTS_TMP, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            for row in reader:
                key = (
                    row.get("query", "").strip(),
                    row.get("url", "").strip(),
                    row.get("local_path", "").strip(),
                )
                if key not in seen:
                    new_rows.append(row)
                    seen.add(key)
    except Exception as exc:
        slog(f"[merge] error reading tmp results: {exc}")
        return 0

    if not new_rows:
        if log_noop:
            slog("[merge] 0 new leads (all already in results_local.csv)")
        return 0

    write_header = not os.path.exists(RESULTS_FINAL)
    try:
        with open(RESULTS_FINAL, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            if write_header:
                writer.writeheader()
            writer.writerows(new_rows)
    except Exception as exc:
        slog(f"[merge] error writing results_local.csv: {exc}")
        return 0

    slog(f"[merge] appended {len(new_rows)} new leads → {RESULTS_FINAL}")
    return len(new_rows)


# ---------------------------------------------------------------------------
# Crawler launch + watchdog
# ---------------------------------------------------------------------------

def launch_crawler():
    """Start run_local.sh and return the Popen object."""
    slog(f"[supervisor] launching run_local.sh")
    proc = subprocess.Popen(
        ["bash", RUN_LOCAL_SH],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    slog(f"[supervisor] pid={proc.pid}")
    return proc


def watch(proc):
    """
    Monitor proc until it exits or stalls.

    Returns:
        "done"      — proc exited with code 0
        "failed"    — proc exited with non-zero code
        "restarted" — stall detected; proc was killed
    """
    last_line    = _last_log_line()
    last_changed = time.monotonic()

    while True:
        time.sleep(POLL_INTERVAL)

        # Drain stdout so the pipe buffer doesn't fill and block the child
        if proc.stdout:
            try:
                while True:
                    line = proc.stdout.readline()
                    if not line:
                        break
            except Exception:
                pass

        # Publish any new leads discovered so far even before the run ends.
        merge_results(log_noop=False)

        ret = proc.poll()
        if ret is not None:
            if ret == 0:
                slog(f"[supervisor] pid={proc.pid} exited cleanly (rc=0)")
                return "done"
            else:
                slog(f"[supervisor] pid={proc.pid} exited with rc={ret}")
                return "failed"

        # Stall detection
        current_line = _last_log_line()
        if current_line != last_line:
            last_line    = current_line
            last_changed = time.monotonic()
        else:
            stalled_for = time.monotonic() - last_changed
            if stalled_for >= STALL_TIMEOUT:
                slog(
                    f"[supervisor] STALL detected — crawl.log unchanged for "
                    f"{int(stalled_for)}s. Killing pid={proc.pid} and restarting."
                )
                try:
                    proc.kill()
                    proc.wait(timeout=10)
                except Exception as exc:
                    slog(f"[supervisor] error killing pid={proc.pid}: {exc}")
                return "restarted"
            else:
                slog(
                    f"[supervisor] pid={proc.pid} still running — "
                    f"log unchanged for {int(stalled_for)}s / {STALL_TIMEOUT}s"
                )


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_once():
    """Launch, watch (restarting on stall), then merge results."""
    attempt = 0
    while True:
        attempt += 1
        if attempt > 1:
            slog(f"[supervisor] restart attempt #{attempt}")

        proc   = launch_crawler()
        result = watch(proc)

        if result == "done":
            slog("[supervisor] run complete — merging results")
            merge_results()
            return
        elif result == "failed":
            slog("[supervisor] run failed — merging whatever results exist")
            merge_results()
            return
        elif result == "restarted":
            # Loop back and launch again
            slog("[supervisor] restarting crawler after stall …")
            continue


def main():
    slog("=" * 60)
    slog("[supervisor] supervisor.py starting")
    slog(f"[supervisor] run_local.sh : {RUN_LOCAL_SH}")
    slog(f"[supervisor] results      : {RESULTS_FINAL}")
    slog(f"[supervisor] crawl log    : {CRAWL_LOG}")
    slog(f"[supervisor] stall timeout: {STALL_TIMEOUT}s")
    slog(f"[supervisor] sleep between: {SLEEP_BETWEEN}s")
    slog("=" * 60)

    cycle = 0
    while True:
        cycle += 1
        slog(f"[supervisor] === cycle {cycle} starting ===")
        run_once()
        slog(f"[supervisor] === cycle {cycle} done — sleeping {SLEEP_BETWEEN}s ===")
        if SLEEP_BETWEEN > 0:
            time.sleep(SLEEP_BETWEEN)


if __name__ == "__main__":
    main()
