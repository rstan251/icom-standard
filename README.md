# ICOM — proposed inter-agent communication format

Version: **v1.3** · 2026-11-04
Maintained by Robert Stanley / Iron Noodle Technologies.

ICOM (Inter-agent Comms) is a compact, unambiguous message format for multi-agent systems. All inter-agent traffic routes through an ICOM router agent, uses a fixed header plus `key=val` tokens, and cites a task/ticket id. It cuts tokens ~40% vs English prose while staying machine-parseable.

## Status

**Proposal.** This repository is an open draft, not a finished or adopted standard. Nothing here is ratified by a standards body. Feedback is invited: open an [issue](https://github.com/rstan251/icom-standard/issues) or a [pull request](https://github.com/rstan251/icom-standard/pulls) against `main`. See [CONTRIBUTING.md](CONTRIBUTING.md).

## What this is / is not

**This is**
- A public proposal for a one-line, codebook-backed agent-to-agent handoff format (CHP/1, the v1.1 expander, v1.2 no-echo, and v1.3 `CO.CLIENT`).
- A draft you can implement, measure, critique, and change.

**This is not**
- A finished, ratified, or widely adopted standard.
- A requirement that any product or agent runtime implement ICOM.
- A language for humans. Owner-facing and client-facing copy stays English.

## Message format
```
@FROM>ICOM>TO P0-3 CO.CLIENT #ticket VERB object key=val ...
```
- `FROM` / `TO`: agent codes (`codebook.yaml` → `agents`); multiple recipients `>TO1,TO2`
- `P0-3`: priority (P0 now, P1 today, P2 this week, P3 whenever)
- `CO.CLIENT`: company shorthand + client shorthand (`CM.ABC`); `IN.INT0` if no client. Bare legacy lane codes (`WST`, `INT0`, `LAP`, …) stay valid during the transition.
- `#ticket`: task/ticket id (required; no ticket → NAK)
- `VERB`: GO HOLD DONE BLOCKED REC FYI ASK ACK NAK
- `object`: an [ICX](https://github.com/rstan251/icx) concept code (Dewey-style, coarse to fine, e.g. `pr.voice.intake`); then `key=val` tokens (f= path, v=, rb=, n=, ask=, nx=, ...)

Example: `@ENG>ICOM>OPS P1 CM.ABC #T-n ASK pr.voice.intake~cfg`

No client: `@ENG>ICOM>OPS P1 IN.INT0 #T-n GO org.proto`

Outbound (leaves the fleet; plain-word tokens required):
```
@ENG>ICOM>EXT P1 CM.ABC #T-n ASK pr.voice.intake~cfg co=cogent-marketing cl=abc topic=voice-intake-config icx=1.2.0
```

## Scope: English vs ICOM
- **English only** for messages to the owner (human), clients, and outside humans.
- **ICOM for everything else**, including each agent's own chat display text, status and summaries.
- Strict: header + key=val only, max 1 line per item; no prose, TL;DR sentences or quotes. ICOM NAKs non-compliant messages.

## Related

- **[ICX](https://github.com/rstan251/icx)** — object taxonomy / codebook (1.2.0). ICOM defines how agents talk; ICX defines what they talk about. The header `object` slot is an ICX concept code. Rule 14a sets the `CO.CLIENT` form of the CLIENT/LANE slot.

Upcoming docs (in progress): BitChat payload spec; Buzz event schema.

## Adopting it in another agent
Prepend `adopt/HDR.txt` to the top of the agent's profile/system prompt. Then use agent codes and `CO.CLIENT` (or a legacy lane during the transition) from `codebook.yaml` and address all agent messages to ICOM.
(Note: the paste-in header previously lived at `patch12/HDR.txt`; it now lives at `adopt/HDR.txt`.)

## Files
- `PROTOCOL-v1.md` — full spec (rules 1–14, 14a, 17–18; rule 14 = ICX object codes, rule 14a = company/client designation, rule 17 = REC-LABEL, rule 18 = NO-ECHO)
- `codebook.yaml` — verbs, priorities, agents, companies, legacy clients, objects, fields
- `clients.example.yaml` — placeholder private customer registry (`id: 0000`, `short: ABC`)
- `examples.txt` — same handoff in English, house style, ICOM, JSON, etc.
- `AGENT-INSTRUCTIONS.md` — prompt template for an ICOM router agent
- `adopt/HDR.txt` — paste-in header for agent profiles
- `CONTRIBUTING.md`, `LICENSE` (MIT)
- `v1.1/` — expander (engine 1.3.0) plus rule-18 no-echo reference and tests

Company codes and client/lane codes in this repo are generic placeholders (`ABC`, `0000`, `XXXX`). Numeric customer ids are private.
