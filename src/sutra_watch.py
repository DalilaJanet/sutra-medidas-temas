import os
import re
import json
import time
import hashlib
import datetime as dt
from typing import List, Dict
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SUTRA_MEDIDAS_URL = "https://sutra.oslpr.org/medidas"

DEFAULT_KEYWORDS = [
    "Departamento de Educación",
    "Municipio de San Juan",
    "salario",
    "trabajadores",
]

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

    for i in range(3):
        try:
            print(f"[GET] {url}")
            r = session.get(url, timeout=timeout, verify=False)
            r.raise_for_status()
            return r.text
        except Exception as e:
            last_err = e
            print(f"[GET ERROR] {e}")
            time.sleep(2)

    raise RuntimeError(f"GET failed for {url}: {last_err}")


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

    # quitar duplicados
    seen = set()
    out = []

    for u in links:
        if u not in seen:
            seen.add(u)
            out.append(u)

    return out


def parse_detail_page(detail_html: str, url: str) -> Dict:

    soup = BeautifulSoup(detail_html, "lxml")
    text = soup.get_text(" ", strip=True)

    m = MEASURE_CODE_RE.search(text)

    measure = m.group(0).upper().replace(" ", "") if m else ""

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


def keyword_hits(text: str, keywords: List[str]) -> List[str]:

    t = text.lower()

    hits = []

    for kw in keywords:
        if kw.lower() in t:
            hits.append(kw)

    return hits


def post_to_zapier(session, hook, payload):

    print("[POST] Sending to Zapier")
    print(json.dumps(payload)[:500])

    r = session.post(hook, json=payload, timeout=25)

    print("[POST STATUS]", r.status_code)

    return r.status_code


def main():

    zapier_hook = os.environ.get("ZAPIER_HOOK_URL", "").strip()

    if not zapier_hook:
        print("Missing ZAPIER_HOOK_URL")
        return

    state_path = os.environ.get("STATE_PATH", "state.json")

    kw_list = DEFAULT_KEYWORDS

    now = dt.datetime.now(dt.timezone.utc).isoformat()

    session = requests.Session()

    session.headers.update(
        {
            "User-Agent": "sutra-monitor",
        }
    )

    try:

        state = load_state(state_path)
        seen = state["seen"]

        print("Downloading medidas page...")

        list_html = http_get(session, SUTRA_MEDIDAS_URL)

        print("HTML size:", len(list_html))

        links = extract_detail_links(list_html, "https://sutra.oslpr.org")

        print("Detail links found:", len(links))

        new_items = []

        for url in links[:80]:

            try:
                html = http_get(session, url)
            except Exception:
                continue

            item = parse_detail_page(html, url)

            combined = item["title"] + " " + item["full_text"]

            hits = keyword_hits(combined, kw_list)

            if not hits:
                continue

            item_id = stable_id(item["url"], item["measure"], item["title"])

            if item_id in seen:
                continue

            item["id"] = item_id
            item["hits"] = hits

            new_items.append(item)

        print("New matches:", len(new_items))

        if new_items:

            for item in new_items:

                payload = {
                    "measure": item.get("measure", ""),
                    "title": item.get("title", ""),
                    "summary": item.get("summary", ""),
                    "hits": ", ".join(item.get("hits", [])),
                    "url": item.get("url", ""),
                    "checked_at": now,
                    "is_empty": False,
                }

                post_to_zapier(session, zapier_hook, payload)

                seen[item["id"]] = now

            save_state(state_path, state)

        else:

            payload = {
                "measure": "",
                "title": "",
                "summary": "",
                "hits": "",
                "url": "",
                "checked_at": now,
                "is_empty": True,
                "status": "No relevant measures found today",
            }

            post_to_zapier(session, zapier_hook, payload)

    except Exception as e:

        print("ERROR:", str(e))

        payload = {
            "error": True,
            "message": str(e),
            "checked_at": now,
        }

        try:
            post_to_zapier(session, zapier_hook, payload)
        except:
            pass


if __name__ == "__main__":
    main()
