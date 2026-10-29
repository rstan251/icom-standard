# ICOM Compact Handoff Protocol — v1.2 ("CHP/1")

Status: draft, 2026-10-29. Extends the house rule `TL;DR + D/R/F/O/Q/A`. Goal: unambiguous internal handoffs at fewer tokens than English. Not binary: measured base64 costs 42–49% MORE tokens than English (see Measurements). v1.2 adds rule 18 (NO-ECHO). The on-the-wire header is unchanged from v1.

## 1. Hard rules
1. **Client-facing mail, SMS, voice scripts and anything a human outside the system reads stay plain English.** CHP is internal-bus only. The owner (human) gets English unless they ask for CHP.
2. One message = one header line + optional body lines. Unknown code → reply `NAK` with the code; never guess.
3. Reference, don't restate: point to `f=` paths, ticket `#T-n`, commit/deploy ids.
4. Never put secrets, tokens, or keys in a message; reference the secret by name only.
5. Free text is allowed only in a quoted `"…"` value or a `txt:` body line, kept ≤ 1 sentence.

## 2. Grammar (ABNF-ish)
```
msg     = header *(LF body)
header  = "@" from ">" to [ "," to ]* SP pri SP client [SP ticket] SP verb [SP action] SP object *(SP kv)
from/to = AGENT-code            ; codebook.agents
pri     = "P0" / "P1" / "P2" / "P3"
client  = CLIENT-code           ; codebook.clients, INT0 if none
ticket  = "#" 1*VCHAR           ; e.g. #T-1234
verb    = GO / HOLD / DONE / BLOCKED / REC / FYI / ASK / ACK / NAK
action  = verb                  ; only after REC (REC HOLD, REC GO)
object  = lower.dot code or new noun
kv      = key "=" value         ; value: token, list "a,b", alternatives "a|b", or "quoted text"
body    = ("D:"/"R:"/"F:"/"O:"/"Q:"/"A:"/"txt:") SP text   ; legacy house lines, allowed
```
Example: `@INFRA>CTO P1 CL01 #T-1234 BLOCKED srv.migrate why=dns.a:unprop,ssl:le-ratelimit ask=APPROVE le-staging|WAIT24h f=~/work/infra/client01-migration.md cc=LEAD`

Mapping to house style: DONE≈D, REC≈R, f=≈F, #ticket/own=≈O, ASK/ask=≈Q, nx=/ret=≈A.

## 3. Codebook (see codebook.yaml)
YAML with sections `verbs, priority, agents, clients, objects, fields, paths`. Rules: codes ≤6 chars; agents/clients/verbs UPPER, objects lower.dot; append-only with semver bump; retired codes are tombstoned, never reused; the ICOM router agent is the sole editor and proposes additions weekly (codes seen ≥5×/week as free text).
Current registries: see codebook.yaml for agents, 26 clients (generic placeholders in public spec), 9 verbs, 15 field keys.

## 4. Replies
`@CTO>INFRA P1 CL01 #T-1234 ACK` / `... GO le-staging` / `NAK code=XYZ`. Threads keep the ticket.

## 5. Measurements (tiktoken, 5 realistic handoffs, totals)
| format | cl100k tokens | saved vs English | o200k tokens | saved vs English | vs house (o200k) |
|---|---|---|---|---|---|
| English prose | 429 | — | 424 | — | −40% |
| House TL;DR+codes | 305 | 28.9% | 303 | 28.5% | — |
| **CHP v1** | **248** | **42.2%** | **250** | **41.0%** | **+17.5% saved** |
| JSON compact | 369 | 14.0% | 377 | 11.1% | −24% (worse) |
| TOON | 376 | 12.4% | 377 | 11.1% | −24% (worse) |
| JSON pretty | 558 | −30.1% | 559 | −31.8% | −85% |
| base64 of v1 | 641 | −49.4% | 604 | −42.5% | −99% |

Notes: full paths are ~25–35% of a v1 message; a short path alias (e.g. `%w=~/work`) cuts another ~3–5 tokens each. One example (#2) was 3 tokens longer than house style (dense English already) — v1 wins on structure, not every line. Measured with tiktoken encodings cl100k_base and o200k_base.

## 6. Optional cost guidance
1. One model turn per handoff where possible.
2. No ack-only messages unless the sender asked for ACK.
3. Hand back a file path, not a summary chain.
4. Run long analysis, drafting, log review and audits on the cheapest capable model or worker; keep router/dispatcher agents thin.
5. Cap the number of concurrent helper agents.
6. Shared memory = files: keep standing rules and decisions in a shared knowledge base and tasks in a ticket tracker; read the ticket before acting, write results back.
7. Every active task needs a ticket before work starts; GOs, decisions, results and file paths are logged as ticket comments. No ticket, no work.

## Rule 11 — ICOM routing
All inter-agent messages route through ICOM, the LEAD agent included. No direct agent-to-agent sends.
Format: `@FROM>ICOM>TO[,TO] P0-3 CLIENT #ticket VERB [ACTION] object key=val ...`
- Address agent-to-agent sends to ICOM only. `>TO` after ICOM names the final recipient(s).
- ICOM relays the line unchanged to TO, logs it (e.g. `~/work/icom/relay/YYYY-MM-DD.log`), and encodes plain English into CHP if needed.
- Replies come back the same way: `@TO>ICOM>FROM ...`.
- priority=true only if TO must act now; else false (ICOM keeps the sender's priority).
- Example: `@LEAD>ICOM>CTO P1 INT0 #T-1234 GO deploy f=~/work/x.md nx=CTO:review`

### Enforcement
The rule-11 header is required system-wide. ICOM sends LEAD a daily digest of untagged or direct messages, flagging senders by count. Hard enforcement can use per-agent inboxes that only ICOM may write to.

### Ticket logging
- Every relayed message is logged as a comment on its cited ticket, in this format:
  `ICOM: <exact shorthand line>` / `Plain English: <one sentence, no codes>`
- No ticket cited: ICOM NAKs the message back to the sender (`@ICOM>FROM P2 INT0 NAK why=no-ticket`) and does not relay it.
- Comments never include keys, passwords, card data or full account ids. Secrets are referred to by name only.
- P0 and P1 are logged immediately. FYI and P2-3 items are batched into one comment per ticket per hour.

### ICOM stall fallback
If ICOM hasn't relayed a message within 1h, the sender sends it direct with the full rule-11 header and cc's LEAD. ICOM backfills the ticket log afterward. The daily digest does not flag these sends as bypasses.
Stall-fallback direct messages are allowed for internal traffic only. Client sends always wait for LEAD + GATE approval.

## Rule 12: shorthand only
- All agent chat + handoffs = CHP shorthand only. No English prose: no sentence TL;DRs, no expanded lists.
- LEAD alone translates for the owner (human).
- Client-facing mail/SMS/voice unchanged (plain English, house voice; COMMS lane).
- Ticket comments keep the "Plain English:" line (ICOM logging rule).
- ICOM NAKs prose handoffs: `@ICOM>X P2 INT0 #T-1234 NAK why=prose ask=resend-CHP`.

## Rule 12 strict
- Header + key=val tokens only. Max 1 line per item.
- Banned: "TL;DR:" sentences, prose, articles, numbered explanations, quotes (except exact client-copy refs; use f=).
- ICOM NAKs + returns non-compliant msgs, does not relay; daily FAIL count in audit.

## Rule 12a scope
- English ONLY for: msgs addressed to the owner (human), clients, external humans.
- ICOM format for everything else, incl. each agent's own chat display text, status, summaries.
- English otherwise only when the owner explicitly asks.
- Agents' own chat display = ICOM always, even when the owner reads it. English to the owner goes through LEAD, or only when the owner explicitly asks in that chat. Direct per-agent owner orders stand.

## Rule 14: ICX object codes
- The header `object` slot uses ICX (Iron Concept indeX), a Dewey-style concept code: class.division.section, coarse to fine, e.g. `pr.voice.intake~cfg`.
- Every prefix is a valid code, so routing and search work by prefix. The lane/client stays in the `LANE` slot, never inside the object.
- Exact values (IDs, amounts, dates, paths) stay in `key=val` tokens, never in the object.
- Unknown concept: send `x.<word>`; the ICOM router places it on the next codebook review. Unregistered codes are NAKed with `why=icx.unk`.
- Spec, example codebook, relative index and validator: https://github.com/rstan251/icx

## Rule 17: REC-LABEL (2026-10-19)
- Every agent-originated recommended action surfaced to the owner (human) is prefixed `AGENTCODE: action` (AGENTCODE = originating agent, codebook.yaml `agents`).
- Examples: `LEGAL: send notice`; `CFO: create pricing`.
- LEAD keeps the label unchanged when translating to English for the owner (rules 12, 12a).
- No unlabeled recommendations to the owner.

## Rule 18: NO-ECHO (2026-10-29)

Designed against a class of failure: agents answered each other's terminal and informational messages (DONE, and also ACK/FYI/REC-style informational messages) with more terminal messages on the same work item. A relay that only deduplicated identical message IDs forwarded every reply because each reply had a fresh ID. Over several days, thousands of DONE messages accumulated on one item whose real work was never completed. The loop restarted after daily usage-cap pauses: agents that stopped reading re-read their unread backlog when the cap reset, and every backlog DONE triggered new replies. Inflated DONE counts were mistaken for progress.

**Quiet verbs** (terminal or informational; no reply expected): DONE, FYI, ACK, REC, and codebook equivalents.
**Action verbs** (may follow a quiet verb): GO, ASK, BLOCKED, NAK, HOLD, and any later verb that is a real state change (not an acknowledgement). Silence is a valid response to a quiet verb.

### 18.1 Sender
- A quiet verb is never answered with another quiet verb on the same ticket.
- Only an action verb may follow a quiet verb on that ticket.
- Send DONE once per ticket per state change. A second DONE on the same ticket is allowed only when the system-of-record state actually changed. A second DONE for the same state is a protocol error; do not send it.
- ACK is sent only when the prior sender asked for ACK (§6.2). ACK is quiet: never ACK an ACK, DONE, FYI, or REC.

### 18.2 Relay
- Suppress a repeat quiet verb from the same sender on the same ticket within a window (reference default: 6h).
- Key: `(from, ticket, verb)`. Not message ID. Message-ID dedup alone does not satisfy this rule.
- Disposition of a suppressed line: log it as suppressed (never a silent drop). Deliver it to OWNER and LEAD. Do not fan it out to other agents.
- Action verbs are never suppressed by this rule. The first quiet verb in a window is relayed normally.
- Do not emit a NAK solely because a line was suppressed (NAK is new traffic).

### 18.3 Backlog / replay
- After a pause, cap, or reconnect: before acting, collapse repeated quiet verbs per ticket (keep the newest quiet line per ticket; keep action lines).
- Never reply to a quiet verb that is stale (already acted on, older than the newest line on that ticket, or dated before the pause).

### 18.4 Metrics
- Progress and DONE counts use distinct `(ticket, from, state)` completions, not raw DONE lines. `state` is the work-item status in the system of record (or the object plus outcome if no SoR status is cited).
- The ticket's status in the system of record wins over any message count.
- Loop flag: more than 12 quiet verbs on one ticket within 24h → `@ICOM>LEAD … FYI echo.loop why=echo n=<count>` for human triage. Do not treat the count as progress. Relays MAY lower 12.

### Example — non-conformant loop (must not happen)
```
@INT>ICOM>QC P2 CL13 #T-1001 DONE contacts.import qa=pass
@QC>ICOM>INT P2 CL13 #T-1001 ACK contacts.import
@INT>ICOM>QC P2 CL13 #T-1001 ACK contacts.import
@QC>ICOM>INT P2 CL13 #T-1001 DONE contacts.import
@INT>ICOM>QC P2 CL13 #T-1001 DONE contacts.import
```
18.1: QC does not ACK the DONE; INT does not ACK an ACK; neither sends DONE in reply to a quiet verb. If those lines are sent anyway, 18.2: INT's second DONE on #T-1001 within 6h is not fanned out (LEAD and OWNER still receive it; relay log: suppressed, why=echo, key=INT:#T-1001:DONE). Peers do not.

### Example — conformant follow-up
```
@INT>ICOM>QC P2 CL13 #T-1001 DONE contacts.import qa=pass
@QC>ICOM>INT P2 CL13 #T-1001 ASK contacts.import ask=sample|none
```
Quiet then action. No second DONE unless the SoR state changes.

## Changelog
- 2026-10-29: v1.2 rule 18 NO-ECHO (quiet-verb reply ban, relay suppress window, backlog collapse, unique DONE metrics).
- 2026-10-19: rule 17 REC-LABEL added.
