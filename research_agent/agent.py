"""The research agent: deep internet research on behalf of customer service."""

import os

from google.adk.agents import LlmAgent
from linkup import LinkupClient

MODEL = os.environ.get("MODEL", "gemini-3.5-flash")

# Linkup search configuration. depth: "fast" | "standard" | "deep".
LINKUP_DEPTH = os.environ.get("LINKUP_DEPTH", "standard")
LINKUP_TIMEOUT_S = float(os.environ.get("LINKUP_TIMEOUT_S", "60"))

INSTRUCTION = (
    "You are the Research Agent. Your job is to conduct deep internet research "
    "using the web_search tool when the Customer Service agent asks you a "
    "question. Base your reply on the search results and cite the source URLs."
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
        misconfiguration the dict contains an ``error`` field instead.
    """
    api_key = os.environ.get("LINKUP_API_KEY")
    if not api_key:
        return {
            "query": query,
            "error": "LINKUP_API_KEY is not set; cannot run web search.",
        }

    client = LinkupClient(api_key=api_key)
    response = client.search(
        query=query,
        depth=LINKUP_DEPTH,
        output_type="sourcedAnswer",
        timeout=LINKUP_TIMEOUT_S,
    )
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
    model=MODEL,
    instruction=INSTRUCTION,
    tools=[web_search],
)
