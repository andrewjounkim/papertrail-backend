"""Thin wrapper around NCBI E-utilities (esearch, esummary, efetch)."""

import os
import re
import threading
import time
import xml.etree.ElementTree as ET

import requests

from errors import NotFoundError, UpstreamError

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
REQUEST_TIMEOUT = 10  # seconds, applied to every outbound call

# --- Rate limiting -----------------------------------------------------
# NCBI asks for <=3 req/s without an API key, <=10 req/s with one. This is a
# process-wide throttle (good enough for a single free-tier Render dyno).
_last_request_at = 0.0
_throttle_lock = threading.Lock()


def _min_interval():
    return 0.11 if os.environ.get("NCBI_API_KEY") else 0.35


def _throttle():
    global _last_request_at
    with _throttle_lock:
        wait = _min_interval() - (time.monotonic() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()


def _common_params():
    params = {
        "tool": os.environ.get("NCBI_TOOL_NAME", "papertrail"),
        "email": os.environ.get("NCBI_EMAIL", ""),
    }
    api_key = os.environ.get("NCBI_API_KEY")
    if api_key:
        params["api_key"] = api_key
    return params


def _get(path, params):
    _throttle()
    url = f"{EUTILS_BASE}/{path}"
    try:
        resp = requests.get(url, params={**_common_params(), **params}, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp
    except requests.RequestException as err:
        raise UpstreamError(f"PubMed request failed: {err}") from err


# --- Input parsing -------------------------------------------------------

_PMID_RE = re.compile(r"^\d{1,9}$")
_PUBMED_URL_RE = re.compile(r"(?:pubmed\.ncbi\.nlm\.nih\.gov/|ncbi\.nlm\.nih\.gov/pubmed/)(\d+)")
_DOI_RE = re.compile(r"10\.\d{4,9}/\S+")


def resolve_to_pmid(raw_input):
    """Turn a PMID, PubMed URL, or DOI into a bare PMID string. Raises AppError."""
    if not raw_input or not raw_input.strip():
        raise NotFoundError("no input provided")  # caller checks emptiness separately too
    text = raw_input.strip()

    url_match = _PUBMED_URL_RE.search(text)
    if url_match:
        return url_match.group(1)

    if _PMID_RE.match(text):
        return text

    doi_match = _DOI_RE.search(text)
    if doi_match:
        doi = doi_match.group(0).rstrip(".,;)")
        return _doi_to_pmid(doi)

    return None  # signals "not a recognizable PMID/URL/DOI" to the caller


def _doi_to_pmid(doi):
    resp = _get(
        "esearch.fcgi",
        {"db": "pubmed", "term": f"{doi}[doi]", "retmode": "json"},
    )
    data = resp.json().get("esearchresult", {})
    ids = data.get("idlist", [])
    if not ids:
        raise NotFoundError(f"No PubMed record found for DOI {doi}")
    return ids[0]


# --- Metadata / abstract ---------------------------------------------------

def get_summary(pmid):
    """Title, authors, journal, year, doi for a PMID."""
    resp = _get("esummary.fcgi", {"db": "pubmed", "id": pmid, "retmode": "json"})
    result = resp.json().get("result", {})
    doc = result.get(pmid)
    # NCBI doesn't 404 on an unknown PMID; it echoes the id back with an
    # "error" field instead, so we have to check for that explicitly.
    if not doc or doc.get("error"):
        raise NotFoundError(f"No PubMed record found for PMID {pmid}")

    doi = ""
    for article_id in doc.get("articleids", []):
        if article_id.get("idtype") == "doi":
            doi = article_id.get("value", "")
            break

    authors = [a.get("name", "") for a in doc.get("authors", []) if a.get("name")]

    year = ""
    pubdate = doc.get("pubdate", "")
    year_match = re.search(r"\d{4}", pubdate)
    if year_match:
        year = year_match.group(0)

    return {
        "pmid": pmid,
        "title": doc.get("title", "").strip() or "(no title available)",
        "authors": authors,
        "journal": doc.get("fulljournalname") or doc.get("source", ""),
        "year": year,
        "doi": doi,
    }


def get_abstract(pmid):
    """Plain-text abstract for a PMID (empty string if the article has none)."""
    resp = _get(
        "efetch.fcgi",
        {"db": "pubmed", "id": pmid, "rettype": "abstract", "retmode": "xml"},
    )
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as err:
        raise UpstreamError(f"Could not parse PubMed abstract XML: {err}") from err

    parts = []
    for abstract_text in root.iter("AbstractText"):
        label = abstract_text.get("Label")
        text = "".join(abstract_text.itertext()).strip()
        if not text:
            continue
        parts.append(f"{label}: {text}" if label else text)

    return "\n\n".join(parts)


# --- Yearly counts (for the trend chart) -----------------------------------

def search_count_for_year(query, year):
    """Number of PubMed articles matching `query` published in a given year."""
    resp = _get(
        "esearch.fcgi",
        {
            "db": "pubmed",
            "term": query,
            "retmode": "json",
            "rettype": "count",
            "datetype": "pdat",
            "mindate": str(year),
            "maxdate": str(year),
        },
    )
    try:
        return int(resp.json()["esearchresult"]["count"])
    except (KeyError, ValueError) as err:
        raise UpstreamError(f"Unexpected PubMed count response: {err}") from err
