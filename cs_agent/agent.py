"""Rho-Bank customer service agent: policy + env tools + KB search (RAG)."""

import os
from pathlib import Path

from google.adk.agents import LlmAgent

from env_toolset import EnvApiToolset
from rag_tools import kb_search

MODEL = os.environ.get("MODEL", "gemini-3.5-flash")
POLICY_PATH = Path(os.environ.get("KB_POLICY_PATH", "/app/kb/policy.md"))

RAG_GUIDANCE = """

## Knowledge Base Access

You do NOT have the knowledge base inlined. Before answering policy questions or
performing scenario-specific procedures, search it:
- kb_search(query): returns the most relevant knowledge-base *sections* (title,
  section heading, content), combining keyword and semantic search.

Search before you act; procedures, eligibility rules, internal tool names, and
scenario-specific guidance all live in the knowledge base. If a search comes up
empty or off-target, rephrase and search again before telling the customer you
can't find the information.

## Answering style (be fast and actionable)

- Lead with the direct answer and the single next step or exact tool name. Do not
  write multi-section "comprehensive guides" or long comparisons unless explicitly
  asked.
- When the caller is an assistant acting for a user, give the specific action or
  tool to use, not a step-by-step human tutorial.
- Concise means format, not shortcuts: still verify identity when required, state
  the real eligibility conditions, and never invent policy.

## Getting write actions right

When you call a tool that changes state (submitting, approving, ordering, paying,
filing), use the EXACT argument values and enum options named in the knowledge
base and the user's verified details — don't guess, round, or fabricate them. If
the knowledge base lists specific requirements for that action, follow them.
"""

root_agent = LlmAgent(
    name="cs_agent",
    model=MODEL,
    instruction=POLICY_PATH.read_text() + RAG_GUIDANCE,
    tools=[EnvApiToolset(), kb_search],
)
