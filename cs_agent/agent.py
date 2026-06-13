"""Rho-Bank customer service agent: policy + env tools + KB search (RAG)."""

import os
from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.models.google_llm import Gemini
from google.genai import types

from context_store import inject_context, remember_context
from env_toolset import EnvApiToolset
from rag_tools import kb_search, kb_search_bm25, kb_search_vector
from research_client_tool import ask_research_agent
from sequencer import unlock_and_call
from tool_guard import dedupe_after_tool, dedupe_before_tool

MODEL = os.environ.get("MODEL", "gemini-3.5-flash")
POLICY_PATH = Path(os.environ.get("KB_POLICY_PATH", "/app/kb/policy.md"))

# Retry on Vertex rate-limit / transient errors with exponential backoff + jitter,
# so running the eval at higher concurrency on a single API key degrades into
# slower calls instead of 429 RESOURCE_EXHAUSTED -> TIMEOUT -> reward 0. Also a
# grading-reliability win: the scored run hits the same quota.
_RETRY = types.HttpRetryOptions(
    attempts=4, initial_delay=1.0, max_delay=20.0, exp_base=2.0, jitter=0.5,
    http_status_codes=[429, 500, 503],
)

RAG_GUIDANCE = """

## Knowledge Base Access

You do NOT have the knowledge base inlined. Before answering policy questions
or performing scenario-specific procedures, search the knowledge base:
- kb_search(query): hybrid keyword+semantic search — PREFER THIS. It fuses both
  methods and is the most reliable way to find procedures, eligibility rules,
  and exact internal/discoverable tool names.
- kb_search_bm25(query): keyword-only search (fallback for exact strings).
- kb_search_vector(query): semantic-only search (fallback).

Search before you act; procedures, eligibility rules, internal tool names,
and scenario-specific guidance all live in the knowledge base. If a search
comes up empty, rephrase and try again before telling the customer you can't
find the information.
"""

SEQUENCER_GUIDANCE = """

## Using agent-discoverable tools (do it in ONE step)

When the knowledge base names an agent-discoverable tool you must use, call
`unlock_and_call(agent_tool_name, arguments_json)` — it unlocks AND calls the
tool in a single step. Do NOT split this into a separate unlock then call: that
wastes a turn and is a common way the call gets dropped. If a procedure needs
the tool called several times (e.g. once per account or card), call
`unlock_and_call` once per argument set, and complete EVERY required call before
you finish.
"""

RESEARCH_GUIDANCE = """

## Research agent + shared session context

For information OUTSIDE the bank knowledge base (general/public facts), delegate
to `ask_research_agent(message)`; it researches and writes what it finds into
this session's shared context. For bank policy and procedures, use the knowledge
base directly (kb_search) — do not route policy questions to research. If the
research agent is unavailable, answer from the knowledge base instead; never
stall waiting on it.

A shared session context (shown above, refreshed each turn) carries facts the
agents in this conversation have already gathered. Treat it as a cache: reuse it
to avoid re-deriving work, but verify anything you act on, and work normally if
it is empty. When you establish something durable and reusable — the user's
verified identity, their record fields, the resolved procedure, or an exact
discoverable tool name and its arguments — save it with
`remember_context(key, value)` so the rest of the chain benefits.
"""

root_agent = LlmAgent(
    name="cs_agent",
    model=Gemini(model=MODEL, retry_options=_RETRY),
    instruction=(
        POLICY_PATH.read_text() + RAG_GUIDANCE + SEQUENCER_GUIDANCE + RESEARCH_GUIDANCE
    ),
    tools=[
        EnvApiToolset(),
        kb_search,
        kb_search_bm25,
        kb_search_vector,
        unlock_and_call,
        ask_research_agent,
        remember_context,
    ],
    before_model_callback=inject_context,
    before_tool_callback=dedupe_before_tool,
    after_tool_callback=dedupe_after_tool,
)
