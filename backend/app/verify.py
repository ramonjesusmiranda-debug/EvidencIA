"""Verificación determinista de la respuesta. Es la barrera real contra alucinaciones:
no confiamos en que el LLM cite bien, lo comprobamos."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .pubmed import Article

CITE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
NUM = re.compile(r"\d+(?:[.,]\d+)?")
INSUFFICIENT = "EVIDENCIA_INSUFICIENTE"


@dataclass
class Verified:
    text: str
    used: list[int]  # índices 1-based de fuentes realmente citadas
    dropped: list[str]
    insufficient: bool


def _split(text: str) -> list[str]:
    # separa por líneas y luego por frases; conserva viñetas
    parts: list[str] = []
    for line in text.splitlines():
        line = line.rstrip()
        if not line:
            parts.append("")
            continue
        parts.extend(s for s in re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ¿¡\-\*•\d])", line) if s)
    return parts


def _numbers(s: str) -> set[str]:
    s = CITE.sub("", s)
    return {n.replace(",", ".") for n in NUM.findall(s)}


def verify(answer: str, sources: list[Article]) -> Verified:
    """Reglas:
    1. Toda frase afirmativa debe llevar [n] con n existente; si no, se elimina.
    2. Cada cifra de la frase debe aparecer en el texto de alguna fuente citada
       (evita estadísticas inventadas); si no, se elimina.
    3. Si no sobrevive ninguna afirmación -> evidencia insuficiente.
    """
    if INSUFFICIENT in answer:
        return Verified("", [], [], True)

    n_src = len(sources)
    kept: list[str] = []
    dropped: list[str] = []
    used: set[int] = set()

    for sent in _split(answer):
        if not sent.strip():
            kept.append("")
            continue
        cites = [int(x) for m in CITE.finditer(sent) for x in re.split(r"\s*,\s*", m.group(1))]
        body = CITE.sub("", sent).strip(" -*•\t")
        # solo se admiten sin cita los encabezados puros (sin cifras)
        if not cites:
            is_header = sent.lstrip().startswith("#") or body.endswith(":") or re.fullmatch(r"\*\*[^*]+\*\*:?", body)
            if is_header and not NUM.search(body):
                kept.append(sent)
            else:
                dropped.append(sent)
            continue
        if any(c < 1 or c > n_src for c in cites):
            dropped.append(sent)
            continue
        corpus = " ".join(
            f"{sources[c-1].title} {sources[c-1].abstract} {sources[c-1].journal} {sources[c-1].year}"
            for c in cites
        ).replace(",", ".")
        if not _numbers(sent) <= set(NUM.findall(corpus)):
            dropped.append(sent)
            continue
        used.update(cites)
        kept.append(sent)

    text = "\n".join(kept).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    if not used:
        return Verified("", [], dropped, True)
    return Verified(text, sorted(used), dropped, False)
