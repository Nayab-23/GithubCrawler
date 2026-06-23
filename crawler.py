import csv
import json
import os
import re
import sys
import threading
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from html import unescape
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

load_dotenv()

USER_AGENT = os.environ.get(
    "CRAWLER_USER_AGENT",
    "Mozilla/5.0 (compatible; VerificationDocCrawler/1.0; +https://example.invalid)",
).strip()
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT_SECONDS", "30"))
SEARCH_DELAY_SECONDS = float(os.environ.get("SEARCH_DELAY_SECONDS", "1.0"))
MAX_WEB_RESULTS_PER_QUERY = int(os.environ.get("MAX_WEB_RESULTS_PER_QUERY", "8"))
MAX_LOCAL_RESULTS_PER_QUERY = int(os.environ.get("MAX_LOCAL_RESULTS_PER_QUERY", "12"))
MAX_LOCAL_FILE_BYTES = int(os.environ.get("MAX_LOCAL_FILE_BYTES", str(2 * 1024 * 1024)))
MIN_PRIORITY_SCORE = int(os.environ.get("MIN_PRIORITY_SCORE", "6"))
LOCAL_DOC_DIRS = [
    part.strip()
    for part in os.environ.get("LOCAL_DOC_DIRS", "").split(",")
    if part.strip()
]

HEADERS = {"User-Agent": USER_AGENT}
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crawl.log")
_log_lock = threading.Lock()
_rate_lock = threading.Lock()
_next_call_at = 0.0

CSV_FIELDS = [
    "query",
    "source_type",
    "document_type",
    "title",
    "source_name",
    "source_domain",
    "url",
    "local_path",
    "file_type",
    "matched_keywords",
    "snippet",
    "published_hint",
    "priority_score",
    "priority",
    "query_family",
    "legacy_key",
    "repo",
    "repo_name",
    "org",
    "org_type",
    "contributor_count",
    "language",
    "stars",
    "username",
    "display_name",
    "email",
    "company",
    "bio",
    "location",
    "github_profile",
    "linkedin",
    "twitter",
    "blog",
    "commit_message",
    "commit_url",
    "commit_date",
]

TEXT_EXTENSIONS = {
    ".sv",
    ".svh",
    ".v",
    ".vh",
    ".sva",
    ".txt",
    ".md",
    ".rst",
    ".csv",
    ".json",
    ".yaml",
    ".yml",
    ".xml",
    ".html",
    ".htm",
    ".log",
    ".rpt",
}
SCAN_EXTENSIONS = TEXT_EXTENSIONS | {".pdf", ".doc", ".docx", ".ppt", ".pptx"}

DOCUMENT_RULES = [
    ("ieee_systemverilog", (r"\bieee\b", r"\b1800\b", r"\bsystemverilog\b")),
    ("sva_tutorial", (r"\bsva\b", r"\bassertion", r"\btutorial|\bguide|\btraining")),
    ("internal_rulebook", (r"\brulebook\b", r"\bguideline\b|\bstyle guide\b|\bcoding standard\b")),
    ("protocol_spec", (r"\bprotocol\b", r"\bspec\b|\bspecification\b|\bstandard\b")),
    ("design_spec", (r"\bdesign\b", r"\bspec\b|\bspecification\b|\barchitecture\b")),
    ("assertion_example", (r"\bassertion", r"\bproperty\b|\bsequence\b|\bchecker\b")),
    ("formal_log", (r"\bformal\b", r"\blog\b|\bproof\b|\bcounterexample\b")),
    ("hil_correction", (r"\bhil\b|\bhardware in the loop\b", r"\bfix\b|\bcorrection\b|\bpatch\b")),
    ("rca_report", (r"\brca\b|\broot cause\b", r"\breport\b|\banalysis\b|\bpostmortem\b")),
    ("coverage_report", (r"\bcoverage\b", r"\breport\b|\bclosure\b")),
    ("uvm_reference", (r"\buvm\b", r"\bguide\b|\breference\b|\btutorial\b")),
    ("verification_plan", (r"\bverification\b", r"\bplan\b|\bstrategy\b")),
    ("errata", (r"\berrata\b|\bwaiver\b",)),
]

QUERY_FAMILIES = {
    "ieee_systemverilog": ("ieee", "1800", "systemverilog"),
    "sva_tutorial": ("sva", "assertion", "property", "sequence"),
    "protocol_spec": ("protocol", "spec", "specification", "interface"),
    "design_spec": ("design", "architecture", "microarchitecture", "block"),
    "assertion_example": ("assertion", "checker", "property", "prior generated assertions"),
    "formal_log": ("formal", "proof", "counterexample", "jasper", "vc formal"),
    "hil_correction": ("hil", "hardware in the loop", "correction", "patch"),
    "rca_report": ("rca", "root cause", "postmortem", "failure analysis"),
}

SEARCH_PRESETS = [
    {"source_name": "general-web", "site": None},
    {"source_name": "ieee", "site": "ieeexplore.ieee.org"},
    {"source_name": "verification-academy", "site": "verificationacademy.com"},
    {"source_name": "accellera", "site": "accellera.org"},
    {"source_name": "github", "site": "github.com"},
    {"source_name": "pdf-index", "site": None, "filetype": "pdf"},
]

STOPWORDS = {
    "and",
    "the",
    "for",
    "with",
    "pdf",
    "guide",
    "best",
    "practices",
    "report",
    "tutorial",
    "spec",
    "specification",
}


def _ts() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def log_line(message: str) -> None:
    line = f"[{_ts()}] {message}"
    print(line, flush=True)
    with _log_lock:
        with open(LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def rate_limited_get(url: str, params: dict[str, str] | None = None) -> requests.Response:
    global _next_call_at
    with _rate_lock:
        now = time.monotonic()
        fire_at = max(now, _next_call_at)
        _next_call_at = fire_at + SEARCH_DELAY_SECONDS
    wait = fire_at - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    return requests.get(url, headers=HEADERS, params=params, timeout=REQUEST_TIMEOUT)


def text_to_words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_+\-/.#]+", (text or "").lower())


def matched_keywords(text: str, query: str) -> list[str]:
    haystack = f"{text} {query}".lower()
    words = []
    for token in text_to_words(query):
        if len(token) >= 3 and token in haystack and token not in words:
            words.append(token)
    return words[:8]


def query_terms(query: str) -> list[str]:
    return [token for token in text_to_words(query) if len(token) >= 3 and token not in STOPWORDS]


def is_relevant_result(query: str, title: str, snippet: str, link: str, site: str | None) -> bool:
    text = f"{title} {snippet} {link}".lower()
    terms = query_terms(query)
    hits = sum(1 for token in terms if token in text)
    if site and site not in source_domain_from_url(link):
        return False
    if "systemverilog" in query.lower() and "systemverilog" not in text and "sva" not in text:
        return False
    if "formal" in query.lower() and "formal" not in text and "counterexample" not in text and "proof" not in text:
        return False
    return hits >= 2


def classify_query(query: str) -> str:
    lowered = query.lower()
    for family, terms in QUERY_FAMILIES.items():
        if any(term in lowered for term in terms):
            return family
    return "verification_misc"


def classify_document(text: str, domain: str, file_type: str) -> str:
    lowered = f"{text} {domain} {file_type}".lower()
    for doc_type, patterns in DOCUMENT_RULES:
        if all(re.search(pattern, lowered) for pattern in patterns):
            return doc_type
    if "ieeexplore.ieee.org" in domain and "systemverilog" in lowered:
        return "ieee_systemverilog"
    if file_type in {"sv", "svh", "sva"} and re.search(r"\bassert", lowered):
        return "assertion_example"
    if file_type in {"log", "rpt"} and "formal" in lowered:
        return "formal_log"
    return "verification_misc"


def normalize_title(raw: str, fallback: str) -> str:
    title = re.sub(r"\s+", " ", unescape(raw or "")).strip()
    return title or fallback


def file_type_from_name(path_or_url: str) -> str:
    parsed = urlparse(path_or_url)
    candidate = parsed.path if parsed.scheme else path_or_url
    suffix = Path(candidate).suffix.lower().lstrip(".")
    return suffix or "html"


def source_domain_from_url(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower()
    except Exception:
        return ""


def score_document(result: dict[str, str]) -> int:
    score = 0
    doc_type = result.get("document_type", "")
    file_type = result.get("file_type", "")
    domain = result.get("source_domain", "")
    keyword_count = len((result.get("matched_keywords") or "").split(", ")) if result.get("matched_keywords") else 0

    doc_type_weights = {
        "ieee_systemverilog": 5,
        "protocol_spec": 5,
        "design_spec": 4,
        "formal_log": 4,
        "assertion_example": 4,
        "sva_tutorial": 3,
        "internal_rulebook": 3,
        "hil_correction": 3,
        "rca_report": 3,
        "coverage_report": 2,
        "verification_plan": 2,
    }
    score += doc_type_weights.get(doc_type, 1)

    if domain in {"ieeexplore.ieee.org", "standards.ieee.org"}:
        score += 4
    elif domain in {"verificationacademy.com", "accellera.org", "github.com"}:
        score += 2

    if file_type in {"pdf", "sv", "svh", "sva", "log", "rpt"}:
        score += 2
    if result.get("source_type") == "local_file":
        score += 3

    score += min(keyword_count, 4)
    return score


def priority_label(score: int) -> str:
    if score >= 11:
        return "P1"
    if score >= 7:
        return "P2"
    return "P3"


def write_snapshot(rows: Iterable[dict[str, str]], output_path: str) -> None:
    parent = os.path.dirname(output_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in CSV_FIELDS})


def to_row(
    *,
    query: str,
    source_type: str,
    title: str,
    source_name: str,
    source_domain: str,
    url: str = "",
    local_path: str = "",
    file_type: str = "",
    snippet: str = "",
    published_hint: str = "",
) -> dict[str, str]:
    doc_type = classify_document(f"{title} {snippet}", source_domain, file_type)
    keywords = matched_keywords(f"{title} {snippet} {local_path} {url}", query)
    family = classify_query(query)
    legacy_key = url or local_path or f"{source_name}:{title}"
    row = {
        "query": query,
        "source_type": source_type,
        "document_type": doc_type,
        "title": title,
        "source_name": source_name,
        "source_domain": source_domain,
        "url": url,
        "local_path": local_path,
        "file_type": file_type,
        "matched_keywords": ", ".join(keywords),
        "snippet": snippet.strip(),
        "published_hint": published_hint,
        "query_family": family,
        "legacy_key": legacy_key,
        "repo": source_domain or source_name,
        "repo_name": title,
        "org": source_name,
        "org_type": source_type,
        "contributor_count": "",
        "language": doc_type,
        "stars": "",
        "username": source_name,
        "display_name": title,
        "email": "",
        "company": source_domain,
        "bio": snippet[:280],
        "location": local_path,
        "github_profile": url if source_domain == "github.com" else "",
        "linkedin": "",
        "twitter": "",
        "blog": local_path,
        "commit_message": snippet[:200] or title[:200],
        "commit_url": url,
        "commit_date": published_hint or _ts(),
    }
    score = score_document(row)
    row["priority_score"] = str(score)
    row["priority"] = priority_label(score)
    return row


def search_bing_rss(query: str, source_name: str, site: str | None, filetype: str | None) -> list[dict[str, str]]:
    q = query
    if site:
        q = f"{q} site:{site}"
    if filetype:
        q = f"{q} filetype:{filetype}"
    url = "https://www.bing.com/search"
    params = {"q": q, "format": "rss"}
    try:
        resp = rate_limited_get(url, params=params)
    except requests.RequestException as exc:
        log_line(f"web_search_failed source={source_name} query={json.dumps(query)} error={exc}")
        return []
    if not resp.ok:
        log_line(
            f"web_search_failed source={source_name} query={json.dumps(query)} status={resp.status_code}"
        )
        return []

    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError as exc:
        log_line(f"web_search_parse_failed source={source_name} query={json.dumps(query)} error={exc}")
        return []

    rows = []
    for item in root.findall("./channel/item"):
        title = normalize_title(item.findtext("title", default=""), "Untitled result")
        link = (item.findtext("link", default="") or "").strip()
        snippet = normalize_title(item.findtext("description", default=""), "")
        if not link:
            continue
        if not is_relevant_result(query, title, snippet, link, site):
            continue
        domain = source_domain_from_url(link)
        rows.append(
            to_row(
                query=query,
                source_type="web_result",
                title=title,
                source_name=source_name,
                source_domain=domain,
                url=link,
                file_type=file_type_from_name(link),
                snippet=snippet,
            )
        )
        if len(rows) >= MAX_WEB_RESULTS_PER_QUERY:
            break
    log_line(f'web_search source="{source_name}" query="{query}" results={len(rows)}')
    return rows


def read_local_text(path: Path) -> str:
    if path.suffix.lower() not in TEXT_EXTENSIONS:
        return ""
    if path.stat().st_size > MAX_LOCAL_FILE_BYTES:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def search_local_docs(query: str) -> list[dict[str, str]]:
    if not LOCAL_DOC_DIRS:
        return []

    query_tokens = [token for token in text_to_words(query) if len(token) >= 3]
    rows: list[dict[str, str]] = []

    for root_dir in LOCAL_DOC_DIRS:
        root = Path(root_dir).expanduser()
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in SCAN_EXTENSIONS:
                continue

            file_type = file_type_from_name(str(path))
            haystack_parts = [str(path.name), str(path)]
            body = read_local_text(path)
            if body:
                haystack_parts.append(body[:20000])
            haystack = " ".join(haystack_parts).lower()
            hits = [token for token in query_tokens if token in haystack]
            if not hits:
                continue

            snippet = ""
            if body:
                for line in body.splitlines():
                    candidate = line.strip()
                    if candidate and any(token in candidate.lower() for token in hits):
                        snippet = candidate[:240]
                        break
            rows.append(
                to_row(
                    query=query,
                    source_type="local_file",
                    title=path.name,
                    source_name="local-docs",
                    source_domain="local",
                    local_path=str(path),
                    file_type=file_type,
                    snippet=snippet,
                    published_hint=datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                )
            )

    rows.sort(key=lambda row: int(row["priority_score"]), reverse=True)
    limited = rows[:MAX_LOCAL_RESULTS_PER_QUERY]
    log_line(f'local_search query="{query}" results={len(limited)} roots={len(LOCAL_DOC_DIRS)}')
    return limited


def dedupe_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict[str, str]] = []
    for row in rows:
        key = (
            (row.get("query") or "").strip(),
            (row.get("url") or "").strip(),
            (row.get("local_path") or "").strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def crawl_query(query: str) -> list[dict[str, str]]:
    rows = []
    for preset in SEARCH_PRESETS:
        rows.extend(
            search_bing_rss(
                query=query,
                source_name=preset["source_name"],
                site=preset.get("site"),
                filetype=preset.get("filetype"),
            )
        )
    rows.extend(search_local_docs(query))
    rows = dedupe_rows(rows)
    rows = [row for row in rows if int(row["priority_score"]) >= MIN_PRIORITY_SCORE]
    rows.sort(key=lambda row: int(row["priority_score"]), reverse=True)
    return rows


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: python crawler.py '<json_query_array>' <output_csv>", file=sys.stderr)
        sys.exit(1)

    try:
        queries = json.loads(sys.argv[1])
    except json.JSONDecodeError as exc:
        print(f"ERROR: Could not parse queries JSON: {exc}", file=sys.stderr)
        sys.exit(1)

    output_path = sys.argv[2]
    print("=== Verification Document Crawler starting ===")
    print(f"  Queries        : {len(queries)}")
    print(f"  Output         : {output_path}")
    print(f"  Local doc dirs : {', '.join(LOCAL_DOC_DIRS) if LOCAL_DOC_DIRS else '(none)'}")
    print(f"  Log            : {LOG_PATH}")
    print()

    all_rows: list[dict[str, str]] = []
    for query in queries:
        rows = crawl_query(query)
        all_rows.extend(rows)
        unique_rows = dedupe_rows(all_rows)
        write_snapshot(unique_rows, output_path)
        log_line(f'query_complete query="{query}" rows={len(rows)} cumulative={len(unique_rows)}')

    final_rows = dedupe_rows(all_rows)
    final_rows.sort(key=lambda row: int(row["priority_score"]), reverse=True)
    write_snapshot(final_rows, output_path)

    print(f"[done] wrote {len(final_rows)} results to {output_path}")
    log_line(f"CRAWL COMPLETE total_rows={len(final_rows)}")


if __name__ == "__main__":
    if "--test" in sys.argv:
        sys.argv = [
            sys.argv[0],
            json.dumps(["IEEE 1800 SystemVerilog SVA tutorial", "formal verification counterexample log"]),
            "/tmp/test_output.csv",
        ]
    main()
