from __future__ import annotations

import argparse
import json
import os
import re
import time
from dataclasses import asdict, dataclass
from typing import Iterator
from urllib.parse import urljoin
import urllib3
from urllib3.exceptions import InsecureRequestWarning

urllib3.disable_warnings(InsecureRequestWarning)
import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
from tqdm import tqdm

from keywords import build_topics, extract_keywords


BASE = "https://sutra.oslpr.org"
LIST_URL = "https://sutra.oslpr.org/medidas"

UA = "sutra-topic-scraper/1.1 (+https://github.com/<TU_ORG>/<TU_REPO>)"

# ✅ Aquí NO pegues la URL hardcodeada.
# Pásala por variable de entorno (local o GitHub Secrets).
ZAPIER_WEBHOOK_URL = os.getenv("ZAPIER_WEBHOOK_URL")


@dataclass
class Measure:
    url: str
    numero_o_nombre: str
    titulo_completo: str
    fecha_radicacion: str
    resumen_breve: str
    palabras_clave: list[str]


def http_get(session: requests.Session, url: str, timeout: int = 30, verify: bool = True) -> str:
    r = session.get(url, timeout=timeout, verify=verify)
    r.raise_for_status()
    return r.text
    
def is_sutra(url: str) -> bool:
    return url.startswith("https://sutra.oslpr.org")

def find_detail_links(list_html: str) -> list[str]:
    soup = BeautifulSoup(list_html, "lxml")
    links: set[str] = set()

    # Busca anchors que apunten a /medidas/<id>
    for a in soup.select("a[href]"):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        if re.search(r"^/medidas/\d+", href):
            links.add(urljoin(BASE, href))

    return sorted(links)


def parse_measure_detail(detail_html: str, url: str) -> tuple[str, str, str]:
    """
    Devuelve (numero_o_nombre, fecha_radicacion, titulo_completo)
    usando texto plano para robustez ante cambios de HTML.
    """
    text = BeautifulSoup(detail_html, "lxml").get_text("\n", strip=True)

    # Número / código (fallbacks)
    numero = ""
    m = re.search(
        r"\b(?:Proyecto|Resoluci[oó]n|Resoluci[oó]n\s+Conjunta|Ley)\b.*?\(([^)]+)\)",
        text,
        re.IGNORECASE,
    )
    if m:
        numero = m.group(1).strip()
    else:
        m2 = re.search(r"\b(?:PS|PC|RC|RS|RCS|RCC)\s*0*\d{1,4}\b", text)
        numero = m2.group(0).replace(" ", "") if m2 else "N/D"

    # Fecha de radicación (formato típico mm/dd/yyyy)
    fecha = "N/D"
    m = re.search(
        r"Fecha\s+de\s+Radicaci[oó]n:\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})",
        text,
        re.IGNORECASE,
    )
    if m:
        fecha = m.group(1).strip()
    else:
        m2 = re.search(
            r"Radicado\s+Fecha:\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})",
            text,
            re.IGNORECASE,
        )
        if m2:
            fecha = m2.group(1).strip()

    # Título
    titulo = "N/D"
    m = re.search(
        r"T[ií]tulo:\s*[“\"]?(.+?)(?:[”\"]?\s*(?:Eventos|Autores|Documentos|Radicado\s+Fecha:|$))",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        titulo = " ".join(m.group(1).split())

    return numero, fecha, titulo


def normalize_date_mmddyyyy(s: str) -> str:
    try:
        dt = dateparser.parse(s, dayfirst=False, yearfirst=False)
        return dt.date().isoformat()
    except Exception:
        return s


def brief_summary_from_title(title: str) -> str:
    """
    Resumen 2–4 oraciones basado en el título (sin LLM).
    """
    if not title or title == "N/D":
        return "Resumen no disponible por falta de título."
    first = title.strip().rstrip(".")
    return (
        f"Esta medida propone lo siguiente: {first}. "
        "El detalle completo debe validarse en el texto oficial radicado y sus enmiendas, según aplique."
    )


def iter_list_pages(session: requests.Session, max_pages: int, delay_s: float, timeout: int) -> Iterator[str]:
    for p in range(1, max_pages + 1):
        url = f"{LIST_URL}?page={p}"
        html = http_get(session, url, timeout=timeout, verify=not is_sutra(url))
        yield html
        if delay_s:
            time.sleep(delay_s)


# ✅ Envío a Zapier (1 POST por medida)
def send_to_zapier(measure: Measure) -> None:
    if not ZAPIER_WEBHOOK_URL:
        return

    payload = {
        "id_unico": measure.numero_o_nombre,
        "numero_o_nombre": measure.numero_o_nombre,
        "titulo_completo": measure.titulo_completo,
        "fecha_radicacion": measure.fecha_radicacion,
        "resumen_breve": measure.resumen_breve,
        "palabras_clave": measure.palabras_clave,
        "url": measure.url,
    }

    try:
        r = requests.post(ZAPIER_WEBHOOK_URL, json=payload, timeout=20)
        if r.status_code >= 400:
            print(f"[WARN] Zapier HTTP {r.status_code}: {r.text[:300]}")
    except Exception as e:
        print(f"[WARN] Error enviando a Zapier ({measure.numero_o_nombre}): {e}")


def scrape(max_pages: int, delay_s: float, timeout: int, output_path: str) -> list[Measure]:
    topics = build_topics()
    session = requests.Session()
    session.headers.update({"User-Agent": UA})

    detail_urls: set[str] = set()

    # 1) Recopilar URLs de detalle desde las páginas de listado
    for list_html in tqdm(
        iter_list_pages(session, max_pages=max_pages, delay_s=delay_s, timeout=timeout),
        total=max_pages,
        desc="List pages",
    ):
        for u in find_detail_links(list_html):
            detail_urls.add(u)

    results: list[Measure] = []

    # 2) Visitar detalle, extraer campos, filtrar por keywords explícitas
    for url in tqdm(sorted(detail_urls), desc="Detail pages"):
        try:
            detail_html = http_get(session, url, timeout=timeout, verify=not is_sutra(url))
        except Exception:
            continue

        numero, fecha, titulo = parse_measure_detail(detail_html, url)
        keywords = extract_keywords(f"{numero}\n{titulo}\n{detail_html}", topics)

        # ✅ Filtra: solo si menciona explícitamente algún tema
        if not keywords:
            continue

        measure = Measure(
            url=url,
            numero_o_nombre=numero,
            titulo_completo=titulo,
            fecha_radicacion=normalize_date_mmddyyyy(fecha),
            resumen_breve=brief_summary_from_title(titulo),
            palabras_clave=keywords,
        )

        results.append(measure)

        # ✅ Enviar a Zapier en el momento
        send_to_zapier(measure)

        if delay_s:
            time.sleep(delay_s)

    # 3) Guardar JSON local en el repo (para histórico/backup)
    payload = [asdict(r) for r in results]
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-pages", type=int, default=25)
    ap.add_argument("--delay", type=float, default=0.25)
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--out", type=str, default="data/medidas_filtradas.json")
    args = ap.parse_args()

    if ZAPIER_WEBHOOK_URL:
        print("[INFO] ZAPIER_WEBHOOK_URL configurado: enviando resultados a Zapier.")
    else:
        print("[INFO] ZAPIER_WEBHOOK_URL NO configurado: solo se guardará el JSON.")

    results = scrape(
        max_pages=args.max_pages,
        delay_s=args.delay,
        timeout=args.timeout,
        output_path=args.out,
    )
    print(f"OK: {len(results)} medidas guardadas en {args.out}")


if __name__ == "__main__":
    main()
