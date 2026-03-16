import os
import re
import json
import time
import hashlib
import datetime as dt
from typing import List, Dict
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://sutra.oslpr.org"
SUTRA_MEDIDAS_URL = f"{BASE_URL}/medidas"

DEFAULT_KEYWORDS = [
    "Departamento de Educación",
    "Municipio de San Juan",
    "salario",
    "trabajadores",
]

MEASURE_CODE_RE = re.compile(r"\b(?:PC|PS|RC|RS|RCC|RCS)\s*0*\d+\b", re.IGNORECASE)

DATE_PATTERNS = [
    re.compile(r"(?:Fecha de Radicación|Radicada)\s*:?\s*(\d{1,2}/\d{1,2}/\d{4})", re.IGNORECASE),
    re.compile(r"\b(\d{4}-\d{2}-\d{2})\b"),
]
def build_previous_day_url() -> str:
    pr_today = dt.datetime.now(ZoneInfo("America/Puerto_Rico")).date()
    yesterday = pr_today - dt.timedelta(days=1)
    y = yesterday.isoformat()

    return (
        f"{BASE_URL}/medidas"
        f"?cuatrienio_id=2025"
        f"&fecha_radicacion_desde={y}"
        f"&fecha_radicacion_hasta={y}"
    )

def load_state(path: str) -> Dict:
    if not os.path.exists(path):
        return {"seen": {}}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("seen", {})
    return data


def save_state(path: str, state: Dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def stable_id(url: str, measure: str, title: str) -> str:
    raw = f"{url}||{measure}||{title}".strip().lower().encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def http_get(session: requests.Session, url: str, timeout: int = 25) -> str:
    last_err = None
    for attempt in range(3):
        try:
            print(f"[GET] {url} (attempt {attempt + 1})")
            r = session.get(url, timeout=timeout, verify=False)
            r.raise_for_status()
            print(f"[GET OK] status={r.status_code} bytes={len(r.text)}")
            return r.text
        except Exception as e:
            last_err = e
            print(f"[GET ERROR] {url}: {e}")
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"GET failed for {url}: {last_err}")


def build_list_pages(max_pages: int) -> List[str]:
    pages = []
    for page in range(1, max_pages + 1):
        pages.append(f"{SUTRA_MEDIDAS_URL}?page={page}")
    return pages


def extract_detail_links(list_html: str, base_url: str) -> List[str]:
    soup = BeautifulSoup(list_html, "lxml")
    links = []

    for a in soup.select("a[href]"):
        href = (a.get("href") or "").strip()
        if not href:
            continue

        if href.startswith("/"):
            full = urljoin(base_url, href)
        elif href.startswith("http"):
            full = href
        else:
            full = urljoin(base_url, "/" + href)

        if "sutra.oslpr.org" not in full:
            continue

        if "/medidas/" in full:
            links.append(full)

    seen = set()
    out = []
    for link in links:
        if link not in seen:
            seen.add(link)
            out.append(link)

    return out


def parse_filed_date(text: str) -> str:
    for pattern in DATE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue

        raw = match.group(1).strip()
        for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
            try:
                parsed = dt.datetime.strptime(raw, fmt).date()
                return parsed.isoformat()
            except ValueError:
                continue

    return ""


def parse_detail_page(detail_html: str, url: str) -> Dict:
    soup = BeautifulSoup(detail_html, "lxml")
    text = soup.get_text(" ", strip=True)

    measure_match = MEASURE_CODE_RE.search(text)
    measure = measure_match.group(0).upper().replace(" ", "") if measure_match else ""

    title = ""
    h1 = soup.find(["h1", "h2"])
    if h1 and h1.get_text(strip=True):
        title = h1.get_text(" ", strip=True)
    elif soup.title and soup.title.get_text(strip=True):
        title = soup.title.get_text(" ", strip=True)

    summary = text[:700]
    filed_date = parse_filed_date(text)

    return {
        "url": url,
        "measure": measure,
        "title": title,
        "full_text": text,
        "summary": summary,
        "filed_date": filed_date,
    }


def keyword_hits(text: str, keywords: List[str]) -> List[str]:
    t = text.lower()
    hits = []
    for kw in keywords:
        if kw.lower() in t:
            hits.append(kw)
    return hits


def post_to_zapier(session: requests.Session, hook_url: str, payload: Dict) -> None:
    print("[POST] Sending to Zapier")
    print(json.dumps(payload, ensure_ascii=False)[:1200])

    r = session.post(hook_url, json=payload, timeout=25)

    print(f"[POST STATUS] {r.status_code}")
    print(r.text[:500])

    r.raise_for_status()


def main() -> None:
    zapier_hook = os.environ.get("ZAPIER_HOOK_URL", "").strip()
    if not zapier_hook:
        print("[ERROR] Missing ZAPIER_HOOK_URL")
        return

    state_path = os.environ.get("STATE_PATH", "state.json")
    max_pages = int(os.environ.get("MAX_PAGES", "1025"))
    max_details = int(os.environ.get("MAX_DETAILS", "250"))
    days_back = int(os.environ.get("DAYS_BACK", "1"))

    keywords_env = (os.environ.get("KEYWORDS") or "").strip()
    kw_list = [k.strip() for k in keywords_env.split("|") if k.strip()] if keywords_env else DEFAULT_KEYWORDS

    now = dt.datetime.now(dt.timezone.utc)
    now_iso = now.isoformat()
    cutoff_date = now.date() - dt.timedelta(days=days_back)

    print("[INFO] Starting SUTRA monitor")
    print(f"[INFO] STATE_PATH={state_path}")
    print(f"[INFO] MAX_PAGES={max_pages}")
    print(f"[INFO] MAX_DETAILS={max_details}")
    print(f"[INFO] DAYS_BACK={days_back}")
    print(f"[INFO] CUTOFF_DATE={cutoff_date.isoformat()}")
    print(f"[INFO] KEYWORDS={kw_list}")

    session = requests.Session()
    session.headers.update({
        "User-Agent": "sutra-monitor/1.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })

    try:
        state = load_state(state_path)
        seen = state["seen"]

        all_links: List[str] = []
        page_urls = build_list_pages(max_pages)

        list_url = build_previous_day_url()
        print("[INFO] Using filtered URL:", list_url)

        html = http_get(session, list_url)
        links = extract_detail_links(html, BASE_URL)

        print("[INFO] Links found for previous day:", len(links))

        unique_links = list(dict.fromkeys(links))
        dedup = set()
        for link in all_links:
            if link not in dedup:
                dedup.add(link)
                unique_links.append(link)

        print(f"[INFO] Total unique detail links found: {len(unique_links)}")

        new_items: List[Dict] = []

        for url in unique_links[:max_details]:
            try:
                html = http_get(session, url)
            except Exception as e:
                print(f"[WARN] Failed detail page {url}: {e}")
                continue

            item = parse_detail_page(html, url)

            filed_date_str = item.get("filed_date", "")
            if not filed_date_str:
                print(f"[SKIP] No filed_date detected: {url}")
                continue

            try:
                filed_date = dt.date.fromisoformat(filed_date_str)
            except ValueError:
                print(f"[SKIP] Invalid filed_date {filed_date_str}: {url}")
                continue

            if filed_date < cutoff_date:
                print(f"[SKIP] Older than cutoff ({filed_date_str}): {url}")
                continue

            combined = f"{item.get('title', '')} {item.get('full_text', '')}"
            hits = keyword_hits(combined, kw_list)

            if not hits:
                print(f"[SKIP] No keyword hits: {url}")
                continue

            item_id = stable_id(item["url"], item.get("measure", ""), item.get("title", ""))
            if item_id in seen:
                print(f"[SEEN] Already processed: {item.get('measure', '')} {item.get('title', '')}")
                continue

            item["id"] = item_id
            item["hits"] = hits
            new_items.append(item)

        print(f"[INFO] New relevant matches: {len(new_items)}")

        if new_items:
            for item in new_items:
                payload = {
                    "measure": item.get("measure", ""),
                    "title": item.get("title", ""),
                    "summary": item.get("summary", ""),
                    "hits": ", ".join(item.get("hits", [])),
                    "url": item.get("url", ""),
                    "filed_date": item.get("filed_date", ""),
                    "checked_at": now_iso,
                    "is_empty": False,
                    "status": "New relevant measure found",
                }

                post_to_zapier(session, zapier_hook, payload)
                seen[item["id"]] = now_iso

            save_state(state_path, state)
            print("[INFO] state.json updated")
        else:
            payload = {
                "measure": "",
                "title": "",
                "summary": "",
                "hits": "",
                "url": "",
                "filed_date": "",
                "checked_at": now_iso,
                "is_empty": True,
                "status": f"No relevant measures found in the last {days_back} days",
            }

            post_to_zapier(session, zapier_hook, payload)
            print("[INFO] Empty result sent to Zapier")

    except Exception as e:
        print(f"[ERROR] {e}")

        payload = {
            "error": True,
            "message": str(e),
            "checked_at": now_iso,
        }

        try:
            post_to_zapier(session, zapier_hook, payload)
        except Exception as post_err:
            print(f"[FATAL] Could not notify Zapier: {post_err}")


if __name__ == "__main__":
    main()
