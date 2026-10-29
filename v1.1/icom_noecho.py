#!/usr/bin/env python3
"""ICOM rule 18 NO-ECHO reference (engine 1.2.0).

Quiet verbs are never answered with quiet verbs. Relays suppress a repeat
quiet verb from the same sender on the same item inside a window. Backlogs
collapse before replay. DONE counts are unique (item, sender, state).

Copyright (c) 2026 Robert Stanley / Iron Noodle Technologies. MIT License.

No network, no model calls. Python 3 standard library only.
"""
import os
from collections import defaultdict

ENGINE_VERSION = "1.2.0"
QUIET = frozenset({"DONE", "FYI", "ACK", "REC"})
ACTION = frozenset({"GO", "HOLD", "ASK", "BLOCKED", "NAK"})
FLAG_VERB = "FLAG"        # loop flag: not quiet, never suppressed
WINDOW_S = 21600          # 6h reference default
LOOP_N = 50
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
    if is_action(new_verb) or new_verb == FLAG_VERB:
        return True
    if new_verb == "DONE" and new_state_change:
        return True
    return False


def relay_key(msg):
    return (msg["sender"], msg["item"], msg["verb"])


def _park(path):
    """Set a corrupt state file aside. Never delete it."""
    dest, n = path + ".old", 1
    while os.path.exists(dest):
        dest = "%s.old.%d" % (path, n)
        n += 1
    os.replace(path, dest)
    return dest


class Relay:
    """In-window suppress of repeat quiet verbs, keyed on (sender, item, verb).

    The window is fixed from the first relayed line: a suppress does not
    slide or extend it. Echo-check errors fail open (deliver + log).
    """

    def __init__(self, window_s=WINDOW_S, state_path=None):
        self.window_s = window_s
        self.state_path = state_path
        self.last = {}          # key -> timestamp of first relay in window
        self.log = []           # disposition records (never silent)
        if state_path:
            self.load_state(state_path)

    def load_state(self, path):
        """Load {key: ts}. Corrupt files are parked, never deleted."""
        if not path or not os.path.exists(path):
            self.last = {}
            return
        try:
            import json
            raw = json.load(open(path))
            if not isinstance(raw, dict):
                raise ValueError("state is not an object")
            self.last = {tuple(k.split("|")) if isinstance(k, str) else tuple(k): int(v)
                         for k, v in raw.items()}
        except Exception as e:
            parked = _park(path)
            self.last = {}
            self.log.append({
                "disposition": "fail-open", "why": "state-corrupt",
                "parked": parked, "err": str(e)[:80],
            })

    def handle(self, msg, now):
        """Return {disposition, deliver_to, record}.

        disposition: 'relay' | 'suppress' | 'pass' | 'fail-open'
        Action verbs and FLAG always pass. First quiet verb in the window
        is relayed. A suppressed quiet verb is delivered only to LEAD or
        OWNER already in the addressed recipients. Echo errors fail open.
        """
        try:
            return self._handle(msg, now)
        except Exception as e:
            to = list((msg or {}).get("to") or [])
            rec = {
                "ts": now, "sender": (msg or {}).get("sender"),
                "item": (msg or {}).get("item"), "verb": (msg or {}).get("verb"),
                "id": (msg or {}).get("id"), "disposition": "fail-open",
                "why": "echo-error", "err": str(e)[:80],
            }
            self.log.append(rec)
            return {"disposition": "fail-open", "deliver_to": to, "record": rec}

    def _handle(self, msg, now):
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
            # no-slide: do not write last[key] on suppress
            keep = [a for a in to if a in LEAD_LANES]
            return {"disposition": "suppress", "deliver_to": keep, "record": rec}

        self.last[key] = now
        rec["disposition"] = "relay"
        self.log.append(rec)
        return {"disposition": "relay", "deliver_to": to, "record": rec}


def collapse_backlog(msgs, resume_ts=None):
    """Keep the first quiet line per (from, ticket, verb); drop later echoes.

    Action lines pass through. The kept quiet line notes collapsed_n and
    is never answered (no_reply). Quiet lines older than resume_ts are stale.
    """
    first = {}              # (sender, item, verb) -> (index, copy)
    counts = defaultdict(int)
    passthrough = []        # (index, msg) for non-quiet
    for i, m in enumerate(msgs):
        if is_quiet(m["verb"]):
            key = (m["sender"], m["item"], m["verb"])
            counts[key] += 1
            if key not in first:
                q = dict(m)
                q["no_reply"] = True
                if resume_ts is not None and q.get("ts", 0) < resume_ts:
                    q["stale"] = True
                first[key] = (i, q)
        else:
            passthrough.append((i, m))
    for key, (i, q) in first.items():
        q["collapsed_n"] = counts[key]
    kept = passthrough + list(first.values())
    kept.sort(key=lambda r: r[0])
    return [m for _, m in kept]


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


def quiet_count(msgs, item, now, window_s=LOOP_S):
    n = 0
    for m in msgs:
        if m.get("item") != item or not is_quiet(m.get("verb")):
            continue
        if now - m.get("ts", 0) <= window_s:
            n += 1
    return n


def loop_flag_line(item, count, version="1.6.0"):
    """Non-quiet FLAG to LEAD,OWNER. Never itself a quiet/suppressible verb."""
    return "@ICOM>ICOM>LEAD,OWNER P1 INT0 %s FLAG echo.loop why=echo n=%d cb=%s" % (
        item, count, version)


class LoopWatch:
    """Emit at most one FLAG per ticket per loop window."""

    def __init__(self, n=LOOP_N, window_s=LOOP_S):
        self.n, self.window_s = n, window_s
        self.flagged = {}       # item -> ts of last FLAG

    def consider(self, msgs, now):
        out = []
        for item in loop_items(msgs, now, self.n, self.window_s):
            prev = self.flagged.get(item)
            if prev is not None and now - prev < self.window_s:
                continue
            self.flagged[item] = now
            out.append(loop_flag_line(item, quiet_count(msgs, item, now, self.window_s)))
        return out
