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

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS

import icite
import pubmed
from errors import AppError, BadRequestError

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

    summary = pubmed.get_summary(pmid)
    abstract = pubmed.get_abstract(pmid)
    citation_stats = icite.get_icite_data(pmid)

    return jsonify(
        {
            "pmid": pmid,
            "title": summary["title"],
            "authors": summary["authors"],
            "journal": summary["journal"],
            "year": summary["year"],
            "doi": summary["doi"],
            "abstract": abstract,
            "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "citation_count": citation_stats["citation_count"],
            "relative_citation_ratio": citation_stats["relative_citation_ratio"],
        }
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
