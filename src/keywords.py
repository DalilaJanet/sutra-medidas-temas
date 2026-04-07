from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Pattern


@dataclass
class Topic:
    name: str
    patterns: List[Pattern[str]]


def build_topics() -> List[Topic]:
    return [
        Topic(
            name="Trabajadores",
            patterns=[
                re.compile(r"\btrabajador(?:es|as)?\b", re.IGNORECASE),
                re.compile(r"\bobrero(?:s|as)?\b", re.IGNORECASE),
                re.compile(r"\bempleado(?:s)?\b", re.IGNORECASE),
                re.compile(r"\bempleada(?:s)?\b", re.IGNORECASE),
                re.compile(r"\bempleoman[ií]a\b", re.IGNORECASE),
                re.compile(r"\bpersonal\b", re.IGNORECASE),
                re.compile(r"\blaboral(?:es)?\b", re.IGNORECASE),
                re.compile(r"\brelaciones?\s+laborales?\b", re.IGNORECASE),
                re.compile(r"\brecursos?\s+humanos?\b", re.IGNORECASE),
                re.compile(r"\bservidor(?:es)?\s+p[uú]blico(?:s)?\b", re.IGNORECASE),
                re.compile(r"\bfuncionario(?:s)?\b", re.IGNORECASE),
                re.compile(r"\bnombramiento(?:s)?\b", re.IGNORECASE),
                re.compile(r"\breclutamiento\b", re.IGNORECASE),
                re.compile(r"\bretenci[oó]n\s+de\s+empleados?\b", re.IGNORECASE),
                re.compile(r"\bsindicato(?:s)?\b", re.IGNORECASE),
                re.compile(r"\bsindical(?:es)?\b", re.IGNORECASE),
                re.compile(r"\bnegociaci[oó]n\s+colectiva\b", re.IGNORECASE),
                re.compile(r"\bconvenio(?:s)?\s+colectivo(?:s)?\b", re.IGNORECASE),
                re.compile(r"\bunionad[oa]s?\b", re.IGNORECASE),
            ],
        ),
        Topic(
            name="Salarios",
            patterns=[
                re.compile(r"\bsalario(?:s)?\b", re.IGNORECASE),
                re.compile(r"\bsueldo(?:s)?\b", re.IGNORECASE),
                re.compile(r"\bremuneraci[oó]n(?:es)?\b", re.IGNORECASE),
                re.compile(r"\bcompensaci[oó]n(?:es)?\b", re.IGNORECASE),
                re.compile(r"\bjornal(?:es)?\b", re.IGNORECASE),
                re.compile(r"\bpaga(?:s)?\b", re.IGNORECASE),
                re.compile(r"\bescala(?:s)?\s+salarial(?:es)?\b", re.IGNORECASE),
                re.compile(r"\baumento(?:s)?\s+salarial(?:es)?\b", re.IGNORECASE),
                re.compile(r"\bsalario\s+m[ií]nimo\b", re.IGNORECASE),
                re.compile(r"\bajuste\s+salarial\b", re.IGNORECASE),
            ],
        ),
        Topic(
            name="Departamento de Educación",
            patterns=[
                re.compile(r"\bdepartamento\s+de\s+educaci[oó]n\b", re.IGNORECASE),
                re.compile(r"\beducaci[oó]n\b", re.IGNORECASE),
                re.compile(r"\bmaestro(?:s|as)?\b", re.IGNORECASE),
                re.compile(r"\bdocente(?:s)?\b", re.IGNORECASE),
                re.compile(r"\bescuela(?:s)?\b", re.IGNORECASE),
            ],
        ),
        Topic(
            name="Municipio de San Juan",
            patterns=[
                re.compile(r"\bmunicipio\s+de\s+san\s+juan\b", re.IGNORECASE),
                re.compile(r"\bsan\s+juan\b", re.IGNORECASE),
                re.compile(r"\balcald[ií]a\s+de\s+san\s+juan\b", re.IGNORECASE),
            ],
        ),
    ]


def extract_keywords(text: str, topics: List[Topic]) -> List[str]:
    found = []

    if not text:
        return found

    for topic in topics:
        for pattern in topic.patterns:
            if pattern.search(text):
                found.append(topic.name)
                break

    return found
