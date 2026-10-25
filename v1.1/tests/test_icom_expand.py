#!/usr/bin/env python3
"""Plain-assert tests for icom_expand.py. Run: python3 tests/test_icom_expand.py
Copyright (c) 2026 Robert Stanley / Iron Noodle Technologies."""
import hashlib, io, json, os, sys, contextlib
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import icom_expand as E
import scrub_check as S
FX = os.path.join(ROOT, "fixtures", "codebook-fixture.json")
WORK = os.path.join(ROOT, ".work"); os.makedirs(WORK, mode=0o700, exist_ok=True)
CB = E.Codebook(FX)
T = "#tkt-0a1b2c3d"
results = []

def case(name):
    def deco(fn):
        try: fn(); results.append((name, True, ""))
        except AssertionError as e: results.append((name, False, str(e)))
        except Exception as e: results.append((name, False, "%s: %s" % (type(e).__name__, e)))
        return fn
    return deco

def ok(line, th=None): r, out = E.process(line, CB, th or E.Thread()); assert r, out; return out
def nak(line, code, th=None):
    r, out = E.process(line, CB, th or E.Thread())
    assert not r, "expected NAK %s got %s" % (code, out)
    assert (" why=%s" % code) in out, out
    assert out.startswith("@ICOM>ICOM>") and " NAK org.proto " in out and out.endswith(" cb=" + CB.version), out
    return out

# --- backward compat: v1 canonical passes unchanged ---
@case("v1-canonical-unchanged")
def _():
    l = "@LEAD>ICOM>DEV P1 INT0 %s GO ops.deploy f=ROOT/x.md nx=DEV:review" % T
    assert ok(l) == l
@case("v1-multi-to-and-client-lane")
def _():
    l = "@LEAD>ICOM>DEV,QA P2 AAA %s FYI ops.qc qa=pass" % T; assert ok(l) == l
@case("v1-rec-action")
def _():
    l = "@QA>ICOM>LEAD P2 INT0 %s REC HOLD ops.deploy why=flaky" % T; assert ok(l) == l
@case("v1-r19-shortid-passthrough")
def _():
    th = E.Thread(); th.put(E.Thread.key("LEAD", ["DEV"]), {"ticket": T, "pri": "P1", "lane": "INT0"})
    assert ok("@LEAD>ICOM>DEV P1 INT0 2c3d#2 ACK ops.deploy", th) == "@LEAD>ICOM>DEV P1 INT0 2c3d#2 ACK ops.deploy"

# --- implied header ---
@case("implied-hop-pri-lane")
def _():
    assert ok("@LEAD>DEV %s GO ops.deploy" % T) == "@LEAD>ICOM>DEV P2 INT0 %s GO ops.deploy" % T
@case("implied-bare-ticket-hex")
def _():
    assert ok("@LEAD>DEV P1 #0a1b2c3d GO ops.deploy") == "@LEAD>ICOM>DEV P1 INT0 %s GO ops.deploy" % T
@case("implied-thread-carry")
def _():
    th = E.Thread()
    ok("@LEAD>DEV P1 AAA %s GO ops.deploy" % T, th)
    assert ok("@DEV>LEAD DONE ops.deploy qa=pass", th) == "@DEV>ICOM>LEAD P1 AAA %s DONE ops.deploy qa=pass" % T
@case("implied-thread-change-pri")
def _():
    th = E.Thread(); ok("@LEAD>DEV P1 AAA %s GO ops.deploy" % T, th)
    assert ok("@DEV>LEAD P3 FYI ops.qc", th).startswith("@DEV>ICOM>LEAD P3 AAA %s " % T)
@case("implied-thread-persist-state-file")
def _():
    p = os.path.join(WORK, "state-test.json")
    if os.path.exists(p): os.replace(p, p + ".old")   # never delete: park
    ok("@LEAD>DEV P1 BBB %s GO ops.deploy" % T, E.Thread(p))
    assert ok("@DEV>LEAD ACK ops.deploy", E.Thread(p)) == "@DEV>ICOM>LEAD P1 BBB %s ACK ops.deploy" % T
    assert oct(os.stat(p).st_mode & 0o777) == "0o600"
@case("implied-no-ticket-no-thread")
def _(): nak("@LEAD>DEV GO ops.deploy", "bad-ticket")

# --- phrase shortcuts + cb token ---
@case("shortcut-expand")
def _():
    assert ok("@LEAD>DEV %s $RERUN-GO cb=%s" % (T, CB.version)) == \
        "@LEAD>ICOM>DEV P2 INT0 %s GO ops.deploy act=rerun cb=%s" % (T, CB.version)
@case("shortcut-override-kv")
def _():
    o = ok("@DEV>LEAD %s $DONE-CLEAN qa=DEV:12/12 cb=%s" % (T, CB.version))
    assert o == "@DEV>ICOM>LEAD P2 INT0 %s DONE ops.qc risk=none qa=DEV:12/12 cb=%s" % (T, CB.version), o
@case("shortcut-default-pri")
def _():
    assert ok("@DEV>LEAD %s $BLK-DEP cb=%s" % (T, CB.version)).startswith("@DEV>ICOM>LEAD P1 INT0 ")
@case("shortcut-explicit-pri-wins")
def _():
    assert ok("@DEV>LEAD P3 %s $BLK-DEP cb=%s" % (T, CB.version)).startswith("@DEV>ICOM>LEAD P3 INT0 ")
@case("shortcut-unknown")
def _(): nak("@LEAD>DEV %s $NOPE cb=%s" % (T, CB.version), "unk-shortcut")
@case("shortcut-needs-cb")
def _(): nak("@LEAD>DEV %s $RERUN-GO" % T, "cb-required")
@case("cb-mismatch")
def _(): nak("@LEAD>DEV %s $RERUN-GO cb=1.0" % T, "cb-mismatch")
@case("cb-mismatch-on-v1-line")
def _(): nak("@LEAD>ICOM>DEV P2 INT0 %s GO ops.deploy cb=0.1" % T, "cb-mismatch")
@case("cb-ok-on-v1-line-kept")
def _():
    l = "@LEAD>ICOM>DEV P2 INT0 %s GO ops.deploy cb=%s" % (T, CB.version); assert ok(l) == l

# --- path alias (~w/) ---
@case("path-alias-expanded-from-codebook")
def _():
    assert ok("@LEAD>DEV %s GO ops.deploy f=~w/a/b.md" % T).endswith(" f=ROOT/a/b.md")
@case("path-alias-not-in-other-keys")
def _():
    assert ok("@LEAD>DEV %s GO ops.deploy note=~w/x" % T).endswith(" note=~w/x")

# --- autoNAK ---
@case("nak-bad-verb")
def _(): nak("@LEAD>ICOM>DEV P2 INT0 %s DECIDE ops.deploy" % T, "bad-verb")
@case("nak-prose")
def _(): nak("@LEAD>ICOM>DEV P2 INT0 %s GO ops.deploy please rerun the job" % T, "prose")
@case("nak-full-email")
def _(): nak("@LEAD>ICOM>DEV P2 INT0 %s FYI ops.qc to=bob@example.com" % T, "email")
@case("short-email-allowed")
def _(): ok("@LEAD>ICOM>DEV P2 INT0 %s FYI ops.qc to=s@example" % T)
@case("nak-p0-int0")
def _(): nak("@LEAD>ICOM>DEV P0 INT0 %s GO ops.deploy why=down" % T, "p0-misuse")
@case("nak-p0-no-why")
def _(): nak("@LEAD>ICOM>DEV P0 AAA %s GO ops.deploy" % T, "p0-misuse")
@case("p0-client-down-ok")
def _(): ok("@LEAD>ICOM>DEV P0 AAA %s GO ops.deploy why=down" % T)
@case("nak-bad-pri")
def _(): nak("@LEAD>DEV P7 %s GO ops.deploy" % T, "bad-pri")
@case("nak-bad-lane")
def _(): nak("@LEAD>DEV P2 ZZZ %s GO ops.deploy" % T, "bad-lane")
@case("nak-bad-agent")
def _(): nak("@NOBODY>DEV %s GO ops.deploy" % T, "bad-agent")
@case("nak-bad-route")
def _(): nak("@LEAD>QA>DEV %s GO ops.deploy" % T, "bad-route")
@case("nak-no-header")
def _(): nak("GO ops.deploy", "no-header")
@case("nak-multiline")
def _(): nak("@LEAD>DEV %s GO ops.deploy\nsecond line" % T, "multiline")
@case("nak-missing-object")
def _(): nak("@LEAD>DEV %s GO" % T, "bad-icx")
@case("nak-keeps-ticket")
def _(): assert " %s NAK " % T in nak("@LEAD>DEV %s BOGUS ops.qc" % T, "bad-verb")

# --- codebook loading / pinning ---
@case("codebook-sha12-pin-ok")
def _():
    h = hashlib.sha256(open(FX, "rb").read()).hexdigest()[:12]
    assert E.Codebook(FX, expect_sha12=h).sha12 == h
@case("codebook-sha12-pin-bad")
def _():
    try: E.Codebook(FX, expect_sha12="000000000000"); assert False, "no error"
    except E.CodebookError: pass
@case("codebook-version-pin-bad")
def _():
    try: E.Codebook(FX, expect_version="1.0.0"); assert False, "no error"
    except E.CodebookError: pass
@case("codebook-yaml-dict-form")
def _():
    p = os.path.join(WORK, "cb-dict.yaml")
    open(p, "w").write("version: 0.0.1-t\nverbs: {GO: go, DONE: done}\nclients: {AAA: a}\nagents: {LEAD: l, DEV: d}\n")
    cb = E.Codebook(p); assert cb.version == "0.0.1-t" and "AAA" in cb.lanes and "INT0" in cb.lanes and not cb.shortcuts
    assert cb.ticket_prefix == "tkt-"
@case("ticket-prefix-default")
def _():
    assert CB.ticket_prefix == "tkt-"
    assert ok("@LEAD>DEV #%s GO ops.deploy" % T[5:]) == "@LEAD>ICOM>DEV P2 INT0 %s GO ops.deploy" % T
@case("ticket-prefix-explicit")
def _():
    pfx = "x" * 3 + "-"
    hid = "0a1b2c3d"
    full = "#" + pfx + hid
    p = os.path.join(WORK, "cb-pfx.yaml")
    open(p, "w").write(
        "version: 0.0.2-t\nverbs: {GO: go, ACK: ack}\nagents: {LEAD: l, DEV: d, ICOM: i}\n"
        "ticket_prefix: %s\n" % pfx
    )
    cb = E.Codebook(p)
    assert cb.ticket_prefix == pfx
    r, out = E.process("@LEAD>DEV %s GO ops.deploy" % full, cb)
    assert r and out == "@LEAD>ICOM>DEV P2 INT0 %s GO ops.deploy" % full, out
    r, out = E.process("@LEAD>DEV #%s GO ops.deploy" % hid, cb)
    assert r and out == "@LEAD>ICOM>DEV P2 INT0 %s GO ops.deploy" % full, out
    th = E.Thread()
    r, out = E.process("@LEAD>DEV P1 %s GO ops.deploy" % full, cb, th)
    assert r, out
    r, out = E.process("@DEV>LEAD ACK ops.deploy", cb, th)
    assert r and out == "@DEV>ICOM>LEAD P1 INT0 %s ACK ops.deploy" % full, out
    r, out = E.process("@LEAD>DEV %s BOGUS ops.qc" % full, cb)
    assert (not r) and (" %s NAK " % full) in out, out
@case("engine-version-1.2.0")
def _():
    assert E.ENGINE_VERSION == "1.2.0"
@case("ticket-prefix-legacy-default-nak")
def _():
    old = "#" + ("x" * 3 + "-") + "0a1b2c3d"
    out = nak("@LEAD>DEV %s GO ops.deploy" % old, "bad-ticket")
    assert "#icom-nak" in out and old not in out, out
@case("ticket-prefix-legacy-explicit-keeps")
def _():
    pfx = "x" * 3 + "-"
    hid = "0a1b2c3d"
    full = "#" + pfx + hid
    p = os.path.join(WORK, "cb-mig.yaml")
    open(p, "w").write(
        "version: 0.0.3-t\nverbs: {GO: go}\nagents: {LEAD: l, DEV: d, ICOM: i}\n"
        "ticket_prefix: %s\n" % pfx
    )
    cb = E.Codebook(p)
    r, out = E.process("@LEAD>DEV %s GO ops.deploy" % full, cb)
    assert r and out == "@LEAD>ICOM>DEV P2 INT0 %s GO ops.deploy" % full, out
@case("ticket-prefix-state-not-rewritten")
def _():
    pfx = "x" * 3 + "-"
    hid = "0a1b2c3d"
    old = "#" + pfx + hid
    pth = os.path.join(WORK, "state-legacy.json")
    if os.path.exists(pth): os.replace(pth, pth + ".old")
    p = os.path.join(WORK, "cb-state.yaml")
    open(p, "w").write(
        "version: 0.0.3-t\nverbs: {GO: go, ACK: ack}\nagents: {LEAD: l, DEV: d, ICOM: i}\n"
        "ticket_prefix: %s\n" % pfx
    )
    E.process("@LEAD>DEV P1 %s GO ops.deploy" % old, E.Codebook(p), E.Thread(pth))
    r, out = E.process("@DEV>LEAD ACK ops.deploy", CB, E.Thread(pth))
    assert r and old in out and T not in out, out
@case("ticket-prefix-uppercase-input-normalized")
def _():
    assert ok("@LEAD>DEV #" + "TKT-" + "0a1b2c3d GO ops.deploy") == \
        "@LEAD>ICOM>DEV P2 INT0 %s GO ops.deploy" % T
@case("ticket-prefix-rejects-invalid")
def _():
    head = "version: 0.0.3-t\nverbs: {GO: go}\nagents: {LEAD: l}\n"
    samples = [
        'ticket_prefix: ""\n',
        "ticket_prefix:\n",
        "ticket_prefix: \"-\"\n",
        'ticket_prefix: "a b"\n',
        "ticket_prefix: TKT-\n",
        "ticket_prefix: tkt\n",
        'ticket_prefix: "#"\n',
        'ticket_prefix: "x--"\n',
        'ticket_prefix: "a.b"\n',
        "ticket_prefix: true\n",
        "ticket_prefix: 0\n",
    ]
    p = os.path.join(WORK, "cb-bad.yaml")
    for extra in samples:
        open(p, "w").write(head + extra)
        try:
            E.Codebook(p)
            assert False, "accepted %r" % extra
        except E.CodebookError as e:
            assert "ticket_prefix" in str(e), (extra, e)
    pj = os.path.join(WORK, "cb-bad.json")
    json.dump({"version": "0.0.3-t", "verbs": ["GO"], "ticket_prefix": ["a"]}, open(pj, "w"))
    try:
        E.Codebook(pj)
        assert False, "accepted list"
    except E.CodebookError as e:
        assert "ticket_prefix" in str(e), e
@case("scrub-allow-exact-placeholders")
def _():
    assert S.ticket_shape_hits("see tkt-0a1b2c3d here") == []
    assert S.ticket_shape_hits("form tkt-xxxxxxxx used") == []
@case("scrub-allow-not-any-hex")
def _():
    other = "tkt-" + "9f8e7d6c"
    hits = S.ticket_shape_hits("id " + other)
    assert hits and any(h.lower().endswith("9f8e7d6c") for h in hits), hits
@case("scrub-bypass-case")
def _():
    samples = [
        "".join(("I", "R", "O")) + "-" + "0A1B2C3D",
        "".join(("I", "r", "o")) + "-" + "0a1b2c3d",
        "".join(("P", "L", "T")) + "-" + "1234ABCD",
    ]
    for s in samples:
        assert S.ticket_shape_hits(s), s
@case("scrub-bypass-underscore")
def _():
    s = "".join(("i", "r", "o")) + "_" + "0a1b2c3d"
    assert S.ticket_shape_hits(s), s
@case("scrub-bypass-no-separator")
def _():
    s = "".join(("i", "r", "o")) + "0a1b2c3d"
    assert S.ticket_shape_hits(s), s
@case("scrub-bypass-long-prefix")
def _():
    s = "noodle" + "-" + "0a1b2c3d"
    assert S.ticket_shape_hits(s), s
@case("scrub-bypass-glued-placeholder")
def _():
    s = "".join(("i", "r", "o")) + "-" + "tkt-0a1b2c3d"
    assert S.ticket_shape_hits(s), s
@case("scrub-false-positive-rel-inv")
def _():
    assert S.ticket_shape_hits("rel-20261025") == []
    assert S.ticket_shape_hits("inv-12345678") == []
@case("cli-exit-codes")
def _():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert E.main(["--codebook", FX, "@LEAD>DEV %s GO ops.deploy" % T]) == 0
        assert E.main(["--codebook", FX, "@LEAD>DEV %s XX ops.deploy" % T]) == 1
    with contextlib.redirect_stderr(io.StringIO()):
        assert E.main(["--codebook", FX, "--expect-sha12", "000000000000", "x"]) == 2

if __name__ == "__main__":
    fails = [r for r in results if not r[1]]
    for n, g, m in results: print(("PASS " if g else "FAIL ") + n + ("" if g else "  " + m))
    print("TOTAL %d PASS %d FAIL %d" % (len(results), len(results) - len(fails), len(fails)))
    sys.exit(1 if fails else 0)
