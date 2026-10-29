#!/usr/bin/env python3
"""Rule 18 NO-ECHO vectors. Run: python3 tests/test_no_echo.py
Copyright (c) 2026 Robert Stanley / Iron Noodle Technologies."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import icom_noecho as N
WORK = os.path.join(ROOT, ".work"); os.makedirs(WORK, mode=0o700, exist_ok=True)

T = "#iro-0a1b2c3d"
T2 = "#iro-aabb0002"
IRO_A = "#iro-1111b6dc"
IRO_B = "#iro-2222b6dc"
SHORT = "b6dc#3"
NONIRO = "#OPS-12"
results = []

def case(name):
    def deco(fn):
        try: fn(); results.append((name, True, ""))
        except AssertionError as e: results.append((name, False, str(e)))
        except Exception as e: results.append((name, False, "%s: %s" % (type(e).__name__, e)))
        return fn
    return deco

def M(sender, verb, item=T, to=None, ts=0, mid=None, state=None, obj="ops.qc",
      action=None, **kv):
    d = {"sender": sender, "verb": verb, "item": item, "to": to or ["QA"],
         "ts": ts, "id": mid or ("%s-%s-%s" % (sender, verb, ts)), "object": obj}
    if state is not None:
        d["state"] = state
    if action is not None:
        d["action"] = action
    d.update(kv)
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
    assert out["deliver_to"] == []          # QA is not LEAD/OWNER
    rec = r.log[-1]
    assert rec["disposition"] == "suppressed" and rec["why"] == "echo"
    assert rec["key"].startswith("DEV:%s:DONE:" % T)
    assert rec["id"] == "m2"          # keyed on sender/item/verb/body, not id

@case("relay-suppress-only-addressed-lead")
def _():
    r = N.Relay()
    r.handle(M("DEV", "DONE", to=["QA", "LEAD"], ts=0), 0)
    out = r.handle(M("DEV", "DONE", to=["QA", "LEAD"], ts=10), 10)
    assert out["disposition"] == "suppress"
    assert out["deliver_to"] == ["LEAD"]
    assert "QA" not in out["deliver_to"]
    assert "OWNER" not in out["deliver_to"]   # not an addressee

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

@case("relay-suppress-does-not-slide")
def _():
    r = N.Relay()
    r.handle(M("DEV", "DONE", to=["QA"], ts=0), 0)
    mid = r.handle(M("DEV", "DONE", to=["QA"], ts=N.WINDOW_S - 1), N.WINDOW_S - 1)
    assert mid["disposition"] == "suppress"
    out = r.handle(M("DEV", "DONE", to=["QA"], ts=N.WINDOW_S), N.WINDOW_S)
    assert out["disposition"] == "relay"     # clock stayed on the first relay

@case("relay-ack-repeat-same-sender-suppressed")
def _():
    r = N.Relay()
    r.handle(M("QA", "ACK", to=["DEV"], ts=0), 0)
    out = r.handle(M("QA", "ACK", to=["DEV"], ts=5), 5)
    assert out["disposition"] == "suppress"

@case("relay-fail-open-on-error")
def _():
    r = N.Relay()
    out = r.handle({"sender": "DEV", "to": ["QA"]}, 0)   # missing verb/item
    assert out["disposition"] == "fail-open"
    assert out["deliver_to"] == ["QA"]
    assert r.log[-1]["why"] == "echo-error"

@case("relay-corrupt-state-parked")
def _():
    p = os.path.join(WORK, "echo-state.json")
    open(p, "w").write("{not-json")
    r = N.Relay(state_path=p)
    assert r.last == {}
    assert os.path.exists(p + ".old")
    assert not os.path.exists(p)
    assert any(x.get("why") == "state-corrupt" for x in r.log)
    out = r.handle(M("DEV", "DONE", to=["QA"], ts=0), 0)
    assert out["disposition"] == "relay"

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
    # t4 was addressed only to QA, so LEAD/OWNER are not injected
    assert r.handle(M("DEV", "DONE", to=["QA"], ts=4, mid="id-4"), 4)["deliver_to"] == []
    act = r.handle(M("QA", "ASK", to=["DEV"], ts=5, mid="id-5"), 5)
    assert act["disposition"] == "pass"

@case("loop-sender-forbids-quiet-reply")
def _():
    assert not N.sender_ok("DONE", "ACK")
    assert not N.sender_ok("ACK", "ACK")
    assert not N.sender_ok("ACK", "DONE")
    assert not N.sender_ok("DONE", "DONE")
    assert N.sender_ok("DONE", "ASK")

# --- 18.3 backlog: first quiet per ticket; reset starts a new group ---
@case("backlog-keeps-first-quiet-key")
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
    assert quiets[0]["ts"] == 1 and quiets[0]["sender"] == "DEV"
    assert quiets[0]["collapsed_n"] == 4 and quiets[0]["no_reply"] is True

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
    assert quiet["ts"] == 2 and quiet["collapsed_n"] == 1   # first after GO; one dropped

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
    assert by[T]["ts"] == 1 and by[T2]["ts"] == 1
    assert by[T]["collapsed_n"] == 1 and by[T2]["collapsed_n"] == 1
    assert by[T]["no_reply"] and by[T2]["no_reply"]

@case("backlog-reset-starts-new-group")
def _():
    msgs = [
        M("DEV", "DONE", ts=1, mid="d1"),
        M("QA", "ACK", ts=2, mid="a1"),
        M("LEAD", "GO", ts=3, mid="g1"),
        M("DEV", "DONE", ts=4, mid="d2"),
        M("DEV", "DONE", ts=5, mid="d3"),
    ]
    out = N.collapse_backlog(msgs)
    verbs = [m["verb"] for m in out]
    assert verbs == ["DONE", "GO", "DONE"], verbs
    assert out[0]["ts"] == 1 and out[0]["collapsed_n"] == 1
    assert out[2]["ts"] == 4 and out[2]["collapsed_n"] == 1

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
    msgs = [M("DEV", "DONE", obj="ops.qc", ts=1), M("DEV", "DONE", obj="ops.qc", ts=2)]
    assert N.progress_count(msgs) == 1
    assert N.completion_state(M("DEV", "DONE", state="done", obj="ops.qc")) == "done"

@case("metrics-loop-flag-over-50-in-24h")
def _():
    msgs = [M("DEV", "DONE", ts=i * 60, mid="x%d" % i) for i in range(51)]
    flagged = N.loop_items(msgs, now=51 * 60)
    assert flagged == [T]
    line = N.loop_flag_line(T, 51)
    assert line.startswith("@ICOM>ICOM>LEAD,OWNER P1 INT0 %s FLAG echo.loop why=echo n=51" % T)
    assert " FYI " not in line

@case("metrics-loop-flag-50-is-not-a-loop")
def _():
    msgs = [M("DEV", "ACK", ts=i, mid="y%d" % i) for i in range(50)]
    assert N.loop_items(msgs, now=50) == []

@case("metrics-loop-ignores-old-quiet")
def _():
    msgs = [M("DEV", "DONE", ts=0, mid="old")] + [M("DEV", "DONE", ts=N.LOOP_S + 10 + i, mid="n%d" % i) for i in range(3)]
    assert N.loop_items(msgs, now=N.LOOP_S + 20) == []

@case("metrics-action-verbs-do-not-trip-loop")
def _():
    msgs = [M("LEAD", "GO", ts=i, mid="g%d" % i) for i in range(20)]
    assert N.loop_items(msgs, now=20) == []

@case("loop-flag-once-per-ticket-window")
def _():
    w = N.LoopWatch()
    msgs = [M("DEV", "DONE", ts=i, mid="z%d" % i) for i in range(51)]
    a = w.consider(msgs, now=51)
    b = w.consider(msgs, now=52)
    assert len(a) == 1 and len(b) == 0, (a, b)
    later = [M("DEV", "DONE", ts=51 + N.LOOP_S - 50 + i, mid="w%d" % i) for i in range(51)]
    c = w.consider(later, now=51 + N.LOOP_S)
    assert len(c) == 1, c

@case("loop-flag-never-suppressed")
def _():
    r = N.Relay()
    flag = M("ICOM", "FLAG", to=["LEAD", "OWNER"], ts=0, mid="f1", obj="echo.loop")
    assert not N.is_quiet("FLAG")
    assert r.handle(flag, 0)["disposition"] == "pass"
    assert r.handle(flag, 1)["disposition"] == "pass"

@case("loop-non-iro-not-counted")
def _():
    msgs = [M("DEV", "DONE", item="#OPS-12", ts=i, mid="o%d" % i) for i in range(60)]
    w = N.LoopWatch()
    assert w.consider(msgs, now=60) == []
    assert N.loop_items(msgs, now=60) == []

@case("loop-last4-binds-one-flag")
def _():
    msgs = [M("DEV", "DONE", item=IRO_A, ts=i, mid="a%d" % i) for i in range(30)]
    msgs += [M("DEV", "DONE", item=SHORT, ts=30 + i, mid="s%d" % i) for i in range(30)]
    w = N.LoopWatch()
    out = w.consider(msgs, now=60)
    assert len(out) == 1, out
    assert IRO_A in out[0] and "n=60" in out[0]
    assert N.loop_items(msgs, now=60) == [IRO_A]

# --- F8 body hash / ticket resolve / reset ---
@case("relay-fyi-new-body-relays")
def _():
    r = N.Relay()
    r.handle(M("DEV", "FYI", ts=0, note="old"), 0)
    out = r.handle(M("DEV", "FYI", ts=1, note="new"), 1)
    assert out["disposition"] == "relay"

@case("relay-rec-new-action-relays")
def _():
    r = N.Relay()
    r.handle(M("QA", "REC", action="HOLD", ts=0), 0)
    out = r.handle(M("QA", "REC", action="GO", ts=1), 1)
    assert out["disposition"] == "relay"

@case("relay-done-after-go-relays")
def _():
    r = N.Relay()
    r.handle(M("DEV", "DONE", ts=0), 0)
    assert r.handle(M("LEAD", "GO", ts=1), 1)["disposition"] == "pass"
    out = r.handle(M("DEV", "DONE", ts=2), 2)
    assert out["disposition"] == "relay"

@case("relay-flag-does-not-reset")
def _():
    r = N.Relay()
    r.handle(M("DEV", "DONE", ts=0), 0)
    r.handle(M("ICOM", "FLAG", to=["LEAD", "OWNER"], ts=1, obj="echo.loop"), 1)
    out = r.handle(M("DEV", "DONE", ts=2), 2)
    assert out["disposition"] == "suppress"

@case("relay-last4-unresolved-no-sup")
def _():
    r = N.Relay()
    short = "2c3d#2"
    r.handle(M("DEV", "DONE", item=short, ts=0), 0)
    out = r.handle(M("DEV", "DONE", item=short, ts=1), 1)
    assert out["disposition"] == "relay"
    assert r.log[-1].get("why") == "unresolved-ticket"

@case("relay-unwritable-state-open")
def _():
    p = os.path.join(WORK, "no-write-dir", "echo.json")
    real = os.makedirs
    def boom(*a, **k):
        raise PermissionError("read-only")
    os.makedirs = boom
    try:
        r = N.Relay(state_path=p)
    finally:
        os.makedirs = real
    assert r.persist is False
    assert any(x.get("why") == "state-unwritable" for x in r.log)
    out = r.handle(M("DEV", "DONE", ts=0), 0)
    assert out["disposition"] == "relay"

@case("relay-parent-is-a-file")
def _():
    parent = os.path.join(WORK, "state-parent-file")
    open(parent, "w").write("not-a-dir")
    r = N.Relay(state_path=os.path.join(parent, "echo.json"))
    assert r.persist is False
    assert any(x.get("why") == "state-unwritable" for x in r.log)
    out = r.handle(M("DEV", "DONE", ts=0), 0)
    assert out["disposition"] == "relay"

@case("relay-readonly-dir-fail-open")
def _():
    d = os.path.join(WORK, "ro-parent")
    os.makedirs(d, exist_ok=True)
    os.chmod(d, 0o555)
    try:
        r = N.Relay(state_path=os.path.join(d, "child", "echo.json"))
        assert r.persist is False
        assert any(x.get("why") == "state-unwritable" for x in r.log)
        out = r.handle(M("DEV", "DONE", ts=0), 0)
        assert out["disposition"] == "relay"
    finally:
        os.chmod(d, 0o700)

@case("backlog-last4-unresolved-keep")
def _():
    msgs = [M("DEV", "DONE", item=SHORT, ts=1), M("DEV", "DONE", item=SHORT, ts=2)]
    out = N.collapse_backlog(msgs)
    assert len(out) == 2
    assert all("collapsed_n" not in m for m in out)

@case("backlog-last4-binds-to-one")
def _():
    msgs = [
        M("DEV", "DONE", item=IRO_A, ts=1),
        M("DEV", "DONE", item=SHORT, ts=2),
    ]
    out = N.collapse_backlog(msgs)
    quiets = [m for m in out if N.is_quiet(m["verb"])]
    assert len(quiets) == 1
    assert quiets[0]["item"] == IRO_A and quiets[0]["collapsed_n"] == 1

@case("backlog-last4-ambiguous-keep")
def _():
    msgs = [
        M("DEV", "DONE", item=IRO_A, ts=1),
        M("QA", "DONE", item=IRO_B, ts=2),
        M("DEV", "DONE", item=SHORT, ts=3),
    ]
    out = N.collapse_backlog(msgs)
    assert len(out) == 3   # last4 does not join either group

@case("backlog-non-iro-never-collapse")
def _():
    msgs = [M("DEV", "DONE", item=NONIRO, ts=1), M("DEV", "DONE", item=NONIRO, ts=2)]
    out = N.collapse_backlog(msgs)
    assert len(out) == 2
    assert all("collapsed_n" not in m for m in out)

@case("relay-last4-binds-then-suppress")
def _():
    r = N.Relay()
    assert r.handle(M("DEV", "DONE", item=IRO_A, ts=0), 0)["disposition"] == "relay"
    out = r.handle(M("DEV", "DONE", item=SHORT, ts=1), 1)
    assert out["disposition"] == "suppress"

@case("relay-last4-ambiguous-relays")
def _():
    r = N.Relay()
    r.handle(M("DEV", "DONE", item=IRO_A, ts=0), 0)
    r.handle(M("QA", "DONE", item=IRO_B, ts=1), 1)
    out = r.handle(M("DEV", "DONE", item=SHORT, ts=2), 2)
    assert out["disposition"] == "relay"
    assert r.log[-1].get("why") == "unresolved-ticket"

@case("relay-non-iro-never-suppress")
def _():
    r = N.Relay()
    r.handle(M("DEV", "DONE", item=NONIRO, ts=0), 0)
    out = r.handle(M("DEV", "DONE", item=NONIRO, ts=1), 1)
    assert out["disposition"] == "relay"
    assert r.log[-1].get("why") == "unresolved-ticket"

def _from_line(line):
    toks = line.split()
    frm = toks[0][1:].split(">")[0]
    tos = toks[0].split(">")[-1].split(",")
    ticket = [t for t in toks if t.startswith("#iro-") or t.startswith("#")][0]
    ti = toks.index(ticket)
    verb = toks[ti + 1]
    j = ti + 2
    action = None
    if verb == "REC" and j < len(toks) and "=" not in toks[j] and toks[j].isupper():
        action = toks[j]; j += 1
    obj = toks[j]
    extra = {}
    for t in toks[j + 1:]:
        if "=" in t:
            k, v = t.split("=", 1)
            extra[k] = v
    return M(frm, verb, item=ticket, to=tos, obj=obj, action=action, **extra)

@case("decide-clears-window-via-parser")
def _():
    sys.path.insert(0, ROOT)
    import icom_expand as E
    fx = os.path.join(ROOT, "fixtures", "codebook-fixture.json")
    cb = E.Codebook(fx)
    assert "DECIDE" in cb.verbs and "HOLD" in cb.verbs
    th = E.Thread()
    ok1, l1 = E.process("@DEV>LEAD %s DONE ops.qc qa=pass" % T, cb, th)
    ok2, l2 = E.process("@LEAD>DEV %s DECIDE ops.qc" % T, cb, th)
    ok3, l3 = E.process("@DEV>LEAD %s DONE ops.qc qa=pass" % T, cb, th)
    assert ok1 and ok2 and ok3, (l1, l2, l3)
    assert " DECIDE " in l2
    r = N.Relay(codebook_verbs=cb.verbs)
    assert r.handle(_from_line(l1), 0)["disposition"] == "relay"
    assert r.handle(_from_line(l2), 1)["disposition"] == "pass"
    assert r.handle(_from_line(l3), 2)["disposition"] == "relay"

if __name__ == "__main__":
    fails = [r for r in results if not r[1]]
    for n, g, m in results: print(("PASS " if g else "FAIL ") + n + ("" if g else "  " + m))
    print("TOTAL %d PASS %d FAIL %d" % (len(results), len(results) - len(fails), len(fails)))
    sys.exit(1 if fails else 0)
