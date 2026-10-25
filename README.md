# ICOM — open bot-to-bot communication standard

Version: **v1** · 2026-10-18
Maintained by Robert Stanley / Iron Noodle Technologies.

ICOM (Inter-agent Comms) is a compact, unambiguous message standard for multi-agent systems. All inter-agent traffic routes through an ICOM router agent, uses a fixed header plus `key=val` tokens, and cites a task/ticket id. It cuts tokens ~40% vs English prose while staying machine-parseable.

## Message format
```
@FROM>ICOM>TO P0-3 LANE #ticket VERB object key=val ...
```
- `FROM` / `TO`: agent codes (`codebook.yaml` → `agents`); multiple recipients `>TO1,TO2`
- `P0-3`: priority (P0 now, P1 today, P2 this week, P3 whenever)
- `LANE`: client/lane code, `INT0` if internal
- `#ticket`: task/ticket id (required; no ticket → NAK)
- `VERB`: GO HOLD DONE BLOCKED REC FYI ASK ACK NAK
- `object`: an [ICX](https://github.com/rstan251/icx) concept code (Dewey-style, coarse to fine, e.g. `pr.voice.intake`); then `key=val` tokens (f= path, v=, rb=, n=, ask=, nx=, ...)

Example: `@LEAD>ICOM>CTO P1 INT0 #T-1234 GO ops.deploy f=~/work/x.md nx=CTO:review`

## Scope: English vs ICOM
- **English only** for messages to the owner (human), clients, and outside humans.
- **ICOM for everything else**, including each agent's own chat display text, status and summaries.
- Strict: header + key=val only, max 1 line per item; no prose, TL;DR sentences or quotes. ICOM NAKs non-compliant messages.

## Companion standard: ICX
ICOM defines how agents talk; [ICX](https://github.com/rstan251/icx) defines what they talk about. ICX is the concept index for the `object` slot: one address per concept, routed and searched by prefix. Use them together.

## Adopting it in another agent
Prepend `adopt/HDR.txt` to the top of the agent's profile/system prompt. Then use agent/lane codes from `codebook.yaml` and address all agent messages to ICOM.
(Note: the paste-in header previously lived at `patch12/HDR.txt`; it now lives at `adopt/HDR.txt`.)

## Files
- `PROTOCOL-v1.md` — full spec (rules 1–14, 17; rule 14 = ICX object codes, rule 17 = REC-LABEL)
- `codebook.yaml` — verbs, priorities, agents, lanes, objects, fields
- `examples.txt` — same handoff in English, house style, ICOM, JSON, etc.
- `AGENT-INSTRUCTIONS.md` — prompt template for an ICOM router agent
- `adopt/HDR.txt` — paste-in header for agent profiles
- `CONTRIBUTING.md`, `LICENSE` (MIT)
- `v1.1/` — ICOM v1.1 spec and reference expander

Client/lane codes in this repo are generic placeholders.
