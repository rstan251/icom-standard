# Contributing to ICOM

Contributions are welcome.

- **Questions, bugs, ideas:** open an issue.
- **Changes:** open a pull request against `main` with a short description of why.
- **New codes** (agents, objects, fields, verbs): propose them in an issue or PR with
  - the proposed code (≤6 chars; UPPER for agents/lanes/verbs, lower.dot for objects; company full codes are `L-ST-XXXX`),
  - its meaning,
  - at least one example message using it.
- The codebook is append-only: bump the semver, tombstone retired codes, never reuse one.
- Keep ICOM messages one line (header + key=val tokens). No secrets, tokens or keys in examples.
