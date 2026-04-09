"""GitHub enrichment helpers for robotics teams."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import requests

import config

GITHUB_API_BASE_URL = "https://api.github.com"


class GitHubEnricher:
    """Search GitHub organizations and collect contact signals."""

    def __init__(
        self,
        pat: str | None = None,
        base_url: str = GITHUB_API_BASE_URL,
        session: requests.Session | None = None,
        request_delay: float = 0.2,
        rate_limit_sleep: float = 60.0,
        timeout: float = 30.0,
    ) -> None:
        self.pat = config.GITHUB_PAT if pat is None else pat
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.request_delay = request_delay
        self.rate_limit_sleep = rate_limit_sleep
        self.timeout = timeout
        self.headers = {"Accept": "application/vnd.github+json"}
        if self.pat:
            self.headers["Authorization"] = f"Bearer {self.pat}"
        self._last_request_at: float | None = None

    def _sleep_between_requests(self) -> None:
        if self._last_request_at is None:
            return

        elapsed = time.monotonic() - self._last_request_at
        remaining = self.request_delay - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def _get_json(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any | None:
        url = f"{self.base_url}{path}"

        for attempt in range(2):
            try:
                self._sleep_between_requests()
                response = self.session.get(
                    url,
                    params=params,
                    headers=self.headers,
                    timeout=self.timeout,
                )
                self._last_request_at = time.monotonic()
            except requests.RequestException:
                return None

            if response.status_code == 403 and attempt == 0:
                time.sleep(self.rate_limit_sleep)
                continue

            if response.status_code >= 400:
                return None

            try:
                return response.json()
            except ValueError:
                return None

        return None

    def _is_relevant_org(
        self,
        login: str,
        team_number: str,
        team_name: str,
        school_name: str,
    ) -> bool:
        login_lower = login.lower()
        team_number_lower = team_number.lower()
        team_number_digits = team_number_lower.removeprefix("frc")

        name_tokens = [
            token.lower()
            for token in f"{team_name} {school_name}".split()
            if len(token) > 2
        ]

        if team_number_lower and team_number_lower in login_lower:
            return True
        if team_number_digits and team_number_digits in login_lower:
            return True
        return any(token in login_lower for token in name_tokens)

    def _pick_org_login(
        self,
        team_number: str,
        team_name: str,
        school_name: str,
    ) -> tuple[str | None, str | None]:
        queries = [
            f"{team_number} type:org",
            f"{team_name} robotics type:org",
        ]

        first_fallback: dict[str, Any] | None = None
        for query in queries:
            payload = self._get_json("/search/users", params={"q": query})
            if not isinstance(payload, dict):
                continue

            items = payload.get("items") or []
            if not items:
                continue

            if first_fallback is None:
                first_fallback = items[0]

            for item in items:
                login = item.get("login")
                if not login:
                    continue
                if self._is_relevant_org(login, team_number, team_name, school_name):
                    return login, item.get("html_url")

        if first_fallback is None:
            return None, None
        return first_fallback.get("login"), first_fallback.get("html_url")

    def _extract_year(self, timestamp: str | None) -> int | None:
        if not timestamp:
            return None

        try:
            return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).year
        except ValueError:
            return None

    def enrich(
        self,
        team_number: str,
        team_name: str,
        school_name: str,
    ) -> dict[str, Any]:
        """Search GitHub for an org and collect email and recency signals."""

        result = {
            "github_org_url": None,
            "emails": [],
            "github_last_commit_year": None,
        }

        org_login, org_url = self._pick_org_login(team_number, team_name, school_name)
        if not org_login:
            return result

        result["github_org_url"] = org_url or f"https://github.com/{org_login}"

        repos = self._get_json(
            f"/orgs/{org_login}/repos",
            params={"sort": "updated", "per_page": 10},
        )
        if not isinstance(repos, list):
            return result

        email_set: set[str] = set()
        ordered_emails: list[str] = []
        latest_year: int | None = None

        for repo in repos:
            repo_name = repo.get("name")
            if not repo_name:
                continue

            pushed_year = self._extract_year(repo.get("pushed_at"))
            if pushed_year is not None:
                latest_year = (
                    pushed_year
                    if latest_year is None
                    else max(latest_year, pushed_year)
                )

            contributors = self._get_json(
                f"/repos/{org_login}/{repo_name}/contributors",
                params={"per_page": 5},
            )
            if not isinstance(contributors, list):
                continue

            for contributor in contributors:
                username = contributor.get("login")
                if not username:
                    continue

                user = self._get_json(f"/users/{username}")
                if not isinstance(user, dict):
                    continue

                email = user.get("email")
                if not email:
                    continue
                if "noreply" in email.lower():
                    continue
                if email in email_set:
                    continue

                email_set.add(email)
                ordered_emails.append(email)

        result["emails"] = ordered_emails
        result["github_last_commit_year"] = latest_year
        return result
