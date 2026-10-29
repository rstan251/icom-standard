#!/usr/bin/env python3
"""ICOM rule 18 NO-ECHO reference (engine 1.2.0).

Quiet verbs are never answered with quiet verbs. Relays suppress a repeat
quiet verb from the same sender on the same item inside a window. Backlogs
collapse before replay. DONE counts are unique (item, sender, state).

Copyright (c) 2026 Robert Stanley / Iron Noodle Technologies. MIT License.

No network, no model calls. Python 3 standard library only.
"""
from collections import defaultdict

ENGINE_VERSION = "1.2.0"
QUIET = frozenset({"DONE", "FYI", "ACK", "REC"})
ACTION = frozenset({"GO", "HOLD", "ASK", "BLOCKED", "NAK"})
WINDOW_S = 21600          # 6h reference default
LOOP_N = 12
LOOP_S = 86400            # 24h
LEAD_LANES = frozenset({"LEAD", "OWNER"})


def is_quiet(verb):
    return verb in QUIET


def is_action(verb):
    return verb in ACTION


def completion_state(msg):
    """SoR status if cited, else object (message-side proxy)."""
    return msg.get("state") or msg.get("object") or "-"


def sender_ok(prev_verb, new_verb, new_state_change=False):
    """True if sending new_verb after prev_verb on the same item is allowed.

    A quiet verb may not be answered with a quiet verb. A second DONE is
    allowed only when the system-of-record state actually changed.
    """
    if not prev_verb or not is_quiet(prev_verb):
        return True
    if is_action(new_verb):
        return True
    if new_verb == "DONE" and new_state_change:
        return True
    return False


def relay_key(msg):
    return (msg["sender"], msg["item"], msg["verb"])


class Relay:
    """In-window suppress of repeat quiet verbs, keyed on (sender, item, verb)."""

    def __init__(self, window_s=WINDOW_S):
        self.window_s = window_s
        self.last = {}          # key -> timestamp
        self.log = []           # disposition records (never silent)

    def handle(self, msg, now):
        """Return {disposition, deliver_to, record}.

        disposition: 'relay' | 'suppress' | 'pass'
        Action verbs always pass. First quiet verb in the window is relayed.
        A suppressed quiet verb still goes to LEAD and OWNER.
        """
        verb = msg["verb"]
        to = list(msg.get("to") or [])
        rec = {
            "ts": now, "sender": msg["sender"], "item": msg["item"],
            "verb": verb, "id": msg.get("id"),
        }
        if not is_quiet(verb):
            rec["disposition"] = "pass"
            self.log.append(rec)
            return {"disposition": "pass", "deliver_to": to, "record": rec}

        key = relay_key(msg)
        prev = self.last.get(key)
        if prev is not None and (now - prev) < self.window_s:
            rec["disposition"] = "suppressed"
            rec["why"] = "echo"
            rec["key"] = "%s:%s:%s" % key
            self.log.append(rec)
            lead = sorted((set(to) | LEAD_LANES) & LEAD_LANES)
            return {"disposition": "suppress", "deliver_to": lead, "record": rec}

        self.last[key] = now
        rec["disposition"] = "relay"
        self.log.append(rec)
        return {"disposition": "relay", "deliver_to": to, "record": rec}


def collapse_backlog(msgs, resume_ts=None):
    """After a pause or cap: one newest quiet line per item; keep action lines.

    Quiet lines older than resume_ts are stale: kept for context if newest,
    but marked no_reply so they are never answered.
    """
    by_item = defaultdict(list)
    order = []
    for i, m in enumerate(msgs):
        by_item[m["item"]].append((i, m))
        if m["item"] not in order:
            order.append(m["item"])
    out = []
    for item in order:
        rows = by_item[item]
        actions = [(i, m) for i, m in rows if is_action(m["verb"])]
        quiets = [(i, m) for i, m in rows if is_quiet(m["verb"])]
        other = [(i, m) for i, m in rows if not is_quiet(m["verb"]) and not is_action(m["verb"])]
        kept = actions + other
        if quiets:
            newest = max(quiets, key=lambda r: (r[1].get("ts", r[0]), r[0]))
            q = dict(newest[1])
            # Collapsed quiet lines are never answered (rule 18.3), including
            # those older than the resume instant.
            q["no_reply"] = True
            q["collapsed_n"] = len(quiets)
            if resume_ts is not None and q.get("ts", 0) < resume_ts:
                q["stale"] = True
            kept.append((newest[0], q))
        kept.sort(key=lambda r: r[0])
        out.extend(m for _, m in kept)
    return out


def unique_completions(msgs):
    """Distinct (item, sender, state) DONE completions. SoR `state` wins."""
    seen = set()
    for m in msgs:
        if m.get("verb") != "DONE":
            continue
        seen.add((m["item"], m["sender"], completion_state(m)))
    return seen


def progress_count(msgs):
    return len(unique_completions(msgs))


def loop_items(msgs, now, n=LOOP_N, window_s=LOOP_S):
    """Items with more than n quiet verbs inside the trailing window."""
    counts = defaultdict(int)
    for m in msgs:
        if not is_quiet(m.get("verb")):
            continue
        ts = m.get("ts", 0)
        if now - ts <= window_s:
            counts[m["item"]] += 1
    return sorted(item for item, c in counts.items() if c > n)


def loop_flag_line(item, count, version="1.6.0"):
    return "@ICOM>ICOM>LEAD P1 INT0 %s FYI echo.loop why=echo n=%d cb=%s" % (item, count, version)
