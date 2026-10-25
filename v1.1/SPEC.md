# ICOM v1.1 shorthand: specification

By Robert Stanley / Iron Noodle Technologies. MIT License.

## Canonical v1 line (output)
`@FROM>ICOM>TO[,TO] Pn LANE #tkt-xxxxxxxx VERB [ACTION] object key=val ...`
- One line per message. No prose: everything after the object is `key=val`.
- The ticket prefix is codebook `ticket_prefix` (default `tkt-`, written without `#`). Examples here use the default. A deployment may set another prefix; parse and normalize against that value.
- P0 is reserved for a customer-facing outage: it needs a non-internal lane and `why=down|outage|sec|money`.
- Emails are written as `initial@domain` with no TLD.

## v1.1 input additions
1. **Phrase shortcuts.** `$NAME` in the verb slot expands from the codebook `shortcuts.NAME.expand`. An optional `shortcuts.NAME.pri` supplies the priority if the sender gave none. Sender `key=val` pairs override template keys. A shortcut line must carry `cb=<codebook version>`.
2. **Implied header.**
   - The `>ICOM` hop may be omitted.
   - Priority defaults to the thread value, else P2. Lane defaults to the thread value, else INT0.
   - The ticket may be omitted once the thread (the sorted party set) is bound. A bare `#` followed by 8 hex characters is normalized to `#` plus the configured ticket prefix (default `tkt-`).
   - FROM, TO, verb and object are never implied.
   - The short forms `last4#seq` and `^tag` pass through unchanged.
3. **Version token.** `cb=<version>` is optional on v1 lines and required on shortcut lines. A mismatch with the loaded codebook produces a NAK.
4. **Path alias.** `f=` values starting with an alias from the codebook `paths:` map are expanded. Aliases save no tokens, so writing full paths is preferred.
5. **Close.** A thread closes on DONE ops.docket carrying the full prefixed ticket (`#` + codebook `ticket_prefix` + 8 hex; default `#tkt-`) or after 24h idle. A plain DONE does not close. Short forms (last4#seq, ^tag) cannot close.

## autoNAK
`@ICOM>ICOM>FROM P2 INT0 <ticket|#icom-nak> NAK org.proto why=<code> [det=<token>] cb=<version>`

Codes: empty, multiline, no-header, bad-route, bad-agent, bad-pri, bad-lane, bad-ticket, bad-verb, bad-icx, prose, email, unk-shortcut, cb-required, cb-mismatch, p0-misuse.

Relays may add codes for relay-level checks (bad-grammar, bad-from, k1-pci, unbound_tag, unbound_short, tag_in_ref, bad_tag, tag_clash, reject), spelled lowercase with hyphens. R18 codes keep their underscores for compatibility.

## Codebook (external; keys read)
- `version`
- `verbs`
- `lanes` and/or `clients`
- `agents`
- `icx.codes`
- `paths`
- `shortcuts`
- `ticket_prefix` (optional string; default `tkt-`)

Each list may be given as a list, as dict keys, or as a list of `{code: ...}`.

The object should be in icx.codes; unknown objects are delivered (no NAK) in v1.1.

## Deferred to v1.1.1
- Layered codebook (core, then role, then lane).
- Conflict checker (one code, one meaning, across every section and layer).
