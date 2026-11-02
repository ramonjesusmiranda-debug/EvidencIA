from __future__ import annotations

import hashlib
import logging
import os
from urllib.parse import urlparse

import re
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, SecretStr, StringConstraints

from .llm import LLM, ClaudeLLM, LLMError, OllamaLLM, make_llm
from .phi import redact
from .pubmed import Article, PubMedClient
from .verify import CITE, verify

log = logging.getLogger("evidencia")
app = FastAPI(title="EvidencIA API")

DISCLAIMER = (
    "Herramienta de apoyo a la decisión basada en resúmenes de PubMed. No sustituye el juicio clínico, "
    "las guías locales ni la ficha técnica. No introduzcas datos identificativos de pacientes."
)
INSUFFICIENT_MSG = "No he encontrado evidencia suficiente en PubMed para responder con fiabilidad a esta pregunta."

_pubmed: PubMedClient | None = None
_llm: LLM | None = None


def get_pubmed() -> PubMedClient:
    global _pubmed
    _pubmed = _pubmed or PubMedClient()
    return _pubmed


def get_llm() -> LLM:
    global _llm
    _llm = _llm or make_llm()
    return _llm


def check_token(x_app_token: str | None = Header(default=None)):
    expected = os.getenv("APP_TOKEN")
    if expected and x_app_token != expected:
        raise HTTPException(401, "token inválido")


class LLMConfig(BaseModel):
    """Configuración de modelo enviada por la app. Si falta algún campo se usa el del servidor."""
    provider: Literal["claude", "ollama"]
    api_key: SecretStr | None = None  # solo claude
    model: str | None = Field(default=None, max_length=100)
    ollama_host: str | None = Field(default=None, max_length=200)  # solo ollama; relativo al SERVIDOR


Pmid = Annotated[str, StringConstraints(pattern=r"^\d{1,9}$")]  # va a la URL de efetch: solo dígitos


class HistoryTurn(BaseModel):
    # límites holgados a propósito: se TRUNCA en _clean_history; rechazar rompería toda la conversación
    question: str = Field(max_length=2000)
    answer: str = Field(default="", max_length=20000)
    pmids: list[Pmid] = Field(default_factory=list, max_length=10)  # fuentes citadas en ese turno


class AskRequest(BaseModel):
    question: str = Field(min_length=5, max_length=1000)
    history: list[HistoryTurn] = Field(default_factory=list, max_length=20)
    llm: LLMConfig | None = None


_LLM_CACHE: dict[tuple, LLM] = {}
_LOOPBACK = {"localhost", "127.0.0.1", "::1"}


def build_llm(cfg: LLMConfig) -> LLM:
    """Construye (y cachea) el LLM pedido. ValueError -> 400 con mensaje seguro."""
    key = cfg.api_key.get_secret_value() if cfg.api_key else ""
    ident = (cfg.provider, cfg.ollama_host or "", cfg.model or "", hashlib.sha256(key.encode()).hexdigest())
    if ident in _LLM_CACHE:
        return _LLM_CACHE[ident]
    if cfg.provider == "ollama":
        host = cfg.ollama_host or None
        if host:
            u = urlparse(host)
            if u.scheme not in ("http", "https") or not u.hostname:
                raise ValueError("Dirección de Ollama no válida")
            if u.hostname not in _LOOPBACK and not os.getenv("APP_TOKEN"):
                raise ValueError("Un Ollama remoto exige definir APP_TOKEN en el servidor")
        llm: LLM = OllamaLLM(host=host, model=cfg.model or None)
    else:
        if not key and not os.getenv("ANTHROPIC_API_KEY"):
            raise ValueError("Falta la clave de API (ni en la app ni en el servidor)")
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=key) if key else None  # None -> ANTHROPIC_API_KEY del servidor
        llm = ClaudeLLM(client=client, model=cfg.model) if cfg.model else ClaudeLLM(client=client)
    if len(_LLM_CACHE) >= 8:
        _LLM_CACHE.pop(next(iter(_LLM_CACHE)))
    _LLM_CACHE[ident] = llm
    return llm


def _llm_from_request(cfg: LLMConfig) -> LLM:
    if os.getenv("ALLOW_CLIENT_LLM_CONFIG", "1") != "1":
        raise HTTPException(403, "El servidor no admite configuración de modelo desde la app")
    try:
        return build_llm(cfg)
    except ValueError as e:
        raise HTTPException(400, str(e))


class CheckRequest(BaseModel):
    llm: LLMConfig


@app.post("/check", dependencies=[Depends(check_token)])
async def check(req: CheckRequest):
    """Valida la configuración de modelo (Ollama alcanzable + modelo descargado / clave y modelo válidos)."""
    try:
        return {"ok": True, "message": await _llm_from_request(req.llm).check()}
    except LLMError as e:
        raise HTTPException(502, str(e))


class Citation(BaseModel):
    n: int
    pmid: str
    title: str
    journal: str
    year: str
    study_type: str
    url: str


class AskResponse(BaseModel):
    answer: str
    insufficient_evidence: bool
    citations: list[Citation]
    pubmed_query: str
    omitted_unverified: int = 0
    question_used: str = ""  # pregunta tras el filtro de datos identificativos
    redactions: list[str] = Field(default_factory=list)  # tipos de dato eliminados
    standalone_question: str = ""  # cómo se interpretó la pregunta con el contexto
    disclaimer: str = DISCLAIMER


@app.get("/health")
def health():
    return {"ok": True}


MAX_SOURCES = 10
ANSWER_TURNS = 3  # solo los últimos turnos aportan su respuesta al contexto
PRIOR_TURNS = 2  # de cuántos turnos se reutilizan las fuentes citadas
MAX_STANDALONE = 400


def _clean_history(turns: list[HistoryTurn]) -> list[tuple[str, str]]:
    """Redacta, quita marcadores [n] (su numeración no vale en el turno actual) y acota el tamaño."""
    out = []
    recent = len(turns) - ANSWER_TURNS
    for i, t in enumerate(turns[-8:], start=len(turns) - len(turns[-8:])):
        q = redact(t.question)[0][:1000]
        a = ""
        if i >= recent and t.answer:
            a, _ = redact(CITE.sub("", t.answer))
            a = re.sub(r"[ \t]+", " ", a).strip()[:1500]
        out.append((q, a))
    return out


_PREFIX = re.compile(r"^\s*(?:pregunta\s+(?:reescrita|aut[oó]noma|completa)|reescritura|pregunta)\s*:\s*", re.I)


def _clean_standalone(s: str) -> str:
    """Los modelos pequeños suelen anteponer 'Pregunta reescrita:' o entrecomillar."""
    return _PREFIX.sub("", s.strip()).strip().strip("\"'«»“”")


def _standalone_ok(s: str) -> bool:
    s = s.strip()
    return bool(s) and len(s) <= MAX_STANDALONE and "\n" not in s and not CITE.search(s)


def merge_sources(new: list[Article], prior: list[Article], cap: int = MAX_SOURCES, new_first: int = 6) -> list[Article]:
    """Mezcla sin duplicados: primero lo más relevante de la nueva búsqueda, luego las fuentes de turnos previos."""
    seen: set[str] = set()
    out: list[Article] = []

    def add(items):
        for a in items:
            if a.pmid not in seen and len(out) < cap:
                seen.add(a.pmid)
                out.append(a)

    add(new[:new_first])
    add(prior)
    add(new[new_first:])
    return out


def _response(query: str, q: str, kinds: list[str], standalone: str, **kw) -> AskResponse:
    return AskResponse(pubmed_query=query, question_used=q, redactions=kinds, standalone_question=standalone, **kw)


@app.post("/ask", response_model=AskResponse, dependencies=[Depends(check_token)])
async def ask(req: AskRequest, pubmed: PubMedClient = Depends(get_pubmed), llm: LLM = Depends(get_llm)):
    if req.llm is not None:
        llm = _llm_from_request(req.llm)
    # 1. Filtro de datos identificativos ANTES de cualquier llamada externa. Nunca se registra la pregunta.
    q, kinds = redact(req.question)
    hist = _clean_history(req.history)
    prior_pmids = list(dict.fromkeys(p for t in req.history[-PRIOR_TURNS:] for p in t.pmids))[:6]

    try:
        # 2. Pregunta autónoma si hay contexto
        standalone = q
        if hist:
            cand = _clean_standalone(await llm.condense(q, hist))
            standalone = cand if _standalone_ok(cand) else f"{hist[-1][0]} — {q}"
        # 3-4. Consulta PubMed + fuentes de turnos previos
        query = await llm.to_pubmed_query(standalone)
        new = await pubmed.retrieve(query)
        prior: list[Article] = []
        if prior_pmids:
            try:
                prior = await pubmed.fetch(prior_pmids)
            except Exception:
                log.warning("no se pudieron recuperar las fuentes previas")
        sources = merge_sources(new, prior)
    except LLMError as e:
        raise HTTPException(502, str(e))
    except Exception:
        log.exception("consulta de evidencia falló")
        raise HTTPException(502, "No se pudo consultar la evidencia")

    def insufficient() -> AskResponse:
        return _response(query, q, kinds, standalone, answer=INSUFFICIENT_MSG, insufficient_evidence=True, citations=[])

    if not sources:
        return insufficient()

    # 5. Respuesta (el historial se rotula como "no fuente")
    try:
        draft = await llm.answer(standalone, sources, history=hist or None)
    except LLMError as e:
        raise HTTPException(502, str(e))
    except Exception:
        log.exception("LLM falló")
        raise HTTPException(502, "No se pudo generar la respuesta")
    # 6. Verificación solo contra las fuentes actuales
    v = verify(draft, sources)
    if v.dropped:  # 7. un reintento indicando qué se rechazó, con el mismo contexto
        try:
            v2 = verify(await llm.answer(standalone, sources, rejected=v.dropped, history=hist or None), sources)
            if len(v2.dropped) < len(v.dropped) or (v2.used and not v.used):
                v = v2
        except Exception:
            log.warning("reintento falló; se usa el primer intento")
    if v.dropped:
        log.info("frases descartadas por verificación: %d", len(v.dropped))
    if v.insufficient:
        return insufficient()

    cites = [
        Citation(
            n=i, pmid=sources[i - 1].pmid, title=sources[i - 1].title, journal=sources[i - 1].journal,
            year=sources[i - 1].year, study_type=", ".join(sources[i - 1].pub_types), url=sources[i - 1].url,
        )
        for i in v.used
    ]
    return _response(query, q, kinds, standalone, answer=v.text, insufficient_evidence=False, citations=cites,
                     omitted_unverified=len(v.dropped))
