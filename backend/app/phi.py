"""Filtro heurístico de datos identificativos (PHI) en español.

IMPORTANTE: es una red de seguridad, no una garantía. Detecta patrones estructurados (DNI/NIE, correo,
teléfono, fechas completas, nº de historia) y nombres tras 'paciente/Sr./Sra./D./Dña.'. Los nombres
dentro de texto libre sin esos indicadores NO se detectan.
No se redactan edades, años sueltos, ni cifras clínicas."""
from __future__ import annotations

import re

_NAME = r"[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){0,2}"
_MONTHS = r"(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)"
DNI_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"

# (tipo, patrón, marcador)
_RULES: list[tuple[str, re.Pattern[str], str]] = [
    ("correo", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[CORREO]"),
    ("DNI/NIE", re.compile(rf"(?<![\w])(?:\d{{8}}[- ]?[{DNI_LETTERS}]|[XYZ][- ]?\d{{7}}[- ]?[{DNI_LETTERS}])(?![\w])", re.I), "[DNI]"),
    ("nº de historia", re.compile(
        r"(?<![\w])(?:NHC|HC|SIP|CIP|historia\s+cl[ií]nica)(?![\w])\W{0,4}(?:n[ºo°]\W{0,3})?(?=[A-Z0-9]*\d)[A-Z0-9]{5,}", re.I), "[Nº HISTORIA]"),
    ("fecha", re.compile(
        rf"(?<![\w])(?:\d{{1,2}}[/.-]\d{{1,2}}[/.-](?:19|20)\d{{2}}|(?:19|20)\d{{2}}-\d{{2}}-\d{{2}}"
        rf"|\d{{1,2}}\s+de\s+{_MONTHS}\s+de\s+(?:19|20)\d{{2}})(?![\w])", re.I), "[FECHA]"),
    ("teléfono", re.compile(r"(?<![\w.,])(?:\+34[\s-]?)?[6-9]\d{2}[\s.-]?\d{3}[\s.-]?\d{3}(?![\w])"), "[TELÉFONO]"),
]
_NAME_RULE = re.compile(rf"(?<![\w/])((?i:paciente|sr\.?|sra\.?|doña|dña\.?))\s+{_NAME}(?![\w])")
# 'D.' (p. ej. 'vitamina D. En pacientes') y 'Don' son ambiguos: exigen al menos dos palabras con mayúscula
_NAME_WEAK = re.compile(rf"(?<![\w/])((?i:don|d\.))\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){{1,2}}(?![\w])")


def redact(text: str) -> tuple[str, list[str]]:
    """Devuelve (texto redactado, tipos de dato eliminados sin repetir)."""
    kinds: list[str] = []

    def note(k: str):
        if k not in kinds:
            kinds.append(k)

    for kind, pat, marker in _RULES:
        def sub(m: re.Match[str], kind=kind, marker=marker) -> str:
            if kind == "teléfono" and "pmid" in text[max(0, m.start() - 8):m.start()].lower():
                return m.group(0)  # un PMID de 9 cifras no es un teléfono
            note(kind)
            return marker

        text = pat.sub(sub, text)

    def name_sub(m: re.Match[str]) -> str:
        note("nombre")
        return f"{m.group(1)} [NOMBRE]"

    text = _NAME_RULE.sub(name_sub, text)
    text = _NAME_WEAK.sub(name_sub, text)
    return text, kinds
