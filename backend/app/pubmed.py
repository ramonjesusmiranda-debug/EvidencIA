"""Recuperación de evidencia desde PubMed (NCBI E-utilities)."""
from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import httpx

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# Mayor = mejor nivel de evidencia. Se usa solo para ordenar.
PUBTYPE_RANK = {
    "Practice Guideline": 6,
    "Guideline": 6,
    "Meta-Analysis": 5,
    "Systematic Review": 5,
    "Randomized Controlled Trial": 4,
    "Clinical Trial": 3,
    "Review": 2,
    "Observational Study": 2,
}


@dataclass
class Article:
    pmid: str
    title: str
    abstract: str
    journal: str = ""
    year: str = ""
    pub_types: list[str] = field(default_factory=list)

    @property
    def rank(self) -> int:
        return max((PUBTYPE_RANK.get(t, 0) for t in self.pub_types), default=0)

    @property
    def url(self) -> str:
        return f"https://pubmed.ncbi.nlm.nih.gov/{self.pmid}/"


def parse_efetch(xml_text: str) -> list[Article]:
    """Parsea PubmedArticleSet. Descarta artículos sin resumen (no hay nada que citar)."""
    root = ET.fromstring(xml_text)
    out: list[Article] = []
    for art in root.iter("PubmedArticle"):
        pmid = (art.findtext(".//MedlineCitation/PMID") or "").strip()
        title = "".join(art.find(".//ArticleTitle").itertext()).strip() if art.find(".//ArticleTitle") is not None else ""
        parts = []
        for node in art.findall(".//Abstract/AbstractText"):
            text = "".join(node.itertext()).strip()
            label = node.get("Label")
            parts.append(f"{label}: {text}" if label else text)
        abstract = "\n".join(p for p in parts if p)
        if not pmid or not abstract:
            continue
        year = (
            art.findtext(".//JournalIssue/PubDate/Year")
            or (art.findtext(".//JournalIssue/PubDate/MedlineDate") or "")[:4]
        )
        out.append(
            Article(
                pmid=pmid,
                title=title,
                abstract=abstract,
                journal=art.findtext(".//Journal/Title") or "",
                year=year or "",
                pub_types=[(n.text or "").strip() for n in art.findall(".//PublicationTypeList/PublicationType")],
            )
        )
    return out


class PubMedClient:
    def __init__(self, client: httpx.AsyncClient | None = None, api_key: str | None = None):
        self._client = client or httpx.AsyncClient(timeout=20)
        self._api_key = api_key or os.getenv("NCBI_API_KEY")

    def _params(self, **p):
        p["tool"] = "evidencia"
        if self._api_key:
            p["api_key"] = self._api_key
        return p

    async def search_ids(self, query: str, retmax: int = 30) -> list[str]:
        r = await self._client.get(
            f"{EUTILS}/esearch.fcgi",
            params=self._params(db="pubmed", term=query, retmode="json", retmax=retmax, sort="relevance"),
        )
        r.raise_for_status()
        return r.json()["esearchresult"].get("idlist", [])

    async def fetch(self, pmids: list[str]) -> list[Article]:
        if not pmids:
            return []
        r = await self._client.get(
            f"{EUTILS}/efetch.fcgi",
            params=self._params(db="pubmed", id=",".join(pmids), retmode="xml"),
        )
        r.raise_for_status()
        return parse_efetch(r.text)

    async def retrieve(self, query: str, top_k: int = 8) -> list[Article]:
        ids = await self.search_ids(query)
        if not ids:  # filtros demasiado estrictos: reintento sin [pt]/tipo de estudio
            relaxed = re.sub(r"\s+AND\s+\([^()]*\[(?:pt|Publication Type)\][^()]*\)", "", query, flags=re.I)
            if relaxed != query:
                ids = await self.search_ids(relaxed)
        arts = await self.fetch(ids)
        pos = {p: i for i, p in enumerate(ids)}  # orden de relevancia de PubMed
        # relevancia manda; el nivel de evidencia solo da un bonus pequeño
        arts.sort(key=lambda a: pos.get(a.pmid, 99) - 1.5 * a.rank)
        return arts[:top_k]
