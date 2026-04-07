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

from src.keywords import build_topics, extract_keywords

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://sutra.oslpr.org"

MEASURE_CODE_RE = re.compile(r"\b(?:PC|PS|RC|RS|RCC|RCS)\s*0*\d+\b", re.IGNORECASE)


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
            print(f"[GET] {url}")
            r = session.get(url, timeout=timeout, verify=False)
            r.raise_for_status()
            return r.text
        except Exception as e:
            last_err = e
            print(f"[GET ERROR] {e}")
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"GET failed for {url}: {last_err}")


def build_recent_days_url(days_back: int = 3) -> str:
    pr_today = dt.datetime.now(ZoneInfo("America/Puerto_Rico")).date()
    end_date = pr_today - dt.timedelta(days=1)
    start_date = end_date - dt.timedelta(days=days_back - 1)

    return (
        f"{BASE_URL}/medidas"
        f"?cuatrienio_id=2025"
        f"&fecha_radicacion_desde={start_date.isoformat()}"
        f"&fecha_radicacion_hasta={end_date.isoformat()}"
    )


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

    return {
        "url": url,
        "measure": measure,
        "title": title,
        "full_text": text,
        "summary": summary,
    }


def post_to_zapier(session: requests.Session, hook_url: str, payload: Dict) -> None:
    print("[POST] Sending to Zapier")
    print(json.dumps(payload, ensure_ascii=False)[:600])

    r = session.post(hook_url, json=payload, timeout=25)

    print("[POST STATUS]", r.status_code)
    print(r.text[:500])

    r.raise_for_status()


def main():
    zapier_hook = os.environ.get("ZAPIER_HOOK_URL", "").strip()

    if not zapier_hook:
        print("Missing ZAPIER_HOOK_URL")
        return

    state_path = os.environ.get("STATE_PATH", "state.json")
    lookback_days = int(os.environ.get("LOOKBACK_DAYS", "3"))

    now = dt.datetime.now(dt.timezone.utc)
    now_iso = now.isoformat()

    session = requests.Session()
    state = load_state(state_path)
    seen = state["seen"]
    topics = build_topics()

    try:
        list_url = build_recent_days_url(lookback_days)
        print("[INFO] Using filtered URL:", list_url)

        html = http_get(session, list_url)
        links = extract_detail_links(html, BASE_URL)
        unique_links = list(dict.fromkeys(links))

        print("[INFO] Links found in date range:", len(unique_links))

        new_items = []

        for url in unique_links:
            try:
                detail_html = http_get(session, url)
            except Exception as e:
                print("[WARN] Error loading detail:", e)
                continue

            item = parse_detail_page(detail_html, url)
            combined = f"{item.get('title', '')} {item.get('full_text', '')}"
            hits = extract_keywords(combined, topics)

            if not hits:
                continue

            item_id = stable_id(item["url"], item["measure"], item["title"])

            if item_id in seen:
                print("[SEEN] Already processed:", item.get("measure", ""), item.get("title", ""))
                continue

            item["id"] = item_id
            item["hits"] = hits
            new_items.append(item)

        print("[INFO] New matches:", len(new_items))

        if new_items:
            for item in new_items:
                payload = {
                    "measure": item.get("measure", ""),
                    "title": item.get("title", ""),
                    "summary": item.get("summary", ""),
                    "hits": ", ".join(item.get("hits", [])),
                    "url": item.get("url", ""),
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
                "checked_at": now_iso,
                "is_empty": True,
                "status": "No new relevant measures found",
            }
            post_to_zapier(session, zapier_hook, payload)

    except Exception as e:
        print("[FATAL]", e)
        raise


if __name__ == "__main__":
    main()
