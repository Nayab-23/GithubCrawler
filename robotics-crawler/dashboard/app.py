"""Flask dashboard application."""

from __future__ import annotations

import csv
import io
import json
from typing import Any
from urllib.parse import urlparse

from flask import Flask, Response, jsonify, render_template

from config import DASHBOARD_PORT, DB_PATH
from db.models import get_all_teams, get_stats

app = Flask(__name__)

PRIORITY_ORDER = {"P1": 0, "P2": 1, "P3": 2}


def _split_csv(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple | set):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(value).strip()] if str(value).strip() else []


def _parse_json_field(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _team_number_display(team_number: Any) -> str:
    text = str(team_number or "").strip()
    if text.lower().startswith("frc"):
        return text[3:]
    return text


def _clean_external_url(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"}:
        return ""
    return text


def _location_label(team: dict[str, Any]) -> str:
    city = str(team.get("city") or "").strip()
    state = str(team.get("state_province") or "").strip()

    if city and state:
        return f"{city} / {state}"
    return city or state or ""


def _serialize_team(team: dict[str, Any]) -> dict[str, Any]:
    emails = _split_csv(team.get("emails"))
    mentor_names = _split_csv(team.get("mentor_names"))

    serialized = {
        "id": team.get("id"),
        "team_number": str(team.get("team_number") or ""),
        "team_number_display": _team_number_display(team.get("team_number")),
        "team_name": team.get("team_name") or "",
        "school_name": team.get("school_name") or "",
        "city": team.get("city") or "",
        "state_province": team.get("state_province") or "",
        "city_state": _location_label(team),
        "country": team.get("country") or "",
        "website": _clean_external_url(team.get("website")),
        "github_org_url": _clean_external_url(team.get("github_org_url")),
        "emails": emails,
        "emails_count": len(emails),
        "mentor_names": mentor_names,
        "social_links": _parse_json_field(team.get("social_links")),
        "last_active_year": team.get("last_active_year"),
        "github_last_commit_year": team.get("github_last_commit_year"),
        "priority": team.get("priority") or "P3",
        "notes": team.get("notes") or "",
        "created_at": team.get("created_at"),
        "updated_at": team.get("updated_at"),
    }
    return serialized


def _team_sort_key(team: dict[str, Any]) -> tuple[Any, ...]:
    number_display = team.get("team_number_display") or ""
    try:
        numeric_team_number = int(number_display)
    except (TypeError, ValueError):
        numeric_team_number = 10**9

    return (
        PRIORITY_ORDER.get(team.get("priority"), 99),
        str(team.get("country") or ""),
        numeric_team_number,
        str(team.get("team_name") or ""),
    )


def load_dashboard_teams() -> list[dict[str, Any]]:
    teams = [_serialize_team(team) for team in get_all_teams(DB_PATH)]
    return sorted(teams, key=_team_sort_key)


def load_dashboard_stats() -> dict[str, int]:
    stats = get_stats(DB_PATH)
    return {
        "total": int(stats.get("total") or 0),
        "P1": int(stats.get("p1_count") or 0),
        "P2": int(stats.get("p2_count") or 0),
        "P3": int(stats.get("p3_count") or 0),
        "emails_found": int(stats.get("emails_found_count") or 0),
    }


@app.get("/")
def index() -> str:
    return render_template(
        "index.html",
        teams=load_dashboard_teams(),
        stats=load_dashboard_stats(),
        refresh_seconds=60,
    )


@app.get("/api/teams")
def api_teams() -> Response:
    return jsonify(load_dashboard_teams())


@app.get("/api/stats")
def api_stats() -> Response:
    return jsonify(load_dashboard_stats())


@app.post("/api/export")
def export_csv() -> Response:
    teams = load_dashboard_teams()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "priority",
            "team_number",
            "team_name",
            "school_name",
            "city",
            "state_province",
            "country",
            "emails",
            "github_org_url",
            "website",
            "last_active_year",
            "github_last_commit_year",
            "notes",
        ]
    )

    for team in teams:
        writer.writerow(
            [
                team.get("priority") or "",
                team.get("team_number") or "",
                team.get("team_name") or "",
                team.get("school_name") or "",
                team.get("city") or "",
                team.get("state_province") or "",
                team.get("country") or "",
                ", ".join(team.get("emails") or []),
                team.get("github_org_url") or "",
                team.get("website") or "",
                team.get("last_active_year") or "",
                team.get("github_last_commit_year") or "",
                team.get("notes") or "",
            ]
        )

    response = Response(output.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = (
        "attachment; filename=robotics_teams_export.csv"
    )
    return response


def run() -> None:
    app.run(host="0.0.0.0", port=DASHBOARD_PORT, debug=False)


if __name__ == "__main__":
    run()
