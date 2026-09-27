"""OpenAI calls, all grounded in real PubMed/iCite data - never the model's
own memory of a paper. Every system prompt says so explicitly."""

import os

import openai
from openai import OpenAI

from errors import UpstreamError

_client = None


def _client_instance():
    global _client
    if _client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise UpstreamError("Server is missing OPENAI_API_KEY")
        _client = OpenAI(api_key=api_key)
    return _client


def _model():
    return os.environ.get("OPENAI_MODEL", "gpt-4o-mini")


def _call(system, user_message, max_tokens=700):
    try:
        response = _client_instance().chat.completions.create(
            model=_model(),
            max_completion_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_message},
            ],
        )
    except openai.OpenAIError as err:
        raise UpstreamError(f"LLM request failed: {err}") from err

    text = (response.choices[0].message.content or "").strip()
    if not text:
        raise UpstreamError("LLM returned an empty response")
    return text


# --- /api/explain ------------------------------------------------------

_LEVEL_SYSTEM_PROMPTS = {
    "high_school": (
        "You explain research papers to a curious high school student who has "
        "no specialized science background. Use plain everyday language, short "
        "sentences, and concrete analogies. Avoid jargon; when a technical term "
        "is unavoidable, define it in the same sentence. 3-5 sentences. "
        "Base your explanation ONLY on the title and abstract provided below - "
        "do not add outside facts about the paper or its authors."
    ),
    "undergrad": (
        "You explain research papers to a college undergraduate who has taken "
        "introductory courses in the relevant field. You can use standard "
        "technical vocabulary for that field, but still explain the paper's "
        "goal, method, and main finding clearly. 3-5 sentences. "
        "Base your explanation ONLY on the title and abstract provided below - "
        "do not add outside facts about the paper or its authors."
    ),
    "expert": (
        "You explain research papers to a domain expert (e.g. a grad student "
        "or researcher in the same field). Be precise and technical, and "
        "highlight what is methodologically or scientifically notable, novel, "
        "or limited about the work. 3-5 sentences. "
        "Base your explanation ONLY on the title and abstract provided below - "
        "do not add outside facts about the paper or its authors."
    ),
}

VALID_LEVELS = set(_LEVEL_SYSTEM_PROMPTS)


def explain_paper(title, abstract, level):
    system = _LEVEL_SYSTEM_PROMPTS[level]
    abstract_text = abstract or "(no abstract available - use the title only.)"
    user_message = f"Title: {title}\n\nAbstract: {abstract_text}"
    return _call(system, user_message, max_tokens=400)


# --- /api/what-next ------------------------------------------------------

_CITATIONS_SYSTEM_PROMPT = (
    "You summarize how later research has engaged with an original paper, "
    "based ONLY on the titles (and abstracts, when available) of a list of "
    "papers that cite it - you have not read the full text of any of them "
    "and have no other knowledge of this research area or these papers. "
    "In 3-5 sentences, describe patterns you can actually see in the given "
    "titles/abstracts: common applications, methods, extensions, or "
    "disagreements. If some entries have no abstract, rely on their titles "
    "only for those. Do not invent findings, numbers, or conclusions that "
    "are not visible in the text given to you. End your summary with a "
    "short clause making clear it is based only on the retrieved titles/"
    "abstracts of these citing papers, not their full text."
)


def summarize_citations(paper_title, citing_papers):
    """citing_papers: list of {title, year, abstract} dicts, most-recent first."""
    lines = []
    for i, paper in enumerate(citing_papers, 1):
        abstract_text = (paper.get("abstract") or "").strip() or "(no abstract retrieved)"
        lines.append(f'{i}. "{paper["title"]}" ({paper["year"]})\nAbstract: {abstract_text}')
    listing = "\n\n".join(lines)

    user_message = (
        f'Original paper: "{paper_title}"\n\n'
        f"Citing papers (most recent first):\n\n{listing}"
    )
    return _call(_CITATIONS_SYSTEM_PROMPT, user_message, max_tokens=350)
