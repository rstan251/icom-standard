# ICOM over BitChat — payload spec

Status: Draft, 2026-10-25. Complements ICOM v1 / v1.1.
By Robert Stanley / Iron Noodle Technologies. MIT License.

This document says how **one ICOM message line** is carried as a BitChat
payload (mesh / Bluetooth chat). BitChat is the carrier. ICOM is the
content. The carrier does not rewrite the line.

Ticket: PLT-21. Examples use placeholder lanes (`CL01`, `INT0`) and
placeholder agent codes from `codebook.yaml`. Signature material below
is notional; do not treat it as a key.

## 1. Purpose

Agents already speak one line:

```
@FROM>ICOM>TO P0-3 LANE #ticket VERB object key=val ...
```

A mesh / BLE chat hop is useful when the usual hub path is down, or when
two agents share a radio and need the same line without a network. This
spec defines:

1. The ICOM line that goes in the payload (header, ICX object, tokens).
2. Signed-identity tokens (`sts`, `nc`, `sig` / `hsig`) and how they are
   checked.
3. UTF-8 encoding, a size budget for small BLE writes, and a compact
   frame with optional ICOM-level fragmentation.
4. Validation order and NAK codes.

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
  cover the line bytes.

## 3. ICOM line

### 3.1 Header

Canonical v1 / v1.1 line (one line, no CR/LF, no prose):

```
@FROM>ICOM>TO[,TO] Pn LANE #ticket VERB [ACTION] object *(SP key=val)
```

| Slot | Rule |
|---|---|
| `FROM` / `TO` | Codebook agent codes. Multiple recipients: `>TO1,TO2`. `ALL` is broadcast. |
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
| `sts` | Signed time, unix seconds, decimal, 10 digits. |
| `nc` | Nonce: 12 fresh random bytes, base64url without padding (16 chars). |

**Wire tokens.** A signed agent line appends three tokens, in this
order, `sig` always last:

```
sts=<unix10> nc=<nonce16> sig=ed25519:<kid>:<b64url-86>
```

Token names are `sts` / `nc` / `sig` on purpose: `ts` is reserved for a
relay timestamp, and `n` already means count.

A hub-signed line (relayed or NAK) may instead end with:

```
hsig=ed25519:<hub-kid>:<b64url-86>
```

A line has at most one `sig=` and at most one `hsig=`. `sig=` / `hsig=`
MUST be the last token. Signing never inserts CR/LF.

**Canonical bytes** (what is signed / verified), taken from the line
exactly as received:

1. Bytes MUST be valid UTF-8 and MUST NOT contain CR or LF; else
   `sig-bad` with `det=enc` (or `multiline` if a second line is present).
   No Unicode normalization; bytes are signed as sent.
2. Strip leading and trailing ASCII space and tab. Split on runs of
   ASCII space/tab.
3. Require exactly one `sig=` (agent) or exactly one `hsig=` (hub),
   exactly one `sts=`, exactly one `nc=`. Duplicates → `sig-bad`
   `det=dup`.
4. Drop every token whose key is `sig` or `hsig`. Keep the rest in
   order, including `sts=` and `nc=`.
5. Join with a single `0x20`. Then
   `M = domain || 0x00 || UTF-8(joined)`.

Domain string is `icom-sig-v1` for an agent signature and
`icom-hsig-v1` for a hub signature (so one cannot be replayed as the
other).

**Verify order** (first failure wins):

1. Existing line checks: `empty`, `multiline`, `no-header`.
2. No `sig=` when the receiver is enforcing agent signatures →
   `sig-missing`.
3. Malformed `sig` / `sts` / `nc` (wrong alg, length, or base64url) →
   `sig-bad` `det=fmt` (or `dup` / `enc`).
4. `kid` not in the registry → `sig-kid-unknown`.
5. `kid` revoked; or retired with `sts` after `not_after`; or `sts`
   before `not_before` → `sig-revoked`.
6. Registry agent for that `kid` ≠ header `FROM` → `sig-from-mismatch`.
7. Ed25519 verify of `M` fails → `sig-bad` `det=verify`.
8. `|ref_time - sts| > W` → `sig-stale`. `W = 120` seconds.
   `ref_time` is the carrier timestamp when the hop provides one,
   otherwise the receiver clock.
9. Pair `(kid, nc)` already seen → `sig-replay`. Insert only after
   steps 2–8 pass.

Nonce-cache entries expire at `sts + W`. A full cache fails closed:
`sig-replay` with `det=cache-full`. Lines delayed past `W` MUST be
re-signed. Receivers MAY run `off` (tokens pass through), `observe`
(verify and log only), or `enforce` (NAK and do not relay).

**Registry (public data).** One `kid` binds to exactly one agent. An
agent may have up to two `active` kids during rotation. Status is
`active` (sign and verify), `retired` (verify only while
`sts <= not_after`), or `revoked` (never verifies). Private keys never
appear in a line, a log, a ticket, or this spec.

A BitChat hop is a **carrier**, not a hub. Mesh senders keep `sig` /
`sts` / `nc` on the line. Mesh receivers that hold the registry SHOULD
verify when present; they MUST NOT strip those tokens. If a hub later
ingests the line, the hub verifies, then MAY drop the agent signature
and attach `hsig=` on the copy it emits.

## 4. Encoding and size budget

- Character set: UTF-8. No BOM. No CR (`0x0D`) or LF (`0x0A`) inside a
  frame.
- The ICOM line is the UTF-8 encoding of the header in section 3.
- Unsigned identity tokens add about 120 octets (`sts` + `nc` + `sig`).
  A typical signed line is a few hundred octets and fits in one write.

| Name | Octets | Why |
|---|---|---|
| `SOFT_BUDGET` | 400 | Stay inside a common BLE write after a mesh envelope (ATT MTU up to 512; many stacks split near ~469). |
| `HARD_CHUNK` | 2048 | Max ICOM-BC fragment chunk. |
| `MAX_LINE` | 4096 | Max reassembled ICOM line. Oversize → `bc-oversize`. |
| `MAX_FRAGS` | 16 | More → `bc-oversize`. |
| `FRAG_TTL` | 30 s | Incomplete fragment set → `bc-frag-timeout`. |

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
single      = %s"IC1" SP %s"S" SP icom-line
fragment    = %s"IC1" SP %s"F" SP msgid SP index "/" total SP chunk

msgid       = 8HEXDIG
index       = 1*2DIGIT          ; 1-based
total       = 1*2DIGIT          ; 1..16
chunk       = 1*VCHAR           ; UTF-8, no CR / LF

icom-line   = "@" agent %s">ICOM>" recips SP pri SP lane SP ticket
              SP verb [SP verb] SP icx-code *(SP kv) [SP sig-tail]

recips      = agent *("," agent)
agent       = 2*8UPALPHA        ; codebook.agents
pri         = %s"P0" / %s"P1" / %s"P2" / %s"P3"
lane        = 2*8(ALPHA / DIGIT)
ticket      = "#" 1*(ALPHA / DIGIT / "-" / "_" / ".")
verb        = %s"GO" / %s"HOLD" / %s"DONE" / %s"BLOCKED"
              / %s"REC" / %s"FYI" / %s"ASK" / %s"ACK" / %s"NAK"
icx-code    = 1*lcalpha *("." 1*lcalpha / "~" 1*lcalpha)
kv          = key "=" kv-val
key         = 1*(lcalpha / DIGIT / "-" / "_")
kv-val      = 1*unquoted / DQUOTE *(%x20-21 / %x23-7E) DQUOTE
unquoted    = %x21-7E           ; printable, including "|"; no SP
sig-tail    = %s"sts=" 10DIGIT SP %s"nc=" nonce16 SP sig-tok
nonce16     = 16(ALPHA / DIGIT / "-" / "_")
sig-tok     = (%s"sig" / %s"hsig") "=" %s"ed25519:" kid ":" sigb64
kid         = 12HEXDIG
sigb64      = 86(ALPHA / DIGIT / "-" / "_")

lcalpha     = %x61-7A
UPALPHA     = %x41-5A
```

`msgid` is the first 8 lowercase hex digits of `SHA-256(UTF-8 ICOM
line)`. It only correlates fragments. It is not a secret.

Logical JSON (same meaning as the text frame; schema at
`schemas/icom-bc-frame.schema.json`):

```
{ "v": 1, "kind": "single", "line": "<icom-line>" }
{ "v": 1, "kind": "fragment", "msgid": "<8hex>", "index": 1, "total": 2, "chunk": "..." }
```

Wire mapping:

- single → `IC1 S ` + `line`
- fragment → `IC1 F ` + `msgid` + ` ` + `index` + `/` + `total` + ` ` + `chunk`

### 5.2 Optional binary prefix

Implementations that put ICOM in a typed binary payload MAY use:

```
magic[3] = "IC1"
ver_u8   = 1
flags_u8 = bit0 fragment; bit1 last-fragment
if fragment: msgid_u32be, index_u8 (0-based), total_u8, then chunk
else: UTF-8 icom-line
```

Text (`IC1 S` / `IC1 F`) remains the interoperable BitChat body. A
receiver that sees `IC1` as the first three bytes and the fourth byte
is not `0x20` MAY try the binary form; otherwise it parses text.

## 6. Validation and NAK codes

Receivers parse the BitChat body as ICOM-BC, reassemble if needed, then
apply ICOM and signature checks. First failure wins. A NAK is itself an
ICOM line (hub or peer), never an echo of `sig`, `nc`, or key material:

```
@ICOM>ICOM>FROM P2 INT0 #ticket NAK org.proto why=<code> [det=<token>]
```

If the inbound line had no usable ticket, the NAK ticket is `#icom-nak`.

### 6.1 Frame codes

| Code | When |
|---|---|
| `bc-bad-frame` | Body does not match `single` / `fragment`, or `index`/`total` out of range. |
| `bc-bad-utf8` | Reassembled bytes are not UTF-8. |
| `bc-oversize` | Chunk, fragment count, or reassembled line exceeds the budget. |
| `bc-frag-timeout` | `FRAG_TTL` expired with a missing index. |
| `bc-msgid-mismatch` | Reassembled line hashes to a different `msgid`. |

### 6.2 ICOM codes

`empty`, `multiline`, `no-header`, `bad-route`, `bad-agent`, `bad-pri`,
`bad-lane`, `bad-ticket`, `bad-verb`, `bad-icx`, `prose`, `email`,
`unk-shortcut`, `cb-required`, `cb-mismatch`, `p0-misuse`. Relays may
add lowercase hyphenated codes. Hyphen is canonical; `_` is accepted as
`-`.

### 6.3 Signature codes

| Code | Typical `det` |
|---|---|
| `sig-missing` | (none) |
| `sig-bad` | `fmt` / `dup` / `enc` / `verify` |
| `sig-kid-unknown` | the unknown `kid` |
| `sig-revoked` | `revoked` / `retired` / `early` |
| `sig-from-mismatch` | the `kid` |
| `sig-stale` | `skew` |
| `sig-replay` | (none) or `cache-full` |

`det` is only one of the values above, or a `kid`. A bad hub signature
on a delivered line is reported as `hsig-bad` (flag, not a relay NAK).

## 7. Worked examples

Placeholders: lane `CL01` / `INT0`; agents `LEAD`, `CTO`, `QC`, `ICOM`;
`kid` `0123456789ab`; nonce sixteen `A`s; `sts` `1792954800`
(2026-10-25T19:00:00Z). `<b64url-86>` stands for an 86-character
base64url signature and is **not** a real signature.

### 7.1 Single-frame FYI (unsigned)

ICOM line:

```
@LEAD>ICOM>CTO P2 CL01 #T-1234 FYI org.proto n=1
```

Wire:

```
IC1 S @LEAD>ICOM>CTO P2 CL01 #T-1234 FYI org.proto n=1
```

Logical:

```json
{"v":1,"kind":"single","line":"@LEAD>ICOM>CTO P2 CL01 #T-1234 FYI org.proto n=1"}
```

Fits in `SOFT_BUDGET`. Receiver: parse frame → one line → header OK →
in `enforce` mode, `sig-missing`.

### 7.2 Single-frame signed GO

ICOM line (wrapped for the page; on the wire it is one line):

```
@LEAD>ICOM>CTO P1 INT0 #T-1234 GO ops.deploy nx=CTO:review sts=1792954800 nc=AAAAAAAAAAAAAAAA sig=ed25519:0123456789ab:<b64url-86>
```

Wire:

```
IC1 S @LEAD>ICOM>CTO P1 INT0 #T-1234 GO ops.deploy nx=CTO:review sts=1792954800 nc=AAAAAAAAAAAAAAAA sig=ed25519:0123456789ab:<b64url-86>
```

Canonical join (signature dropped, single spaces):

```
@LEAD>ICOM>CTO P1 INT0 #T-1234 GO ops.deploy nx=CTO:review sts=1792954800 nc=AAAAAAAAAAAAAAAA
```

`M = "icom-sig-v1" || 0x00 || UTF-8(that string)`. `kid` MUST equal
`SHA-256(pub)[:12]` and MUST belong to `LEAD`. `|ref_time - 1792954800|`
MUST be ≤ 120.

### 7.3 Fragmented ASK, then a stale-sig NAK

Long lines (many `key=val` tokens, or a quoted `ask=`) can exceed the
local write budget. Two fragments of one line; `msgid` is shown as
`deadbeef` (illustrative, not a real digest):

```
IC1 F deadbeef 1/2 @QC>ICOM>LEAD P1 CL01 #T-5678 ASK qa.review ask=APPROVE|HOLD why=tests,lint
IC1 F deadbeef 2/2  n=3 sts=1792954800 nc=AAAAAAAAAAAAAAAA sig=ed25519:0123456789ab:<b64url-86>
```

Reassembly is the concatenation of the two chunks (note the leading
space on chunk 2, which restores the `key=val` separator). If
`ref_time` is 121 seconds or more away from `sts`, the receiver does
not accept the line and returns:

```
@ICOM>ICOM>QC P2 INT0 #T-5678 NAK org.proto why=sig-stale det=skew
```

That NAK MAY itself travel as `IC1 S @ICOM>ICOM>QC ...`. It MUST NOT
repeat the rejected signature or nonce.

## 8. Conformance

A producer is conformant if it emits only `ICOM-BC/1` frames, keeps
each ICOM line to one UTF-8 line, places `sig=` last when signing, and
fragments only when the single frame would exceed the budget.

A consumer is conformant if it implements section 6 in order, ignores
unknown future `key=val` tokens, and never logs `sig`, `nc`, or key
bytes (kid only).

JSON Schema for the logical frame: `schemas/icom-bc-frame.schema.json`.
Examples: `schemas/examples/icom-bc-*.json`.
