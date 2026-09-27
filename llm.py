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
