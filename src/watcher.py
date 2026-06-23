from __future__ import annotations

import hashlib
import os
import re
import smtplib
import sys
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

load_dotenv()
base_url = os.getenv("BASE_URL")
property_re = os.getenv("PROPERTY_RE")
room_hint_re = os.getenv("ROOM_HINT_RE")


@dataclass(frozen=True, order=True)
class Vacancy:
    key: str
    title: str
    url: str

    def line(self) -> str:
        return f"{self.key}\t{self.title}\t{self.url}"


def canonical_url(raw_url: str, base: str = base_url) -> str:
    absolute = urljoin(base, raw_url)
    parts = urlsplit(absolute)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def make_key(url: str, title: str) -> str:
    return hashlib.sha256(f"{url}\n{title}".encode("utf-8")).hexdigest()[:16]


def clean_text(value: str) -> str:
    return " ".join(value.split())


def parse_vacancies(html: str, page_url: str) -> set[Vacancy]:
    """Extract individual room rows when possible, falling back to property cards.

    UR renders some vacancy content with JavaScript and changes CSS class names from
    time to time, so this parser intentionally relies on semantic clues and URL shapes.
    """
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, Vacancy] = {}

    # Individual room/detail links: links inside a compact ancestor containing room-like data.
    for anchor in soup.find_all("a", href=True):
        url = canonical_url(anchor["href"], page_url)
        if "ur-net.go.jp/chintai/" not in url:
            continue

        node = anchor
        text = ""
        for _ in range(5):
            if node is None:
                break
            candidate = clean_text(node.get_text(" ", strip=True))
            if room_hint_re.search(candidate) and len(candidate) <= 600:
                text = candidate
                break
            node = node.parent

        href = anchor.get("href", "")
        looks_like_room = any(token in href.lower() for token in ("room", "detail", "apply", "vacant"))
        has_room_number = bool(re.search(r"\d+号室", text))
        if (looks_like_room or has_room_number) and text:
            title = text[:300]
            key = make_key(url, title)
            found[key] = Vacancy(key, title, url)

    if found:
        return set(found.values())

    # Fallback: result-page property cards. This still detects a newly listed building.
    for anchor in soup.find_all("a", href=True):
        url = canonical_url(anchor["href"], page_url)
        if not property_re.search(url):
            continue
        node = anchor
        text = ""
        for _ in range(4):
            if node is None:
                break
            candidate = clean_text(node.get_text(" ", strip=True))
            if 2 <= len(candidate) <= 500:
                text = candidate
            if room_hint_re.search(candidate):
                text = candidate
                break
            node = node.parent
        title = text or clean_text(anchor.get_text(" ", strip=True)) or url.rsplit("/", 1)[-1]
        key = make_key(url, title)
        found[key] = Vacancy(key, title[:300], url)

    return set(found.values())


def fetch_rendered_html(url: str, headless: bool = True) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page(
            locale="ja-JP",
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "Chrome/124.0 Safari/537.36 URVacancyWatcher/1.0"
            ),
        )
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        try:
            page.wait_for_load_state("networkidle", timeout=20_000)
        except PlaywrightTimeoutError:
            pass
        page.wait_for_timeout(3_000)
        html = page.content()
        browser.close()
        return html


def read_state(path: Path) -> set[Vacancy]:
    if not path.exists():
        return set()
    vacancies: set[Vacancy] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw or raw.startswith("#"):
            continue
        parts = raw.split("\t", 2)
        if len(parts) == 3:
            vacancies.add(Vacancy(*parts))
    return vacancies


def write_state(path: Path, vacancies: set[Vacancy]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# key\ttitle\turl", *(v.line() for v in sorted(vacancies))]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def send_email(new_items: set[Vacancy], search_url: str) -> None:
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    username = os.environ["SMTP_USERNAME"]
    password = os.environ["SMTP_PASSWORD"]
    recipient = os.environ.get("NOTIFY_EMAIL", "kyuhur2@gmail.com")

    msg = EmailMessage()
    msg["Subject"] = f"UR vacancy alert: {len(new_items)} new listing(s)"
    msg["From"] = username
    msg["To"] = recipient
    body = ["New UR vacancy listings were detected:", ""]
    for item in sorted(new_items):
        body.extend([item.title, item.url, ""])
    body.extend(["Search page:", search_url])
    msg.set_content("\n".join(body))

    with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
        smtp.login(username, password)
        smtp.send_message(msg)


def main() -> int:
    load_dotenv()
    search_url = os.environ.get("SEARCH_URL", "").strip()
    if not search_url:
        print("SEARCH_URL is required", file=sys.stderr)
        return 2

    state_path = Path(os.environ.get("STATE_FILE", "data/vacancies.txt"))
    headless = os.environ.get("HEADLESS", "true").lower() != "false"
    send_initial = os.environ.get("SEND_INITIAL", "false").lower() == "true"

    html = fetch_rendered_html(search_url, headless=headless)
    current = parse_vacancies(html, search_url)
    if not current:
        Path("debug").mkdir(exist_ok=True)
        Path("debug/last-page.html").write_text(html, encoding="utf-8")
        print("No vacancies were parsed. Saved debug/last-page.html; state was not changed.", file=sys.stderr)
        return 1

    previous = read_state(state_path)
    first_run = not previous
    additions = current - previous
    removals = previous - current

    print(f"Current: {len(current)} | Added: {len(additions)} | Removed: {len(removals)}")
    for item in sorted(additions):
        print(f"NEW: {item.title} | {item.url}")

    if additions and (not first_run or send_initial):
        send_email(additions, search_url)
        print("Notification email sent.")
    elif first_run:
        print("Initial snapshot created; email suppressed (SEND_INITIAL=false).")

    write_state(state_path, current)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
