"""Priority scoring helpers for robotics leads."""

from __future__ import annotations

from typing import Any


def _as_email_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple | set):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(value).strip()] if str(value).strip() else []


def _as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _team_label(team_dict: dict[str, Any]) -> str | None:
    team_number = str(team_dict.get("team_number") or "").strip()
    if team_number:
        normalized = team_number[3:] if team_number.lower().startswith("frc") else team_number
        return f"FRC Team {normalized}"

    return team_dict.get("team_name") or team_dict.get("nickname")


def _location_label(team_dict: dict[str, Any]) -> str | None:
    city = str(team_dict.get("city") or "").strip()
    state = str(
        team_dict.get("state_prov") or team_dict.get("state_province") or ""
    ).strip()
    country = str(team_dict.get("country") or "").strip()

    if city and state:
        return f"{city} {state}"
    if city and country:
        return f"{city} {country}"
    if city:
        return city
    if state and country:
        return f"{state} {country}"
    return state or country or None


def score_team(team_dict: dict[str, Any]) -> str:
    """Classify a team as P1, P2, or P3."""

    emails = _as_email_list(team_dict.get("emails"))
    github_last_commit_year = _as_int(team_dict.get("github_last_commit_year"))
    last_active_year = _as_int(team_dict.get("last_active_year"))
    github_org_url = team_dict.get("github_org_url")
    website = team_dict.get("website")

    if (
        github_org_url
        and len(emails) > 0
        and (
            (github_last_commit_year is not None and github_last_commit_year >= 2023)
            or (last_active_year is not None and last_active_year >= 2023)
        )
    ):
        return "P1"

    if website and len(emails) > 0:
        return "P2"

    return "P3"


def generate_notes(team_dict: dict[str, Any]) -> str:
    """Generate a short human-readable summary for a team lead."""

    emails = _as_email_list(team_dict.get("emails"))
    github_last_commit_year = _as_int(team_dict.get("github_last_commit_year"))
    last_active_year = _as_int(team_dict.get("last_active_year"))

    parts: list[str] = []

    if github_last_commit_year is not None:
        parts.append(f"GitHub active {github_last_commit_year}")
    elif last_active_year is not None:
        parts.append(f"TBA active {last_active_year}")

    parts.append(f"{len(emails)} emails found")

    team_label = _team_label(team_dict)
    if team_label:
        parts.append(team_label)

    location_label = _location_label(team_dict)
    if location_label:
        parts.append(location_label)

    return " | ".join(parts)
