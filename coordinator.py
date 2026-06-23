import os
import sys
import json
import time
import threading
import subprocess
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def require_env(key):
    val = os.environ.get(key, "").strip()
    if not val:
        print(f"ERROR: {key} environment variable is not set. Exiting.", file=sys.stderr)
        sys.exit(1)
    return val


PC_IPS        = [ip.strip() for ip in require_env("PC_IPS").split(",") if ip.strip()]
PC_USER       = os.environ.get("PC_USER", "student").strip()
QUERIES_FILE  = os.environ.get("QUERIES_FILE", "./queries.txt").strip()
RESULTS_DIR   = os.environ.get("RESULTS_DIR",  "./results").strip()
OUTPUT_FILE   = os.environ.get("OUTPUT_FILE",  "./final_leads.csv").strip()
LOCAL_DOC_DIRS = os.environ.get("LOCAL_DOC_DIRS", "").strip()

CRAWLER_LOCAL  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crawler.py")
CRAWLER_REMOTE = "/tmp/crawler.py"
REMOTE_CSV     = "/tmp/results.csv"

POLL_INTERVAL  = 60        # seconds between completion checks
TIMEOUT        = 4 * 3600  # 4 hours

SSH_OPTS = [
    "-o", "StrictHostKeyChecking=no",
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=15",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ts():
    return datetime.now().strftime("%H:%M:%S")


def log(msg):
    print(f"[{ts()}] {msg}", flush=True)


def ssh_cmd(ip, remote_command):
    return ["ssh"] + SSH_OPTS + [f"{PC_USER}@{ip}", remote_command]


def scp_to(local, ip, remote):
    return ["scp"] + SSH_OPTS + [local, f"{PC_USER}@{ip}:{remote}"]


def scp_from(ip, remote, local):
    return ["scp"] + SSH_OPTS + [f"{PC_USER}@{ip}:{remote}", local]


def run(cmd, capture=False):
    """Run a subprocess; return (returncode, stdout, stderr)."""
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        text=True,
    )
    return result.returncode, result.stdout or "", result.stderr or ""


def count_csv_rows(path):
    """Return number of data rows (excluding header) in a CSV file."""
    try:
        with open(path, encoding="utf-8") as f:
            return max(sum(1 for _ in f) - 1, 0)
    except OSError:
        return 0


# ---------------------------------------------------------------------------
# Query loading and distribution
# ---------------------------------------------------------------------------

def load_queries():
    try:
        with open(QUERIES_FILE, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError as exc:
        log(f"ERROR: cannot read {QUERIES_FILE}: {exc}")
        sys.exit(1)

    queries = [
        line.strip()
        for line in lines
        if line.strip() and not line.strip().startswith("#")
    ]
    if not queries:
        log(f"ERROR: no queries found in {QUERIES_FILE}")
        sys.exit(1)
    return queries


def split_queries(queries, n):
    """Split queries into n roughly-equal chunks."""
    chunks = [[] for _ in range(n)]
    for i, q in enumerate(queries):
        chunks[i % n].append(q)
    return chunks


# ---------------------------------------------------------------------------
# Per-PC worker
# ---------------------------------------------------------------------------

def run_pc(ip, queries, results_dir, status):
    """
    Full lifecycle for one PC:
      1. SCP crawler.py
      2. Launch SSH crawl in background (non-blocking subprocess)
      3. Poll until done or timeout
      4. SCP results back
      5. Validate
    Updates the shared `status` dict under key `ip`.
    """
    local_csv = os.path.join(results_dir, f"results_{ip}.csv")
    queries_json = json.dumps(queries)
    local_doc_dirs_escaped = LOCAL_DOC_DIRS.replace("'", "'\"'\"'")

    def update(state, detail=""):
        status[ip] = {"state": state, "detail": detail}
        log(f"[{ip}] {state}{': ' + detail if detail else ''}")

    update("starting")

    # -- 1. SCP crawler.py ------------------------------------------------
    rc, _, err = run(scp_to(CRAWLER_LOCAL, ip, CRAWLER_REMOTE))
    if rc != 0:
        update("FAILED", f"scp crawler.py failed (rc={rc}): {err.strip()}")
        return

    update("crawler uploaded")

    # -- 2. Launch SSH crawl ----------------------------------------------
    # Escape any single quotes inside the JSON so the shell single-quote
    # wrapper is never broken (replace ' with '"'"').
    queries_json_escaped = queries_json.replace("'", "'\"'\"'")
    env_prefix = f"LOCAL_DOC_DIRS='{local_doc_dirs_escaped}' " if LOCAL_DOC_DIRS else ""
    remote_cmd = f"{env_prefix}python3 {CRAWLER_REMOTE} '{queries_json_escaped}' {REMOTE_CSV}"
    proc = subprocess.Popen(
        ssh_cmd(ip, remote_cmd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    update("crawling", f"{len(queries)} queries")

    # -- 3. Poll until done or timeout ------------------------------------
    start = time.monotonic()
    while True:
        ret = proc.poll()
        if ret is not None:
            break
        elapsed = time.monotonic() - start
        if elapsed > TIMEOUT:
            proc.terminate()
            update("TIMEOUT", f"exceeded {TIMEOUT//3600}h limit — process killed")
            return
        log(f"[{ip}] still running … ({int(elapsed // 60)}m elapsed)")
        time.sleep(POLL_INTERVAL)

    stdout, stderr = proc.communicate()
    if ret != 0:
        detail = stderr.strip().splitlines()[-1] if stderr.strip() else f"rc={ret}"
        update("FAILED", f"crawl exited {ret}: {detail}")
        return

    update("crawl finished, collecting results")

    # -- 4. SCP results back ----------------------------------------------
    rc, _, err = run(scp_from(ip, REMOTE_CSV, local_csv))
    if rc != 0:
        update("FAILED", f"scp results back failed (rc={rc}): {err.strip()}")
        return

    # -- 5. Validate ------------------------------------------------------
    rows = count_csv_rows(local_csv)
    if rows < 1:
        update("WARNING", f"collected CSV has 0 data rows — {local_csv}")
    else:
        update("DONE", f"{rows} leads written to {local_csv}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)

    log("=== Verification Document Crawler Coordinator ===")
    log(f"  PCs         : {', '.join(PC_IPS)}")
    log(f"  SSH user    : {PC_USER}")
    log(f"  Queries     : {QUERIES_FILE}")
    log(f"  Results dir : {RESULTS_DIR}")
    log(f"  Output      : {OUTPUT_FILE}")
    print()

    # Load and distribute queries
    all_queries = load_queries()
    log(f"Loaded {len(all_queries)} queries from {QUERIES_FILE}")

    chunks = split_queries(all_queries, len(PC_IPS))
    for ip, chunk in zip(PC_IPS, chunks):
        log(f"  {ip} → {len(chunk)} queries")
    print()

    # Shared status dict, updated by threads (GIL protects simple dict writes)
    status = {ip: {"state": "pending", "detail": ""} for ip in PC_IPS}

    def worker(ip, queries):
        run_pc(ip, queries, RESULTS_DIR, status)

    # Launch all PC workers in parallel
    threads = []
    for ip, chunk in zip(PC_IPS, chunks):
        t = threading.Thread(target=worker, args=(ip, chunk), daemon=True)
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    # Final status report
    print()
    log("=== All PC workers finished ===")
    failed = []
    warnings = []
    for ip in PC_IPS:
        s = status[ip]
        state = s["state"]
        detail = s["detail"]
        marker = "OK" if state == "DONE" else state
        log(f"  {ip:>15}  [{marker}]  {detail}")
        if state == "FAILED" or state == "TIMEOUT":
            failed.append(ip)
        elif state == "WARNING":
            warnings.append(ip)

    if warnings:
        log(f"Warning: {len(warnings)} PC(s) returned empty results: {', '.join(warnings)}")
    if failed:
        log(f"Warning: {len(failed)} PC(s) failed: {', '.join(failed)}. Proceeding with available results.")

    print()

    # Merge results
    log("Running merge_results.py …")
    merge_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "merge_results.py")
    rc = subprocess.call([sys.executable, merge_script, RESULTS_DIR, OUTPUT_FILE])
    if rc != 0:
        log(f"ERROR: merge_results.py exited with code {rc}")
        sys.exit(rc)

    log(f"=== Coordinator complete. Final leads: {OUTPUT_FILE} ===")


if __name__ == "__main__":
    main()
