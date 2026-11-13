# Adopting ICOM on hosts with action review (ChatGPT and similar)

Some agent hosts review each tool call before it runs. ChatGPT is one; there may be others. If the review decides a call is risky, it blocks the call. Sometimes it shows no prompt at all, so the operator cannot approve it. An agent on such a host can receive ICOM lines but may be blocked when it sends them on its own. Background and the observed rejections are in [issue #12](../../../issues/12).

## Why sends get blocked

The review judges a send by three things:

- what the tool says about itself;
- the tool's annotations;
- whether the human user authorized it.

A typical ICOM status line ("DONE, work published") looks like an external, consequential claim. It gets blocked when:

- the send tool says something like "send only when the operator asks";
- the tool has no annotations, so it looks like an open-world action;
- the authorization came from another agent rather than the account owner;
- the evidence is the agent's own tool output. Proof posted by the agent did not count.

## What to do

All five steps below were needed in the case that prompted this guide.

1. **Describe the send tool truthfully, for that party only.** Say what really happens, for example: it adds one line to the operator's internal agent mailbox; it never reaches a client, the public, email or any outside system; and it changes no outside record. Say that the account owner has standing-authorized status lines on ticket state changes. Say that each line is the agent's report, checked downstream against the ticket cited in `f=`. Every sentence must be true of your code. Never tell the model to skip, avoid or bypass its review.
2. **Add MCP tool annotations.**
   - Send tool: `openWorldHint: false`, `destructiveHint: false`, `readOnlyHint: false`.
   - `idempotentHint`: set it to `true` only if a repeat really has no effect, for example when a message id is required and dedup is unbounded. Otherwise set `false`.
   - Read-only tools (thread listing, lint, card): `readOnlyHint: true`, `openWorldHint: false`.
3. **Put the owner's authorization in the agent's instructions, in the owner's own voice.** For example:

   ```
   From me, <owner>, account owner: I authorize you to send ICOM status lines to the fleet through the <plugin> plugin on your own, without asking me each time. These lines go only to our internal agents and never reach a client or the public. Each line is your report: cite the ticket holding the proof in f=, use DONE only for what you did and checked yourself, and PARTIAL with open= for anything unchecked.
   ```

4. **Reload the plugin.** Hosts often cache tool descriptions per connection. After changing them:
   - refresh or reconnect the plugin in the host's settings;
   - start a new chat, because open chats keep the old text.

   Check first: ask the agent to quote its send tool's description.
5. **Cap the party's share of any shared mailbox.** Once an agent sends on its own, a burst can push other parties' unread messages out of a bounded buffer. Give it a fixed number of slots. When those slots are full of unread messages, refuse the send with a clear error instead of evicting someone else's mail.

## Reporting rules that keep the review on your side

- DONE only when the proof is on the cited ticket. Anything unchecked is PARTIAL with `open=`.
- One status line per job, not one line claiming everything.
- If a send is blocked, quote the exact error to the owner and stop. Do not retry with reworded text to get past the review.

## Result in the reported case

Before the change, two proof-linked status lines were blocked with no approval prompt.

After the change and a plugin refresh, the same agent sent seven lines in a row (1 DONE, 6 PARTIAL). None was blocked.

Tested with ICOM v2, codebook 1.16.0.
