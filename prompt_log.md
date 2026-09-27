# Prompt log

AI tools used on this project:
- **Claude Code** (Sonnet 5) — pair-programmed the entire backend and frontend in this session.
- **OpenAI API** (model set via `OPENAI_MODEL`, default `gpt-4o-mini`) — the in-app LLM that powers `/api/explain`, `/api/what-next`, and query generation for `/api/trend`.

This log is updated after each build step with the key prompts/decisions that shaped the code, plus the exact system prompts sent to the in-app LLM.

---

## Initial project brief (summarized)

Build PaperTrail, a research paper reading companion, for a class assignment (HW4) due today. Two repos: a Flask backend on Render, a static HTML/CSS/JS frontend on GitHub Pages. The backend normalizes a PMID/URL/DOI, fetches metadata + abstract from PubMed E-utilities and citation stats from iCite, and uses an LLM (grounded only in retrieved data, never invented) to: (1) explain the paper at three reading levels, (2) summarize how later citing papers built on/challenged it, and (3) generate a PubMed query to chart the field's yearly publication trend. Hard requirements: no secrets committed (env vars + `.env`/`.gitignore` from the first commit), CORS restricted to the GitHub Pages origin + localhost, JSON error responses with correct status codes and timeouts on every outbound call, loading states and friendly errors on the frontend, and a "wake up the sleeping Render backend" health check. Build order: backend skeleton → `/api/paper` → `/api/explain` → `/api/what-next` → `/api/trend` → frontend wired locally → README + this log → deploy instructions.

Follow-up decisions from the user: initially chose the Anthropic Claude API, then switched to the **OpenAI API** (`gpt-4o-mini` by default) before `/api/explain` was implemented, so the app uses OpenAI throughout; develop the frontend locally first and add it to a repo (new repo vs. portfolio page — TBD) once it's working end-to-end.

---

## Step 1: Backend skeleton

Prompt: "Backend skeleton: /health, .gitignore, .env.example, requirements.txt. Run locally."

- `app.py` created with Flask app, `flask-cors` restricted via an `ALLOWED_ORIGINS` env var (comma-separated), a catch-all exception handler that always returns JSON instead of a traceback, and `GET /health`.
- `.gitignore` (covering `.env`, venv, caches) written and committed *before* `.env.example`/`app.py` so no secret could ever land in history.
- `.env.example` documents every env var the app needs (originally `ANTHROPIC_API_KEY`/`ANTHROPIC_MODEL`, later swapped for `OPENAI_API_KEY`/`OPENAI_MODEL` — see below), plus `NCBI_API_KEY`, `NCBI_EMAIL`, `NCBI_TOOL_NAME`, `ALLOWED_ORIGINS`, `PORT`.
- `requirements.txt`: flask, flask-cors, requests, python-dotenv, gunicorn, anthropic (later swapped for openai).
- Verified locally: `python app.py` (port 5000 was taken by macOS AirPlay Receiver, moved local dev to 5001 via `.env`) → `curl localhost:5001/health` → `{"status": "ok"}`.

---

## Step 2: `/api/paper`

Prompt: "/api/paper with PubMed + iCite. Test with curl."

- Before writing code, hit the live iCite and E-utilities endpoints directly with curl to verify real field names rather than guessing (per the brief's instruction). Findings that shaped the code:
  - iCite: `citation_count`, `relative_citation_ratio` (float or absent for very new/uncited papers), a flat `cited_by` PMID list, and `citedByPmidsByYear` — a list of single-key `{pmid: year}` dicts, which is what lets `/api/what-next` sort citing papers most-recent-first later.
  - esummary (JSON) doesn't HTTP-404 on an unknown PMID — it echoes the id back with `{"error": "cannot get document summary"}` inside `result`, so "not found" has to be detected by inspecting the payload, not the status code. Caught this via a live curl test with a bogus PMID and fixed `pubmed.get_summary`.
  - efetch abstracts come back as PubMed XML with one or more `<AbstractText Label="...">` elements (structured abstracts have multiple, e.g. Background/Methods/Results); parsed with `xml.etree.ElementTree` and re-joined with labels preserved.
  - esearch resolves a DOI via the `[doi]` field tag: `term=10.xxxx/yyyy[doi]`.
- New modules: `errors.py` (typed `BadRequestError`/`NotFoundError`/`UpstreamError` → 400/404/502, raised from anywhere and turned into JSON by a Flask `errorhandler`), `pubmed.py` (input normalization for PMID/URL/DOI, esearch/esummary/efetch, a process-wide throttle honoring NCBI's 3 req/s / 10 req/s-with-key limit), `icite.py` (citation stats + citing-PMID/year list).
- `POST /api/paper` wires these together and returns normalized metadata + abstract + citation stats.
- Tested with curl: bare PMID, DOI, PubMed URL (all resolve to the same paper), empty input (400), unrecognizable input (400), non-existent PMID (404), and a missing JSON body (400).

---

## Step 3: `/api/explain`

Prompt: "wait im going to use an open ai key can you help set that up" (mid-step-3 LLM provider switch).

- Swapped the LLM provider from Anthropic to **OpenAI** before any LLM code had shipped to a user-facing endpoint: `requirements.txt` (`anthropic` → `openai`), `.env.example`/`.env` (`ANTHROPIC_API_KEY`/`ANTHROPIC_MODEL` → `OPENAI_API_KEY`/`OPENAI_MODEL`, default model `gpt-4o-mini`), and rewrote `llm.py` to use the `openai` SDK's `chat.completions.create` instead of the `anthropic` SDK's `messages.create`. `app.py`/`errors.py`/`pubmed.py`/`icite.py` were untouched since they never referenced the LLM provider directly.
- `llm.py` holds three level-specific **system prompts** (`high_school`/`undergrad`/`expert`), each instructing the model to explain using only the given title/abstract and never add outside facts about the paper — this is the grounding requirement from the brief. Exact system prompt text is in `llm.py`; copied into the README's documentation section too.
- `POST /api/explain` in `app.py`: validates `pmid`/`level`, reuses a new `_get_paper_details()` in-memory cache (also used by `/api/paper`) to avoid re-hitting PubMed, then caches the LLM's explanation itself by `(pmid, level)` so flipping the slider back and forth doesn't re-call the API.
- Hit a real bug on first live test: `openai==1.54.4`'s bundled httpx client broke against httpx 0.28+ (`TypeError: Client.__init__() got an unexpected keyword argument 'proxies'`), a known version-skew issue. Pinned `httpx==0.27.2` in `requirements.txt` to fix it. Verified all three levels return distinct, appropriately-pitched explanations, the `(pmid, level)` cache returns in ~15ms on a repeat call, and 400/400/404 fire correctly for an invalid level, missing pmid, and nonexistent pmid.

