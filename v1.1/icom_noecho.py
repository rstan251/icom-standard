#!/usr/bin/env python3
"""ICOM rule 18 NO-ECHO reference (engine 1.2.0).

Quiet verbs are never answered with quiet verbs. Relays suppress a repeat
quiet verb from the same sender on the same full ticket with the same
normalized body inside a window. Backlogs collapse per ticket and reset
on a non-quiet verb. DONE counts are unique (item, sender, state).

Copyright (c) 2026 Robert Stanley / Iron Noodle Technologies. MIT License.

No network, no model calls. Python 3 standard library only.
"""
import hashlib, os, re
from collections import defaultdict

ENGINE_VERSION = "1.2.0"
QUIET = frozenset({"DONE", "FYI", "ACK", "REC"})
ACTION = frozenset({"GO", "HOLD", "ASK", "BLOCKED", "NAK", "DECIDE"})
# Non-quiet verbs that reset the suppress window and the backlog group.
# HOLD is included when present in the codebook (it is, in the public one).
RESET = frozenset({"GO", "ASK", "DECIDE", "BLOCKED", "NAK", "HOLD"})
FLAG_VERB = "FLAG"        # loop flag: not quiet, never suppressed, does not reset
WINDOW_S = 21600          # 6h reference default
LOOP_N = 50
LOOP_S = 86400            # 24h
LEAD_LANES = frozenset({"LEAD", "OWNER"})
LAST4 = re.compile(r"^[0-9a-f]{4}#[0-9]{1,6}$")
TAG = re.compile(r"^\^[a-z0-9]{4,8}$")
SKIP_BODY = frozenset({
    "sender", "from", "item", "ticket", "verb", "to", "ts", "id",
    "object", "action", "state", "no_reply", "collapsed_n", "stale", "kv",
})


def is_quiet(verb):
    return verb in QUIET


def is_action(verb):
    return verb in ACTION


def is_reset(verb, codebook_verbs=None):
    """True if verb clears the suppress window and backlog group on its ticket."""
    if verb == "HOLD":
        if codebook_verbs is None:
            return True
        return "HOLD" in codebook_verbs
    return verb in RESET


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


def resolve_ticket(item, bound=None):
    """Full ticket id, or None for an unscoped last4/tag that cannot be resolved.

    Suppress keys use only a resolved full id. last4 (`abcd#1`) and `^tag`
    never key a suppress unless the caller supplies a binding to a full id.
    """
    if not item:
        return None
    if LAST4.match(str(item)) or TAG.match(str(item)):
        return (bound or {}).get(item)
    return item


def normalize_body(msg):
    """verb + optional REC action + object + sorted key=val tokens."""
    verb = str(msg.get("verb") or "")
    action = str(msg.get("action") or "")
    obj = str(msg.get("object") or "")
    kv = dict(msg.get("kv") or {})
    for k, v in msg.items():
        if k in SKIP_BODY:
            continue
        kv[k] = v
    tokens = ["%s=%s" % (k, kv[k]) for k in sorted(kv)]
    parts = [verb]
    if action:
        parts.append(action)
    parts.append(obj)
    parts.extend(tokens)
    return " ".join(parts)


def body_hash(msg):
    return hashlib.sha256(normalize_body(msg).encode("utf-8")).hexdigest()[:16]


def relay_key(msg, ticket=None):
    tk = ticket if ticket is not None else resolve_ticket(msg.get("item"))
    return (msg["sender"], tk, msg["verb"], body_hash(msg))


def _park(path):
    """Set a corrupt state file aside. Never delete it."""
    dest, n = path + ".old", 1
    while os.path.exists(dest):
        dest = "%s.old.%d" % (path, n)
        n += 1
    os.replace(path, dest)
    return dest


class Relay:
    """In-window suppress of repeat quiet verbs.

    Key: (from, full-ticket, verb, bodyhash). A suppress does not slide
    the window. A reset verb on the ticket clears the window. Echo-check
    errors and an unwritable state dir fail open (deliver + log, no persist).
    """

    def __init__(self, window_s=WINDOW_S, state_path=None, codebook_verbs=None):
        self.window_s = window_s
        self.state_path = state_path
        self.codebook_verbs = codebook_verbs
        self.last = {}          # key -> timestamp of first relay in window
        self.log = []           # disposition records (never silent)
        self.persist = True
        if state_path:
            self._startup_state(state_path)

    def _startup_state(self, path):
        """Load or create state. PermissionError -> fail open, no persist."""
        try:
            d = os.path.dirname(os.path.abspath(path))
            if d and not os.path.isdir(d):
                os.makedirs(d, mode=0o700)
            self.load_state(path)
        except PermissionError as e:
            self.persist = False
            self.last = {}
            self.log.append({
                "disposition": "fail-open", "why": "state-unwritable",
                "err": str(e)[:80],
            })

    def load_state(self, path):
        """Load {key: ts}. Corrupt files are parked, never deleted."""
        if not path or not os.path.exists(path):
            return
        try:
            import json
            raw = json.load(open(path))
            if not isinstance(raw, dict):
                raise ValueError("state is not an object")
            self.last = {tuple(k.split("|")) if isinstance(k, str) else tuple(k): int(v)
                         for k, v in raw.items()}
        except PermissionError as e:
            self.persist = False
            self.last = {}
            self.log.append({
                "disposition": "fail-open", "why": "state-unwritable",
                "err": str(e)[:80],
            })
        except Exception as e:
            parked = _park(path)
            self.last = {}
            self.log.append({
                "disposition": "fail-open", "why": "state-corrupt",
                "parked": parked, "err": str(e)[:80],
            })

    def handle(self, msg, now, bound=None):
        """Return {disposition, deliver_to, record}.

        disposition: 'relay' | 'suppress' | 'pass' | 'fail-open'
        Reset verbs and FLAG always pass. First quiet body in the window
        is relayed. A suppressed quiet verb is delivered only to LEAD or
        OWNER already in the addressed recipients. Echo errors fail open.
        Unresolved last4/tag: do not suppress.
        """
        try:
            return self._handle(msg, now, bound)
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

    def _reset_ticket(self, ticket):
        self.last = {k: v for k, v in self.last.items() if k[1] != ticket}

    def _handle(self, msg, now, bound=None):
        verb = msg["verb"]
        to = list(msg.get("to") or [])
        rec = {
            "ts": now, "sender": msg["sender"], "item": msg["item"],
            "verb": verb, "id": msg.get("id"),
        }
        ticket = resolve_ticket(msg.get("item"), bound)
        if is_reset(verb, self.codebook_verbs):
            if ticket:
                self._reset_ticket(ticket)
            rec["disposition"] = "pass"
            rec["reset"] = True
            self.log.append(rec)
            return {"disposition": "pass", "deliver_to": to, "record": rec}
        if not is_quiet(verb):
            rec["disposition"] = "pass"
            self.log.append(rec)
            return {"disposition": "pass", "deliver_to": to, "record": rec}

        if ticket is None:
            rec["disposition"] = "relay"
            rec["why"] = "unresolved-ticket"
            self.log.append(rec)
            return {"disposition": "relay", "deliver_to": to, "record": rec}

        key = relay_key(msg, ticket)
        rec["body"] = normalize_body(msg)
        rec["bhash"] = key[3]
        prev = self.last.get(key)
        if prev is not None and (now - prev) < self.window_s:
            rec["disposition"] = "suppressed"
            rec["why"] = "echo"
            rec["key"] = "%s:%s:%s:%s" % key
            self.log.append(rec)
            # no-slide: do not write last[key] on suppress
            keep = [a for a in to if a in LEAD_LANES]
            return {"disposition": "suppress", "deliver_to": keep, "record": rec}

        self.last[key] = now
        rec["disposition"] = "relay"
        rec["key"] = "%s:%s:%s:%s" % key
        self.log.append(rec)
        return {"disposition": "relay", "deliver_to": to, "record": rec}


def collapse_backlog(msgs, resume_ts=None, codebook_verbs=None):
    """Per ticket: keep the first quiet line; drop later quiets until a reset.

    A non-quiet reset verb (GO, ASK, DECIDE, BLOCKED, NAK, HOLD-if-coded)
    starts a new group. collapsed_n is the number of quiet lines dropped.
    The kept quiet line is never answered (no_reply).
    """
    groups = defaultdict(list)   # ticket -> [(index, msg)]
    order = []
    for i, m in enumerate(msgs):
        item = m["item"]
        if item not in order:
            order.append(item)
        groups[item].append((i, m))
    kept = []
    for item in order:
        first = None            # (index, copy) of first quiet in current group
        dropped = 0
        for i, m in groups[item]:
            if is_reset(m["verb"], codebook_verbs):
                if first is not None:
                    first[1]["collapsed_n"] = dropped
                    kept.append(first)
                    first, dropped = None, 0
                kept.append((i, m))
                continue
            if is_quiet(m["verb"]):
                if first is None:
                    q = dict(m)
                    q["no_reply"] = True
                    if resume_ts is not None and q.get("ts", 0) < resume_ts:
                        q["stale"] = True
                    first = (i, q)
                else:
                    dropped += 1
                continue
            kept.append((i, m))
        if first is not None:
            first[1]["collapsed_n"] = dropped
            kept.append(first)
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
