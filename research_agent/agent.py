"""The research agent: gathers context for the customer-service chain.

It researches questions the CS agent can't answer from the bank knowledge base
(general/public facts, via the Linkup web search API), synthesises an answer
with citations, and writes the durable findings into the session's shared
context layer (Redis) so the personal and CS agents can reuse them without
asking again. It also sees whatever the chain has already gathered, so it never
re-researches something already known this session.
"""

import os

from google.adk.agents import LlmAgent
from google.adk.models.google_llm import Gemini
from google.genai import types
from linkup import LinkupClient

from context_store import inject_context, remember_context

MODEL = os.environ.get("MODEL", "gemini-3.5-flash")

# Linkup search configuration. depth: "fast" | "standard" | "deep".
LINKUP_DEPTH = os.environ.get("LINKUP_DEPTH", "standard")
LINKUP_TIMEOUT_S = float(os.environ.get("LINKUP_TIMEOUT_S", "60"))

# Retry transient/rate-limit errors with bounded backoff, same as the graded
# agents, so this hop stays inside the chain's turn/task time budget.
_RETRY = types.HttpRetryOptions(
    attempts=4, initial_delay=1.0, max_delay=20.0, exp_base=2.0, jitter=0.5,
    http_status_codes=[429, 500, 503],
)

INSTRUCTION = (
    "You are the Research Agent in a customer-service chain. The customer "
    "service agent delegates questions to you that it cannot answer from the "
    "bank knowledge base.\n\n"
    "Your job:\n"
    "1. Use the `web_search` tool to research the question. Base your reply "
    "strictly on the search results and cite the source URLs.\n"
    "2. Save the durable, reusable findings to the shared session context with "
    "`remember_context(key, value)` (e.g. key=\"fx_usd_gbp\", value=\"0.79 as "
    "of <date> (source: ...)\"), so the rest of the chain can reuse them.\n"
    "3. Check the shared session context shown in your prompt first — if the "
    "answer is already there, return it instead of searching again.\n\n"
    "If web search is unavailable (it returns an error), say so plainly and "
    "concisely rather than inventing facts."
)


def web_search(query: str) -> dict:
    """Search the public internet for information relevant to a query.

    Backed by the Linkup search API, which returns a synthesized answer with
    citations to the source material.

    Args:
        query: A natural-language question or set of keywords to research.

    Returns:
        A dict with the original query, a synthesized ``answer``, and a list of
        ``sources`` (each with ``name``, ``url``, and ``snippet``). On
        misconfiguration or failure the dict contains an ``error`` field.
    """
    api_key = os.environ.get("LINKUP_API_KEY")
    if not api_key:
        return {
            "query": query,
            "error": "LINKUP_API_KEY is not set; cannot run web search.",
        }

    try:
        client = LinkupClient(api_key=api_key)
        response = client.search(
            query=query,
            depth=LINKUP_DEPTH,
            output_type="sourcedAnswer",
            timeout=LINKUP_TIMEOUT_S,
        )
    except Exception as exc:
        return {"query": query, "error": f"Web search failed: {exc}"}

    return {
        "query": query,
        "answer": response.answer,
        "sources": [
            {"name": source.name, "url": source.url, "snippet": source.snippet}
            for source in response.sources
        ],
    }


root_agent = LlmAgent(
    name="research_agent",
    model=Gemini(model=MODEL, retry_options=_RETRY),
    instruction=INSTRUCTION,
    tools=[web_search, remember_context],
    before_model_callback=inject_context,
)
