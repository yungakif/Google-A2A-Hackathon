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

## Strict Boundary: never act as the user

You are the bank's side of the conversation. NEVER attempt to use user-side
tools or take actions on the user's behalf (e.g. applying for a card,
submitting a referral, accepting an offer) — those belong to the personal
agent, not to you. When a policy or procedure requires a user action, do not
perform it yourself; instead tell the personal agent exactly what the user
needs to do, and which details are required, so the personal agent can carry
it out.
"""

RESEARCH_GUIDANCE = """

## Research Agent

The knowledge base only covers Rho-Bank policy. ALWAYS search the internal
knowledge base (kb_search_bm25 / kb_search_vector) FIRST for any question.
Only call ask_research_agent(message) when BOTH of these hold:
- the internal knowledge base search has failed to answer the question, AND
- the question is about external market or competitor data from the public
  internet (e.g. other banks' rates, broader market conditions) rather than
  Rho-Bank policy.
Never delegate Rho-Bank policy questions to the research agent. When you do
delegate, relay the research agent's findings back faithfully.
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
