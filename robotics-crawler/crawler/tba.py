"""Client for working with The Blue Alliance API."""

from __future__ import annotations

import time
from typing import Any

import requests
from tqdm import tqdm

import config

TBA_BASE_URL = "https://www.thebluealliance.com/api/v3"


class TBAClient:
    """Thin client for loading and filtering team data from TBA."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = TBA_BASE_URL,
        session: requests.Session | None = None,
        request_delay: float = 0.1,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = config.TBA_API_KEY if api_key is None else api_key
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.request_delay = request_delay
        self.timeout = timeout
        self.headers = {"X-TBA-Auth-Key": self.api_key}
        self._last_request_at: float | None = None
        self._target_countries = set(config.TARGET_COUNTRIES)

    def _sleep_between_requests(self) -> None:
        if self._last_request_at is None:
            return

        elapsed = time.monotonic() - self._last_request_at
        remaining = self.request_delay - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def _get_json(self, path: str) -> Any | None:
        url = f"{self.base_url}{path}"

        for attempt in range(2):
            try:
                self._sleep_between_requests()
                response = self.session.get(
                    url,
                    headers=self.headers,
                    timeout=self.timeout,
                )
                self._last_request_at = time.monotonic()
            except requests.RequestException as exc:
                tqdm.write(f"TBA request failed for {path}: {exc}")
                return None

            if response.status_code == 429 and attempt == 0:
                retry_after = response.headers.get("Retry-After")
                retry_delay = self.request_delay
                if retry_after:
                    try:
                        retry_delay = max(float(retry_after), self.request_delay)
                    except ValueError:
                        retry_delay = max(1.0, self.request_delay)
                else:
                    retry_delay = max(1.0, self.request_delay)
                tqdm.write(f"TBA rate limited on {path}, retrying once.")
                time.sleep(retry_delay)
                continue

            if response.status_code >= 400:
                tqdm.write(
                    f"TBA request failed for {path}: "
                    f"HTTP {response.status_code}"
                )
                return None

            try:
                return response.json()
            except ValueError as exc:
                tqdm.write(f"TBA returned invalid JSON for {path}: {exc}")
                return None

        tqdm.write(f"TBA request failed after retry for {path}.")
        return None

    def fetch_all_teams(self) -> list[dict[str, Any]]:
        """Fetch teams from TBA, then keep only recent active teams in target countries."""

        country_filtered_teams: list[dict[str, Any]] = []
        page_num = 0

        with tqdm(desc="Fetching TBA pages", unit="page") as page_bar:
            while True:
                teams = self._get_json(f"/teams/{page_num}/simple")
                page_bar.update(1)

                if teams is None:
                    break
                if not teams:
                    break

                for team in teams:
                    if team.get("country") not in self._target_countries:
                        continue

                    team_number = team.get("team_number")
                    if team_number is None:
                        continue

                    country_filtered_teams.append(
                        {
                            "team_number": f"frc{team_number}",
                            "nickname": team.get("nickname"),
                            "school_name": team.get("school_name"),
                            "city": team.get("city"),
                            "state_prov": team.get("state_prov"),
                            "country": team.get("country"),
                            "website": team.get("website"),
                        }
                    )
                page_num += 1

        active_teams: list[dict[str, Any]] = []
        with tqdm(
            country_filtered_teams,
            desc="Checking TBA activity",
            unit="team",
        ) as team_bar:
            for team in team_bar:
                last_active_year = self.get_team_years_participated(team["team_number"])
                if last_active_year is None:
                    continue
                if last_active_year < config.MIN_ACTIVE_YEAR:
                    continue

                team_with_activity = dict(team)
                team_with_activity["last_active_year"] = last_active_year
                active_teams.append(team_with_activity)

        return active_teams

    def get_team_years_participated(self, team_key: str) -> int | None:
        """Return the most recent participation year for a team."""

        years = self._get_json(f"/team/{team_key}/years_participated")
        if not years:
            return None

        try:
            return max(int(year) for year in years)
        except (TypeError, ValueError):
            tqdm.write(f"TBA returned invalid years for {team_key}: {years}")
            return None

    def is_active_since(self, team_key: str, min_year: int) -> bool:
        """Return whether the team has been active on or after min_year."""

        last_active_year = self.get_team_years_participated(team_key)
        return last_active_year is not None and last_active_year >= min_year
