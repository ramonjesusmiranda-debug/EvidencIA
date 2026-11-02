"""Prueba de humo REAL (necesita red a eutils.ncbi.nlm.nih.gov y ANTHROPIC_API_KEY (o LLM_BACKEND=ollama con Ollama en marcha)).
Uso:  cd backend && .venv/bin/python -m scripts.smoke
Comprueba: (1) las citas devueltas están entre las fuentes recuperadas, (2) la pregunta absurda da 'insuficiente'."""
import asyncio
import sys

from app.llm import make_llm
from app.pubmed import PubMedClient
from app.verify import CITE, verify

QS = [
    ("¿Los iSGLT2 reducen hospitalización en insuficiencia cardiaca con FEVI reducida?", False),
    ("¿Anticoagulación en fibrilación auricular con CHA2DS2-VASc ≥2?", False),
    ("¿Eficacia de metformina en prevención de diabetes tipo 2 en prediabetes?", False),
    ("¿Qué dosis de cristales de cuarzo cura la sepsis neonatal?", True),  # debe ser insuficiente
]


async def main() -> int:
    llm, pm, fails = make_llm(), PubMedClient(), 0
    for q, expect_insufficient in QS:
        query = await llm.to_pubmed_query(q)
        src = await pm.retrieve(query)
        v = verify(await llm.answer(q, src), src) if src else None
        insufficient = v is None or v.insufficient
        print(f"\n### {q}\nPubMed: {query}\nfuentes: {[a.pmid for a in src]}")
        print("INSUFICIENTE" if insufficient else v.text, f"| omitidas: {len(v.dropped) if v else 0}")
        if insufficient != expect_insufficient:
            print("  !! resultado inesperado"); fails += 1
    # Contexto: pregunta de seguimiento (la única prueba real de la reescritura con historial)
    q1, q2 = "¿Los iSGLT2 reducen hospitalización en insuficiencia cardiaca con FEVI reducida?", "¿y con enfermedad renal crónica avanzada?"
    src = await pm.retrieve(await llm.to_pubmed_query(q1))
    a1 = verify(await llm.answer(q1, src), src).text if src else ""
    standalone = await llm.condense(q2, [(q1, CITE.sub("", a1))])
    print(f"\n### SEGUIMIENTO\nPregunta: {q2}\nInterpretada como: {standalone}")
    if not standalone or len(standalone) > 400:
        print("  !! reescritura inservible"); fails += 1
    return fails


sys.exit(asyncio.run(main()))
