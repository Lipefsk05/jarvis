"""A quick answer from the internet: Gemini with Google Search grounding (free tier). Only the owner's question
leaves for Google, never the Mind. Blocking call; the bot runs it in a thread."""
from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import date
from typing import Callable

DEFAULT_MODEL = "gemini-2.5-flash"
MAX_SOURCES = 4

PROMPT = (
    "Hoje é {today}. Responda em português, direto, em no máximo 700 caracteres, texto simples (sem markdown), com "
    "datas e valores exatos quando houver. Se a busca não achar uma resposta confiável, diga isso em vez de chutar.\n\n"
    "Pergunta: {question}"
)


class SearchError(Exception):
    """The quick search failed (no key, quota, network, empty answer). The caller falls back to the Worker."""


@dataclass(frozen=True)
class Answer:
    text: str
    sources: tuple[tuple[str, str], ...]  # (title, url)


def parse_response(response) -> Answer:
    """Text and cited pages from a Gemini grounded response (duck-typed, so tests need no SDK)."""
    text = (getattr(response, "text", None) or "").strip()
    if not text:
        raise SearchError("empty answer")
    sources, seen = [], set()
    try:
        chunks = response.candidates[0].grounding_metadata.grounding_chunks or []
    except (AttributeError, IndexError, TypeError):
        chunks = []
    for chunk in chunks:
        web = getattr(chunk, "web", None)
        url = getattr(web, "uri", None)
        if url and url not in seen:
            seen.add(url)
            sources.append(((getattr(web, "title", None) or url)[:80], url))
    return Answer(text, tuple(sources[:MAX_SOURCES]))


def gemini_search(question: str, api_key: str, today: date, model: str = DEFAULT_MODEL, timeout_s: float = 25,
                  client_factory: Callable | None = None) -> Answer:
    if not api_key:
        raise SearchError("no Gemini key")
    try:
        from google import genai
        from google.genai import types

        client = (client_factory or genai.Client)(api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout_s * 1000)))
        response = client.models.generate_content(
            model=model,
            contents=PROMPT.format(today=today.strftime("%d/%m/%Y"), question=question),
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                thinking_config=types.ThinkingConfig(thinking_budget=0),
                max_output_tokens=900,
            ),
        )
    except SearchError:
        raise
    except Exception as exc:  # quota (429), network, a model that changed: all mean "use the Worker instead"
        raise SearchError(type(exc).__name__) from exc
    return parse_response(response)


def format_answer(answer: Answer) -> str:
    """Telegram HTML: the answer, then the cited sites as short clickable names (the raw links are huge redirects)."""
    text = html.escape(answer.text, quote=False)
    if not answer.sources:
        return text
    links = ", ".join(f'<a href="{html.escape(url, quote=True)}">{html.escape(title, quote=False)}</a>' for title, url in answer.sources)
    return f"{text}\n\nFontes: {links}"
