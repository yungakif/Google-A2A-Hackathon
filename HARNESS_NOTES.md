# Engineering Map: a2anet/a2a-hackathon Banking Harness

A field guide for optimizing the two A2A banking agents against the tau2-derived
marking harness. Harness code: `/Users/rafe/a2a-hackathon/src/a2a_hack/`. tau2
internals: `/Users/rafe/a2a-hackathon/.venv/lib/python3.12/site-packages/tau2/`.
(Generated from a multi-agent read of the harness; file:line refs are concrete.)

## 1. End-to-end flow of one scored task

One `uuid4().hex` is minted per task (`runner.py:90`) and is simultaneously the env
session id AND the A2A `contextId`. Lose it → nothing is recorded → reward 0.

- A fresh isolated tau2 `Environment`/DB is built per session (`sessions.py:154-161`) — hard cross-contextId isolation.
- `A2ABridgeAgent(personal_url, context_id=sid)` (`bridge.py:59-70`) is the tau2 "agent" slot AND the A2A client for **leg 1** (user-sim ↔ personal). It POSTs an A2A `Message` with `context_id=self.context_id` (`bridge.py:91-96`); identity rides entirely on contextId, no metadata. Per-turn timeout 300s (`bridge.py:22`).
- **Leg 2 (personal ↔ CS) is observed, not driven.** The personal agent reaches the CS agent through the harness gateway `POST /cs-agent` (`server.py:173-225`) — a transparent passthrough to the real CS url that records the `personal` and `cs` messages keyed by contextId. The `/cs-agent` well-known card rewrites `card.url` back to the gateway (`server.py:130-148`) so all later CS calls keep routing through the harness.
- Both agents run bank tools via `POST /sessions/{cid}/tools/{name}` (`server.py:112-124`), bearer-scoped.
- Post-run: `merge_trajectory` (`merge.py:28-68`) interleaves leg-1 messages with recorded env-tool calls by timestamp, then `evaluate_simulation(..., ALL)` scores the merged trajectory.
- `smoke` (`cli.py:155-242`) runs one task (default: first feedback task) and prints both legs + warns on zero tool calls / zero leg-2 — the fastest contextId check.

## 2. Tools + the discoverable-tool mechanics (where complex tasks are won/lost)

Bearer token → scope (`sessions.py:146-152`): user_token→`user`, agent_token→`agent`.
- **user scope** (personal agent): `env.get_user_tools(include=task.user_tools)` — filtered to the task's declared `user_tools` only.
- **agent scope** (CS agent): `env.get_tools()` — full `KnowledgeTools`. NOTE: domain is registered with **`no_knowledge`** retrieval (`domain.py:55-68`), so the harness gives the CS agent NO KB-search tool — KB retrieval is entirely the team's own Redis RAG.

Default agent tools: `transfer_to_human_agents` (no mutation), `get_current_time()` (hardcoded `'2025-11-14 03:40:00 EST'`), `get_user_information_by_id/_by_name/_by_email`, `change_user_email`, `get_referrals_by_user`, `get_credit_card_*_by_user`, `log_verification`, and the discoverable dispatchers. Default user tools: `apply_for_credit_card`, `submit_referral`, `submit_transaction`, `request_human_agent_transfer`, + user dispatchers.

**Discoverable tools — the trap:** ~50 agent-side + 4 user-side reward-bearing tools are
EXCLUDED from `GET /tools` and the list NEVER grows on unlock (`toolkit.py:144-165`). What
changes is internal gate state.
- Agent side (two-step): `unlock_discoverable_agent_tool(name)` (in-memory only, no DB write, `tools.py:591`) → `call_discoverable_agent_tool(name, args)` (hard-fails if not unlocked, `tools.py:652-656`; on success writes audit row + mutates real tables).
- User side (cross-agent handshake): CS agent calls `give_discoverable_user_tool(name,args)` FIRST (writes a `GIVEN` row, `tools.py:570-578`) → personal agent calls `call_discoverable_user_tool(name,args)`, which self-checks the GIVEN row and errors otherwise (`tools.py:4070-4083`).
- Winning trajectory: `KB_search → unlock/give → call`. Retrieval quality gates which tool the agent even knows to unlock.

## 3. Reward (per reward_basis) + termination gate

1. **Termination gate first** (`evaluator.py:113-123`): only `AGENT_STOP`/`USER_STOP` pass. `MAX_STEPS`/`TOO_MANY_ERRORS`/`TIMEOUT` (600s task / 300s turn)/`*_ERROR` → reward **0** regardless of DB correctness.
2. Components **multiply** over the task's `reward_basis` (any 0 zeroes the task). Default basis `[DB, COMMUNICATE]`.
   - **DB** (`evaluator_env.py`): hash of the ENTIRE TransactionalDB (agent- AND user-side, both must match) after replaying the trajectory vs replaying the gold `actions`. Path-independent; any stray/missing/mis-formatted write fails. 87/97 tasks are DB-only.
   - **ACTION** (9 tasks): all golden tool calls must appear with matching args (`compare_with_tool_call`).
   - **NL_ASSERTION** (1 task): LLM judge over the transcript.
   - **COMMUNICATE**: every `communicate_info` string must appear as a substring in agent messages.
3. Pairing aggregate: `final = 0.5·a + 0.25·b + 0.25·c` (`scoring.py:17`). `INFRASTRUCTURE_ERROR` → 0 AND drops the task from the cross-team `completed` set.

## 4. DB model + identity verification

One Pydantic `TransactionalDB` of schemaless `{record_id → record}` tables. Entities:
`users` (id/name/address/email/phone/DOB), `accounts`, `debit_cards`, `credit_card_accounts`
(balance as `$`-string, rewards as `"N points"`), `referrals`, `verification_history`,
transactions/disputes/orders, plus empty-but-defined tables the agent populates.

**Verification:** 2-of-4 of {DOB, email, phone, address} (`tools.py:482-483`). `log_verification`
does NOT enforce the match — it writes the supplied fields + canonical time into
`verification_history`, which IS hashed, so the row must be exact (true user values +
`'2025-11-14 03:40:00 EST'`). Determinism: use the `generate_*_id` helpers (seeded from args);
invented ids never collide with gold; exact string formatting ($, "N points", MM/DD/YYYY) required.

## 5. tau2 reference RAG — port shortlist for Redis + Gemini

Pipeline (`tau2/knowledge/`): index (no chunking — one doc = one unit) → query encode →
retrieve (BM25Okapi + numpy cosine + grep, unioned by max-score, NOT RRF) → postprocess
(pointwise LLM reranker, default for `*_reranker` variants).

Port ideas, by leverage:
1. **Pointwise LLM reranker** (highest leverage, simplest): a Gemini call rates each candidate 0–10 vs a relevance prompt, drop <7, keep top_k. No infra.
2. **Hybrid BM25 + Gemini cosine fused with RRF** (reference unions by max-score; RRF is better given different score scales).
3. **Symmetric encoding** for Gemini (no instruction prefix on either side; the Qwen `Instruct:` prefix is model-specific).
4. **Grep/shell fallback** over raw KB for exact strings (account numbers, fee tables).
5. **Content-hash embedding cache** for free re-runs (we already bake `kb/embeddings.json`).
6. **Bracket eval** with `golden_retrieval` (ceiling) and `no_knowledge` (floor).
7. Skip chunking unless docs are large; feed full doc content to the agent.

## 6. Optimization priorities (mapped to the baseline failure pattern)

Simple `apply_for_credit_card` tasks pass: default user tool, one deterministic row, no
unlock/handshake. Complex verify + discoverable-agent-tool tasks fail at these seams:

- **P0 contextId** on every CS call + every env tool call. Drop it → empty trajectory → 0. Verify via `smoke` zero-call warnings. Point `CS_AGENT_URL` at the `/cs-agent` gateway.
- **P0 end cleanly** (AGENT_STOP/USER_STOP). Keep each personal turn's full CS sub-loop < 300s, task < 600s; watch step/error budgets.
- **P1 discoverable-agent-tool loop**: `KB_search → unlock → call`; don't re-poll the schema (it never grows) — drive discovery from the KB.
- **P1 give/call handshake**: CS agent must `give_discoverable_user_tool` before the personal agent calls it — sequence give-before-call across the A2A boundary.
- **P1 optimize destination DB state, not tool sequence**: no stray writes, use deterministic id helpers, exact string formats.
- **P2 verification exactly right** (2-of-4 + exact `log_verification` row + canonical time).
- **P2 COMMUNICATE verbatim** in TextParts (Task artifacts or final status.message; DataParts and non-final status are invisible).
- **P3 robustness with a stranger agent** (50/25/25; pairing `a` is 2×) and reliable infra (INFRASTRUCTURE_ERROR shrinks the comparison set).
