"""Tests con PubMed y LLM simulados. Validan el verificador y el flujo, NO la calidad clínica real."""
import pytest
from fastapi.testclient import TestClient

from app import main
from app.pubmed import Article, parse_efetch
from app.verify import verify

XML = """<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>111</PMID><Article>
<Journal><JournalIssue><PubDate><Year>2020</Year></PubDate></JournalIssue><Title>NEJM</Title></Journal>
<ArticleTitle>Dapagliflozin in HFrEF</ArticleTitle>
<Abstract><AbstractText Label="RESULTS">HR 0.74 (95% CI 0.65 to 0.85); 26% reduction.</AbstractText></Abstract>
<PublicationTypeList><PublicationType>Randomized Controlled Trial</PublicationType></PublicationTypeList>
</Article></MedlineCitation></PubmedArticle>
<PubmedArticle><MedlineCitation><PMID>222</PMID><Article><ArticleTitle>No abstract</ArticleTitle></Article></MedlineCitation></PubmedArticle>
</PubmedArticleSet>"""

SRC = [Article("111", "Dapagliflozin in HFrEF", "HR 0.74 (95% CI 0.65 to 0.85); 26% reduction.", "NEJM", "2020", ["Randomized Controlled Trial"])]


def test_parse_skips_no_abstract():
    arts = parse_efetch(XML)
    assert [a.pmid for a in arts] == ["111"]
    assert arts[0].year == "2020" and "HR 0.74" in arts[0].abstract


def test_valid_claim_kept():
    v = verify("Reduce el riesgo (HR 0.74) [1].", SRC)
    assert not v.insufficient and v.used == [1]


def test_invented_number_dropped():
    v = verify("Reduce el riesgo (HR 0.55) [1].", SRC)
    assert v.insufficient and v.dropped


def test_nonexistent_citation_dropped():
    v = verify("Reduce mortalidad [7].", SRC)
    assert v.insufficient


def test_uncited_claim_dropped_but_valid_kept():
    v = verify("Reduce el riesgo (HR 0.74) [1].\nTambién cura la diabetes en todos los pacientes.", SRC)
    assert v.used == [1] and "cura" not in v.text and len(v.dropped) == 1


def test_model_says_insufficient():
    assert verify("EVIDENCIA_INSUFICIENTE", SRC).insufficient


class FakePubMed:
    def __init__(self, arts, by_pmid=None):
        self.arts, self.by_pmid, self.fetched = arts, by_pmid or {}, []
    async def retrieve(self, q, top_k=8): return self.arts
    async def fetch(self, pmids):
        self.fetched.append(list(pmids))
        return [self.by_pmid[p] for p in pmids if p in self.by_pmid]


class FakeLLM:
    def __init__(self, ans, standalone="pregunta autónoma"):
        self.ans, self.standalone = ans, standalone
        self.condense_calls, self.query_in, self.answer_calls = [], [], []
    async def condense(self, q, history):
        self.condense_calls.append((q, history)); return self.standalone
    async def to_pubmed_query(self, q):
        self.query_in.append(q); return "q"
    async def answer(self, q, s, rejected=None, history=None):
        self.answer_calls.append({"q": q, "sources": s, "history": history}); return self.ans


def client(arts, ans):
    main.app.dependency_overrides[main.get_pubmed] = lambda: FakePubMed(arts)
    main.app.dependency_overrides[main.get_llm] = lambda: FakeLLM(ans)
    return TestClient(main.app)


def test_endpoint_ok():
    r = client(SRC, "Reduce el riesgo (HR 0.74) [1].").post("/ask", json={"question": "SGLT2 en IC con FEVr?"}).json()
    assert not r["insufficient_evidence"] and r["citations"][0]["pmid"] == "111"


def test_endpoint_no_sources():
    r = client([], "x").post("/ask", json={"question": "pregunta sin evidencia"}).json()
    assert r["insufficient_evidence"] and r["citations"] == []


def test_endpoint_hallucinated_answer_blocked():
    r = client(SRC, "Reduce la mortalidad un 80% [1].").post("/ask", json={"question": "SGLT2 en IC con FEVr?"}).json()
    assert r["insufficient_evidence"]


def test_short_uncited_claims_dropped():
    for bad in ["Dosis: 10 mg/día.", "Contraindicado si TFGe <20.", "Sí, se recomienda."]:
        v = verify(f"Reduce el riesgo (HR 0.74) [1].\n{bad}", SRC)
        assert bad not in v.text and len(v.dropped) == 1, bad


def test_headers_allowed():
    v = verify("**Evidencia:**\nReduce el riesgo (HR 0.74) [1].", SRC)
    assert "Evidencia" in v.text and not v.dropped


def test_realistic_spanish_answer_not_dropped():
    src = [Article("1", "Dapagliflozin in HFrEF", "HR 0.74 (95% CI 0.65 to 0.85); p<0.001. 4744 patients.", "NEJM", "2019", ["Randomized Controlled Trial"])]
    ans = ("Dapagliflozina reduce el riesgo del objetivo primario [1].\n"
           "- En un ECA de 2019 (4744 pacientes), HR 0,74 (IC 95% 0,65–0,85; p<0,001) [1].")
    v = verify(ans, src)
    assert not v.dropped and v.used == [1], v.dropped


def test_clean_query():
    from app.llm import clean_query
    assert clean_query('```\nQuery: "sglt2 AND heart failure"\n```') == "sglt2 AND heart failure"


def test_omitted_count_reported():
    r = client(SRC, "Reduce el riesgo (HR 0.74) [1].\nAfirmación sin fuente alguna aquí.").post("/ask", json={"question": "SGLT2 en IC con FEVr?"}).json()
    assert r["omitted_unverified"] == 1


def test_ollama_backend():
    import asyncio, httpx
    from app.llm import OllamaLLM, make_llm

    seen = {}
    def handler(req):
        import json
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"message": {"content": "```\nQuery: sglt2 AND hf\n```"}})
    llm = OllamaLLM(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), host="http://x", model="m")
    assert asyncio.run(llm.to_pubmed_query("pregunta")) == "sglt2 AND hf"
    assert seen["body"]["model"] == "m" and seen["body"]["stream"] is False


def test_make_llm_selects_backend(monkeypatch):
    from app.llm import OllamaLLM, make_llm
    monkeypatch.setenv("LLM_BACKEND", "ollama")
    assert isinstance(make_llm(), OllamaLLM)


def test_client_llm_config_builds_requested_backend(monkeypatch):
    from app.llm import OllamaLLM
    r = client(SRC, "x")  # instala overrides
    main.app.dependency_overrides[main.get_llm] = lambda: FakeLLM("EVIDENCIA_INSUFICIENTE")
    built = {}
    monkeypatch.setattr(main, "build_llm", lambda cfg: built.setdefault("cfg", cfg) and FakeLLM("Reduce el riesgo (HR 0.74) [1]."))
    body = {"question": "SGLT2 en IC con FEVr?", "llm": {"provider": "ollama", "model": "m", "ollama_host": "http://h:1"}}
    out = r.post("/ask", json=body).json()
    assert built["cfg"].provider == "ollama" and built["cfg"].model == "m"
    assert not out["insufficient_evidence"]


def test_client_llm_config_can_be_disabled(monkeypatch):
    monkeypatch.setenv("ALLOW_CLIENT_LLM_CONFIG", "0")
    r = client(SRC, "x").post("/ask", json={"question": "SGLT2 en IC con FEVr?", "llm": {"provider": "claude"}})
    assert r.status_code == 403


def test_api_key_never_serialized():
    from app.main import LLMConfig
    c = LLMConfig(provider="claude", api_key="sk-secret")
    assert "sk-secret" not in repr(c) and "sk-secret" not in c.model_dump_json()


def _ollama(handler):
    import httpx
    from app.llm import OllamaLLM
    return OllamaLLM(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), host="http://h:1", model="m")


def test_ollama_model_missing_is_actionable():
    import asyncio, httpx
    from app.llm import LLMError
    llm = _ollama(lambda req: httpx.Response(404, json={"error": "model not found"}))
    with pytest.raises(LLMError, match="ollama pull m"):
        asyncio.run(llm.to_pubmed_query("pregunta"))


def test_ollama_connection_refused_propagates():
    import asyncio, httpx
    from app.llm import LLMError
    def boom(req): raise httpx.ConnectError("refused")
    with pytest.raises(LLMError, match="no responde en http://h:1"):
        asyncio.run(_ollama(boom).to_pubmed_query("pregunta"))


def test_ollama_check():
    import asyncio, httpx
    from app.llm import LLMError
    ok = _ollama(lambda req: httpx.Response(200, json={"models": [{"name": "m:latest"}]}))
    assert "disponibles" in asyncio.run(ok.check())
    bad = _ollama(lambda req: httpx.Response(200, json={"models": [{"name": "otro"}]}))
    with pytest.raises(LLMError, match="no está descargado"):
        asyncio.run(bad.check())


def test_endpoint_surfaces_llm_error_detail():
    from app.llm import LLMError
    class Down(FakeLLM):
        async def to_pubmed_query(self, q): raise LLMError("Ollama no responde en http://h:1")
    main.app.dependency_overrides[main.get_pubmed] = lambda: FakePubMed(SRC)
    main.app.dependency_overrides[main.get_llm] = lambda: Down("x")
    r = TestClient(main.app).post("/ask", json={"question": "SGLT2 en IC con FEVr?"})
    assert r.status_code == 502 and "Ollama no responde" in r.json()["detail"]


def test_missing_api_key_is_400(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    main._LLM_CACHE.clear()
    r = client(SRC, "x").post("/ask", json={"question": "SGLT2 en IC con FEVr?", "llm": {"provider": "claude"}})
    assert r.status_code == 400 and "clave" in r.json()["detail"].lower()


def test_remote_ollama_requires_app_token(monkeypatch):
    monkeypatch.delenv("APP_TOKEN", raising=False)
    main._LLM_CACHE.clear()
    body = {"question": "SGLT2 en IC con FEVr?", "llm": {"provider": "ollama", "ollama_host": "http://169.254.169.254"}}
    assert client(SRC, "x").post("/ask", json=body).status_code == 400
    body["llm"]["ollama_host"] = "http://localhost:11434"
    assert client(SRC, "Reduce el riesgo (HR 0.74) [1].").post("/ask", json=body).status_code != 400


def test_check_endpoint_maps_errors(monkeypatch):
    import httpx
    main._LLM_CACHE.clear()
    monkeypatch.setattr(main, "build_llm", lambda cfg: _ollama(lambda req: httpx.Response(200, json={"models": []})))
    r = client(SRC, "x").post("/check", json={"llm": {"provider": "ollama", "model": "m"}})
    assert r.status_code == 502 and "ollama pull" in r.json()["detail"]


# ---------- contexto + filtro de datos identificativos ----------
def ctx(arts, ans, by_pmid=None, standalone="¿iSGLT2 en IC con FEVr y ERC avanzada?"):
    pm, llm = FakePubMed(arts, by_pmid), FakeLLM(ans, standalone)
    main.app.dependency_overrides[main.get_pubmed] = lambda: pm
    main.app.dependency_overrides[main.get_llm] = lambda: llm
    return TestClient(main.app), pm, llm


GOOD = "Reduce el riesgo (HR 0.74) [1]."
HIST = [{"question": "¿iSGLT2 en IC con FEVr?", "answer": "Reduce el riesgo (HR 0,99) [2].", "pmids": ["999"]}]


def test_condense_only_with_history():
    c, pm, llm = ctx(SRC, GOOD)
    r = c.post("/ask", json={"question": "SGLT2 en IC con FEVr?"}).json()
    assert llm.condense_calls == [] and r["standalone_question"] == "SGLT2 en IC con FEVr?"
    c.post("/ask", json={"question": "¿y con ERC avanzada?", "history": HIST})
    assert len(llm.condense_calls) == 1


def test_standalone_used_for_query_and_answer_and_returned():
    c, pm, llm = ctx(SRC, GOOD)
    r = c.post("/ask", json={"question": "¿y con ERC avanzada?", "history": HIST}).json()
    assert llm.query_in == [llm.standalone] and llm.answer_calls[0]["q"] == llm.standalone
    assert r["standalone_question"] == llm.standalone


@pytest.mark.parametrize("bad", ["", "x" * 401, "línea 1\nlínea 2", "Reduce [1] mortalidad"])
def test_bad_condense_output_falls_back_to_prev_question_plus_followup(bad):
    c, pm, llm = ctx(SRC, GOOD, standalone=bad)
    r = c.post("/ask", json={"question": "¿y con ERC avanzada?", "history": HIST}).json()
    assert r["standalone_question"] == "¿iSGLT2 en IC con FEVr? — ¿y con ERC avanzada?"


def test_llm_never_receives_identifiers():
    c, pm, llm = ctx(SRC, GOOD)
    hist = [{"question": "paciente Juan Pérez DNI 12345678Z, ¿iSGLT2?", "answer": "Contactar 612345678 [1]", "pmids": []}]
    r = c.post("/ask", json={"question": "NHC 1234567 ¿y en ERC? mail a a@b.es", "history": hist}).json()
    seen = " ".join([llm.condense_calls[0][0], *[x for h in llm.condense_calls[0][1] for x in h], *llm.query_in,
                     *[a["q"] for a in llm.answer_calls], *[x for a in llm.answer_calls for h in (a["history"] or []) for x in h]])
    for leak in ("Juan", "12345678Z", "612345678", "1234567", "a@b.es"):
        assert leak not in seen, leak
    assert set(r["redactions"]) == {"nº de historia", "correo"}  # los de la pregunta actual
    assert "1234567" not in r["question_used"]


def test_history_answers_have_no_citation_markers_and_old_answers_dropped():
    turns = [{"question": f"pregunta previa número {i}", "answer": f"respuesta {i} [3, 4] texto", "pmids": []} for i in range(6)]
    c, pm, llm = ctx(SRC, GOOD)
    c.post("/ask", json={"question": "¿y en mayores de 75?", "history": turns})
    h = llm.condense_calls[0][1]
    assert all("[" not in a for _, a in h)
    assert [bool(a) for _, a in h] == [False, False, False, True, True, True]  # solo las 3 últimas aportan respuesta
    assert len(h) == 6  # todas las preguntas


def test_number_only_in_prior_answer_is_dropped():
    # HR 0,99 solo aparece en la respuesta previa, no en las fuentes actuales
    c, pm, llm = ctx(SRC, "Reduce el riesgo (HR 0.99) [1].")
    r = c.post("/ask", json={"question": "¿y con ERC avanzada?", "history": HIST}).json()
    assert r["insufficient_evidence"]


def test_invalid_pmid_rejected_422():
    c, pm, llm = ctx(SRC, GOOD)
    bad = [{"question": "q previa", "answer": "", "pmids": ["123&api_key=x"]}]
    assert c.post("/ask", json={"question": "¿y con ERC avanzada?", "history": bad}).status_code == 422


def test_prior_sources_merged_and_deduplicated():
    prior_art = Article("999", "Estudio previo", "texto previo", "JAMA", "2018", ["Review"])
    c, pm, llm = ctx(SRC, GOOD, by_pmid={"999": prior_art, "111": SRC[0]})
    hist = [{"question": "q previa", "answer": "", "pmids": ["999", "111"]}]
    c.post("/ask", json={"question": "¿y con ERC avanzada?", "history": hist})
    pmids = [a.pmid for a in llm.answer_calls[0]["sources"]]
    assert pm.fetched == [["999", "111"]] and sorted(pmids) == ["111", "999"] and len(pmids) == 2


def test_prior_fetch_failure_does_not_fail_request():
    c, pm, llm = ctx(SRC, GOOD)
    async def boom(pmids): raise RuntimeError("red")
    pm.fetch = boom
    r = c.post("/ask", json={"question": "¿y con ERC avanzada?", "history": HIST})
    assert r.status_code == 200 and not r.json()["insufficient_evidence"]


def test_merge_cap():
    arts = [Article(str(i), "t", "a", "j", "2020", []) for i in range(20)]
    out = main.merge_sources(arts[:8], arts[8:20])
    assert len(out) == 10 and len({a.pmid for a in out}) == 10


def test_retry_gets_same_history():
    c, pm, llm = ctx(SRC, "Reduce el riesgo (HR 0.55) [1].")  # fuerza reintento
    c.post("/ask", json={"question": "¿y con ERC avanzada?", "history": HIST})
    assert len(llm.answer_calls) == 2 and llm.answer_calls[0]["history"] == llm.answer_calls[1]["history"]


def test_long_history_is_truncated_not_rejected():
    big = [{"question": "q" * 1900, "answer": "respuesta " * 2000, "pmids": []}]  # ~20000 caracteres
    c, pm, llm = ctx(SRC, GOOD)
    r = c.post("/ask", json={"question": "¿y con ERC avanzada?", "history": big})
    assert r.status_code == 200
    q, a = llm.condense_calls[0][1][0]
    assert len(q) <= 1000 and len(a) <= 1500


@pytest.mark.parametrize("raw", ["Pregunta reescrita: ¿iSGLT2 en ERC?", '"¿iSGLT2 en ERC?"', "Pregunta autónoma: «¿iSGLT2 en ERC?»"])
def test_standalone_prefix_and_quotes_stripped(raw):
    c, pm, llm = ctx(SRC, GOOD, standalone=raw)
    r = c.post("/ask", json={"question": "¿y con ERC avanzada?", "history": HIST}).json()
    assert r["standalone_question"] == "¿iSGLT2 en ERC?"
