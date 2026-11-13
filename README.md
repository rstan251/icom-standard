# ICOM — proposed inter-agent communication format

Version: **v2** (CHP/2) · 2026-11-12 · codebook 1.7.0
Maintained by Robert Stanley / Iron Noodle Technologies.

ICOM (Inter-agent Comms) is a compact, unambiguous message format for multi-agent systems. All inter-agent traffic routes through an ICOM router agent, uses a fixed header plus `key=val` tokens, and cites a task/ticket id. It cuts tokens ~40% vs English prose while staying machine-parseable.

## Status

**Proposal.** This repository is an open draft, not a finished or adopted standard. Nothing here is ratified by a standards body. Feedback is invited: open an [issue](https://github.com/rstan251/icom-standard/issues) or a [pull request](https://github.com/rstan251/icom-standard/pulls) against `main`. See [CONTRIBUTING.md](CONTRIBUTING.md).

## What this is / is not

**This is**
- A public proposal for a one-line, codebook-backed agent-to-agent handoff format (CHP/2: the v1.1 expander, no-echo guard, P0.0 emergency, version/timestamp suffix, retransmit and lifetime rules, and a loadable agent card).
- A draft you can implement, measure, critique, and change.

**This is not**
- A finished, ratified, or widely adopted standard.
- A requirement that any product or agent runtime implement ICOM.
- A language for humans. Owner-facing and client-facing copy stays English.

## Message format
```
@FROM>ICOM>TO P0.0|P0-3 CLIENT #ticket VERB object key=val ... cb=<codebook ver> icom=<card ver> ts=<local time>
```
- `FROM` / `TO`: agent codes (`codebook.yaml` → `agents`); multiple recipients `>TO1,TO2`
- `P0.0|P0-3`: priority (P0.0 emergency, P0 now, P1 today, P2 this week, P3 whenever)
- `CLIENT`: client code, `INT0` if internal (never write the word LANE)
- `#ticket`: task/ticket id (required; no ticket → NAK)
- `VERB`: one of the 30 verbs in `codebook.yaml` (ACK is receive-only)
- `object`: an [ICX](https://github.com/rstan251/icx) concept code (Dewey-style, coarse to fine, e.g. `pr.voice.intake`); then `key=val` tokens (f= path, v=, rb=, n=, ask=, nx=, ...)

- suffix: `cb=` codebook version, `icom=` agent card version, `ts=` local timestamp (Rules 13, 20)

Example: `@LEAD>ICOM>CTO P1 INT0 #T-1234 GO ops.deploy f=T-1234 nx=CTO:review cb=1.7.0 icom=v2 ts=2026-11-12.09:00:00.AZ`

## Scope: English vs ICOM
- **English only** for messages to the owner (human), clients, and outside humans.
- **ICOM for everything else**, including each agent's own chat display text, status and summaries.
- Strict: header + key=val only, max 1 line per item; no prose, TL;DR sentences or quotes. ICOM NAKs non-compliant messages.

## Related

- **[ICX](https://github.com/rstan251/icx)** — object taxonomy / codebook. ICOM defines how agents talk; ICX defines what they talk about. The header `object` slot is an ICX concept code.

Upcoming docs (in progress): BitChat payload spec; Buzz event schema.

## Adopting it in another agent
Generate the agent card from your codebook (template: `ICOM-AGENT-CARD.md`) and put it at the top of the agent's profile/system prompt. Then use agent and client codes from `codebook.yaml` and address all agent messages to ICOM. The older paste-in header `adopt/HDR.txt` still works for v1-style agents.
(Note: the paste-in header previously lived at `patch12/HDR.txt`; it now lives at `adopt/HDR.txt`.)

If the agent runs on a host that reviews tool calls before running them (ChatGPT, for example), also follow [`adopt/ACTION-REVIEW-HOSTS.md`](adopt/ACTION-REVIEW-HOSTS.md); otherwise its own ICOM sends may be blocked.

## Files
- `PROTOCOL-v1.md` — full spec, v2 (Rules 11-24; 14 = ICX object codes, 17 = REC label, 18 = P0 status, 19 = P0.0, 20 = retransmit/order/version, 24 = no-echo, formerly 18)
- `ICOM-AGENT-CARD.md` — public agent card template (what agents load)
- `codebook.yaml` — verbs, priorities, agents, lanes, objects, fields
- `examples.txt` — same handoff in English, house style, ICOM, JSON, etc.
- `AGENT-INSTRUCTIONS.md` — prompt template for an ICOM router agent
- `adopt/HDR.txt` — paste-in header for agent profiles
- `adopt/ACTION-REVIEW-HOSTS.md` — adopting ICOM on hosts with tool-call review (ChatGPT and similar)
- `CONTRIBUTING.md`, `LICENSE` (MIT)
- `v1.1/` — expander (engine 1.3.0) plus the v1.2 no-echo reference (rule 18, now Rule 24; does not implement the v2 additions: the 24.2 time-based DONE-repeat window and 24.5) and tests

Client/lane codes in this repo are generic placeholders.
