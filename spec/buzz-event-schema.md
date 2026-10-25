# Buzz event envelope

Status: Draft, 2026-10-25.
By Robert Stanley / Iron Noodle Technologies. MIT License.

A team webhook posts this envelope to a chat channel so people can see
ICOM traffic, review verdicts, ticket-migration milestones, and hub
alerts in real time. The JSON object is the contract. How a host is
deployed is out of scope.

Schema: `schemas/buzz-event.schema.json` (JSON Schema draft 2020-12).
Examples: `schemas/examples/buzz-event-*.json`. Producer-shaped
fixtures: `schemas/fixtures/team-notify/`. Placeholder tickets and
agent codes only.

## 1. Envelope

`POST` a JSON body. Two shapes are valid.

Canonical envelope:

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

Text form, for chat endpoints that only accept a text field (cap 500):

```
{ "text": "[team-notify] TYPE VERB ticket from>to [status] ref=<ref>" }
```

Example:
`[team-notify] GAUNTLET FAIL T-5678 qc>lead ref=reviews/T-5678.md#a1b2c3d4e5f6`.

`TYPE` is the producer type in uppercase (`ICOM`, `GAUNTLET`, `PLT19`,
`ICOM-ALERT`). The JSON envelope is authoritative. The text line is a
lossy display form: same fields, already redacted, no extra prose. A
body that is only `{text}` and a body that is `{v,source,event}` are
the two schema branches.

## 2. Event object

Required on every event: `type`, `ticket`, `verb`, `from`, `to`, `ts`,
`ref`, `id`. Optional: `status`, `detail`, `severity`. On `icom-alert`,
either `severity` is set or `status` is `P0`..`P3` (producer form).

| Field | Type | Rule |
|---|---|---|
| `type` | string | Producer: `icom`, `gauntlet`, `plt19`, `icom-alert`. Public aliases `gauntlet-verdict` and `plt19-migration` are accepted and mean the same as `gauntlet` / `plt19`. |
| `ticket` | string | Tracker id. Optional leading `#`. Letters, digits, `.` `_` `:` `/` `-`. Directory-style fallback tokens are valid. A lone `-` means missing. |
| `verb` | string | Type-specific (below). A lone `-` means missing. |
| `from` / `to` | string | Agent codes, **case-insensitive**; hyphen allowed (`cl01-bot`). `to` may be a comma list. A lone `-` means missing. |
| `ts` | string | RFC 3339. UTC `Z` **or** a numeric offset. Fractional seconds allowed. |
| `ref` | string | Relative `path#digest` or a short token. No scheme, no host (`https://…` is invalid). |
| `id` | string | Dedupe key, 20 lowercase hex. See §2.5. |
| `status` | string | Delivery or outcome. Required for `icom`. |
| `detail` | string | Short, already-redacted note (≤ 240 chars). |
| `severity` | string | `info` / `warn` / `error` / `crit`. |

Unknown future `type` values: a display consumer MUST accept the HTTP
request and skip the event. An actor that cannot interpret the type
MUST NOT guess.

### 2.1 `type=icom`

One relayed or rejected ICOM line.

- `verb`: `GO` `HOLD` `DONE` `BLOCKED` `REC` `FYI` `ASK` `ACK` `NAK`, or `-`.
- `status`: `SENT` / `SPOOL` / `FAIL` / `REJECT` / `NAK-<code>`.
- `ref`: message id (short token).
- `detail`: optional redacted excerpt. Never a signature, nonce, or secret.

### 2.2 `type=gauntlet` (alias `gauntlet-verdict`)

A review verdict changed (new or content-changed).

- `verb`: `PASS` / `FAIL` / `BLOCKED` / `PASS-COND` / `UNKNOWN`, or `-`.
- `ticket`: first tracker id cited by the verdict.
- `ref`: relative path plus a 12-hex content digest, `relpath#sha12`.
- `status`: optional.

### 2.3 `type=plt19` (alias `plt19-migration`)

A ticket-migration milestone.

- `verb`: any uppercase token (`DRYRUN` `IMPORT` `SPOTCHECK` `STATE`
  `DONE` `FAIL` …). If the producer cannot classify the milestone it
  sends `EVENT`. The verb enum is **not** closed.
- `ticket`: the migration stream or a migrated id (placeholder `T-9001`).
- `ref`: batch or run token (`map:batch-01`).
- `detail`: optional counts or notes (`n=12`), already redacted.

### 2.4 `type=icom-alert`

Hub / signature operational alerts. Verbs are **case-insensitive**.
The producer emits uppercase `HUB-KEY-FAIL-CLOSED` and
`HUB-KEY-RESTORED`. Either `severity` is present, or `status` is
`P0`..`P3` (that is the producer’s severity channel when `severity`
is omitted).

| `verb` (any case) | When |
|---|---|
| `HUB-KEY-FAIL-CLOSED` / `hub-key-fail-closed` | Hub signing key is unusable; hub refuses to emit. |
| `HUB-KEY-RESTORED` / `hub-key-restored` | Hub signing key is usable again. |
| `SIG-FAILURE` / `sig-failure` | A verify failure was recorded (count or sample in `detail`). |
| `HUB-SIGN-SKIP` / `hub-sign-skip` | Hub emitted a line without `hsig=` (mode off, or skip). |

### 2.5 `id` (literal pipe)

```
id = lowercase_hex( SHA-256( type || "|" || source-key ) )[0:20]
```

The separator is a **literal ASCII pipe** `0x7C`, one byte, no spaces.
`type` in the hash is the **producer** type, not the public alias:

| Event `type` on the wire | `type` inside the hash |
|---|---|
| `icom` | `icom` |
| `gauntlet` or `gauntlet-verdict` | `gauntlet` |
| `plt19` or `plt19-migration` | `plt19` |
| `icom-alert` | `icom-alert` |

`source-key` is the producer’s stable key for that row (message id,
`relpath#sha12`, batch id, alert name). Receivers MUST NOT recompute
`id`; they only store and compare.

## 3. Redaction (last-4)

Producers run the same scrub on `detail`, on the text form, and on
their own logs. After scrub, the event is what goes on the wire.
Receivers MUST NOT try to recover masked values.

| Class | Rule | Public example |
|---|---|---|
| Email | Keep the first character of the local-part; mask the rest; keep the domain. | `j***@example.com` |
| Phone | Last 4 digits only. | `***-0142` |
| Card (Luhn pass) | Prefix `card***` plus last 4. | `card***1111` |
| Card-like, Luhn fail | **Keep** the digits. Not a card. | `acct=1234567890123456` |
| Secret / token | Omit. Known prefixes, `Bearer`/`Basic`, `key=val` secrets, PEM blocks, and opaque strings of 32+ chars never appear. | *(empty)* |
| UUID | Keep (not a secret). | |
| URL | Scheme and host only; drop path, query, and fragment. | `https://example.com` |

Logs that a producer keeps for itself may hold event ids, types, HTTP
status codes, and the destination host name. They MUST NOT hold the
full URL, a bearer token, or unredacted event text.

Card-like digit runs inside `sig`, `hsig`, and `nc` values are not
emitted on this envelope (those tokens stay off the event).

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

Changelog for this draft: `v=1` envelope (`icom`, `gauntlet` /
`gauntlet-verdict`, `plt19` / `plt19-migration`, `icom-alert`) plus the
`[team-notify]` text branch.

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

Examples validate against `schemas/buzz-event.schema.json`. Producer
fixtures under `schemas/fixtures/team-notify/` use the short type
names, offset timestamps, path refs, and the text branch.

### 6.1 ICOM line relayed

`id` = `SHA-256("icom|m01ab23cd45ef")[:20]`.

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
    "ts": "2026-10-25T12:00:00.000-07:00",
    "ref": "m01ab23cd45ef",
    "id": "160b13eeb7091bd7ea95",
    "status": "SENT",
    "detail": "ops.deploy nx=CTO:review",
    "severity": "info"
  }
}
```

### 6.2 Review verdict (producer type `gauntlet`)

`id` = `SHA-256("gauntlet|reviews/T-5678.md#a1b2c3d4e5f6")[:20]`.
The alias `gauntlet-verdict` hashes the same short type.

```json
{
  "v": 1,
  "source": "team-notify",
  "event": {
    "type": "gauntlet",
    "ticket": "T-5678",
    "verb": "FAIL",
    "from": "qc",
    "to": "lead",
    "ts": "2026-10-25T12:05:00.250-07:00",
    "ref": "reviews/T-5678.md#a1b2c3d4e5f6",
    "id": "89dd4c037538b2c933c7",
    "detail": "why=tests contact=j***@example.com phone=***-0142 card=card***1111 acct=1234567890123456",
    "severity": "error"
  }
}
```

### 6.3 Ticket-migration milestone (producer type `plt19`)

`id` = `SHA-256("plt19|map:batch-01")[:20]`. Verb `EVENT` is the
fallback when the milestone is unclassified.

```json
{
  "v": 1,
  "source": "team-notify",
  "event": {
    "type": "plt19",
    "ticket": "T-9001",
    "verb": "EVENT",
    "from": "CTO",
    "to": "LEAD",
    "ts": "2026-10-25T12:10:00.500-07:00",
    "ref": "map:batch-01",
    "id": "cb420a33341dc667c63e",
    "status": "SENT",
    "detail": "n=12",
    "severity": "info"
  }
}
```

### 6.4 Hub alert

```json
{
  "v": 1,
  "source": "team-notify",
  "event": {
    "type": "icom-alert",
    "ticket": "T-1234",
    "verb": "hub-key-fail-closed",
    "from": "ICOM",
    "to": "LEAD",
    "ts": "2026-10-25T12:15:00.000-07:00",
    "ref": "alert:hub-key",
    "id": "e59016f7e500eef1228e",
    "severity": "crit",
    "detail": "kid=0123456789ab"
  }
}
```

Producer form (uppercase verb, severity in `status=P1`, no `severity`):

```json
{
  "v": 1,
  "source": "team-notify",
  "event": {
    "type": "icom-alert",
    "ticket": "T-1234",
    "verb": "HUB-KEY-FAIL-CLOSED",
    "from": "ICOM",
    "to": "LEAD",
    "ts": "2026-10-25T12:15:00.000-07:00",
    "ref": "alert:hub-key",
    "id": "e59016f7e500eef1228e",
    "status": "P1",
    "detail": "kid=0123456789ab"
  }
}
```

### 6.5 Text branch

```json
{
  "text": "[team-notify] GAUNTLET FAIL T-5678 qc>lead ref=reviews/T-5678.md#a1b2c3d4e5f6"
}
```

### 6.6 Missing-field fallback

A lone `-` is valid for `from`, `to`, `ticket`, and `verb` when the
producer has no value.

```json
{
  "v": 1,
  "source": "team-notify",
  "event": {
    "type": "plt19",
    "ticket": "-",
    "verb": "-",
    "from": "-",
    "to": "-",
    "ts": "2026-10-25T12:20:00.000-07:00",
    "ref": "map:batch-01",
    "id": "cb420a33341dc667c63e",
    "status": "SENT"
  }
}
```
