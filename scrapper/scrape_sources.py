import json
import re
import time
import hashlib
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "jobs.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; BDJobAggregator/2.0; "
        "+https://github.com/zerolithX/bdjobscreapper)"
    )
}

SOURCES = [
    ("BD Govt Job", "https://bdgovtjob.net/"),
    ("The CV Guy", "https://thecvguy.net/jobs-and-careertips/"),
]

# Number of listing pages to check per source.
# Keep this moderate for GitHub Actions.
MAX_PAGES = 5

# Delay between HTTP requests.
DELAY = 2

# Maximum number of detail pages per source per run.
MAX_DETAIL_PAGES = 40


# ---------------------------------------------------------
# HTTP session
# ---------------------------------------------------------

def make_session():
    session = requests.Session()

    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )

    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    session.headers.update(HEADERS)
    return session


SESSION = make_session()


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def clean(value):
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_digits(text):
    if not text:
        return ""

    return text.translate(
        str.maketrans(
            "০১২৩৪৫৬৭৮৯",
            "0123456789",
        )
    )


def iso_date(text):
    """
    Converts common English/Bengali date formats to YYYY-MM-DD.

    Examples:
        21 September, 2026 -> 2026-09-21
        September 21, 2026 -> 2026-09-21
        21 September 2026  -> 2026-09-21
        ২৬ সেপ্টেম্বর ২০২৬  -> 2026-09-26
    """

    text = normalize_digits(clean(text))

    if not text:
        return None

    months = {
        "january": 1,
        "february": 2,
        "march": 3,
        "april": 4,
        "may": 5,
        "june": 6,
        "july": 7,
        "august": 8,
        "september": 9,
        "october": 10,
        "november": 11,
        "december": 12,
    }

    # 21 September, 2026
    match = re.search(
        r"\b(\d{1,2})\s+([A-Za-z]+),?\s+(\d{4})\b",
        text,
        re.I,
    )

    if match:
        day = int(match.group(1))
        month = months.get(match.group(2).lower())
        year = int(match.group(3))

        if month:
            return f"{year:04d}-{month:02d}-{day:02d}"

    # September 21, 2026
    match = re.search(
        r"\b([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})\b",
        text,
        re.I,
    )

    if match:
        month = months.get(match.group(1).lower())
        day = int(match.group(2))
        year = int(match.group(3))

        if month:
            return f"{year:04d}-{month:02d}-{day:02d}"

    bn_months = {
        "জানুয়ারি": 1,
        "জানুয়ারি": 1,
        "ফেব্রুয়ারি": 2,
        "ফেব্রুয়ারি": 2,
        "মার্চ": 3,
        "এপ্রিল": 4,
        "মে": 5,
        "জুন": 6,
        "জুলাই": 7,
        "আগস্ট": 8,
        "সেপ্টেম্বর": 9,
        "অক্টোবর": 10,
        "নভেম্বর": 11,
        "ডিসেম্বর": 12,
    }

    for name, month in bn_months.items():
        match = re.search(
            rf"(\d{{1,2}})\s+{re.escape(name)}\s+(\d{{4}})",
            text,
        )

        if match:
            day = int(match.group(1))
            year = int(match.group(2))
            return f"{year:04d}-{month:02d}-{day:02d}"

    return None


def jid(url, title):
    value = f"{url}|{title}".encode("utf-8")
    return hashlib.sha1(value).hexdigest()[:16]


def fetch(url):
    response = SESSION.get(url, timeout=30)

    if response.status_code >= 400:
        response.raise_for_status()

    response.encoding = response.apparent_encoding or response.encoding
    return response.text


def absolute_url(base, href):
    if not href:
        return None

    url = urljoin(base, href.strip())

    if not url.startswith(("http://", "https://")):
        return None

    return url.split("#")[0]


def same_domain(url, domain):
    try:
        return urlparse(url).netloc.lower().endswith(domain.lower())
    except Exception:
        return False


def is_source_url(url):
    return same_domain(url, "bdgovtjob.net") or same_domain(
        url, "thecvguy.net"
    )


def extract_first_date(text, patterns):
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            value = iso_date(match.group(1))
            if value:
                return value

    return None


def extract_deadline(text):
    patterns = [
        # Bengali
        r"আবেদনের\s*শেষ\s*তারিখ\s*[:\-]?\s*(.{0,80})",
        r"আবেদন\s*শেষ\s*[:\-]?\s*(.{0,80})",
        r"শেষ\s*তারিখ\s*[:\-]?\s*(.{0,80})",
        # English
        r"application\s*(?:deadline|last\s*date|closing\s*date)\s*[:\-]?\s*(.{0,80})",
        r"last\s*date\s*[:\-]?\s*(.{0,80})",
        r"deadline\s*[:\-]?\s*(.{0,80})",
    ]

    return extract_first_date(text, patterns)


def extract_publish_date(text):
    patterns = [
        r"published\s*(?:on)?\s*[:\-]?\s*(.{0,50})",
        r"publish\s*date\s*[:\-]?\s*(.{0,50})",
        r"প্রকাশের\s*তারিখ\s*[:\-]?\s*(.{0,50})",
        r"প্রকাশিত\s*[:\-]?\s*(.{0,50})",
    ]

    value = extract_first_date(text, patterns)

    if value:
        return value

    # Fallback: find the first recognizable date in the text.
    date_patterns = [
        r"\b\d{1,2}\s+[A-Za-z]+,?\s+\d{4}\b",
        r"\b[A-Za-z]+\s+\d{1,2},?\s+\d{4}\b",
        r"\b\d{1,2}\s+(?:জানুয়ারি|জানুয়ারি|ফেব্রুয়ারি|ফেব্রুয়ারি|মার্চ|এপ্রিল|মে|জুন|জুলাই|আগস্ট|সেপ্টেম্বর|অক্টোবর|নভেম্বর|ডিসেম্বর)\s+\d{4}\b",
    ]

    for pattern in date_patterns:
        match = re.search(pattern, text, re.I)
        if match:
            value = iso_date(match.group(0))
            if value:
                return value

    return None


def extract_vacancies(text):
    text = normalize_digits(text)

    patterns = [
        r"(?:number\s+of\s+vacancies|vacancies|no\.?\s+of\s+posts?|posts?)\s*[:\-]?\s*([\d,]+)",
        r"(?:পদ\s*সংখ্যা|পদসংখ্যা|মোট\s*পদ|পদ)\s*[:\-]?\s*([\d,]+)",
        r"([\d,]+)\s*(?:posts?|vacancies|পদ)",
        r"(\d[\d,]*)\s*জন",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            value = match.group(1).replace(",", "")
            try:
                return int(value)
            except ValueError:
                pass

    return None


def extract_organization(title, text):
    """
    Tries to identify an organization without pretending that
    every title contains one.
    """

    patterns = [
        r"(?:organization|company|employer|প্রতিষ্ঠান)\s*[:\-]\s*([^|.;]{3,100})",
        r"(?:নিয়োগ দিচ্ছে|নিয়োগ দিচ্ছে|hiring|recruiting)\s+([^|.;]{3,100})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            value = clean(match.group(1))
            if 2 <= len(value) <= 100:
                return value

    # Common title pattern:
    # "Organization is Hiring ..."
    match = re.match(
        r"^(.{2,100}?)\s+(?:is\s+)?hiring\b",
        title,
        re.I,
    )

    if match:
        value = clean(match.group(1))
        if value:
            return value

    # "Organization Job Circular..."
    match = re.match(
        r"^(.{2,100}?)\s+(?:job|career|recruitment)\b",
        title,
        re.I,
    )

    if match:
        value = clean(match.group(1))
        if value:
            return value

    return None


def classify_category(title, text, source):
    low = f"{title} {text}".lower()

    if any(x in low for x in ["bank", "banking", "standard chartered"]):
        return "BANK"

    if any(
        x in low
        for x in [
            "defence",
            "defense",
            "air force",
            "navy",
            "army",
            "bgb",
            "police",
        ]
    ):
        return "DEFENCE"

    if any(
        x in low
        for x in [
            "intern",
            "internship",
            "trainee",
            "traineeship",
        ]
    ):
        return "INTERNSHIP"

    if "fresher" in low or "freshers" in low:
        return "FRESHERS"

    if any(
        x in low
        for x in [
            "robi",
            "foodpanda",
            "jti",
            "marico",
            "dhl",
            "nestlé",
            "nestle",
            "berger",
            "reckitt",
            "mnc",
        ]
    ):
        return "MNC"

    if any(x in low for x in ["university", "school", "college"]):
        return "EDUCATION"

    if source == "BD Govt Job":
        return "GOVT"

    return "JOBS_BD"


def extract_apply_url(soup, base, source_url):
    """
    Looks for an external application/career link.
    Falls back to the source article when no external link exists.
    """

    keywords = [
        "apply",
        "apply now",
        "career",
        "careers",
        "recruitment",
        "application",
        "teletalk",
        "join",
        "jobs",
        "job portal",
    ]

    candidates = []

    for a in soup.select("a[href]"):
        href = absolute_url(base, a.get("href"))
        if not href:
            continue

        label = clean(a.get_text(" ", strip=True)).lower()
        url_low = href.lower()

        score = 0

        if any(k in label for k in keywords):
            score += 5

        if any(k in url_low for k in keywords):
            score += 4

        if is_source_url(href):
            score -= 6

        if href.rstrip("/") == source_url.rstrip("/"):
            score -= 10

        if score > 0:
            candidates.append((score, href))

    if candidates:
        candidates.sort(reverse=True)
        return candidates[0][1]

    return source_url


def build_record(
    source,
    title,
    source_url,
    detail_text,
    detail_soup,
):
    publish_date = extract_publish_date(detail_text)
    deadline = extract_deadline(detail_text)
    vacancies = extract_vacancies(detail_text)
    organization = extract_organization(title, detail_text)

    category = classify_category(
        title,
        detail_text,
        source,
    )

    apply_url = extract_apply_url(
        detail_soup,
        source_url,
        source_url,
    )

    return {
        "id": jid(source_url, title),
        "source": source,
        "type": "job",
        "title": title,
        "organization": organization,
        "category": category,
        "publish_date": publish_date,
        "deadline": deadline,
        "vacancies": vacancies,
        "source_url": source_url,
        "apply_url": apply_url,
        "summary": detail_text[:600],
    }


# ---------------------------------------------------------
# Listing URL discovery
# ---------------------------------------------------------

def discover_links(soup, base, source):
    links = []

    for a in soup.select("article h1 a, article h2 a, article h3 a, h2 a, h3 a"):
        title = clean(a.get_text(" ", strip=True))
        url = absolute_url(base, a.get("href"))

        if not title or len(title) < 8 or not url:
            continue

        if source == "BD Govt Job":
            if not same_domain(url, "bdgovtjob.net"):
                continue
        else:
            if not same_domain(url, "thecvguy.net"):
                continue

        links.append((title, url))

    # CV Guy sometimes has article links without h2/h3 structure.
    if source == "The CV Guy":
        for a in soup.select("article a[href]"):
            title = clean(a.get_text(" ", strip=True))
            url = absolute_url(base, a.get("href"))

            if not title or len(title) < 12 or not url:
                continue

            if not same_domain(url, "thecvguy.net"):
                continue

            low = title.lower()

            if any(
                x in low
                for x in [
                    "full job description",
                    "read more",
                    "facebook",
                    "instagram",
                    "linkedin",
                ]
            ):
                continue

            if any(
                k in low
                for k in [
                    "hiring",
                    "job",
                    "intern",
                    "trainee",
                    "executive",
                    "manager",
                    "officer",
                    "analyst",
                    "assistant",
                    "engineer",
                    "director",
                    "recruitment",
                ]
            ):
                links.append((title, url))

    # De-duplicate while preserving order.
    seen = set()
    result = []

    for title, url in links:
        key = (title.lower(), url.lower())

        if key in seen:
            continue

        seen.add(key)
        result.append((title, url))

    return result


def pagination_urls(soup, base, source):
    urls = []

    for a in soup.select("a[href]"):
        label = clean(a.get_text(" ", strip=True)).lower()
        href = absolute_url(base, a.get("href"))

        if not href:
            continue

        if source == "BD Govt Job":
            if not same_domain(href, "bdgovtjob.net"):
                continue

            if (
                "older posts" in label
                or "next" in label
                or re.search(r"\bpage\s*\d+\b", label)
            ):
                urls.append(href)

        else:
            if not same_domain(href, "thecvguy.net"):
                continue

            if (
                "older posts" in label
                or "next" in label
                or re.search(r"\bpage\s*\d+\b", label)
            ):
                urls.append(href)

    # Keep order and remove duplicates.
    return list(dict.fromkeys(urls))


# ---------------------------------------------------------
# Source scrapers
# ---------------------------------------------------------

def scrape_source(source, start_url):
    results = []
    listing_queue = [start_url]
    visited_listing = set()

    while listing_queue and len(visited_listing) < MAX_PAGES:
        listing_url = listing_queue.pop(0)

        if listing_url in visited_listing:
            continue

        visited_listing.add(listing_url)

        print(f"  Listing: {listing_url}")

        try:
            html = fetch(listing_url)
        except Exception as exc:
            print(f"  Listing ERROR: {exc}")
            continue

        soup = BeautifulSoup(html, "html.parser")

        links = discover_links(
            soup,
            listing_url,
            source,
        )

        for title, url in links:
            results.append((title, url))

        for url in pagination_urls(
            soup,
            listing_url,
            source,
        ):
            if url not in visited_listing and url not in listing_queue:
                listing_queue.append(url)

        time.sleep(DELAY)

    # De-duplicate article URLs.
    unique = {}
    for title, url in results:
        unique[url] = title

    rows = []
    detail_count = 0

    for source_url, title in unique.items():
        if detail_count >= MAX_DETAIL_PAGES:
            break

        try:
            print(f"  Detail: {title[:80]}")

            html = fetch(source_url)
            soup = BeautifulSoup(html, "html.parser")

            # Prefer article/main content.
            container = (
                soup.select_one("article")
                or soup.select_one("main")
                or soup.body
            )

            detail_text = clean(
                container.get_text(" ", strip=True)
                if container
                else ""
            )

            if not detail_text:
                continue

            row = build_record(
                source=source,
                title=title,
                source_url=source_url,
                detail_text=detail_text,
                detail_soup=soup,
            )

            rows.append(row)
            detail_count += 1

        except Exception as exc:
            print(f"  Detail ERROR: {source_url} -> {exc}")

        time.sleep(DELAY)

    return rows


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------

def main():
    DATA.parent.mkdir(parents=True, exist_ok=True)

    if DATA.exists():
        try:
            existing_data = json.loads(
                DATA.read_text(encoding="utf-8")
            )

            if not isinstance(existing_data, list):
                existing_data = []

        except (json.JSONDecodeError, OSError):
            existing_data = []
    else:
        existing_data = []

    existing = {
        row.get("id"): row
        for row in existing_data
        if isinstance(row, dict) and row.get("id")
    }

    for source, url in SOURCES:
        print(f"\n=== {source} ===")

        try:
            rows = scrape_source(
                source,
                url,
            )

            for row in rows:
                existing[row["id"]] = row

            print(f"{source}: {len(rows)} jobs collected")

        except Exception as exc:
            print(f"{source}: ERROR {exc}")

        time.sleep(DELAY)

    rows = list(existing.values())

    # Newest publish dates first.
    rows.sort(
        key=lambda row: row.get("publish_date") or "",
        reverse=True,
    )

    DATA.write_text(
        json.dumps(
            rows,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"\nTotal stored jobs: {len(rows)}")
    print(f"Output: {DATA}")


if __name__ == "__main__":
    main()
