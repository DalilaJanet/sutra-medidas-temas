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
            print(f"[GET] {url} (attempt {i + 1})")
            r = session.get(url, timeout=timeout, verify=False)
            r.raise_for_status()
            print(f"[GET OK] {url} status={r.status_code} bytes={len(r.text)}")
            return r.text
        except Exception as e:
            last_err = e
            print(f"[GET ERROR] {url}: {e}")
            time.sleep(2 * (i + 1))
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

        if any(seg in full for seg in ("/proyectos/", "/resoluciones/", "/ordenanzas/", "/leyes/", "/medidas/")):
            links.append(full)

    seen = set()
    out = []
    for url in links:
        if url not in seen:
            seen.add(url)
            out.append(url)

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

    summary = ""
    if title:
        idx = text.lower().find(title.lower())
        if idx >= 0:
            summary = text[idx: idx + 700]

    if not summary:
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


def build_email_body_for_items(items: List[Dict]) -> str:
    lines = []
    lines.append("Saludos,")
    lines.append("")
    lines.append("Se identificaron nuevas medidas relevantes en SUTRA:")
    lines.append("")

    for it in items:
        measure = it.get("measure") or "(sin código detectado)"
        title = it.get("title") or "(sin título)"
        hits = ", ".join(it.get("hits", [])) or "(sin coincidencias detectadas)"
        url = it.get("url") or ""

        lines.append(f"- {measure} — {title}")
        lines.append(f"  Palabras clave: {hits}")
        if url:
            lines.append(f"  Enlace: {url}")
        lines.append("")

    lines.append("Atentamente,")
    return "\n".join(lines).strip()


def build_email_body_empty() -> str:
    return (
        "Saludos,\n\n"
        "Para el día de hoy no se encontraron proyectos relevantes "
        "relacionados con los criterios establecidos.\n\n"
        "Atentamente,"
    )


def post_to_zapier(session: requests.Session, hook_url: str, payload: Dict) -> None:
    print("[POST] Sending payload to Zapier...")
    print(json.dumps(payload, ensure_ascii=False, indent=2)[:4000])

    r = session.post(hook_url, json=payload, timeout=25)
    print(f"[POST RESPONSE] status={r.status_code}")
    print(r.text[:1000])

    r.raise_for_status()


def main():
    zapier_hook = (os.environ.get("ZAPIER_HOOK_URL") or "").strip()
    if not zapier_hook:
        raise SystemExit("Missing env var ZAPIER_HOOK_URL")

    state_path = os.environ.get("STATE_PATH", "state.json")
    keywords = (os.environ.get("KEYWORDS") or "").strip()
    kw_list = [k.strip() for k in keywords.split("|") if k.strip()] if keywords else DEFAULT_KEYWORDS
    max_details = int(os.environ.get("MAX_DETAILS", "80"))

    now_utc = dt.datetime.now(dt.timezone.utc)
    now_iso = now_utc.isoformat()

    session = requests.Session()
    session.headers.update({
        "User-Agent": "sutra-monitor/1.0 (contact: IT)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })

    try:
        state = load_state(state_path)
        seen = state["seen"]

        print("[INFO] Loading main medidas page...")
        list_html = http_get(session, SUTRA_MEDIDAS_URL)
        print(f"[INFO] HTML length from /medidas: {len(list_html)}")

        detail_links = extract_detail_links(list_html, "https://sutra.oslpr.org")
        print(f"[INFO] Detail links found: {len(detail_links)}")

        for link in detail_links[:20]:
            print(f"[LINK] {link}")

        new_matches: List[Dict] = []

        for url in detail_links[:max_details]:
            try:
                html = http_get(session, url)
            except Exception as e:
                print(f"[WARN] Skipping detail URL due to error: {url} -> {e}")
                continue

            item = parse_detail_page(html, url)
            combined = f"{item.get('title', '')} {item.get('full_text', '')}"
            hits = keyword_hits(combined, kw_list)

            if not hits:
                continue

            item_id = stable_id(item["url"], item.get("measure", ""), item.get("title", ""))
            if item_id in seen:
                print(f"[SEEN] Already processed: {item.get('measure', '')} {item.get('title', '')}")
                continue

            item["id"] = item_id
            item["hits"] = hits
            new_matches.append(item)

        print(f"[INFO] New relevant matches found: {len(new_matches)}")

        if new_matches:
            for item in new_matches:
                payload = {
                    "source": "sutra.oslpr.org",
                    "checked_at_utc": now_iso,
                    "measure": item.get("measure", ""),
                    "title": item.get("title", ""),
                    "summary": item.get("summary", ""),
                    "hits": ", ".join(item.get("hits", [])),
                    "url": item.get("url", ""),
                    "is_empty": False,
                    "error": False,
                    "status_message": "Nueva medida relevante encontrada",
                    "email_body": build_email_body_for_items([item]),
                }

                post_to_zapier(session, zapier_hook, payload)

                seen[item["id"]] = now_iso

            save_state(state_path, state)
            print("[INFO] state.json updated.")
        else:
            payload = {
                "source": "sutra.oslpr.org",
                "checked_at_utc": now_iso,
                "measure": "",
                "title": "",
                "summary": "",
                "hits": "",
                "url": "",
                "is_empty": True,
                "error": False,
                "status_message": "No se encontraron medidas relevantes hoy.",
                "email_body": build_email_body_empty(),
            }

            post_to_zapier(session, zapier_hook, payload)
            print("[INFO] Empty result notification sent to Zapier.")

    except Exception as e:
        error_payload = {
            "source": "sutra.oslpr.org",
            "checked_at_utc": now_iso,
            "measure": "",
            "title": "",
            "summary": "",
            "hits": "",
            "url": "",
            "is_empty": False,
            "error": True,
            "error_message": str(e),
            "status_message": "ERROR al intentar analizar SUTRA",
            "email_body": f"ERROR en el scraping de SUTRA:\n\n{str(e)}",
        }

        try:
            post_to_zapier(session, zapier_hook, error_payload)
        except Exception as post_err:
            print(f"[FATAL] Could not notify Zapier about error: {post_err}")

        raise


if __name__ == "__main__":
    main()
