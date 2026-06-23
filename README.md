# Verification Document Crawler

This repo crawls verification-related material instead of GitHub developer leads.

Primary target categories:

- IEEE SystemVerilog references
- SVA tutorials and rulebooks
- Protocol specifications
- Design and microarchitecture specs
- Prior generated assertions and checker examples
- Formal logs, proofs, and counterexamples
- HIL correction notes
- RCA and postmortem reports
- Related verification plans, coverage reports, UVM references, and errata

The crawler combines:

- web discovery through Bing RSS search
- domain-focused queries for `ieeexplore.ieee.org`, `verificationacademy.com`, `accellera.org`, `github.com`, and PDF-heavy results
- optional local document indexing through `LOCAL_DOC_DIRS` for internal specs, logs, rulebooks, and reports

## How It Works

For each query in `queries.txt`, the crawler:

1. searches the web across the configured source presets
2. scans local directories from `LOCAL_DOC_DIRS`
3. classifies each hit into a document type
4. scores and filters results
5. writes incremental CSV snapshots

The main output is `final_leads.csv`, which is now a ranked document inventory rather than a contact-lead file.

## Raspberry Pi Setup

Recommended target:

- Raspberry Pi 4 or newer
- Python 3.10+
- always-on network connection
- enough local storage for logs and CSV history

Clone and set up the repo:

```bash
git clone https://github.com/Nayab-23/GithubCrawler.git
cd GithubCrawler
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Configuration

Minimal `.env` for local continuous crawling:

```bash
QUERIES_FILE=./queries.txt
RESULTS_DIR=./results
OUTPUT_FILE=./final_leads.csv
LOCAL_DOC_DIRS=/home/nayab/specs,/home/nayab/logs,/home/nayab/assertions,/home/nayab/rca
MAX_WEB_RESULTS_PER_QUERY=8
MAX_LOCAL_RESULTS_PER_QUERY=12
SEARCH_DELAY_SECONDS=1.0
MIN_PRIORITY_SCORE=6
POLL_INTERVAL_SECONDS=60
STALL_TIMEOUT_SECONDS=600
SLEEP_BETWEEN_SECONDS=3600
```

Key variables:

- `LOCAL_DOC_DIRS`: comma-separated directories containing internal specs, rulebooks, logs, assertions, RCAs, and similar artifacts
- `SEARCH_DELAY_SECONDS`: delay between external web requests
- `MIN_PRIORITY_SCORE`: low-quality result cutoff
- `SLEEP_BETWEEN_SECONDS`: delay between full crawl cycles when using `supervisor.py`

`LOCAL_DOC_DIRS` is the most important setting for internal verification material.

## Running Once

Run a single local crawl:

```bash
./run_local.sh
```

Run the multi-machine coordinator flow:

```bash
./run_crawl.sh
```

The coordinator still splits `queries.txt` across machines, uploads `crawler.py`, runs it remotely, and merges the returned CSV files.

## Running Continuously

For Raspberry Pi use, the intended continuous entrypoint is:

```bash
. .venv/bin/activate
python supervisor.py
```

Or install it as a systemd service:

```bash
chmod +x install_service.sh
./install_service.sh
```

Useful commands after installation:

```bash
sudo systemctl status githubcrawler
sudo systemctl restart githubcrawler
tail -f supervisor.log
tail -f crawl.log
```

## Should It Run 24/7?

Yes, it can run continuously on a Raspberry Pi, but it should not scrape aggressively in a tight loop.

Recommended approach:

- run `supervisor.py` continuously
- set `SLEEP_BETWEEN_SECONDS` to something sensible like `1800` or `3600`
- keep `SEARCH_DELAY_SECONDS` at `1.0` or higher
- let local document crawling do most of the heavy lifting

Practical guidance:

- `24/7` is fine for periodic refresh cycles
- `24/7 full-speed nonstop` is not a good idea
- external search quality will not improve much from hammering the web every minute
- local/internal document discovery benefits more from stable repeated indexing than from high request volume

Start with hourly cycles:

```bash
SLEEP_BETWEEN_SECONDS=3600
```

If you later need fresher results, reduce to:

```bash
SLEEP_BETWEEN_SECONDS=900
```

I would not recommend a zero-sleep infinite loop on a Pi for this workload.

## Output

The CSV contains document-centric fields such as:

- `document_type`
- `title`
- `source_name`
- `source_domain`
- `url`
- `local_path`
- `file_type`
- `matched_keywords`
- `snippet`
- `published_hint`
- `priority_score`
- `priority`

Higher scores are given to strong matches such as IEEE references, protocol specs, design specs, formal logs, assertion examples, and local internal documents.

## Current Limitations

- IEEE documents may resolve only to metadata or abstract pages when the full content is paywalled.
- Local content extraction is strongest for text files such as `.sv`, `.svh`, `.sva`, `.md`, `.txt`, `.log`, and `.rpt`.
- Binary formats such as `.pdf`, `.docx`, and `.pptx` are currently indexed mainly by path and filename unless you add a text extraction step.
- External web search is best-effort and should be treated as a discovery aid, not as a guaranteed structured corpus feed.
