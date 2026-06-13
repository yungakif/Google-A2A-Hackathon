"""Rho-Bank customer service agent: policy + env tools + KB search (RAG)."""

import os
from pathlib import Path

from google.adk.agents import LlmAgent

from env_toolset import EnvApiToolset
from rag_tools import kb_search_bm25, kb_search_vector
from research_client_tool import ask_research_agent
from shared_memory import inject_shared_memory, update_shared_memory

MODEL = os.environ.get("MODEL", "gemini-3.5-flash")
POLICY_PATH = Path(os.environ.get("KB_POLICY_PATH", "/app/kb/policy.md"))

RAG_GUIDANCE = """

## Knowledge Base Access

You do NOT have the knowledge base inlined. Before answering policy questions
or performing scenario-specific procedures, search the knowledge base:
- kb_search_bm25(query): keyword search.
- kb_search_vector(query): semantic search for natural-language questions.

Search before you act; procedures, eligibility rules, internal tool names,
and scenario-specific guidance all live in the knowledge base. If a search
comes up empty, rephrase and try again before telling the customer you can't
find the information.
"""

RESEARCH_GUIDANCE = """

## Research Agent

The knowledge base only covers Rho-Bank policy. When you need general
information from the public internet that is not in the knowledge base, use
ask_research_agent(message) to delegate the lookup to the research agent and
relay its findings. Prefer the knowledge base for bank policy; use the
research agent for general internet research.
"""

MEMORY_GUIDANCE = """

## Shared Memory

Before taking action, check the current shared memory state to understand the
user's context — it is shown to you under "Shared Memory (session context)".
When you learn a durable fact about the user (e.g. their name, intent, or
verified details), store it with update_shared_memory so the other agents can
see it too.
"""

root_agent = LlmAgent(
    name="cs_agent",
    model=MODEL,
    instruction=POLICY_PATH.read_text()
    + RAG_GUIDANCE
    + RESEARCH_GUIDANCE
    + MEMORY_GUIDANCE,
    tools=[
        EnvApiToolset(),
        kb_search_bm25,
        kb_search_vector,
        ask_research_agent,
        update_shared_memory,
    ],
    before_model_callback=inject_shared_memory,
)
