# PaperTrail — backend

A Flask API that grounds an LLM in **live PubMed and iCite data**, instead of the model's own memory, to help you read a research paper: a plain-language explanation at three levels, what later work built on it, and how its field has trended over time.

Frontend repo: [papertrail-frontend](https://github.com/andrewjounkim/papertrail-frontend) (GitHub Pages).

---

## 1. What the backend does

All endpoints return JSON. All outbound requests (PubMed, iCite, OpenAI) use timeouts, and every error comes back as `{"error": "..."}` with an appropriate HTTP status — never a raw traceback.

### `GET /health`

Liveness check. Used by the frontend to detect/wait out Render's free-tier cold start.

**Response 200**
```json
{ "status": "ok" }
```

### `POST /api/paper`

Normalizes a PMID, PubMed URL, or DOI, then fetches metadata + abstract from PubMed and citation stats from iCite.

**Body**
```json
{ "input": "23193287" }
```
`input` may be a bare PMID (`"23193287"`), a PubMed URL (`"https://pubmed.ncbi.nlm.nih.gov/23193287/"`), or a DOI (`"10.1093/nar/gks1195"`).

**Response 200**
```json
{
  "pmid": "23193287",
  "title": "GenBank.",
  "authors": ["Benson DA", "Cavanaugh M", "..."],
  "journal": "Nucleic acids research",
  "year": "2013",
  "doi": "10.1093/nar/gks1195",
  "abstract": "GenBank® (http://www.ncbi.nlm.nih.gov) is a comprehensive database...",
  "pubmed_url": "https://pubmed.ncbi.nlm.nih.gov/23193287/",
  "citation_count": 2141,
  "relative_citation_ratio": 71.09
}
```

**Errors:** `400` empty/unrecognizable input · `404` no PubMed record for that PMID/DOI · `502` PubMed or iCite failed/timed out.

### `POST /api/explain`

Plain-language explanation of a paper's title + abstract at a chosen reading level. Cached in memory by `(pmid, level)`.

**Body**
```json
{ "pmid": "23193287", "level": "high_school" }
```
`level` is one of `"high_school"`, `"undergrad"`, `"expert"`.

**Response 200**
```json
{ "level": "high_school", "explanation": "GenBank is like a giant library filled with information about the DNA of many living things..." }
```

**Errors:** `400` missing `pmid` / invalid `level` · `404` unknown `pmid` · `502` OpenAI call failed.

### `POST /api/what-next`

Up to the 10 most recent papers that cited this one (from iCite), plus an AI summary that is grounded **only** in their retrieved titles/abstracts — it never invents findings, and says so.

**Body**
```json
{ "pmid": "23193287" }
```

**Response 200**
```json
{
  "citation_count": 2141,
  "citing_papers": [
    {
      "pmid": "42453397",
      "title": "Artificial intelligence in biologic drug discovery: A review...",
      "year": "2026",
      "journal": "Acta pharmaceutica Sinica. B",
      "pubmed_url": "https://pubmed.ncbi.nlm.nih.gov/42453397/"
    }
  ],
  "summary": "The citing papers demonstrate a diverse range of applications... This summary is based solely on the titles and available abstracts of the cited papers."
}
```

If iCite reports zero citing papers, `citing_papers` is `[]` and `summary` is a plain message (`"No papers have cited this one yet, according to iCite."`) — the LLM is **not** called in that case.

**Errors:** `400` missing `pmid` · `404` unknown `pmid` · `502` iCite/PubMed/OpenAI failed.

### `POST /api/trend`

Yearly PubMed publication counts (last 20 years) for the paper's topic. Give a `pmid` to have the LLM generate a search query from the title/abstract, or give an already-edited `query` directly to re-run the chart without another LLM call.

**Body (either form)**
```json
{ "pmid": "23193287" }
```
```json
{ "query": "GenBank nucleotide sequences database AND genome sequencing" }
```

**Response 200**
```json
{
  "query": "GenBank nucleotide sequences database AND genome sequencing AND accession numbers",
  "years": [2007, 2008, "...", 2026],
  "counts": [16, 15, "...", 2]
}
```

**Errors:** `400` neither `pmid` nor `query` given · `404` unknown `pmid` · `502` PubMed/OpenAI failed.

---

## 2. How the frontend communicates with the backend

The frontend (single page, `API_BASE` constant at the top of `app.js`) calls the backend like this:

1. **On page load:** `GET /health`. If it takes more than ~1.5s, a "Waking up the server…" banner is shown (Render free tier sleeps after inactivity).
2. **On paper lookup** (typed input or an example chip): `POST /api/paper`. The response renders the paper card (title, authors, journal, year, abstract, citation stats).
3. **Once the paper card renders**, three calls fire **in parallel**, each with its own loading/error UI so one slow section never blocks the others:
   - `POST /api/explain` with the default slider level (undergrad). Moving the slider re-calls it with the new level.
   - `POST /api/what-next` — renders the citing-papers list and the AI summary.
   - `POST /api/trend` — renders the query (in an editable input) and the Chart.js line chart. Editing the query and clicking "Re-run" calls `/api/trend` again with `{"pmid", "query"}`.
4. Every call goes through a shared `apiPost`/`apiGet` helper with a timeout (`AbortController`); a failed/slow/unreachable backend, a bad-input `400`, or an upstream `502`/`404` all surface as a friendly message in that section's error box — never just a console error.

---

## 3. Running locally

### Requirements
Python 3.10+ (developed on 3.14).

### Setup
```bash
git clone https://github.com/andrewjounkim/papertrail-backend.git
cd papertrail-backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# then edit .env and fill in your real OPENAI_API_KEY (and NCBI_EMAIL)
```

### Env vars (see `.env.example`)
| Var | Required | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | yes | OpenAI API key. Never committed. |
| `OPENAI_MODEL` | no (default `gpt-4o-mini`) | Model used for all LLM calls. |
| `NCBI_API_KEY` | no | Raises the PubMed rate limit from 3 req/s to 10 req/s. |
| `NCBI_EMAIL` | recommended | NCBI asks every tool for a contact email. |
| `NCBI_TOOL_NAME` | no (default `papertrail`) | NCBI tool-identification param. |
| `ALLOWED_ORIGINS` | yes | Comma-separated list of origins CORS will allow. |
| `PORT` | no (default `5000`; Render sets this itself) | Port the Flask app binds to. |

### Run
```bash
python app.py
# Serving on http://127.0.0.1:5000 (or the PORT you set)
```
On Render, the process is started with `gunicorn app:app` instead (see `requirements.txt`/deploy notes below).

### Example curl commands
```bash
curl http://127.0.0.1:5000/health

curl -X POST http://127.0.0.1:5000/api/paper \
  -H "Content-Type: application/json" \
  -d '{"input":"23193287"}'

curl -X POST http://127.0.0.1:5000/api/explain \
  -H "Content-Type: application/json" \
  -d '{"pmid":"23193287","level":"expert"}'

curl -X POST http://127.0.0.1:5000/api/what-next \
  -H "Content-Type: application/json" \
  -d '{"pmid":"23193287"}'

curl -X POST http://127.0.0.1:5000/api/trend \
  -H "Content-Type: application/json" \
  -d '{"pmid":"23193287"}'
```

---

## 4. How secrets are handled

- **Locally:** secrets live only in `.env` (loaded via `python-dotenv`), which is listed in `.gitignore` and was never committed — `.gitignore` was created and committed *before* any code, so no secret could ever land in git history. `.env.example` documents every variable with placeholder values only.
- **On Render:** the same variables are set directly in the Render dashboard (Environment tab) as real environment variables — no `.env` file is deployed or committed.
- **In the frontend:** there are no secrets at all. It only knows the backend's public base URL (`API_BASE` in `app.js`).
- **CORS:** `ALLOWED_ORIGINS` (an env var, not hardcoded) restricts which frontend origins the backend will answer with `Access-Control-Allow-Origin` for — the GitHub Pages origin plus localhost for development.

---

## 5. Deployed URLs

- Backend (Render): `https://papertrail-backend.onrender.com` <!-- placeholder — update after deploying -->
- Frontend (GitHub Pages): `https://andrewjounkim.github.io/papertrail-frontend/` <!-- placeholder — update after deploying -->

---

See `prompt_log.md` for the AI tools/models used and the key prompts that shaped this implementation, including the exact system prompts sent to the LLM.
