"""
PaperTrail backend — Flask API that grounds an LLM in live PubMed / iCite data.

Endpoints (added incrementally, see README.md for full docs):
    GET  /health        - liveness check, used by the frontend to wake Render up
    POST /api/paper      - normalize a PMID/URL/DOI and fetch metadata + citation stats
    POST /api/explain     - plain-language explanation at a chosen reading level
    POST /api/what-next  - papers that cited this one, + an AI summary of them
    POST /api/trend      - yearly PubMed publication counts for the paper's topic
"""

import logging
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS

import icite
import llm
import pubmed
from errors import AppError, BadRequestError, UpstreamError

load_dotenv()  # loads .env when running locally; on Render, real env vars are used instead

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("papertrail")

app = Flask(__name__)

# Restrict CORS to our own frontend + local dev servers. ALLOWED_ORIGINS is a
# comma-separated env var so it can be changed on Render without a code change.
allowed_origins = [
    origin.strip()
    for origin in os.environ.get(
        "ALLOWED_ORIGINS", "http://localhost:5500,http://127.0.0.1:5500"
    ).split(",")
    if origin.strip()
]
CORS(app, origins=allowed_origins)
logger.info("CORS allowed origins: %s", allowed_origins)


@app.errorhandler(AppError)
def handle_app_error(err):
    """Our own typed errors (bad input / not found / upstream failure) -> clean JSON."""
    logger.warning("%s: %s", type(err).__name__, err.message)
    return jsonify({"error": err.message}), err.status_code


@app.errorhandler(Exception)
def handle_uncaught_exception(err):
    """Catch-all so the frontend always gets JSON, never a raw traceback/HTML page."""
    logger.exception("Unhandled exception")
    return jsonify({"error": "Internal server error"}), 500


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


def _get_json_body():
    """Parse the request body as JSON, raising a clean 400 instead of Flask's default."""
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        raise BadRequestError("Request body must be JSON")
    return body


# In-memory caches. Fine for a single free-tier Render dyno for a class demo;
# they reset on every deploy/restart, which is acceptable here.
_paper_cache = {}  # pmid -> {title, authors, journal, year, doi, abstract}
_explain_cache = {}  # (pmid, level) -> explanation text


def _require_pmid(body):
    pmid = str(body.get("pmid") or "").strip()
    if not pmid:
        raise BadRequestError("'pmid' is required")
    return pmid


def _get_paper_details(pmid):
    """Title/authors/journal/year/doi/abstract for a PMID, cached in memory."""
    if pmid not in _paper_cache:
        summary = pubmed.get_summary(pmid)
        abstract = pubmed.get_abstract(pmid)
        _paper_cache[pmid] = {**summary, "abstract": abstract}
    return _paper_cache[pmid]


@app.post("/api/paper")
def api_paper():
    body = _get_json_body()
    raw_input = (body.get("input") or "").strip()
    if not raw_input:
        raise BadRequestError("'input' is required (a PMID, PubMed URL, or DOI)")

    pmid = pubmed.resolve_to_pmid(raw_input)
    if pmid is None:
        raise BadRequestError(
            "Could not recognize that as a PMID, PubMed URL, or DOI"
        )

    details = _get_paper_details(pmid)
    citation_stats = icite.get_icite_data(pmid)

    return jsonify(
        {
            "pmid": pmid,
            "title": details["title"],
            "authors": details["authors"],
            "journal": details["journal"],
            "year": details["year"],
            "doi": details["doi"],
            "abstract": details["abstract"],
            "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "citation_count": citation_stats["citation_count"],
            "relative_citation_ratio": citation_stats["relative_citation_ratio"],
        }
    )


@app.post("/api/explain")
def api_explain():
    body = _get_json_body()
    pmid = _require_pmid(body)
    level = str(body.get("level") or "").strip()
    if level not in llm.VALID_LEVELS:
        raise BadRequestError(
            f"'level' must be one of {sorted(llm.VALID_LEVELS)}"
        )

    cache_key = (pmid, level)
    if cache_key not in _explain_cache:
        details = _get_paper_details(pmid)  # raises NotFoundError for a bad pmid
        _explain_cache[cache_key] = llm.explain_paper(
            details["title"], details["abstract"], level
        )

    return jsonify({"level": level, "explanation": _explain_cache[cache_key]})


@app.post("/api/what-next")
def api_what_next():
    body = _get_json_body()
    pmid = _require_pmid(body)
    details = _get_paper_details(pmid)  # raises NotFoundError for a bad pmid

    citation_stats = icite.get_icite_data(pmid)
    cited_by_years = citation_stats["cited_by_years"]  # most-recent-first already

    if not cited_by_years:
        return jsonify(
            {
                "citation_count": citation_stats["citation_count"],
                "citing_papers": [],
                "summary": "No papers have cited this one yet, according to iCite.",
            }
        )

    top = cited_by_years[:10]
    top_pmids = [str(item["pmid"]) for item in top]

    # Two batched PubMed calls cover all 10 citing papers, instead of 20
    # individual ones.
    summaries = pubmed.get_summaries(top_pmids)
    abstracts = pubmed.get_abstracts(top_pmids)

    citing_papers = []
    llm_inputs = []
    for item in top:
        cited_pmid = str(item["pmid"])
        summary = summaries.get(cited_pmid)
        title = summary["title"] if summary else "(title unavailable)"
        journal = summary["journal"] if summary else ""
        year = summary["year"] if summary else str(item["year"])
        citing_papers.append(
            {
                "pmid": cited_pmid,
                "title": title,
                "year": year,
                "journal": journal,
                "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{cited_pmid}/",
            }
        )
        llm_inputs.append({"title": title, "year": year, "abstract": abstracts.get(cited_pmid, "")})

    summary_text = llm.summarize_citations(details["title"], llm_inputs)

    return jsonify(
        {
            "citation_count": citation_stats["citation_count"],
            "citing_papers": citing_papers,
            "summary": summary_text,
        }
    )


TREND_YEARS_BACK = 20  # ~last 20 years, inclusive of the current one


@app.post("/api/trend")
def api_trend():
    body = _get_json_body()
    query = str(body.get("query") or "").strip()
    pmid = str(body.get("pmid") or "").strip()

    if not query and not pmid:
        raise BadRequestError("Provide either 'pmid' or 'query'")

    if not query:
        details = _get_paper_details(pmid)  # raises NotFoundError for a bad pmid
        query = llm.generate_trend_query(details["title"], details["abstract"])
        if not query:
            raise UpstreamError("LLM did not return a usable search query")

    current_year = datetime.now(timezone.utc).year
    years = list(range(current_year - TREND_YEARS_BACK + 1, current_year + 1))
    counts = [pubmed.search_count_for_year(query, year) for year in years]

    return jsonify({"query": query, "years": years, "counts": counts})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
