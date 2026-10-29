# ICOM v1.2 shorthand: specification

By Robert Stanley / Iron Noodle Technologies. MIT License.

Engine 1.2.0. Line grammar is the v1.1 expander; v1.2 adds rule 18 (NO-ECHO). See PROTOCOL-v1.md.

## Canonical v1 line (output)
`@FROM>ICOM>TO[,TO] Pn LANE #iro-xxxxxxxx VERB [ACTION] object key=val ...`
- One line per message. No prose: everything after the object is `key=val`.
- P0 is reserved for a customer-facing outage: it needs a non-internal lane and `why=down|outage|sec|money`.
- Emails are written as `initial@domain` with no TLD.

## v1.1 input additions
1. **Phrase shortcuts.** `$NAME` in the verb slot expands from the codebook `shortcuts.NAME.expand`. An optional `shortcuts.NAME.pri` supplies the priority if the sender gave none. Sender `key=val` pairs override template keys. A shortcut line must carry `cb=<codebook version>`.
2. **Implied header.**
   - The `>ICOM` hop may be omitted.
   - Priority defaults to the thread value, else P2. Lane defaults to the thread value, else INT0.
   - The ticket may be omitted once the thread (the sorted party set) is bound. A bare `#` followed by 8 hex characters is normalized to `#iro-`.
   - FROM, TO, verb and object are never implied.
   - The short forms `last4#seq` and `^tag` pass through unchanged.
3. **Version token.** `cb=<version>` is optional on v1 lines and required on shortcut lines. A mismatch with the loaded codebook produces a NAK.
4. **Path alias.** `f=` values starting with an alias from the codebook `paths:` map are expanded. Aliases save no tokens, so writing full paths is preferred.
5. **Close.** A thread closes on DONE ops.docket carrying the full #iro- ticket (or 24h idle). A plain DONE does not close. Short forms (last4#seq, ^tag) cannot close.

## autoNAK
`@ICOM>ICOM>FROM P2 INT0 <ticket|#icom-nak> NAK org.proto why=<code> [det=<token>] cb=<version>`

Codes: empty, multiline, no-header, bad-route, bad-agent, bad-pri, bad-lane, bad-ticket, bad-verb, bad-icx, prose, email, unk-shortcut, cb-required, cb-mismatch, p0-misuse.

Relays may add codes for relay-level checks (bad-grammar, bad-from, k1-pci, unbound_tag, unbound_short, tag_in_ref, bad_tag, tag_clash, reject), spelled lowercase with hyphens. Thread-tag codes keep their underscores for compatibility.

`echo` is a relay **disposition** (rule 18), not an autoNAK: a suppressed quiet verb is logged `why=echo` and is not bounced to the sender.

## Codebook (external; keys read)
- `version`
- `verbs`
- `lanes` and/or `clients`
- `agents`
- `icx.codes`
- `paths`
- `shortcuts`
- `echo` (optional; rule 18 tunables)

Each list may be given as a list, as dict keys, or as a list of `{code: ...}`.

The object should be in icx.codes; unknown objects are delivered (no NAK) in v1.1.

`echo` tunables: `window_s` (default 21600), `loop_n` (default 50), `loop_s` (default 86400).

## no-echo (v1.2 / rule 18)

Quiet verbs: DONE, FYI, ACK, REC. Action verbs: GO, HOLD, ASK, DECIDE, BLOCKED, NAK, and any later state-change verb. A codebook that adds a verb MUST classify it as quiet or action. DECIDE is in the codebook and is a reset.

1. **Sender.** Do not answer a quiet verb with a quiet verb on the same ticket. Only an action verb (or silence) may follow. DONE once per ticket per SoR state change. ACK only when asked; never ACK a quiet verb.
2. **Relay.** Suppress a repeat quiet verb from the same `from` on the same full ticket inside `echo.window_s` (reference 6h). Key `(from, ticket, verb, bodyhash)`: `bodyhash` is sha256[:16] of normalized `verb` + REC action + object + sorted tokens. Ticket must resolve to a full `iro-xxxxxxxx` (`#iro-xxxxxxxx`). last4 (`abcd#1`) binds only when exactly one seen full id shares that last4; unresolved, ambiguous, or a non-iro ticket (`#OPS-12`) is never suppressed. An FYI with new tokens, a REC with a different action, or a changed body is a new key. Log `disposition=suppressed why=echo`. Deliver a suppressed line to LEAD or OWNER only when they are already addressed; do not add them. Action verbs and FLAG pass. A suppress does not slide the window. A reset verb on the ticket (GO, ASK, DECIDE, BLOCKED, NAK, and HOLD if in the codebook) clears the window; FLAG does not. So a DONE after a new GO or DECIDE is relayed. If echo checking errors, deliver and log (fail-open); park corrupt state files, never delete them; state-dir `OSError` (parent is a file, read-only, unwritable) fails open and runs without persistence. Do not NAK a suppress. Message-id dedup is not enough.
3. **Backlog.** After a pause, cap, or reconnect: per resolved `#iro-xxxxxxxx` only, keep the first quiet line, drop later quiets, note the dropped count as `collapsed_n`. last4 binds to exactly one seen full id; unresolved, ambiguous, or non-iro tickets are never collapsed. A reset verb starts a new group. Keep action verbs. Do not reply to a quiet verb older than the resume instant or older than the newest line on that ticket.
4. **Metrics.** DONE/progress = distinct `(ticket, from, state)` completions. Ticket SoR status wins over message counts. More than `echo.loop_n` quiet verbs on one resolved `#iro-xxxxxxxx` inside `echo.loop_s` (reference 50 / 24h) → one `@ICOM>LEAD,OWNER … FLAG echo.loop why=echo n=<count>` per ticket per window. Count uses the same resolve as relay: last4 binds to exactly one seen full id; unresolved, ambiguous, and non-iro tickets are not loop-counted. FLAG is not quiet and is never suppressed by this rule. The count is not progress.

### Loop vector (must suppress)
```
t0  @DEV>ICOM>QA P2 INT0 #iro-0a1b2c3d DONE ops.qc qa=pass
t1  @QA>ICOM>DEV P2 INT0 #iro-0a1b2c3d ACK ops.qc
t2  @DEV>ICOM>QA P2 INT0 #iro-0a1b2c3d ACK ops.qc
t3  @QA>ICOM>DEV P2 INT0 #iro-0a1b2c3d DONE ops.qc
t4  @DEV>ICOM>QA P2 INT0 #iro-0a1b2c3d DONE ops.qc qa=pass
```
Sender: t1–t4 are illegal (quiet after quiet). Relay, if they are sent: t0 relay; t1 relay (new key QA/ACK/body); t2 relay (new key DEV/ACK/body); t3 relay (new key QA/DONE/body); t4 **suppress** (same DEV+DONE+body as t0 inside 6h) — log `suppressed why=echo key=DEV:#iro-0a1b2c3d:DONE:<bodyhash>`. t4 is addressed to QA only, so LEAD/OWNER are not added. A later GO, ASK, or DECIDE on the same ticket resets the window; FLAG does not. last4 `2c3d#1` binds to this id if it is the only match; `#OPS-12` never groups.

### Conformant follow-up
```
@DEV>ICOM>QA P2 INT0 #iro-0a1b2c3d DONE ops.qc qa=pass
@QA>ICOM>DEV P2 INT0 #iro-0a1b2c3d ASK ops.qc ask=sample|none
```

Reference checker: `icom_noecho.py`. Tests: `tests/test_no_echo.py`.

## Changelog
- 1.2.0 (2026-10-29): no-echo — quiet-verb reply ban, relay suppress window, backlog collapse, unique DONE metrics (rule 18).
- 1.1.0 (2026-10): implied header, shortcuts, autoNAK, close clause.

## Deferred to v1.1.1
- Layered codebook (core, then role, then lane).
- Conflict checker (one code, one meaning, across every section and layer).
