# ICOM over BitChat — payload spec

Status: Draft, 2026-10-25. Complements ICOM v1 / v1.1.
By Robert Stanley / Iron Noodle Technologies. MIT License.

This document says how **one ICOM message line** is carried as a BitChat
payload (mesh / Bluetooth chat). BitChat is the carrier. ICOM is the
content. The carrier does not rewrite the line.

Examples use placeholder lanes (`CL01`, `INT0`) and placeholder agent
codes from `codebook.yaml`. Live Ed25519 vectors are TEST-ONLY and live
in `schemas/vectors/icom-sig-v1.json`.

## 1. Purpose

Agents already speak one line:

```
@FROM>ICOM>TO P0-3 LANE #ticket VERB object key=val ...
```

A mesh / BLE chat hop is useful when the usual hub path is down, or when
two agents share a radio and need the same line without a network. This
spec defines:

1. The ICOM line that goes in the payload (header, ICX object, tokens).
2. Signed-identity tokens: agent `sts` / `nc` / `sig`, hub `ts` / `hsig`.
3. UTF-8 encoding, a size budget for small BLE writes, and a compact
   frame with optional ICOM-level fragmentation.
4. Validation order, NAK codes, NAK safety, mesh dedupe, and a
   frame-level hop cap (not a signed line token).

A BitChat client that does not implement this spec MUST treat the body
as ordinary chat and MUST NOT guess an ICOM parse.

## 2. Carrier model

```
BitChat envelope (routing, TTL, Noise, peer ids)     -- out of scope
  └── payload bytes  =  one ICOM-BC frame             -- this spec
        └── UTF-8 ICOM line (maybe split across frames)
```

- One ICOM-BC frame is the **entire** BitChat message body (the
  decrypted public or private text), not a field inside some other
  schema.
- ICOM-BC does not require a new BitChat packet type.
- The carrier may fragment underneath (typical BLE write ~400–469
  octets after envelope). That is transparent. ICOM-BC fragmentation
  exists so a receiver can reassemble an ICOM line even when the
  carrier does not, or when the local write budget is smaller.
- Relays MUST NOT strip, reorder, or normalize ICOM tokens. Signatures
  cover the line bytes. Hop count lives on the **frame**, not the line;
  a forward increments the frame hop and leaves the signed line
  untouched.

## 3. ICOM line

### 3.1 Header

Canonical v1 / v1.1 line (one line, no CR/LF, no prose):

```
@FROM>ICOM>TO[,TO] Pn LANE #ticket VERB [ACTION] object *(SP key=val)
```

| Slot | Rule |
|---|---|
| `FROM` / `TO` | Codebook agent codes (letters and digits). Multiple recipients: `>TO1,TO2`. `ALL` is broadcast. |
| `>ICOM>` | Required on the wire. The v1.1 expander may accept a short form; BitChat carries the canonical line. |
| `Pn` | `P0` now (outage / money / sec; needs a non-internal lane and `why=`), `P1` today, `P2` this week, `P3` whenever. |
| `LANE` | Client/lane code (`CL01`…), or `INT0` if internal. |
| `#ticket` | Required. No ticket → NAK `bad-ticket` (or `empty` if the whole line is blank). |
| `VERB` | `GO` `HOLD` `DONE` `BLOCKED` `REC` `FYI` `ASK` `ACK` `NAK`. After `REC`, an optional action verb. |
| `object` | ICX concept code (see below). |
| `key=val` | Tokens. Values are a single token, a list `a,b`, alternatives `a\|b`, or `"quoted text"`. |

Secrets, tokens, and keys never appear as values. Point at a name or a
file with `f=`, do not paste the secret.

### 3.2 ICX object class

ICOM says how agents talk. [ICX](https://github.com/rstan251/icx) says
what they talk about. The `object` slot is an ICX concept code:
class.division.section, coarse to fine (`org.proto`, `ops.deploy`,
`pr.voice.intake`). Every prefix is a valid code, so routing and search
work by prefix.

- Lane/client stays in the `LANE` slot, never inside the object.
- Exact values (ids, counts, paths) stay in `key=val`, never in the object.
- Unknown concept: send `x.<word>`. v1 NAKs `icx.unk` / `bad-icx`.
  v1.1 may deliver an unknown object and leave it for codebook review.

### 3.3 Signed identity

Unsigned `@FROM` is a claim anyone can type. A signed line binds `FROM`
to a key in a public registry (agent code → key id → public key).

**Algorithm.** Ed25519 (RFC 8032). 32-byte public key, 64-byte
signature. No per-signature randomness.

**Encodings.**

| Item | Encoding |
|---|---|
| Public key | Raw 32 bytes, base64url without padding (43 chars). Registry only; never on the line. |
| Key id `kid` | First 12 lowercase hex digits of `SHA-256(raw 32-byte public key)`. |
| Signature | Raw 64 bytes, base64url without padding (86 chars). |
| `sts` | Agent signed time, unix seconds, decimal, 10 digits. Agent lines only. |
| `nc` | Agent nonce: 12 fresh random bytes, base64url without padding (16 chars). Agent lines only. |
| `ts` | Hub / relay timestamp (RFC 3339 or the relay’s usual stamp). Hub lines only. |

**Two grammars.** `sts=` / `nc=` are **not** required on every signed
line.

| Kind | Trailing tokens (last is the signature) |
|---|---|
| Agent line | `sts=<unix10> nc=<nonce16> sig=ed25519:<kid>:<b64url-86>` |
| Hub line (relayed or NAK) | `ts=<hub-stamp> hsig=ed25519:<hub-kid>:<b64url-86>` |

Token names are `sts` / `nc` / `sig` on purpose: `ts` is reserved for
the hub stamp, and `n` already means count. A hub line MUST NOT be
required to carry `sts=` or `nc=`. Delivered hub copies drop the
agent’s `sig` / `sts` / `nc` and carry `ts=` + `hsig=` instead.

A line has at most one `sig=` and at most one `hsig=`. `sig=` / `hsig=`
MUST be the last token. Signing never inserts CR/LF.

**Canonical bytes** (what is signed / verified), taken from the line
exactly as received:

1. Bytes MUST be valid UTF-8 and MUST NOT contain CR or LF; else
   `sig-bad` with `det=enc` (or `multiline` if a second line is present).
   No Unicode normalization; bytes are signed as sent.
2. Strip leading and trailing ASCII space and tab. Split on runs of
   ASCII space/tab.
3. Agent line: exactly one `sig=`, one `sts=`, one `nc=`. Hub line:
   exactly one `hsig=`, one `ts=`. Duplicates → `sig-bad` `det=dup`.
4. Drop every token whose key is `sig` or `hsig`. Keep the rest in
   order (`sts`/`nc` on agent lines, `ts` on hub lines).
5. Join with a single `0x20`. Then
   `M = domain || 0x00 || UTF-8(joined)`.

Domain string is `icom-sig-v1` for an agent signature and
`icom-hsig-v1` for a hub signature (so one cannot be replayed as the
other).

**Verify order** (first failure wins):

1. Existing line checks: `empty`, `multiline`, `no-header`.
2. No `sig=` when the receiver is enforcing agent signatures →
   `sig-missing`. Hub lines are checked for `hsig=` instead.
3. Malformed signature / time / nonce (wrong alg, length, or base64url)
   → `sig-bad` `det=fmt` (or `dup` / `enc`).
4. `kid` not in the registry → `sig-kid-unknown`.
5. `kid` revoked; or retired with signed-time after `not_after`; or
   signed-time before `not_before` → `sig-revoked`.
6. Registry agent for that `kid` ≠ header `FROM` → `sig-from-mismatch`.
7. Ed25519 verify of `M` fails → `sig-bad` `det=verify`.
8. Freshness against the **receiver clock only**. Do not use a sender
   or carrier timestamp as `ref_time` (that is a bypass).
   - Agent `sts`: `|receiver_now - sts| > 120` → `sig-stale`.
   - Hub `ts`: `|receiver_now - ts| > 600` → `hsig-stale` (flag / drop,
     not a relay NAK).
9. Pair `(kid, nc)` already seen on an agent line → `sig-replay`.
   Insert only after steps 2–8 pass.

Nonce-cache entries expire at `sts + 120`. A full cache fails closed:
`sig-replay` with `det=cache-full`. Agent lines delayed past 120 s MUST
be re-signed. Receivers MAY run `off` (tokens pass through), `observe`
(verify and log only), or `enforce` (NAK and do not relay).

**Registry (public data).** One `kid` binds to exactly one agent. An
agent may have up to two `active` kids during rotation. Status is
`active` (sign and verify), `retired` (verify only while
`sts <= not_after`), or `revoked` (never verifies). Private keys never
appear in a line, a log, a ticket, or this spec. TEST-ONLY keys in
`schemas/vectors/` are derived at check time and are marked `"test": true`.

A BitChat hop is a **carrier**, not a hub. Mesh senders keep `sig` /
`sts` / `nc` on the line. Mesh receivers that hold the registry SHOULD
verify when present; they MUST NOT strip those tokens. If a hub later
ingests the line, the hub verifies, then MAY drop the agent signature
and attach `ts=` + `hsig=` on the copy it emits.

## 4. Encoding and size budget

- Character set: UTF-8. No BOM. No CR (`0x0D`) or LF (`0x0A`) inside a
  frame.
- The ICOM line is the UTF-8 encoding of the header in section 3.
- **Signed** identity tokens add about **147** octets
  (` sts=` + unix10 + ` nc=` + 16 + ` sig=ed25519:` + kid + `:` + 86).
  A typical signed line is a few hundred octets and fits in one write.

| Name | Value | Why |
|---|---|---|
| `SOFT_BUDGET` | 400 octets | Stay inside a common BLE write after a mesh envelope (ATT MTU up to 512; many stacks split near ~469). |
| `HARD_CHUNK` | 1024 octets | Max ICOM-BC fragment chunk. |
| `MAX_LINE` | 1024 octets | Max reassembled ICOM line (router cap). Oversize → `bc-oversize`. |
| `MAX_FRAGS` | 16 | More → `bc-oversize`. |
| `FRAG_TTL` | 30 s | Incomplete fragment set → `bc-frag-timeout`. |
| `HOP_CAP` | 8 | Advisory frame hop cap. Hop is unauthenticated; mid dedupe is the loop guard. At 8, silent drop. |
| `MID_TTL` | 600 s | Mesh message-id dedupe window. |
| `MID_CAP` | 4096 | Mesh dedupe entries. Oldest expire first. |

If `len(single-frame)` is ≤ `min(local_write_budget, SOFT_BUDGET)`, send
one `single` frame. Otherwise send `fragment` frames whose chunk size is
`min(local_write_budget, SOFT_BUDGET, HARD_CHUNK)` minus the fragment
prefix. Split on UTF-8 character boundaries. Receivers concatenate in
index order, then UTF-8 decode once.

A sender that knows the peer will apply carrier-level BLE fragments MAY
still send a single ICOM-BC frame larger than 400 octets, but MUST NOT
exceed `MAX_LINE`.

## 5. Compact frame

Profile name: `ICOM-BC/1`.

Text is canonical: BitChat bodies are UTF-8 chat. The prefix is short
and the ICOM line (which may contain `|` in `ask=a|b`) is the remainder
of the frame, so `|` is not a delimiter.

### 5.1 ABNF (RFC 5234, `%s` = case-sensitive)

```
frame       = single / fragment
single      = %s"IC1" SP %s"S" [SP hop-tok] SP icom-line
fragment    = %s"IC1" SP %s"F" SP msgid SP index "/" total SP hop-tok SP chunk
hop-tok     = %s"h=" hop        ; required on every fragment, including h=0
hop         = %x30-38           ; 0..8; frame only, never on the ICOM line

msgid       = 16HEXDIG          ; SHA-256(line)[:16], 64-bit
index       = 1*2DIGIT          ; 1-based
total       = 1*2DIGIT          ; 1..16
chunk       = 1*utf8-no-crlf    ; UTF-8 remainder; may start with SP

icom-line   = "@" agent %s">ICOM>" recips SP pri SP lane SP ticket
              SP verb [SP verb] SP icx-code *(SP kv)
              [SP sig-tail]

recips      = agent *("," agent)
agent       = 2*8(UPALPHA / DIGIT)   ; codebook.agents; digits allowed
pri         = %s"P0" / %s"P1" / %s"P2" / %s"P3"
lane        = 2*8(ALPHA / DIGIT)
ticket      = "#" 1*(ALPHA / DIGIT / "-" / "_" / ".")
verb        = %s"GO" / %s"HOLD" / %s"DONE" / %s"BLOCKED"
              / %s"REC" / %s"FYI" / %s"ASK" / %s"ACK" / %s"NAK"
icx-code    = 1*lcalpha *("." 1*lcalpha / "~" 1*lcalpha)
kv          = key "=" kv-val    ; key is not sts / nc / sig / hsig / ts
key         = 1*(lcalpha / DIGIT / "-" / "_")
kv-val      = 1*unquoted / DQUOTE *(%x20-21 / %x23-7E) DQUOTE
unquoted    = %x21-7E           ; printable, including "|"; no SP

sig-tail    = agent-sig / hub-sig
agent-sig   = %s"sts=" 10DIGIT SP %s"nc=" nonce16 SP
              %s"sig=" %s"ed25519:" kid ":" sigb64
hub-sig     = %s"ts=" ts-val SP
              %s"hsig=" %s"ed25519:" kid ":" sigb64
nonce16     = 16(ALPHA / DIGIT / "-" / "_")
ts-val      = 1*(ALPHA / DIGIT / "-" / ":" / "." / "+" / "T")
kid         = 12HEXDIG
sigb64      = 86(ALPHA / DIGIT / "-" / "_")

utf8-no-crlf = %x09 / %x20-7E / UTF8-2 / UTF8-3 / UTF8-4
UTF8-2       = %xC2-DF UTF8-tail
UTF8-3       = %xE0 %xA0-BF UTF8-tail / %xE1-EC 2UTF8-tail
             / %xED %x80-9F UTF8-tail / %xEE-EF 2UTF8-tail
UTF8-4       = %xF0 %x90-BF 2UTF8-tail / %xF1-F3 3UTF8-tail
             / %xF4 %x80-8F 2UTF8-tail
UTF8-tail    = %x80-BF
2UTF8-tail   = UTF8-tail UTF8-tail
3UTF8-tail   = UTF8-tail UTF8-tail UTF8-tail

lcalpha      = %x61-7A
UPALPHA      = %x41-5A
```

`msgid` is the first 16 lowercase hex digits of `SHA-256(UTF-8 ICOM
line)` (64 bits). It only correlates fragments and mesh dedupe. It is
not a secret.

Logical JSON (same meaning as the text frame; schema at
`schemas/icom-bc-frame.schema.json`):

```
{ "v": 1, "kind": "single", "hop": 0, "line": "<icom-line>" }
{ "v": 1, "kind": "fragment", "hop": 0, "msgid": "<16hex>", "index": 1, "total": 2, "chunk": "..." }
```

`hop` is a frame field. It MUST NOT appear as a `key=val` on the ICOM
line, and it is not covered by `M`. Missing `hop` means 0. JSON Schema
`maxLength` on `line`/`chunk` is a character count; the spec cap is
1024 UTF-8 **octets**.

Wire mapping:

- single → `IC1 S ` + optional `h=<hop> ` + `line` (`h=N` omitted when hop is 0)
- fragment → `IC1 F ` + `msgid` + ` ` + `index` + `/` + `total` + ` h=<hop>` + ` ` + `chunk`

Fragment `hop-tok` is mandatory, including `h=0`. A later chunk may
legitimately start with `h=<0-8> ` (the split point is free), so an
optional hop token before `chunk` is ambiguous. Example: line
`@LEAD>ICOM>CTO P2 CL01 #T-1234 FYI org.proto n=1 h=5 x=1` split
before `h=5` yields chunk 2 `h=5 x=1`; the wire still carries `h=0`
first. `h=` on the ICOM line is an ordinary `key=val`. `hop=` on the
line is forbidden.

### 5.2 Optional binary prefix

Implementations that put ICOM in a typed binary payload MAY use:

```
magic[3] = "IC1"
ver_u8   = 1
flags_u8 = bit0 fragment; bit1 last-fragment
hop_u8   = 0..8          ; frame hop; not part of the signed line
if fragment: msgid_u64be, index_u8 (0-based), total_u8, then chunk
else: UTF-8 icom-line
```

Text (`IC1 S` / `IC1 F`) remains the interoperable BitChat body. A
receiver that sees `IC1` as the first three bytes and the fourth byte
is not `0x20` MAY try the binary form; otherwise it parses text.

## 6. Validation, NAK safety, dedupe, hops

Receivers parse the BitChat body as ICOM-BC, reassemble if needed, then
apply ICOM and signature checks. First failure wins.

### 6.1 Mesh dedupe and hop cap

After reassembly, `mid` = `msgid` (or `SHA-256(line)[:16]` on a single
frame). Cache `(mid → expiry)`. Window `MID_TTL` = 600 s, cap
`MID_CAP` = 4096. A repeat inside the window is a **silent drop**.

Frame `hop` is 0 at the origin (missing means 0). Each ICOM-BC forward
increments the **frame** hop only. The ICOM line, including `sig` /
`hsig`, is copied byte-for-byte. Frame hop is **unauthenticated**: a
relay can reset it. `HOP_CAP` (8) is therefore advisory. The real loop
guard is mid dedupe (`MID_TTL` / `MID_CAP`). A receiver MAY still
silent-drop when `hop >= HOP_CAP`. Do not NAK.

### 6.2 NAK shape

A NAK is itself an ICOM **hub** line. It carries `cb=` (codebook /
spec version) and `ts=` + `hsig=`. It never echoes `sig`, `nc`, or
key material:

```
@ICOM>ICOM>FROM P2 INT0 #ticket NAK org.proto why=<code> [det=<token>] cb=1.1.1 ts=<hub-stamp> hsig=ed25519:<hub-kid>:<b64url-86>
```

If the inbound line had no usable ticket, the NAK ticket is `#icom-nak`.

### 6.3 NAK safety

1. **No NAK-of-NAK.** If the inbound verb is `NAK`, never emit a NAK.
   Drop or log only.
2. **Unrecoverable sender.** If `FROM` is missing, unknown, or
   unroutable, **silent drop**. Do not invent a destination.
3. **Rate limit.** Cap NAKs per sender (4 per 60 s is the default).
   Excess is a silent drop.
4. Frame / hop / dedupe drops above are silent: they do not produce a
   NAK.

### 6.4 Frame codes

| Code | When |
|---|---|
| `bc-bad-frame` | Body does not match `single` / `fragment`, or `index`/`total` out of range. |
| `bc-bad-utf8` | Reassembled bytes are not UTF-8. |
| `bc-oversize` | Chunk, fragment count, or reassembled line exceeds the budget. |
| `bc-frag-timeout` | `FRAG_TTL` expired with a missing index. |
| `bc-msgid-mismatch` | Reassembled line hashes to a different `msgid`. |

### 6.5 ICOM codes

`empty`, `multiline`, `no-header`, `bad-route`, `bad-agent`, `bad-pri`,
`bad-lane`, `bad-ticket`, `bad-verb`, `bad-icx`, `prose`, `email`,
`unk-shortcut`, `cb-required`, `cb-mismatch`, `p0-misuse`. Relays may
add lowercase hyphenated codes. Hyphen is canonical; `_` is accepted as
`-`.

### 6.6 Signature codes

| Code | Typical `det` |
|---|---|
| `sig-missing` | (none) |
| `sig-bad` | `fmt` / `dup` / `enc` / `verify` |
| `sig-kid-unknown` | the unknown `kid` |
| `sig-revoked` | `revoked` / `retired` / `early` |
| `sig-from-mismatch` | the `kid` |
| `sig-stale` | `skew` |
| `sig-replay` | (none) or `cache-full` |

`det` is only one of the values above, or a `kid`. A bad or stale hub
signature on a delivered line is `hsig-bad` / `hsig-stale` (flag, not a
relay NAK).

## 7. Worked examples

Lanes `CL01` / `INT0`; agents `LEAD`, `CTO`, `QC`, `ICOM`. TEST-ONLY
keys are derived as `SHA-256("ICOM-BC-TEST-ONLY-<ROLE>")` (32-byte
Ed25519 seed). Full vectors, including 86-char signatures, are in
`schemas/vectors/icom-sig-v1.json` (hygiene allows `ed25519:` tails
there). The lines below are those vectors.

### 7.1 Single-frame FYI (unsigned)

```
@LEAD>ICOM>CTO P2 CL01 #T-1234 FYI org.proto n=1
```

Wire: `IC1 S ` plus that line (frame hop omitted, meaning 0). A
forwarded copy is `IC1 S h=2 ` plus the **same** line; the hop is
never written onto the ICOM line. Fits in `SOFT_BUDGET`. In `enforce`
mode this is `sig-missing`.

### 7.2 Single-frame signed GO (agent grammar)

Frozen `sts=1792954800`, `nc=AAAAAAAAAAAAAAAA`, role `LEAD`
(`kid=1582fdbfe0e6`). On the wire this is one line:

```
@LEAD>ICOM>CTO P1 INT0 #T-1234 GO ops.deploy nx=CTO:review sts=1792954800 nc=AAAAAAAAAAAAAAAA sig=ed25519:1582fdbfe0e6:DlyyM1zcH71bXqhXblmRZ5k_xDqFe1mfm5N99jWFC6WMPYg4w_wJHjjri0B5R_aaoZUxxwe-BzULd7yTMEjYCA
```

Canonical join (signature dropped):

```
@LEAD>ICOM>CTO P1 INT0 #T-1234 GO ops.deploy nx=CTO:review sts=1792954800 nc=AAAAAAAAAAAAAAAA
```

`M = "icom-sig-v1" || 0x00 || UTF-8(that string)`. Freshness is
`|receiver_now - 1792954800| <= 120`.

### 7.3 Hub-delivered line and a NAK

Same payload after hub ingest (`ts=` + `hsig=`, no `sts`/`nc`/`sig`).
Role `HUB`, `kid=4028bdb5c5bc`. Recipient window is **600 s** against
the receiver clock:

```
@LEAD>ICOM>CTO P1 INT0 #T-1234 GO ops.deploy nx=CTO:review ts=2026-10-25T12:00:00-07:00 hsig=ed25519:4028bdb5c5bc:UYHuu4uuK7HMOLJ86hi7oDFt6pJbIHrx1yU-fbYskJwblN1xgq9YiUixZIR3mFk2oULRJXsU9Nww29qqCGE0CQ
```

If an inbound agent line is `sig-stale`, the hub NAK is:

```
@ICOM>ICOM>QC P2 INT0 #T-5678 NAK org.proto why=sig-stale det=skew cb=1.1.1 ts=2026-10-25T12:00:00-07:00 hsig=ed25519:4028bdb5c5bc:eWyTf0SiCQLJhGc_JaM-6sXIXTONwInbHjZiy1ANNk88Hvvl3TJyDY19FQIWgLkvevtodlpslab8ghqO5Af6Dw
```

That NAK MAY travel as `IC1 S @ICOM>ICOM>QC ...`. A peer MUST NOT NAK
this NAK.

### 7.4 Fragmented ASK

Role `QC`, `kid=12d4819fcc5f`. `msgid=758c7a56aab911a7` =
`SHA-256(full line)[:16]`. Fragment hop-tok is always present (`h=0`
here).

```
IC1 F 758c7a56aab911a7 1/2 h=0 @QC>ICOM>LEAD P1 CL01 #T-5678 ASK qa.review ask=APPROVE|HOLD why=tests,lint
IC1 F 758c7a56aab911a7 2/2 h=0  n=3 sts=1792954800 nc=AAAAAAAAAAAAAAAA sig=ed25519:12d4819fcc5f:zzNnefQsozgYFeEd8ee0F1cCq6N1T4t8Y1MdRCBf438l6Py8MExKyE_nviQVc9AK3bu30XeErn_EfugX6eKnCw
```

Chunk 2 starts with SP so reassembly restores the `key=val` separator.

## 8. Conformance

A producer is conformant if it emits only `ICOM-BC/1` frames, keeps
each ICOM line to one UTF-8 line of at most 1024 octets, uses agent
`sts/nc/sig` or hub `ts/hsig` as specified, places the signature last,
and fragments only when the single frame would exceed the budget.

A consumer is conformant if it implements section 6 in order (including
NAK safety, 600 s / 4096 mid dedupe, frame hop cap 8, and receiver-clock
freshness), ignores unknown future `key=val` tokens, never rewrites the
signed line to carry hop, and never logs `sig`, `nc`, or key bytes
(kid only).

JSON Schema for the logical frame: `schemas/icom-bc-frame.schema.json`.
Examples: `schemas/examples/icom-bc-*.json`. Vectors:
`schemas/vectors/icom-sig-v1.json`.
