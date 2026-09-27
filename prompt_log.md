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

---

## Step 4: `/api/what-next`

Prompt: "/api/what-next."

- iCite's `citedByPmidsByYear` (parsed in `icite.py`, sorted most-recent-first) gives the top 10 citing PMIDs without an extra API call. Getting their titles/abstracts naively would be 20 PubMed requests (10 esummary + 10 efetch); instead added `pubmed.get_summaries()`/`get_abstracts()`, which each take a **comma-separated batch of PMIDs in one request** (NCBI supports this natively), cutting it to 2 calls. `get_summary()`/`get_abstract()` (singular) now just call the batch versions with a list of one, so there's one parsing path.
- New system prompt in `llm.py` (`summarize_citations`) that's explicit about the grounding constraint from the brief: it's given only titles + (when available) abstracts of the citing papers, told it hasn't read the full text of anything, told not to invent findings, and told to end its own output noting the summary is based only on the retrieved titles/abstracts.
- Zero-citation short-circuit: if iCite has no citing PMIDs, `/api/what-next` returns immediately with an empty list and a plain message, skipping the LLM call entirely, per the brief.
- Tested with curl: a paper with 2141 citations (10 recent 2025/2026 citing papers returned, ~4s total incl. the LLM call), a lightly-cited paper (2 citations, correctly summarized), a genuinely zero-citation very-recent PMID (found by searching PubMed sorted by date and checking iCite, confirmed empty list + message in 0.6s, no LLM call), missing pmid (400), nonexistent pmid (404).

---

## Step 5: `/api/trend`

Prompt: "/api/trend."

- New `llm.generate_trend_query`: system prompt asks for one plain PubMed query string (no quotes/explanation) capturing the paper's core topic from its title/abstract - the response is stripped of stray quoting and returned to the frontend so the user can see and edit it, per the brief.
- `POST /api/trend` accepts `{"pmid": ...}` (generates the query via the LLM) or `{"query": ...}` (uses it verbatim - this is the "edit the query and re-run" path from the frontend, and skips the LLM entirely). Then calls `pubmed.search_count_for_year` once per year for the last 20 years (current year back 19) and returns `{query, years, counts}`.
- Hit NCBI rate limiting (`429 Too Many Requests`) on the very first live test of the by-pmid path, because 20 sequential esearch calls in a row is bursty even under our throttle. Fixed by (1) widening the no-API-key throttle interval from 0.35s to 0.4s and (2) adding retry-with-backoff (up to 3 attempts, increasing sleep) specifically for 429s in `pubmed._get`, so a transient rate-limit blip doesn't fail the whole trend request. Also swapped the placeholder `NCBI_EMAIL` in `.env` for a real address, since NCBI asks every tool to identify a real contact.
- Tested with curl: trend by pmid (20 real yearly counts + an LLM-generated query, ~9s total - acceptable for a demo given NCBI's rate limit), trend by an explicit edited query (skips the LLM, still ~8s for the 20 count calls), missing both pmid and query (400), nonexistent pmid with no query (404).

---

## Step 6: Frontend (in `papertrail-frontend`, developed locally first per the user's call)

Prompt: "Frontend wired to the local backend; test every error case."

- Single page (`index.html` + `style.css` + `app.js`), sections in the brief's order: input + example chips, paper card, level slider + explanation, what-happened-next, trend chart. Chart.js pulled from the jsdelivr CDN.
- `API_BASE` is one constant at the top of `app.js` (currently `http://127.0.0.1:5001`, to be swapped for the Render URL at deploy time). All backend calls go through a shared `apiPost`/`apiGet` helper with an `AbortController` timeout, so a hung request always resolves into a friendly error instead of spinning forever.
- After `/api/paper` resolves, `/api/explain`, `/api/what-next`, and `/api/trend` are kicked off in parallel (not chained) so one slow section never blocks the others, each with its own loading/error state.
- `checkServerHealth()` calls `/health` on page load; if it takes >1.5s, shows "Waking up the server, this can take up to a minute…" (handles Render free-tier cold starts).
- Caught and fixed a real bug before it shipped: the explain-slider dedupe check only compared reading *level*, not level+pmid, so looking up a second paper at the same slider position would skip the fetch and silently show the first paper's stale explanation. Fixed by keying the dedupe check on `${pmid}:${level}`.
- Also hardened the citing-papers list against unsafe HTML string interpolation (titles pulled straight from PubMed could contain `&`/`<`) by building those DOM nodes with `textContent` instead of `innerHTML` + template strings.
- Verified locally end-to-end: served the frontend with `python3 -m http.server 5500` (matches the backend's default `ALLOWED_ORIGINS`), confirmed the CORS preflight + actual request both succeed from `http://127.0.0.1:5500`, and confirmed a request from an untrusted origin (`https://evil-site.example.com`) gets **no** `Access-Control-Allow-Origin` header back. All static files (html/css/js) and the Chart.js CDN URL load with HTTP 200. Remaining error-path testing (empty input, fake PMID, backend stopped) to be done by hand in an actual browser next.

---

## Step 8: Deploy to Render + GitHub Pages

Prompt: assignment instructions pasted verbatim, asking for help getting both repos onto GitHub, the backend onto Render, and the frontend onto GitHub Pages.

- `gh auth status` showed an already-authenticated GitHub CLI (account `andrewjounkim`), which also resolved the still-outstanding GitHub-username question from step 1. Used `gh repo create --source=. --push` to create and push both repos as public: [papertrail-backend](https://github.com/andrewjounkim/papertrail-backend), [papertrail-frontend](https://github.com/andrewjounkim/papertrail-frontend). Verified with `git log --all -p | grep` across both histories that no secret/key ever entered a commit.
- Enabled GitHub Pages on the frontend repo via `gh api -X POST repos/.../pages` (serving `main` branch, root) → `https://andrewjounkim.github.io/papertrail-frontend/`.
- Render deployment itself needs a human in the dashboard (no Render CLI/API access from here) - gave step-by-step instructions: new Web Service from the `papertrail-backend` repo, build `pip install -r requirements.txt`, start `gunicorn app:app`, Free tier, env vars set directly in Render's dashboard (`OPENAI_API_KEY`, `OPENAI_MODEL`, `NCBI_EMAIL`, `NCBI_TOOL_NAME`, `ALLOWED_ORIGINS`) - no `.env` file involved at all on Render.
- **Real bug found in production, not caught locally**: hitting the bare Render URL (`/`, no route defined there) returned `{"error":"Internal server error"}` (500) instead of a 404. Root cause: the catch-all `@app.errorhandler(Exception)` was broad enough to also intercept Flask/Werkzeug's own `HTTPException`s (404 on an unknown route, 405 on a wrong method, etc.) and mask them all as a generic 500. Fixed by adding a dedicated `@app.errorhandler(HTTPException)` — registered separately so Flask picks the more specific handler — that preserves the real status code and message; the bare-`Exception` handler now only fires for genuinely unexpected errors. Verified locally (`/` → 404 JSON, wrong method → 405 JSON, `/api/paper` success/400/404 paths all unaffected) and pushed for Render to auto-redeploy.

