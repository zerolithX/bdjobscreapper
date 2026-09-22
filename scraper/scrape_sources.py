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


ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "jobs.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; BDJobAggregator/3.0; "
        "+https://github.com/zerolithX/bdjobscreapper)"
    )
}

SOURCES = [
    ("BD Govt Job", "https://bdgovtjob.net/"),
    ("The CV Guy", "https://thecvguy.net/jobs-and-careertips/"),
]

MAX_PAGES = 5
MAX_DETAIL_PAGES = 40
DELAY = 2


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


def clean(value):
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_digits(text):
    if not text:
        return ""
    return text.translate(str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789"))


def iso_date(text):
    text = normalize_digits(clean(text))
    if not text:
        return None

    months = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
    }

    m = re.search(r"\b(\d{1,2})\s+([A-Za-z]+),?\s+(\d{4})\b", text, re.I)
    if m:
        month = months.get(m.group(2).lower())
        if month:
            return f"{int(m.group(3)):04d}-{month:02d}-{int(m.group(1)):02d}"

    m = re.search(r"\b([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})\b", text, re.I)
    if m:
        month = months.get(m.group(1).lower())
        if month:
            return f"{int(m.group(3)):04d}-{month:02d}-{int(m.group(2)):02d}"

    bn_months = {
        "জানুয়ারি": 1, "জানুয়ারি": 1, "ফেব্রুয়ারি": 2, "ফেব্রুয়ারি": 2,
        "মার্চ": 3, "এপ্রিল": 4, "মে": 5, "জুন": 6, "জুলাই": 7,
        "আগস্ট": 8, "সেপ্টেম্বর": 9, "অক্টোবর": 10, "নভেম্বর": 11, "ডিসেম্বর": 12,
    }

    for name, month in bn_months.items():
        m = re.search(rf"(\d{{1,2}})\s+{re.escape(name)}\s+(\d{{4}})", text)
        if m:
            return f"{int(m.group(2)):04d}-{month:02d}-{int(m.group(1)):02d}"

    return None


def jid(url, title):
    return hashlib.sha1(f"{url}|{title}".encode("utf-8")).hexdigest()[:16]


def fetch(url):
    response = SESSION.get(url, timeout=30)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return response.text


def absolute_url(base, href):
    if not href:
        return None
    url = urljoin(base, href.strip()).split("#")[0]
    return url if url.startswith(("http://", "https://")) else None


def same_domain(url, domain):
    try:
        return urlparse(url).netloc.lower().endswith(domain.lower())
    except Exception:
        return False


def is_source_domain(url):
    return same_domain(url, "bdgovtjob.net") or same_domain(url, "thecvguy.net")


def first_date(text, patterns):
    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            value = iso_date(m.group(1))
            if value:
                return value
    return None


def extract_deadline(text):
    return first_date(text, [
        r"আবেদনের\s*শেষ\s*তারিখ\s*[:\-]?\s*(.{0,100})",
        r"আবেদন\s*শেষ\s*[:\-]?\s*(.{0,100})",
        r"শেষ\s*তারিখ\s*[:\-]?\s*(.{0,100})",
        r"application\s*(?:deadline|last\s*date|closing\s*date)\s*[:\-]?\s*(.{0,100})",
        r"last\s*date\s*[:\-]?\s*(.{0,100})",
        r"deadline\s*[:\-]?\s*(.{0,100})",
    ])


def extract_publish_date(text):
    value = first_date(text, [
        r"published\s*(?:on)?\s*[:\-]?\s*(.{0,60})",
        r"publish\s*date\s*[:\-]?\s*(.{0,60})",
        r"প্রকাশের\s*তারিখ\s*[:\-]?\s*(.{0,60})",
        r"প্রকাশিত\s*[:\-]?\s*(.{0,60})",
    ])
    if value:
        return value

    for pattern in [
        r"\b\d{1,2}\s+[A-Za-z]+,?\s+\d{4}\b",
        r"\b[A-Za-z]+\s+\d{1,2},?\s+\d{4}\b",
        r"\b\d{1,2}\s+(?:জানুয়ারি|জানুয়ারি|ফেব্রুয়ারি|ফেব্রুয়ারি|মার্চ|এপ্রিল|মে|জুন|জুলাই|আগস্ট|সেপ্টেম্বর|অক্টোবর|নভেম্বর|ডিসেম্বর)\s+\d{4}\b",
    ]:
        m = re.search(pattern, text, re.I)
        if m:
            value = iso_date(m.group(0))
            if value:
                return value
    return None


def extract_vacancies(text):
    text = normalize_digits(text)
    patterns = [
        r"(?:number\s+of\s+vacancies|number\s+of\s+posts?|vacancies|no\.?\s+of\s+posts?|posts?|number\s+of\s+interns?)\s*[:\-]?\s*([\d,]+)",
        r"(?:পদ\s*সংখ্যা|পদসংখ্যা|মোট\s*পদ|পদ|জনবল|নিয়োগ\s*দেওয়া\s*হবে)\s*[:\-]?\s*([\d,]+)",
        r"([\d,]+)\s*(?:posts?|vacancies|পদ|জন|interns?)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            try:
                return int(m.group(1).replace(",", ""))
            except ValueError:
                pass
    return None


def extract_organization(title, text):
    patterns = [
        r"(?:company|organization|employer|প্রতিষ্ঠান)\s*[:\-]?\s*([^|.;]{3,100})",
        r"(?:নিয়োগ দিচ্ছে|নিয়োগ দিচ্ছে|hiring|recruiting)\s+([^|.;]{3,100})",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            value = clean(m.group(1))
            if 2 <= len(value) <= 100:
                return value

    if "|" in title:
        parts = [clean(x) for x in title.split("|") if clean(x)]
        if len(parts) >= 2 and len(parts[-1]) <= 100:
            return parts[-1]

    m = re.match(r"^(.{2,100}?)\s+(?:is\s+)?hiring\b", title, re.I)
    if m:
        return clean(m.group(1))

    m = re.match(r"^(.{2,100}?)\s+(?:job|career|recruitment)\b", title, re.I)
    if m:
        return clean(m.group(1))

    return None


def classify_category(title, text, source):
    low = f"{title} {text}".lower()

    if any(x in low for x in ["bank", "banking", "standard chartered"]):
        return "BANK"
    if any(x in low for x in ["defence", "defense", "air force", "navy", "army", "bgb", "police"]):
        return "DEFENCE"
    if any(x in low for x in ["intern", "internship", "trainee", "traineeship"]):
        return "INTERNSHIP"
    if "fresher" in low or "freshers" in low:
        return "FRESHERS"
    if any(x in low for x in ["robi", "foodpanda", "jti", "marico", "dhl", "nestlé", "nestle", "berger", "reckitt", "mnc"]):
        return "MNC"
    if any(x in low for x in ["university", "school", "college"]):
        return "EDUCATION"
    return "GOVT" if source == "BD Govt Job" else "JOBS_BD"


def extract_apply_url(soup, base, source_url):
    candidates = []

    strong_words = [
        "apply now", "apply online", "অনলাইনে আবেদন করুন",
        "আবেদনের লিংক", "আবেদন করুন", "apply",
    ]
    url_words = [
        "apply", "career", "careers", "recruit", "jobs",
        "teletalk", "join.", "jobportal", "application",
    ]

    for a in soup.select("a[href]"):
        href = absolute_url(base, a.get("href"))
        if not href or href.startswith(("javascript:", "mailto:", "tel:")):
            continue

        label = clean(a.get_text(" ", strip=True))
        label_low = label.lower()
        url_low = href.lower()
        score = 0

        for word in strong_words:
            if word.lower() in label_low:
                score += 10

        if any(word in url_low for word in url_words):
            score += 7

        if "teletalk.com.bd" in url_low:
            score += 15

        if not is_source_domain(href):
            score += 8

        if href.rstrip("/") == source_url.rstrip("/"):
            score -= 30

        if any(x in url_low for x in [
            "facebook.com", "instagram.com", "linkedin.com",
            "youtube.com", "twitter.com", "x.com"
        ]):
            score -= 30

        if score > 0:
            candidates.append((score, href, label))

    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1], True

    return None, False


def build_record(source, title, source_url, detail_text, detail_soup, listing_text=""):
    publish_date = extract_publish_date(listing_text) or extract_publish_date(detail_text)
    deadline = extract_deadline(detail_text) or extract_deadline(listing_text)
    vacancies = extract_vacancies(detail_text) or extract_vacancies(listing_text)
    organization = extract_organization(title, detail_text)
    category = classify_category(title, detail_text, source)

    apply_url, apply_found = extract_apply_url(
        detail_soup, source_url, source_url
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
        "apply_found": apply_found,
        "summary": detail_text[:600],
    }


def discover_links(soup, base, source):
    result = []
    selectors = [
        "article h1 a", "article h2 a", "article h3 a",
        "h2 a", "h3 a",
    ]

    for a in soup.select(", ".join(selectors)):
        title = clean(a.get_text(" ", strip=True))
        url = absolute_url(base, a.get("href"))
        if not title or len(title) < 8 or not url:
            continue

        domain = "bdgovtjob.net" if source == "BD Govt Job" else "thecvguy.net"
        if not same_domain(url, domain):
            continue

        card = (
            a.find_parent("article")
            or a.find_parent(class_=re.compile(r"post|card|job", re.I))
            or a.parent
        )
        listing_text = clean(card.get_text(" ", strip=True) if card else "")

        result.append({
            "title": title,
            "url": url,
            "listing_text": listing_text,
        })

    if source == "The CV Guy":
        for a in soup.select("article a[href]"):
            title = clean(a.get_text(" ", strip=True))
            url = absolute_url(base, a.get("href"))
            if not title or len(title) < 12 or not url:
                continue
            if not same_domain(url, "thecvguy.net"):
                continue

            low = title.lower()
            if any(x in low for x in ["full job description", "read more", "facebook", "instagram", "linkedin"]):
                continue
            if not any(k in low for k in [
                "hiring", "job", "intern", "trainee", "executive",
                "manager", "officer", "analyst", "assistant",
                "engineer", "director", "recruitment"
            ]):
                continue

            card = a.find_parent("article") or a.find_parent(class_=re.compile(r"post|card|job", re.I))
            listing_text = clean(card.get_text(" ", strip=True) if card else "")
            result.append({"title": title, "url": url, "listing_text": listing_text})

    seen = set()
    unique = []
    for item in result:
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        unique.append(item)
    return unique


def pagination_urls(soup, base, source):
    urls = []
    domain = "bdgovtjob.net" if source == "BD Govt Job" else "thecvguy.net"

    for a in soup.select("a[href]"):
        label = clean(a.get_text(" ", strip=True)).lower()
        href = absolute_url(base, a.get("href"))
        if not href or not same_domain(href, domain):
            continue
        if (
            "older posts" in label
            or "next" in label
            or re.search(r"\bpage\s*\d+\b", label)
        ):
            urls.append(href)

    return list(dict.fromkeys(urls))


def scrape_source(source, start_url):
    discovered = []
    queue = [start_url]
    visited = set()

    while queue and len(visited) < MAX_PAGES:
        listing_url = queue.pop(0)
        if listing_url in visited:
            continue

        visited.add(listing_url)
        print(f"  Listing: {listing_url}")

        try:
            soup = BeautifulSoup(fetch(listing_url), "html.parser")
        except Exception as exc:
            print(f"  Listing ERROR: {exc}")
            continue

        discovered.extend(discover_links(soup, listing_url, source))

        for next_url in pagination_urls(soup, listing_url, source):
            if next_url not in visited and next_url not in queue:
                queue.append(next_url)

        time.sleep(DELAY)

    unique = {}
    for item in discovered:
        unique[item["url"]] = item

    rows = []
    for source_url, item in list(unique.items())[:MAX_DETAIL_PAGES]:
        try:
            print(f"  Detail: {item['title'][:80]}")
            soup = BeautifulSoup(fetch(source_url), "html.parser")
            container = soup.select_one("article") or soup.select_one("main") or soup.body
            detail_text = clean(container.get_text(" ", strip=True) if container else "")
            if not detail_text:
                continue

            rows.append(build_record(
                source,
                item["title"],
                source_url,
                detail_text,
                soup,
                item.get("listing_text", ""),
            ))
        except Exception as exc:
            print(f"  Detail ERROR: {source_url} -> {exc}")

        time.sleep(DELAY)

    return rows


def main():
    DATA.parent.mkdir(parents=True, exist_ok=True)

    if DATA.exists():
        try:
            data = json.loads(DATA.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                data = []
        except (json.JSONDecodeError, OSError):
            data = []
    else:
        data = []

    existing = {
        row.get("id"): row
        for row in data
        if isinstance(row, dict) and row.get("id")
    }

    for source, url in SOURCES:
        print(f"\n=== {source} ===")
        try:
            rows = scrape_source(source, url)
            for row in rows:
                existing[row["id"]] = row
            print(f"{source}: {len(rows)} jobs collected")
        except Exception as exc:
            print(f"{source}: ERROR {exc}")
        time.sleep(DELAY)

    rows = sorted(
        existing.values(),
        key=lambda x: x.get("publish_date") or "",
        reverse=True,
    )

    DATA.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"\nTotal stored jobs: {len(rows)}")
    print(f"Output: {DATA}")


if __name__ == "__main__":
    main()
