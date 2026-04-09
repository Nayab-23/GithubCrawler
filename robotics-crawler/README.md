# robotics-crawler

`robotics-crawler` collects FRC team leads from The Blue Alliance, enriches them with GitHub and website signals, stores them in SQLite, and exposes a live dashboard for review.

## Setup

1. Clone the repository and enter the project directory:

   ```bash
   git clone <your-repo-url>
   cd GithubCrawler/robotics-crawler
   ```

2. Create and activate a virtual environment:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Copy the example environment file:

   ```bash
   cp .env.example .env
   ```

5. Edit `.env` and fill in:

   - `TBA_API_KEY`
   - `GITHUB_PAT`

## Run The Crawler

Run a fresh crawl:

```bash
python main.py
```

Resume a crawl and skip teams already stored in the database:

```bash
python main.py --resume
```

The crawler writes data into `robotics_leads.db`.

## Run The Dashboard

Start the Flask dashboard:

```bash
python dashboard/app.py
```

Open:

```text
http://localhost:5002
```

The dashboard reads from the same SQLite database and auto-refreshes every 60 seconds.

## Run Both At Once

Two terminal tabs:

1. In tab 1:

   ```bash
   python main.py --resume
   ```

2. In tab 2:

   ```bash
   python dashboard/app.py
   ```

Simple `tmux` example from the `robotics-crawler/` directory:

```bash
tmux new-session -d -s robotics 'cd /Users/nayab/Downloads/Hackathons/GithubCrawler/robotics-crawler && python main.py --resume' \; split-window -h 'cd /Users/nayab/Downloads/Hackathons/GithubCrawler/robotics-crawler && python dashboard/app.py' \; attach -t robotics
```

## Scoring

- `P1`: has a GitHub org, has at least one email, and is active recently on GitHub or in TBA.
- `P2`: has a website and at least one email, but does not meet `P1`.
- `P3`: everything else, usually just a TBA entry with no strong contact signal.

Current logic in code:

- `P1`: `github_org_url` and `len(emails) > 0` and (`github_last_commit_year >= 2023` or `last_active_year >= 2023`)
- `P2`: `website` and `len(emails) > 0`
- `P3`: all remaining teams

## Data Sources

- The Blue Alliance: team roster, location, website, recent participation
- GitHub: org discovery, contributor lookups, public email collection, recent repo activity
- Team websites: contact emails, mentor or coach names, social links
