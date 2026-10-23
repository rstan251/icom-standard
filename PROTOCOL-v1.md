# ICOM Compact Handoff Protocol — v1 ("CHP/1")

Status: draft, 2026-10-18. Extends the house rule `TL;DR + D/R/F/O/Q/A`. Goal: unambiguous internal handoffs at fewer tokens than English. Not binary: measured base64 costs 42–49% MORE tokens than English (see Measurements).

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
pri     = "P0.0" / "P0" / "P1" / "P2" / "P3"
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
2. No ack-only messages unless the sender asked for ACK or P0.0 requires one.
3. Hand back a file path, not a summary chain.
4. Run long analysis, drafting, log review and audits on the cheapest capable model or worker; keep router/dispatcher agents thin.
5. Cap the number of concurrent helper agents.
6. Shared memory = files: keep standing rules and decisions in a shared knowledge base and tasks in a ticket tracker; read the ticket before acting, write results back.
7. Every active task needs a ticket before work starts; GOs, decisions, results and file paths are logged as ticket comments. No ticket, no work.

## Rule 11 — ICOM routing
All inter-agent messages route through ICOM, the LEAD agent included. No direct agent-to-agent sends.
Format: `@FROM>ICOM>TO[,TO] PRI CLIENT #ticket VERB [ACTION] object key=val ...`
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
- P0.0, P0 and P1 are logged immediately. Non-emergency FYI and P2-3 items are batched into one comment per ticket per hour.

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

## Changelog
- 2026-10-19: rule 17 REC-LABEL added.

## P0.0 emergency priority — proposed additive revision (iro-553e3532)

This section takes precedence over older priority, batching and ACK exclusions.
Canonical spelling is exactly `P0.0` (uppercase P, ASCII zero, dot, zero).
`P00`, `P0.00`, `P0.1`, `p0.0`, signed/exponent forms and Unicode lookalikes
are unsupported: reject visibly with `bad-priority`; never normalize, downgrade
or silently discard them. Existing P0, P1, P2 and P3 keep their meanings.

Urgency order, highest first: **P0.0 > P0 > P1 > P2 > P3**. These are string
enumeration labels, not decimal numbers. Use integer ranks 0, 1, 2, 3, 4;
never float conversion. Preserve the original label in routing, ACKs and logs.
ICX defines the object vocabulary only; ICOM defines this priority vocabulary.

P0.0 means the highest emergency urgency. Act immediately within existing
authority. The user may defer OPTIONAL review or finance workflow where the
user has authority; record the instruction, scope, owner, deferred step and
follow-up evidence on the cited ticket. This priority creates no credentials,
expands no access, exposes no secrets, authorizes no unrelated charges or client
sends, and bypasses no mandatory platform safety. It is not a universal
no-restrictions authorization switch or a new approval queue.

Route via ICOM to the named recipients with the same ticket and unchanged
header. P0.0 traffic, including FYI and ACK, must be routed and logged
immediately, never hourly-batched or filtered by the older no-ACK/FYI rule.
The responsible recipient must send ACK (receipt plus owner/next action) or
BLOCKED/NAK with a reason within 30 seconds of receipt. Correlate using the
same ticket and request id where available. ACK does not mean completion or
authorization; do not ACK an ACK. Record DONE or BLOCKED and evidence afterward.
On missing ACK after 30 seconds, surface the timeout to the sender and current
incident owner immediately; retain the emergency label and use only existing
authorized internal escalation routes. Do not wait for the generic one-hour
stall timer or infer permission for external sends.

Deploy compatibility before enabling senders. Old parsers reject P0.0; do not
rewrite it to P0 for them. Unsupported recipients/routes must produce a visible
NAK/status, preserve ticket/id/hash evidence and leave work explicitly blocked.

Reference implementation boundary: the relay validates and forwards unchanged;
it does not schedule or preempt work, enforce recipient response timers, publish
ticket comments, or deliver a sender NAK automatically. `priority_rank` supplies
the exact order for consuming schedulers. Existing bridge/spool transport order
is preserved. Operators must surface returned REJECT/FAIL and dead-letter
records, and the ICOM/recipient integration must provide the ACK/timeout contract
before claiming end-to-end P0.0 support. A SENT transport result is not an ACK.

P0.0 emergency examples (proposed, iro-553e3532):

```text
@CTO>ICOM>INFRA P0.0 INT0 #iro-553e3532 GO org.proto id=p00-1
@INFRA>ICOM>CTO P0.0 INT0 #iro-553e3532 ACK org.proto id=p00-1 own=INFRA nx=INFRA:validate
@INFRA>ICOM>CTO P0.0 INT0 #iro-553e3532 BLOCKED org.proto id=p00-1 why=unsupported-route
```

These are parser/contract examples, not grants to deploy. Do not send them live.
