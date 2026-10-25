# Buzz event envelope

Status: Draft, 2026-10-25.
By Robert Stanley / Iron Noodle Technologies. MIT License.

A team webhook posts this envelope to a chat channel so people can see
ICOM traffic, review verdicts, and ticket-migration milestones in
real time. The JSON object is the contract. How a host is deployed is
out of scope.

Ticket: PLT-22. Schema: `schemas/buzz-event.schema.json` (JSON Schema
draft 2020-12). Examples: `schemas/examples/buzz-event-*.json`.
Placeholder tickets and agent codes only.

## 1. Envelope

`POST` a JSON body. Canonical shape:

```
{ "v": 1, "source": "team-notify", "event": { ... } }
```

| Field | Type | Rule |
|---|---|---|
| `v` | integer ≥ 1 | Envelope version. Current: `1`. |
| `source` | string | Producer id, lowercase + digits + hyphen. `team-notify` is the default producer of these events. |
| `event` | object | One event. See §2. |

Optional HTTP header: `Idempotency-Key: <event.id>` (20 lowercase hex).
Receivers that key on it MUST treat a repeat as the same event.

An alternate body for chat endpoints that only accept a text field:

```
{ "text": "[icom] <TYPE> <VERB> <ticket> <FROM>><TO> [status] ref=<ref>" }
```

Example: `[icom] ICOM GO #T-1234 LEAD>CTO SENT ref=m01ab23cd45ef`.
The JSON envelope is authoritative. The text line is a lossy display
form: same fields, already redacted, no extra prose.

## 2. Event object

Required on every event: `type`, `ticket`, `verb`, `from`, `to`, `ts`,
`ref`, `id`. Optional: `status`, `detail`.

| Field | Type | Rule |
|---|---|---|
| `type` | string | `icom` / `gauntlet-verdict` / `plt19-migration`. |
| `ticket` | string | `#T-…`, `#iro-` + 8 hex, or `PLT-` + digits. `#` optional. |
| `verb` | string | Type-specific (below). |
| `from` / `to` | string | Codebook agent codes. `to` may be a comma list. |
| `ts` | string | Event time, RFC 3339 / UTC (`…Z`). |
| `ref` | string | Stable pointer back to the source record (message id, verdict digest, batch id). No filesystem paths. |
| `id` | string | Dedupe key: first 20 lowercase hex digits of `SHA-256(type \|\| source-key)`. |
| `status` | string | Delivery or outcome. Required in practice for `icom`. |
| `detail` | string | Short, already-redacted note (≤ 240 chars). |

`id` is computed by the producer from a source-specific key (for
example the ICOM message id, or a verdict path token plus a content
digest). Receivers MUST NOT recompute it; they only store and compare.

### 2.1 `type=icom`

One relayed or rejected ICOM line.

- `verb`: ICOM verb (`GO` `HOLD` `DONE` `BLOCKED` `REC` `FYI` `ASK`
  `ACK` `NAK`).
- `status`: `SENT` / `SPOOL` / `FAIL` / `REJECT` / `NAK-<code>`
  (hyphenated NAK code from the ICOM or ICOM-BC spec).
- `ref`: message id (short token, not a path).
- `detail`: optional redacted excerpt (`object` and a few `key=val`s).
  Never a signature, nonce, or secret.

### 2.2 `type=gauntlet-verdict`

A review verdict changed (new or content-changed).

- `verb`: `PASS` / `FAIL` / `BLOCKED` / `PASS-COND` / `UNKNOWN`.
- `ticket`: first `#T-…`, `#iro-…`, or `PLT-…` cited by the verdict.
- `ref`: `verdict:<ticket-token>:<sha12>` where `sha12` is the first 12
  hex digits of the verdict content hash. No host or directory prefix.
- `status`: optional.

### 2.3 `type=plt19-migration`

A ticket-migration milestone (dry-run, import, spot-check, state,
done, fail).

- `verb`: `DRYRUN` / `IMPORT` / `SPOTCHECK` / `STATE` / `DONE` / `FAIL`.
- `ticket`: the migration stream (`PLT-19`) or a migrated id (`PLT-101`).
- `ref`: batch or run token (`map:batch-01`).
- `detail`: optional counts or notes (`n=12`), already redacted.

Unknown future `type` values: a display consumer MUST accept the HTTP
request and skip the event. An actor that cannot interpret the type
MUST NOT guess.

## 3. Redaction (last-4)

Producers run the same scrub on `detail`, on any text form, and on
their own logs. After scrub, the event is what goes on the wire.
Receivers MUST NOT try to recover masked values.

| Class | Rule | Public example |
|---|---|---|
| Email | Keep the first character of the local-part; mask the rest; keep the domain. | `j***@example.com` |
| Phone | Last 4 digits only. | `***-0142` |
| Card | Last 4 only, and only after a Luhn pass. Otherwise drop. | `************1111` |
| Secret / token | Omit. Known prefixes, `Bearer`/`Basic`, `key=val` secrets, PEM blocks, and opaque strings of 32+ chars never appear. | *(empty)* |
| UUID | Keep (not a secret). | |
| URL | Scheme and host only; drop path, query, and fragment. | `https://example.com` |

Logs that a producer keeps for itself may hold event ids, types, HTTP
status codes, and the destination host name. They MUST NOT hold the
full URL, a bearer token, or unredacted event text.

Card-like digit runs inside `sig`, `hsig`, and `nc` values are not
emitted on this envelope in the first place (those tokens stay off the
event).

## 4. Versioning

`v` is the **envelope** version. It is not the ICOM protocol version
and it is not the codebook version.

| Kind of change | What happens |
|---|---|
| Wording, examples, redaction prose | No `v` bump. |
| New *optional* event field, or a new `type` that old consumers can skip | Stay on the same `v`. The published schema gains the field. |
| Rename, remove, or change the type/meaning of a required field; change a `type` or `verb` enum in a breaking way; change redaction so a previously valid event becomes invalid | Bump `v`. |

Rules:

1. Producers MUST send every required field for the `v` they declare.
2. Consumers MUST ignore unknown fields.
3. Consumers MUST reject `v` < 1. For `v` greater than they implement:
   display consumers accept and render known fields; strict actors that
   would take a side effect MAY refuse the event (HTTP 4xx) rather than
   guess.
4. `source` is a stable producer id. A new producer gets a new `source`,
   not a new `v`.
5. Additive schema edits that only add optional properties do **not**
   bump `v`. The schema file is the living contract for the current `v`.

Changelog for this draft: `v=1` initial public envelope (`icom`,
`gauntlet-verdict`, `plt19-migration`).

## 5. Kill switch and delivery

The envelope is inert until something posts it. The producer:

- Is **off** unless an enable flag is the exact token `on`
  (case-sensitive). Any other value, including unset, means no reads
  and no posts.
- Honors a runtime kill marker: hold all sends, do not advance source
  cursors, lose nothing. Removing the marker resumes.
- Does not post when the destination URL is unset.
- Retries 5xx, 408, 425, 429, and network errors with backoff. Other
  4xx are dead-lettered (redacted event only; no URL) and are not
  auto-retried.
- Dedupes on `event.id` (and the `Idempotency-Key` header).
- Applies a token-bucket rate limit before post.

None of those switches belong in the JSON body. A posted envelope means
the producer was enabled and not killed at send time.

## 6. Examples

One example per `type`. All three validate against
`schemas/buzz-event.schema.json`.

### 6.1 ICOM line relayed

```json
{
  "v": 1,
  "source": "team-notify",
  "event": {
    "type": "icom",
    "ticket": "#T-1234",
    "verb": "GO",
    "from": "LEAD",
    "to": "CTO",
    "ts": "2026-10-25T19:00:00Z",
    "ref": "m01ab23cd45ef",
    "id": "4d3c2b1a0f9e8d7c6b5a",
    "status": "SENT",
    "detail": "ops.deploy nx=CTO:review"
  }
}
```

### 6.2 Review verdict

```json
{
  "v": 1,
  "source": "team-notify",
  "event": {
    "type": "gauntlet-verdict",
    "ticket": "#T-5678",
    "verb": "FAIL",
    "from": "QC",
    "to": "LEAD",
    "ts": "2026-10-25T19:05:00Z",
    "ref": "verdict:T-5678:a1b2c3d4e5f6",
    "id": "b0a1928374655e6d7c8b",
    "detail": "why=tests"
  }
}
```

### 6.3 Ticket-migration milestone

```json
{
  "v": 1,
  "source": "team-notify",
  "event": {
    "type": "plt19-migration",
    "ticket": "PLT-19",
    "verb": "DRYRUN",
    "from": "CTO",
    "to": "LEAD",
    "ts": "2026-10-25T19:10:00Z",
    "ref": "map:batch-01",
    "id": "c1d2e3f4a5b60718293a",
    "status": "SENT",
    "detail": "n=12"
  }
}
```

Redaction on a `detail` that once held an email and a phone, after
scrub: `contact=j***@example.com phone=***-0142`.
