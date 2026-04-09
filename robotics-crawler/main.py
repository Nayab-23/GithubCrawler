"""Entry point for the robotics crawler pipeline."""

from __future__ import annotations

import argparse
from typing import Any

from tqdm import tqdm

from config import DB_PATH
from crawler.github_enricher import GitHubEnricher
from crawler.scorer import generate_notes, score_team
from crawler.tba import TBAClient
from crawler.website_scraper import WebsiteScraper
from db.models import get_all_teams, init_db, upsert_team


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple | set):
        return list(value)
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [value]


def _dedupe_strings(values: list[Any]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()

    for value in values:
        text = str(value).strip()
        if not text:
            continue
        lowered = text.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(text)

    return deduped


def _build_team_record(team: dict[str, Any]) -> dict[str, Any]:
    record = dict(team)
    record["team_name"] = record.get("team_name") or record.get("nickname")
    record["state_province"] = (
        record.get("state_province") or record.get("state_prov") or ""
    )
    return record


def _merge_team_data(
    team: dict[str, Any],
    github_data: dict[str, Any],
    website_data: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(team)
    merged.update(github_data)

    if website_data.get("mentor_names"):
        merged["mentor_names"] = website_data["mentor_names"]

    if website_data.get("social_links"):
        merged["social_links"] = website_data["social_links"]

    merged["emails"] = _dedupe_strings(
        _as_list(github_data.get("emails")) + _as_list(website_data.get("emails"))
    )
    return merged


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the robotics crawler pipeline.")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip teams already present in the database.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    init_db(DB_PATH)

    resume_team_numbers: set[str] = set()
    if args.resume:
        resume_team_numbers = {
            str(team["team_number"])
            for team in get_all_teams(DB_PATH)
            if team.get("team_number")
        }

    tba_client = TBAClient()
    github_enricher = GitHubEnricher()
    website_scraper = WebsiteScraper()

    teams = tba_client.fetch_all_teams()
    if args.resume:
        teams = [
            team
            for team in teams
            if str(team.get("team_number") or "") not in resume_team_numbers
        ]

    processed_count = 0
    p1_count = 0
    p2_count = 0
    p3_count = 0
    total_emails_found = 0

    for team in tqdm(teams, desc="Processing teams", unit="team"):
        base_team = dict(team)
        base_team["raw_tba_data"] = dict(team)

        try:
            github_data = github_enricher.enrich(
                team_number=base_team["team_number"],
                team_name=base_team.get("nickname") or "",
                school_name=base_team.get("school_name") or "",
            )
        except Exception:
            github_data = {
                "github_org_url": None,
                "emails": [],
                "github_last_commit_year": None,
            }

        website_data: dict[str, Any] = {}
        if base_team.get("website"):
            try:
                website_data = website_scraper.scrape(base_team["website"])
            except Exception:
                website_data = {}

        merged_team = _merge_team_data(base_team, github_data, website_data)
        merged_team = _build_team_record(merged_team)

        merged_team["priority"] = score_team(merged_team)
        merged_team["notes"] = generate_notes(merged_team)

        upsert_team(DB_PATH, merged_team)

        processed_count += 1
        total_emails_found += len(_as_list(merged_team.get("emails")))

        if merged_team["priority"] == "P1":
            p1_count += 1
        elif merged_team["priority"] == "P2":
            p2_count += 1
        else:
            p3_count += 1

    print(f"Total processed: {processed_count}")
    print(f"P1 count: {p1_count}")
    print(f"P2 count: {p2_count}")
    print(f"P3 count: {p3_count}")
    print(f"Total emails found: {total_emails_found}")


if __name__ == "__main__":
    main()
