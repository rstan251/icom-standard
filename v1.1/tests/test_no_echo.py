#!/usr/bin/env python3
"""Rule 18 NO-ECHO vectors. Run: python3 tests/test_no_echo.py
Copyright (c) 2026 Robert Stanley / Iron Noodle Technologies."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import icom_noecho as N

T = "#iro-0a1b2c3d"
T2 = "#iro-aabbccdd"
results = []

def case(name):
    def deco(fn):
        try: fn(); results.append((name, True, ""))
        except AssertionError as e: results.append((name, False, str(e)))
        except Exception as e: results.append((name, False, "%s: %s" % (type(e).__name__, e)))
        return fn
    return deco

def M(sender, verb, item=T, to=None, ts=0, mid=None, state=None, obj="ops.qc"):
    d = {"sender": sender, "verb": verb, "item": item, "to": to or ["QA"],
         "ts": ts, "id": mid or ("%s-%s-%s" % (sender, verb, ts)), "object": obj}
    if state is not None:
        d["state"] = state
    return d

# --- 18.1 sender ---
@case("sender-quiet-then-action-ok")
def _():
    assert N.sender_ok("DONE", "ASK")
    assert N.sender_ok("DONE", "GO")
    assert N.sender_ok("ACK", "BLOCKED")
    assert N.sender_ok("FYI", "NAK")
    assert N.sender_ok("REC", "HOLD")

@case("sender-quiet-then-quiet-forbidden")
def _():
    for prev in N.QUIET:
        for nxt in N.QUIET:
            assert not N.sender_ok(prev, nxt), "%s -> %s" % (prev, nxt)

@case("sender-done-again-only-on-state-change")
def _():
    assert not N.sender_ok("DONE", "DONE")
    assert N.sender_ok("DONE", "DONE", new_state_change=True)

@case("sender-action-then-quiet-ok")
def _():
    assert N.sender_ok("GO", "DONE")
    assert N.sender_ok("ASK", "ACK")
    assert N.sender_ok(None, "DONE")
    assert N.sender_ok("GO", "FYI")

# --- 18.2 relay ---
@case("relay-first-done-fans-out")
def _():
    r = N.Relay()
    out = r.handle(M("DEV", "DONE", to=["QA", "OPS"], ts=0, mid="m1"), 0)
    assert out["disposition"] == "relay"
    assert out["deliver_to"] == ["QA", "OPS"]
    assert r.log[-1]["disposition"] == "relay"

@case("relay-repeat-done-suppressed")
def _():
    r = N.Relay()
    r.handle(M("DEV", "DONE", to=["QA"], ts=0, mid="m1"), 0)
    out = r.handle(M("DEV", "DONE", to=["QA"], ts=60, mid="m2"), 60)
    assert out["disposition"] == "suppress", out
    assert set(out["deliver_to"]) == {"LEAD", "OWNER"}
    assert "QA" not in out["deliver_to"]
    rec = r.log[-1]
    assert rec["disposition"] == "suppressed" and rec["why"] == "echo"
    assert rec["key"] == "DEV:%s:DONE" % T
    assert rec["id"] == "m2"          # keyed on sender/item/verb, not id

@case("relay-other-sender-done-relays")
def _():
    r = N.Relay()
    r.handle(M("DEV", "DONE", to=["QA"], ts=0), 0)
    out = r.handle(M("QA", "DONE", to=["DEV"], ts=10), 10)
    assert out["disposition"] == "relay"

@case("relay-action-never-suppressed")
def _():
    r = N.Relay()
    r.handle(M("DEV", "GO", to=["QA"], ts=0), 0)
    out = r.handle(M("DEV", "GO", to=["QA"], ts=10), 10)
    assert out["disposition"] == "pass"
    assert out["deliver_to"] == ["QA"]

@case("relay-window-expiry-relays-again")
def _():
    r = N.Relay()
    r.handle(M("DEV", "DONE", to=["QA"], ts=0), 0)
    out = r.handle(M("DEV", "DONE", to=["QA"], ts=N.WINDOW_S), N.WINDOW_S)
    assert out["disposition"] == "relay"

@case("relay-ack-repeat-same-sender-suppressed")
def _():
    r = N.Relay()
    r.handle(M("QA", "ACK", to=["DEV"], ts=0), 0)
    out = r.handle(M("QA", "ACK", to=["DEV"], ts=5), 5)
    assert out["disposition"] == "suppress"

# --- loop scenario from SPEC.md ---
@case("loop-vector-expected-suppress")
def _():
    """t0 DONE DEV; t1 ACK QA; t2 ACK DEV; t3 DONE QA; t4 DONE DEV -> t4 suppress."""
    r = N.Relay()
    seq = [
        (0, M("DEV", "DONE", to=["QA"], ts=0, mid="id-0")),
        (1, M("QA", "ACK", to=["DEV"], ts=1, mid="id-1")),
        (2, M("DEV", "ACK", to=["QA"], ts=2, mid="id-2")),
        (3, M("QA", "DONE", to=["DEV"], ts=3, mid="id-3")),
        (4, M("DEV", "DONE", to=["QA"], ts=4, mid="id-4")),
    ]
    got = []
    for ts, m in seq:
        assert not N.sender_ok(seq[ts - 1][1]["verb"], m["verb"]) if ts else True
        got.append(r.handle(m, ts)["disposition"])
    assert got == ["relay", "relay", "relay", "relay", "suppress"], got
    assert r.log[-1]["why"] == "echo"
    assert set(r.handle(M("DEV", "DONE", to=["QA"], ts=4, mid="id-4"), 4)["deliver_to"]) <= {"LEAD", "OWNER"}
    # a later action verb on the same item is not touched
    act = r.handle(M("QA", "ASK", to=["DEV"], ts=5, mid="id-5"), 5)
    assert act["disposition"] == "pass"

@case("loop-sender-forbids-quiet-reply")
def _():
    assert not N.sender_ok("DONE", "ACK")
    assert not N.sender_ok("ACK", "ACK")
    assert not N.sender_ok("ACK", "DONE")
    assert not N.sender_ok("DONE", "DONE")
    assert N.sender_ok("DONE", "ASK")

# --- 18.3 backlog ---
@case("backlog-collapses-quiet-per-item")
def _():
    msgs = [
        M("DEV", "DONE", ts=1, mid="a"),
        M("QA", "ACK", ts=2, mid="b"),
        M("DEV", "ACK", ts=3, mid="c"),
        M("QA", "DONE", ts=4, mid="d"),
        M("DEV", "DONE", ts=5, mid="e"),
    ]
    out = N.collapse_backlog(msgs, resume_ts=10)
    quiets = [m for m in out if N.is_quiet(m["verb"])]
    assert len(quiets) == 1
    assert quiets[0]["ts"] == 5 and quiets[0]["no_reply"] is True
    assert quiets[0]["collapsed_n"] == 5

@case("backlog-keeps-action-stale-quiet")
def _():
    msgs = [
        M("LEAD", "GO", ts=1, mid="g"),
        M("DEV", "DONE", ts=2, mid="d1"),
        M("DEV", "DONE", ts=3, mid="d2"),
    ]
    out = N.collapse_backlog(msgs, resume_ts=100)
    verbs = [m["verb"] for m in out]
    assert verbs == ["GO", "DONE"]
    quiet = [m for m in out if m["verb"] == "DONE"][0]
    assert quiet["no_reply"] is True and quiet.get("stale") is True
    assert quiet["ts"] == 3

@case("backlog-two-items-collapse-separately")
def _():
    msgs = [
        M("DEV", "DONE", item=T, ts=1),
        M("DEV", "DONE", item=T, ts=2),
        M("QA", "FYI", item=T2, ts=1),
        M("QA", "FYI", item=T2, ts=3),
    ]
    out = N.collapse_backlog(msgs)
    assert len(out) == 2
    by = {m["item"]: m for m in out}
    assert by[T]["ts"] == 2 and by[T2]["ts"] == 3
    assert by[T]["no_reply"] and by[T2]["no_reply"]

# --- 18.4 metrics ---
@case("metrics-raw-done-lines-are-not-progress")
def _():
    msgs = [M("DEV", "DONE", ts=i, mid="m%d" % i, state="fixed") for i in range(20)]
    assert N.progress_count(msgs) == 1
    assert N.unique_completions(msgs) == {(T, "DEV", "fixed")}

@case("metrics-unique-item-sender-state")
def _():
    msgs = [
        M("DEV", "DONE", state="fixed", ts=1),
        M("DEV", "DONE", state="fixed", ts=2),
        M("QA", "DONE", state="fixed", ts=3),
        M("DEV", "DONE", state="reopened", ts=4),
        M("DEV", "FYI", ts=5),
    ]
    assert N.progress_count(msgs) == 3
    assert (T, "DEV", "fixed") in N.unique_completions(msgs)
    assert (T, "QA", "fixed") in N.unique_completions(msgs)
    assert (T, "DEV", "reopened") in N.unique_completions(msgs)

@case("metrics-sor-state-wins-over-missing")
def _():
    # no explicit state -> object is the proxy
    msgs = [M("DEV", "DONE", obj="ops.qc", ts=1), M("DEV", "DONE", obj="ops.qc", ts=2)]
    assert N.progress_count(msgs) == 1
    assert N.completion_state(M("DEV", "DONE", state="done", obj="ops.qc")) == "done"

@case("metrics-loop-flag-over-12-in-24h")
def _():
    msgs = [M("DEV", "DONE", ts=i * 60, mid="x%d" % i) for i in range(13)]
    flagged = N.loop_items(msgs, now=13 * 60)
    assert flagged == [T]
    line = N.loop_flag_line(T, 13)
    assert line.startswith("@ICOM>ICOM>LEAD P1 INT0 %s FYI echo.loop why=echo n=13" % T)

@case("metrics-loop-flag-12-is-not-a-loop")
def _():
    msgs = [M("DEV", "ACK", ts=i, mid="y%d" % i) for i in range(12)]
    assert N.loop_items(msgs, now=12) == []

@case("metrics-loop-ignores-old-quiet")
def _():
    msgs = [M("DEV", "DONE", ts=0, mid="old")] + [M("DEV", "DONE", ts=N.LOOP_S + 10 + i, mid="n%d" % i) for i in range(3)]
    assert N.loop_items(msgs, now=N.LOOP_S + 20) == []

@case("metrics-action-verbs-do-not-trip-loop")
def _():
    msgs = [M("LEAD", "GO", ts=i, mid="g%d" % i) for i in range(20)]
    assert N.loop_items(msgs, now=20) == []

if __name__ == "__main__":
    fails = [r for r in results if not r[1]]
    for n, g, m in results: print(("PASS " if g else "FAIL ") + n + ("" if g else "  " + m))
    print("TOTAL %d PASS %d FAIL %d" % (len(results), len(results) - len(fails), len(fails)))
    sys.exit(1 if fails else 0)
