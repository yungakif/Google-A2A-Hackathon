"""The research agent: deep internet research on behalf of customer service."""

import os

from google.adk.agents import LlmAgent

MODEL = os.environ.get("MODEL", "gemini-3.5-flash")

INSTRUCTION = (
    "You are the Research Agent. Your job is to conduct deep internet research "
    "using search tools when the Customer Service agent asks you a question."
)


def web_search(query: str) -> dict:
    """Search the internet for information relevant to a query.

    Placeholder implementation: wire this up to a real search backend (e.g. a
    web search API) before relying on it. For now it returns a stub result so
    the agent and its tool wiring can be exercised end to end.

    Args:
        query: A natural-language question or set of keywords to research.

    Returns:
        A dict with the original query and a list of result snippets.
    """
    return {
        "query": query,
        "results": [
            {
                "title": "Placeholder result",
                "snippet": (
                    "Web search is not wired up yet. Replace web_search in "
                    "research_agent/agent.py with a real search backend."
                ),
                "url": "",
            }
        ],
    }


root_agent = LlmAgent(
    name="research_agent",
    model=MODEL,
    instruction=INSTRUCTION,
    tools=[web_search],
)
