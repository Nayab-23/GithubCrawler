"""SQLite helpers for robotics crawler data."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

TABLE_NAME = "teams"

TABLE_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_number TEXT UNIQUE,
    team_name TEXT,
    school_name TEXT,
    city TEXT,
    state_province TEXT,
    country TEXT,
    website TEXT,
    github_org_url TEXT,
    emails TEXT,
    mentor_names TEXT,
    social_links TEXT,
    last_active_year INTEGER,
    github_last_commit_year INTEGER,
    priority TEXT,
    notes TEXT,
    raw_tba_data TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

TEAM_COLUMNS = [
    "team_number",
    "team_name",
    "school_name",
    "city",
    "state_province",
    "country",
    "website",
    "github_org_url",
    "emails",
    "mentor_names",
    "social_links",
    "last_active_year",
    "github_last_commit_year",
    "priority",
    "notes",
    "raw_tba_data",
]


def _prepare_db_path(db_path: str | Path) -> Path:
    resolved = Path(db_path).expanduser()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def _connect(db_path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(_prepare_db_path(db_path))
    connection.row_factory = sqlite3.Row
    return connection


def _normalize_csv_field(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value if item not in (None, ""))
    return str(value)


def _normalize_json_field(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _normalize_int_field(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _normalize_team_payload(team_dict: dict[str, Any]) -> dict[str, Any]:
    if not team_dict.get("team_number"):
        raise ValueError("team_dict must include a non-empty 'team_number'")

    payload = {column: team_dict[column] for column in TEAM_COLUMNS if column in team_dict}

    if "emails" in payload:
        payload["emails"] = _normalize_csv_field(payload["emails"])
    if "mentor_names" in payload:
        payload["mentor_names"] = _normalize_csv_field(payload["mentor_names"])
    if "social_links" in payload:
        payload["social_links"] = _normalize_json_field(payload["social_links"])
    if "raw_tba_data" in payload:
        payload["raw_tba_data"] = _normalize_json_field(payload["raw_tba_data"])
    if "last_active_year" in payload:
        payload["last_active_year"] = _normalize_int_field(payload["last_active_year"])
    if "github_last_commit_year" in payload:
        payload["github_last_commit_year"] = _normalize_int_field(
            payload["github_last_commit_year"]
        )

    payload["team_number"] = str(team_dict["team_number"])
    return payload


def init_db(db_path: str | Path) -> None:
    """Create the teams table if it does not already exist."""

    with _connect(db_path) as connection:
        connection.execute(TABLE_SCHEMA)
        connection.commit()


def upsert_team(db_path: str | Path, team_dict: dict[str, Any]) -> None:
    """Insert or update a team record keyed by team_number."""

    normalized_updates = _normalize_team_payload(team_dict)
    init_db(db_path)

    with _connect(db_path) as connection:
        existing_row = connection.execute(
            f"SELECT * FROM {TABLE_NAME} WHERE team_number = ?",
            (normalized_updates["team_number"],),
        ).fetchone()

    payload = {column: None for column in TEAM_COLUMNS}
    if existing_row is not None:
        for column in TEAM_COLUMNS:
            payload[column] = existing_row[column]
    payload.update(normalized_updates)

    insert_columns = ", ".join(TEAM_COLUMNS)
    placeholders = ", ".join(f":{column}" for column in TEAM_COLUMNS)
    update_clause = ", ".join(
        f"{column} = excluded.{column}"
        for column in TEAM_COLUMNS
        if column != "team_number"
    )

    query = f"""
    INSERT INTO {TABLE_NAME} ({insert_columns})
    VALUES ({placeholders})
    ON CONFLICT(team_number) DO UPDATE SET
        {update_clause},
        updated_at = CURRENT_TIMESTAMP
    """

    with _connect(db_path) as connection:
        connection.execute(query, payload)
        connection.commit()


def get_all_teams(db_path: str | Path) -> list[dict[str, Any]]:
    """Return all team rows as dictionaries."""

    init_db(db_path)
    query = f"SELECT * FROM {TABLE_NAME} ORDER BY team_number"

    with _connect(db_path) as connection:
        rows = connection.execute(query).fetchall()
        return [dict(row) for row in rows]


def get_stats(db_path: str | Path) -> dict[str, int]:
    """Return aggregate stats for teams and contact coverage."""

    init_db(db_path)
    query = f"""
    SELECT
        COUNT(*) AS total,
        SUM(CASE WHEN priority = 'P1' THEN 1 ELSE 0 END) AS p1_count,
        SUM(CASE WHEN priority = 'P2' THEN 1 ELSE 0 END) AS p2_count,
        SUM(CASE WHEN priority = 'P3' THEN 1 ELSE 0 END) AS p3_count,
        SUM(
            CASE
                WHEN emails IS NOT NULL AND TRIM(emails) != '' THEN 1
                ELSE 0
            END
        ) AS emails_found_count
    FROM {TABLE_NAME}
    """

    with _connect(db_path) as connection:
        row = connection.execute(query).fetchone()
        stats = dict(row) if row is not None else {}

    return {
        "total": int(stats.get("total") or 0),
        "p1_count": int(stats.get("p1_count") or 0),
        "p2_count": int(stats.get("p2_count") or 0),
        "p3_count": int(stats.get("p3_count") or 0),
        "emails_found_count": int(stats.get("emails_found_count") or 0),
    }
