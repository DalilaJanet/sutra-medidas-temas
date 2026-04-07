from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Pattern


@dataclass(frozen=True)
class Topic:
    name: str
    patterns: List[Pattern]


def build_topics() -> list[Topic]:
    # Patrones pensados para encontrar menciones explícitas (no “relaciones” implícitas).
    return [
        Topic(
            name="Departamento de Educación",
            patterns=[
                re.compile(r"\bDepartamento\s+de\s+Educaci[oó]n\b", re.IGNORECASE),
                re.compile(r"\bDEPR\b", re.IGNORECASE),
            ],
        ),
        Topic(
            name="Municipio de San Juan",
            patterns=[
                re.compile(r"\bMunicipio\s+de\s+San\s+Juan\b", re.IGNORECASE),
                re.compile(r"\bT[eé]rmino\s+Municipal\s+de\s+San\s+Juan\b", re.IGNORECASE),
                re.compile(r"\bSan\s+Juan\b", re.IGNORECASE),
            ],
        ),
        Topic(
            name="Trabajadores",
            patterns=[
                re.compile(r"\btrabajador(?:es|as)?\b", re.IGNORECASE),
                re.compile(r"\bobrero(?:s|as)?\b", re.IGNORECASE),
                re.compile(r"\bempleado(?:s)?\b", re.IGNORECASE),
                re.compile(r"\bempleada(?:s)?\b", re.IGNORECASE),
                re.compile(r"\bservidor(?:es)?\s+p[uú]blico(?:s)?\b", re.IGNORECASE),
                re.compile(r"\bpersonal\b", re.IGNORECASE),
                re.compile(r"\blaboral(?:es)?\b", re.IGNORECASE),
                re.compile(r"\brecursos?\s+humanos?\b", re.IGNORECASE),
                re.compile(r"\bsindicato(?:s)?\b", re.IGNORECASE),
                re.compile(r"\bnegociaci[oó]n\s+colectiva\b", re.IGNORECASE),
            ],
        ),
        Topic(
            name="Salarios",
            patterns=[
                re.compile(r"\bsalario(?:s)?\b", re.IGNORECASE),
                re.compile(r"\bremuneraci[oó]n(?:es)?\b", re.IGNORECASE),
                re.compile(r"\bjornal(?:es)?\b", re.IGNORECASE),
            ],
        ),
    ]


def extract_keywords(text: str, topics: Iterable[Topic]) -> list[str]:
    found: set[str] = set()
    for topic in topics:
        for pat in topic.patterns:
            if pat.search(text or ""):
                found.add(topic.name)
                break
    return sorted(found)
