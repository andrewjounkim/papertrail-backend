# Prompt log

AI tools used on this project:
- **Claude Code** (Sonnet 5) — pair-programmed the backend, frontend, and portfolio integration in this session.
- **OpenAI API** (model set via `OPENAI_MODEL`, default `gpt-4o-mini`) — the in-app LLM that powers `/api/explain`, `/api/what-next`, and query generation for `/api/trend`.

## Key prompts

### 1. Original project brief

Build PaperTrail, a research paper reading companion, for a class assignment (HW4) due today. Two repos: a Flask backend on Render, a static HTML/CSS/JS frontend on GitHub Pages. The backend normalizes a PMID/URL/DOI, fetches metadata + abstract from PubMed E-utilities and citation stats from iCite, and uses an LLM (grounded only in retrieved data, never invented) to: (1) explain the paper at three reading levels, (2) summarize how later citing papers built on/challenged it, and (3) generate a PubMed query to chart the field's yearly publication trend. Hard requirements: no secrets committed (env vars + `.env`/`.gitignore` from the first commit), CORS restricted to the GitHub Pages origin + localhost, JSON error responses with correct status codes and timeouts on every outbound call, loading states and friendly errors on the frontend, and a "wake up the sleeping Render backend" health check. Build order: backend skeleton → `/api/paper` → `/api/explain` → `/api/what-next` → `/api/trend` → frontend wired locally → README + this log → deploy instructions.

### 2. LLM provider switch

"wait im going to use an open ai key can you help set that up" — switched the backend from the originally-planned Anthropic Claude API to the **OpenAI API** partway through building `/api/explain`. This changed `requirements.txt` (`anthropic` → `openai`), the env vars (`ANTHROPIC_API_KEY`/`ANTHROPIC_MODEL` → `OPENAI_API_KEY`/`OPENAI_MODEL`, default model `gpt-4o-mini`), and `llm.py` (rewritten to call the `openai` SDK's `chat.completions.create` instead of the `anthropic` SDK's `messages.create`). Every other module was untouched since none of them talk to the LLM provider directly.

### 3. Credits line

"under the papertrail put credits that it was built by claude code sonnet 5 for 15-113" (later corrected to: put it in the footer, not under the header). The deployed frontend's footer now reads: *"Built with Claude Code (Sonnet 5) for 15-113."*

### 4. Portfolio integration

"can you also help me make the portfolio section in my website" / "just like strikeout lab can you also put in an image of it" — added a PaperTrail project card to the portfolio's `projects.html`, matching the existing "meta-project" card pattern used for another 15-113 project (Strikeout Lab): a description, a stat row, links to the live app and both repos, and a swipeable photo strip. The three screenshots were captured by scripting a real headless-browser run against the live deployed frontend (Playwright), so they show actual live data, not mockups.

## System prompts sent to the LLM

All calls go through one helper (`llm.py: _call`) as a `system` + `user` message pair. The system prompts, verbatim:

**`/api/explain` — high_school level:**
> You explain research papers to a curious high school student who has no specialized science background. Use plain everyday language, short sentences, and concrete analogies. Avoid jargon; when a technical term is unavoidable, define it in the same sentence. 3-5 sentences. Base your explanation ONLY on the title and abstract provided below - do not add outside facts about the paper or its authors.

**`/api/explain` — undergrad level:**
> You explain research papers to a college undergraduate who has taken introductory courses in the relevant field. You can use standard technical vocabulary for that field, but still explain the paper's goal, method, and main finding clearly. 3-5 sentences. Base your explanation ONLY on the title and abstract provided below - do not add outside facts about the paper or its authors.

**`/api/explain` — expert level:**
> You explain research papers to a domain expert (e.g. a grad student or researcher in the same field). Be precise and technical, and highlight what is methodologically or scientifically notable, novel, or limited about the work. 3-5 sentences. Base your explanation ONLY on the title and abstract provided below - do not add outside facts about the paper or its authors.

**`/api/what-next` — citation summary:**
> You summarize how later research has engaged with an original paper, based ONLY on the titles (and abstracts, when available) of a list of papers that cite it - you have not read the full text of any of them and have no other knowledge of this research area or these papers. In 3-5 sentences, describe patterns you can actually see in the given titles/abstracts: common applications, methods, extensions, or disagreements. If some entries have no abstract, rely on their titles only for those. Do not invent findings, numbers, or conclusions that are not visible in the text given to you. End your summary with a short clause making clear it is based only on the retrieved titles/abstracts of these citing papers, not their full text.

**`/api/trend` — search query generation:**
> You write PubMed search queries. Given a paper's title and abstract, write ONE concise PubMed search query (plain keywords/phrases, optionally combined with AND/OR, using PubMed's standard search syntax) that captures the paper's core research topic - broad enough to find other papers in the same field, specific enough to not just match a whole discipline. Respond with ONLY the query text itself: no quotes around it, no explanation, no leading label like 'Query:'.

(Source: `llm.py`.)
