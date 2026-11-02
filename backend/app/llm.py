"""Proveedores de LLM (Claude / Ollama). El modelo de Claude se configura con EVIDENCIA_MODEL."""
from __future__ import annotations

import os
import re
from typing import Protocol

import anthropic
import httpx
from anthropic import AsyncAnthropic

from .pubmed import Article
from .verify import INSUFFICIENT

MODEL = os.getenv("EVIDENCIA_MODEL", "claude-opus-5-5")

QUERY_SYSTEM = (
    "Convierte una pregunta clínica (cualquier idioma) en UNA consulta de PubMed en inglés. "
    "Usa términos MeSH/[tiab] y operadores AND/OR. Añade filtros de diseño solo si encajan "
    "(p. ej. AND (guideline[pt] OR meta-analysis[pt] OR randomized controlled trial[pt])). "
    "Responde solo con la consulta, sin explicación."
)

CONDENSE_SYSTEM = (
    "Recibes una conversación clínica previa y una pregunta de seguimiento que puede depender de ella "
    "(p. ej. '¿y en mayores de 75?'). Reescríbela como UNA pregunta clínica autónoma y completa, en el mismo idioma, "
    "conservando población, intervención, comparador y desenlace mencionados antes cuando sigan siendo relevantes. "
    "No añadas información nueva ni respondas. Si ya es autónoma, devuélvela igual. "
    "Responde solo con la pregunta, en una línea."
)

ANSWER_SYSTEM = f"""Eres un asistente de apoyo a la decisión clínica para profesionales sanitarios.
Respondes ÚNICAMENTE con la información de las FUENTES numeradas que se te dan. No uses conocimiento propio.

Reglas estrictas:
- Cada afirmación clínica termina con su cita [n] (o [n, m]). Sin cita, no se afirma.
- Copia las cifras (HR, IC, %, dosis) tal cual aparecen en la fuente; nunca las calcules ni las redondees.
- Indica el diseño del estudio y la población cuando las fuentes lo permitan; no extrapoles a otras poblaciones.
- Si las fuentes se contradicen, di que hay discrepancia y cita ambas.
- Si las fuentes no responden a la pregunta, responde exactamente: {INSUFFICIENT}
- Si se incluye una CONVERSACIÓN PREVIA, úsala solo para entender a qué se refiere la pregunta. NO es una fuente:
  no afirmes nada que solo aparezca ahí y no uses sus números de cita; cita únicamente las FUENTES actuales.
- Responde en el idioma de la pregunta, de forma concisa (máx. ~200 palabras): una frase de respuesta directa y luego viñetas con la evidencia."""

History = list[tuple[str, str]]  # (pregunta, respuesta) ya redactadas y sin marcadores [n]


class LLMError(Exception):
    """Fallo del proveedor con mensaje apto para mostrar al usuario (nunca incluye claves)."""


class LLMUnusable(LLMError):
    """El modelo respondió pero sin salida utilizable (rechazo / truncado)."""


def clean_query(raw: str) -> str:
    q = re.sub(r"```\w*", "", raw).replace("```", "").strip()
    q = re.sub(r"^(query|consulta)\s*:\s*", "", q, flags=re.I).strip().strip("\"'`")
    return " ".join(q.split())


def format_sources(sources: list[Article]) -> str:
    return "\n\n".join(
        f"[{i}] {a.title} ({a.journal}, {a.year}; {', '.join(a.pub_types) or 'tipo n/d'}; PMID {a.pmid})\n{a.abstract}"
        for i, a in enumerate(sources, 1)
    )


def format_history(history: History) -> str:
    lines = []
    for q, a in history:
        lines.append(f"P: {q}")
        if a:
            lines.append(f"R: {a}")
    return "\n".join(lines)


class LLM(Protocol):
    async def condense(self, question: str, history: History) -> str: ...
    async def to_pubmed_query(self, question: str) -> str: ...
    async def answer(
        self, question: str, sources: list[Article], rejected: list[str] | None = None, history: History | None = None
    ) -> str: ...
    async def check(self) -> str: ...


class _BaseLLM:
    """Prompts compartidos; cada proveedor implementa _gen y check."""

    async def _gen(self, system: str, user: str, kind: str) -> str:  # kind: query | condense | answer
        raise NotImplementedError

    async def condense(self, question: str, history: History) -> str:
        user = f"CONVERSACIÓN PREVIA:\n{format_history(history)}\n\nPREGUNTA DE SEGUIMIENTO: {question}"
        try:
            return (await self._gen(CONDENSE_SYSTEM, user, "condense")).strip()
        except LLMUnusable:
            return ""  # el llamador usa su propio fallback

    async def to_pubmed_query(self, question: str) -> str:
        try:
            raw = await self._gen(QUERY_SYSTEM, question, "query")
        except LLMUnusable:
            return question
        # los errores de conexión/clave se propagan; el fallback es solo para salida vacía o inservible
        return clean_query(raw) or question

    async def answer(
        self, question: str, sources: list[Article], rejected: list[str] | None = None, history: History | None = None
    ) -> str:
        user = ""
        if history:
            user += f"CONVERSACIÓN PREVIA (solo para entender referencias; NO es fuente):\n{format_history(history)}\n\n"
        user += f"PREGUNTA: {question}\n\nFUENTES:\n{format_sources(sources)}"
        if rejected:
            user += (
                "\n\nUn intento anterior fue rechazado porque estas frases no estaban respaldadas por las fuentes. "
                "No las repitas salvo que una fuente las respalde literalmente:\n- " + "\n- ".join(rejected)
            )
        return await self._gen(ANSWER_SYSTEM, user, "answer")


# (max_tokens, effort). Con Opus 5.5 el razonamiento va siempre activo y consume max_tokens: dejamos margen.
_CLAUDE_KIND = {"query": (4000, "low"), "condense": (4000, "low"), "answer": (8000, "medium")}


class ClaudeLLM(_BaseLLM):
    def __init__(self, client: AsyncAnthropic | None = None, model: str = MODEL):
        self._c = client or AsyncAnthropic()  # lee ANTHROPIC_API_KEY
        self._model = model

    def _map(self, e: Exception) -> LLMError:
        if isinstance(e, anthropic.AuthenticationError):
            return LLMError("Clave de API inválida (401)")
        if isinstance(e, anthropic.PermissionDeniedError):
            return LLMError("La clave de API no tiene permiso para este modelo (403)")
        if isinstance(e, anthropic.NotFoundError):
            return LLMError(f"Modelo no encontrado: {self._model}")
        if isinstance(e, anthropic.RateLimitError):
            return LLMError("Límite de uso de la API alcanzado (429)")
        if isinstance(e, anthropic.APIConnectionError):
            return LLMError("No se pudo conectar con la API de Anthropic")
        return LLMError("Error de la API de Anthropic")

    async def _gen(self, system: str, user: str, kind: str) -> str:
        max_tokens, effort = _CLAUDE_KIND[kind]
        try:
            # Fallback por defecto ante rechazos de los clasificadores de seguridad (beta).
            msg = await self._c.beta.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": effort},
                betas=["server-side-fallback-2026-07-01"],
                extra_body={"fallbacks": "default"},
            )
        except anthropic.APIError as e:
            raise self._map(e) from None
        if msg.stop_reason in ("refusal", "max_tokens"):
            raise LLMUnusable(f"respuesta del modelo no utilizable: {msg.stop_reason}")
        return "".join(b.text for b in msg.content if b.type == "text").strip()

    async def check(self) -> str:
        """Valida clave y modelo sin gastar tokens."""
        try:
            await self._c.models.retrieve(self._model)
        except anthropic.APIError as e:
            raise self._map(e) from None
        return f"Clave y modelo válidos ({self._model})"


class OllamaLLM(_BaseLLM):
    """Modelo local vía Ollama (sin coste de API)."""

    def __init__(self, client: httpx.AsyncClient | None = None, host: str | None = None, model: str | None = None):
        self._http = client or httpx.AsyncClient(timeout=300)
        self._host = (host or os.getenv("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")
        self._model = model or os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")

    def _map(self, e: Exception) -> LLMError:
        if isinstance(e, httpx.HTTPStatusError):
            if e.response.status_code == 404:
                return LLMError(f"Modelo {self._model} no descargado: ejecuta `ollama pull {self._model}`")
            return LLMError(f"Ollama devolvió un error ({e.response.status_code})")
        if isinstance(e, httpx.TimeoutException):
            return LLMError(f"Ollama en {self._host} tardó demasiado en responder")
        return LLMError(f"Ollama no responde en {self._host}")

    async def _gen(self, system: str, user: str, kind: str) -> str:
        try:
            r = await self._http.post(
                f"{self._host}/api/chat",
                json={
                    "model": self._model,
                    "stream": False,
                    "options": {"temperature": 0, "num_ctx": 16384},
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                },
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise self._map(e) from None
        return (r.json().get("message", {}).get("content") or "").strip()

    async def check(self) -> str:
        try:
            r = await self._http.get(f"{self._host}/api/tags")
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise self._map(e) from None
        names = {m.get("name", "") for m in r.json().get("models", [])}
        if self._model not in names and f"{self._model}:latest" not in names:
            raise LLMError(f"Ollama responde, pero el modelo {self._model} no está descargado: `ollama pull {self._model}`")
        return f"Ollama y modelo disponibles ({self._model})"


def make_llm() -> LLM:
    return OllamaLLM() if os.getenv("LLM_BACKEND", "claude").lower() == "ollama" else ClaudeLLM()
