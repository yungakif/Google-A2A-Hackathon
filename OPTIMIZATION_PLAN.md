# A2A Banking Hackathon — Optimization Plan (~4–5 hr window)

Built from a 4-lens design panel + adversarial synthesis, grounded in our baseline
failure dissection. Verified against source: the P0 *infrastructure* (contextId
propagation, gateway routing, TextPart extraction) is **already correctly wired**
(`cs_client_tool.py:54`, `env_toolset.py:75`) — do NOT rebuild it. The ~0.30 baseline
is a **write-precision + handshake-discipline** problem, fixable almost entirely in
`kb/policy.md` (loaded verbatim into the CS prompt via `cs_agent/agent.py:32`) and
`personal_agent/agent.py`.

## The single biggest bet
Convert the CS agent from free-acting to **"plan-then-execute-exactly"** via `kb/policy.md`:
kill stray/duplicate writes and make `log_verification` byte-exact. The reward is a
whole-DB exact hash that multiplies to 0 on any extra/missing/mis-formatted write, and
~84% of tasks need verification — so this prompt-only edit moves the most tasks 0→1 per
hour. It helps BOTH scoring halves: intrinsic correctness travels to interop as long as
all coordination stays in plain A2A text (no co-tuning).

## Roadmap (ROI-ordered)

**DO FIRST (15 min): baseline a fixed 7-task subset** for signal —
`task_006,task_053,task_028,task_001,task_005,task_023,task_011` at `--concurrency 2`.
Run `smoke` once; if zero-tool-call / zero-leg-2 warnings fire, contextId/gateway is broken (it shouldn't be).

**P0 — multiplicative-gate fixes (first ~2 hr, all in `kb/policy.md`):**
- **P0-1 Verification SOP:** collect 2-of-4 {DOB,email,phone,address} → `get_current_time()` → pass its exact `'2025-11-14 03:40:00 EST'` as `time_verified` → true user-record values, DOB `MM/DD/YYYY` → call `log_verification` exactly once. Inline a worked example.
- **P0-2 Anti-over-act contract:** "Do the request and NOTHING more. `get_*` reads are free/repeatable; every write/unlock/give/call must be justified. Never call a mutating tool twice with same args. No exploratory writes. When done, ONE final summary, then STOP." List read-only tools explicitly.
- **P0-3 Plan-confirm-execute:** before any write, emit a PLAN of write tool+args once; execute exactly that list; the set of distinct discoverable names called must equal gold's (a stray name = instant 0).
- **P0-4 Copy-values-verbatim:** every write arg must be a value seen (KB doc / read result / user words) — never invent/round/default `card_design`,`*_fee`,`*_date`,points. Transaction/discovery dates come from the record, NOT `get_current_time`. Format appendix: `1500` not `1500.00`; rewards `'N points'`; balances `'$X.XX'`; DOB `MM/DD/YYYY`.

**P1 — handshake + ordering (next ~1–1.5 hr):**
- **P1-1 give→call handshake:** CS calls `give_discoverable_user_tool(name)` once, then states in TEXT the exact tool name + the FULL enumerated list of every arg set. Personal calls `call_discoverable_user_tool` exactly N times with CS's verbatim name+args; echo the list to self-check count. Enumerate the whole set in ONE message.
- **P1-2 unlock-before-call:** `unlock_discoverable_agent_tool` first (read schema), then `call_discoverable_agent_tool`. Unlock once. The GET tools list NEVER grows — drive from KB, don't re-poll. (A stray unlock writes no DB row; only a stray CALL is fatal.)
- **P1-3 ban premature human-transfer:** if the KB has a procedure (even 20 steps), execute it fully; re-search before giving up; only transfer when the KB says to.
- **P1-4 clean termination + bounded loops:** one final message, no trailing calls/questions (open loops → timeout → 0). Cap one `ask_customer_service` round-trip (300s turn). One clarification on a bad stranger reply, then proceed.

**P2 — interop hardening (last hr, only if P0/P1 green):**
- **P2-1** personal = low-opinion stranger-proof relay; ask user for exactly what CS requests; call user tools with CS's verbatim name+args.
- **P2-2** every outbound message self-contained (restate full request + concrete values/ids); all reward-bearing info in literal TextParts (DataParts/non-final status are invisible).

## SKIP (near-zero / negative EV this window)
- RAG reranker / RRF / embedding tuning — retrieval is SECONDARY (task_005 found 8/8 unlocks). Touch only if a specific task fails because `kb_search` returned the wrong tool name.
- COMMUNICATE / NL tuning — ~0 COMMUNICATE tasks, 1 NL task.
- The 3rd research-agent hop as a hard dependency — wire contract TBD. If you add `ask_research`, it MUST fall back to CS's own KB on unset/error/timeout. A research leg that adds latency but not correctness is pure downside under the multiplicative + termination gate.
- Redis shared memory as a cross-agent dependency — trio accelerator at best, interop poison at worst.

## Interop safeguards (protect the 50%)
1. contextId is sacred + already wired — never fresh/null per turn; verify via `smoke`.
2. Route the next hop via the `/cs-agent` gateway (recorded into the scored session); streaming OFF; never a raw bypass URL.
3. All coordination in A2A TextParts — tool names + full arg enumeration in plain language.
4. No co-tuning — no private schema/delimiter/field-order a stranger won't emit. Only hard contracts: contextId + the tool NAME string.
5. Each agent intrinsically correct standalone — CS owns all writes+verification; personal assumes nothing about CS phrasing.
6. Redis only as a contextId-keyed, fully-fallbacked cache (`if miss: compute_from_scratch()` yielding identical calls). Never depend on a key a partner wrote.
7. Bounded sub-loops; parse stranger replies leniently; never hang.

## Traps that LOSE points
- Calling any discoverable tool name not in gold → stray row → 0.
- Guessing/defaulting write args; using `get_current_time` for transaction/discovery dates; format drift.
- `log_verification` with user-typed (not true-record) values, wrong/extra fields, wrong time, or re-verifying.
- Skipping the handshake or dropping a tuple from a multi-item set.
- Open loops / trailing calls / infinite re-ask → MAX_STEPS/TIMEOUT → 0.
- High concurrency on the single key → 429 → TIMEOUT → 0 (and poisons your signal). Keep `--concurrency 2`.
- Bypassing the gateway; fresh/null contextId; answers in DataParts/non-final status (invisible to grader + strangers).

## Measurement loop
Re-run the SAME 7-task ladder after every edit; require monotonic improvement (a task flipping to 0 = new stray write / broken handshake → bisect via `tau2 view`). Green signals: agent-side tool-call count == gold `n_actions`; no discoverable names outside gold; `verification_history` row exact + once; give precedes call with correct count; 0% TIMEOUT/MAX_STEPS. Interop bracket: swap in degraded/stranger partners and watch the DB-match gap shrink; toggling Redis OFF must not change any outcome. Bracket vs `golden_retrieval` (ceiling) / `no_knowledge` (floor). Only run the full set when the subset is all-green; confirm no simple task (e.g. `apply_for_credit_card`) regressed.

**Edit:** `kb/policy.md` (P0 + P1 CS-side) and `personal_agent/agent.py` (P1-1/P1-4 personal, P2). Infra files are correct — read-to-verify only.
