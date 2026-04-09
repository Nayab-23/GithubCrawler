"""Website scraping helpers."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from bs4 import FeatureNotFound

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
MENTOR_KEYWORDS = ("mentor", "coach", "advisor", "lead")
SOCIAL_DOMAINS = {
    "twitter": "twitter.com",
    "instagram": "instagram.com",
    "youtube": "youtube.com",
    "facebook": "facebook.com",
    "linkedin": "linkedin.com",
}
NAME_RE = re.compile(r"\b[A-Z][a-zA-Z'.-]+(?:\s+[A-Z][a-zA-Z'.-]+){1,3}\b")
NAMES_AFTER_ROLE_RE = re.compile(
    r"(?:mentor|coach|advisor|lead)(?:\s+\w+){0,2}\s*[:\-]\s*"
    r"([A-Z][a-zA-Z'.-]+(?:\s+[A-Z][a-zA-Z'.-]+){1,3}"
    r"(?:\s*(?:,|/|&|and)\s*[A-Z][a-zA-Z'.-]+(?:\s+[A-Z][a-zA-Z'.-]+){1,3})*)",
    re.IGNORECASE,
)
NAMES_BEFORE_ROLE_RE = re.compile(
    r"([A-Z][a-zA-Z'.-]+(?:\s+[A-Z][a-zA-Z'.-]+){1,3})\s*"
    r"(?:[-,(]\s*)?(?:lead\s+)?(?:mentor|coach|advisor)\b",
    re.IGNORECASE,
)
CHROME_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class WebsiteScraper:
    """Scrape team websites for contact signals."""

    def __init__(
        self,
        session: requests.Session | None = None,
        timeout: float = 8.0,
    ) -> None:
        self.session = session or requests.Session()
        self.timeout = timeout
        self.headers = {"User-Agent": CHROME_USER_AGENT}

    def _normalize_url(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme:
            return url
        return f"https://{url.lstrip('/')}"

    def _fetch_html(self, url: str) -> str | None:
        try:
            response = self.session.get(
                url,
                headers=self.headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException:
            return None
        return response.text

    def _clean_email(self, email: str) -> str | None:
        normalized = email.strip().strip(".,;:()[]{}<>\"'").lower()
        if not normalized:
            return None
        if any(bad in normalized for bad in ("noreply", "sentry", "placeholder")):
            return None
        if normalized.endswith("@example.com") or "@example.com." in normalized:
            return None

        local_part = normalized.split("@", 1)[0]
        if local_part.endswith(
            (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico")
        ):
            return None
        if any(token in local_part for token in ("image", "icon", "logo")):
            return None
        return normalized

    def _extract_emails(self, text: str) -> list[str]:
        emails: list[str] = []
        seen: set[str] = set()
        for match in EMAIL_RE.findall(text):
            cleaned = self._clean_email(match)
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            emails.append(cleaned)
        return emails

    def _extract_mentor_names(self, soup: BeautifulSoup) -> list[str]:
        names: list[str] = []
        seen: set[str] = set()
        text_lines = [
            line.strip()
            for line in soup.get_text("\n", strip=True).splitlines()
            if line.strip()
        ]

        for line in text_lines:
            line_lower = line.lower()
            if not any(keyword in line_lower for keyword in MENTOR_KEYWORDS):
                continue

            candidates: list[str] = []
            for raw_match in NAMES_AFTER_ROLE_RE.findall(line):
                parts = re.split(r"\s*(?:,|/|&|and)\s*", raw_match)
                candidates.extend(part for part in parts if part)

            candidates.extend(NAMES_BEFORE_ROLE_RE.findall(line))
            candidates.extend(NAME_RE.findall(line))

            for candidate in candidates:
                candidate = candidate.strip()
                candidate_lower = candidate.lower()
                if len(candidate.split()) < 2:
                    continue
                if any(keyword in candidate_lower for keyword in MENTOR_KEYWORDS):
                    continue
                if candidate in seen:
                    continue
                seen.add(candidate)
                names.append(candidate)

        return names

    def _extract_social_links(self, soup: BeautifulSoup, base_url: str) -> dict[str, str]:
        links: dict[str, str] = {}
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()
            if not href:
                continue
            absolute_href = urljoin(base_url, href)
            href_lower = absolute_href.lower()
            for platform, domain in SOCIAL_DOMAINS.items():
                if domain not in href_lower:
                    continue
                links.setdefault(platform, absolute_href)
        return links

    def _parse_page(self, html: str, page_url: str) -> dict[str, Any]:
        try:
            soup = BeautifulSoup(html, "lxml")
        except FeatureNotFound:
            soup = BeautifulSoup(html, "html.parser")
        text = f"{soup.get_text(' ', strip=True)} {html}"
        page_result = {
            "emails": self._extract_emails(text),
            "mentor_names": self._extract_mentor_names(soup),
            "social_links": self._extract_social_links(soup, page_url),
        }
        return page_result

    def _merge_results(
        self,
        merged: dict[str, Any],
        page_result: dict[str, Any],
    ) -> None:
        for email in page_result.get("emails", []):
            if email not in merged["emails"]:
                merged["emails"].append(email)

        for name in page_result.get("mentor_names", []):
            if name not in merged["mentor_names"]:
                merged["mentor_names"].append(name)

        for platform, link in page_result.get("social_links", {}).items():
            merged["social_links"].setdefault(platform, link)

    def scrape(self, url: str) -> dict[str, Any]:
        """Fetch a website and extract emails, mentor names, and social links."""

        try:
            normalized_url = self._normalize_url(url)
            parsed = urlparse(normalized_url)
            site_root = f"{parsed.scheme}://{parsed.netloc}"
            homepage_html = self._fetch_html(normalized_url)
            if not homepage_html:
                return {}

            result = {
                "emails": [],
                "mentor_names": [],
                "social_links": {},
            }

            homepage_result = self._parse_page(homepage_html, normalized_url)
            self._merge_results(result, homepage_result)

            if result["emails"]:
                return result

            for extra_path in ("/contact", "/about"):
                page_url = urljoin(site_root, extra_path)
                html = self._fetch_html(page_url)
                if not html:
                    continue
                self._merge_results(result, self._parse_page(html, page_url))

            return result
        except Exception:
            return {}
