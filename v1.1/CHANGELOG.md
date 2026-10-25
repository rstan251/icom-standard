# Changelog

## 1.2.0
- Ticket prefix is codebook `ticket_prefix` (default `tkt-`), validated as lowercase `[a-z][a-z0-9]{1,7}-`.
- **Breaking (default):** full tickets that use a previous deployment prefix NAK unless `ticket_prefix` is set to that prefix. Bare `#` plus 8 hex now normalizes to `#tkt-`.
- Migration: set `ticket_prefix` to the prefix you used before; re-pin `--expect-sha12`. Re-bind `--state` threads after a prefix change (stored tickets are not rewritten).
- Scrub check: case-insensitive short-id shapes (2–12 letters; `-`, `_`, or no separator). Allow only the public placeholders `tkt-0a1b2c3d` and `tkt-xxxxxxxx`. All-digit tails (`rel`/`inv` style) are ignored. Default scan root is this directory (`v1.1/`), not the repo root.

## 1.1.0
- Initial v1.1 expander: implied header, phrase shortcuts, codebook pin, autoNAK.
