"""Thin wrapper around the NIH iCite API (citation stats + citing PMIDs)."""

import requests

from errors import UpstreamError

ICITE_URL = "https://icite.od.nih.gov/api/pubs"
REQUEST_TIMEOUT = 10


def get_icite_data(pmid):
    """
    Citation stats for a PMID.

    Returns a dict with citation_count, relative_citation_ratio (may be None -
    iCite doesn't compute it for very recent/uncited papers), and
    cited_by_years: a list of {"pmid": int, "year": int} for every citing
    paper, most-recent-first (field-verified against the live API: iCite
    exposes this as `citedByPmidsByYear`, a list of single-key {pmid: year}
    dicts, plus a flat `cited_by` list of PMIDs with no year attached).

    If iCite has no record for this PMID (common for very new papers), all
    values come back empty/zero rather than raising - that's a valid answer,
    not an error.
    """
    try:
        resp = requests.get(
            ICITE_URL, params={"pmids": pmid}, timeout=REQUEST_TIMEOUT
        )
        resp.raise_for_status()
    except requests.RequestException as err:
        raise UpstreamError(f"iCite request failed: {err}") from err

    try:
        records = resp.json().get("data", [])
    except ValueError as err:
        raise UpstreamError(f"iCite returned invalid JSON: {err}") from err

    if not records:
        return {
            "citation_count": 0,
            "relative_citation_ratio": None,
            "cited_by_years": [],
        }

    record = records[0]

    cited_by_years = []
    for entry in record.get("citedByPmidsByYear", []) or []:
        for pmid_str, year in entry.items():
            try:
                cited_by_years.append({"pmid": int(pmid_str), "year": int(year)})
            except (TypeError, ValueError):
                continue
    cited_by_years.sort(key=lambda item: item["year"], reverse=True)

    return {
        "citation_count": record.get("citation_count", 0) or 0,
        "relative_citation_ratio": record.get("relative_citation_ratio"),
        "cited_by_years": cited_by_years,
    }
