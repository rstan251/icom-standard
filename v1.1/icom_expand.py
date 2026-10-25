#!/usr/bin/env python3
"""ICOM v1.1 script expander + autoNAK (engine only).

Copyright (c) 2026 Robert Stanley / Iron Noodle Technologies.

Loads an EXTERNAL codebook file (YAML or JSON) by path, optionally pins its
version and sha256 first-12, then expands v1.1 shorthand lines to canonical v1
form or emits one autoNAK line. Deterministic, no network, no model calls.
v1 canonical lines pass through unchanged (backward compatible).

Usage:
  icom_expand.py --codebook PATH [--expect-version V] [--expect-sha12 H]
                 [--state FILE] [LINE ...]        (lines from stdin if none)
Exit: 0 all lines OK, 1 one or more NAKs, 2 codebook load/pin error.
"""
import argparse, hashlib, json, os, re, sys

ENGINE_VERSION = "1.1.0"
DEFAULT_PRI = "P2"
DEFAULT_LANE = "INT0"
PRIS = ("P0", "P1", "P2", "P3")
P0_WHY = ("down", "outage", "sec", "money")       # P0 = client-down / outage / security / money at risk

# --- NAK reason codes (stable; relay-compatible spelling: lowercase, hyphen) ---
NAK_CODES = {
    "empty": "empty line", "multiline": "more than one line", "no-header": "line does not start with @",
    "bad-route": "hop other than ICOM", "bad-agent": "unknown FROM/TO agent", "bad-pri": "priority not P0-P3",
    "bad-lane": "unknown lane/client code", "bad-ticket": "no ticket and none implied by thread",
    "bad-verb": "verb not in codebook", "bad-icx": "missing object after verb", "prose": "bare words after object",
    "email": "full email address (use initial@domain, no TLD)", "unk-shortcut": "shortcut not in codebook",
    "cb-mismatch": "cb= token differs from loaded codebook version", "cb-required": "shortcut used without cb= token",
    "p0-misuse": "P0 needs a client lane and why=down|outage|sec|money",
}

class CodebookError(Exception): pass
class Nak(Exception):
    def __init__(self, code, det=""):
        super().__init__(code); self.code = code; self.det = det

def sha12_bytes(b): return hashlib.sha256(b).hexdigest()[:12]

def _names(v):
    """Accept list, dict (keys), or list of {code: ...} dicts."""
    if v is None: return set()
    if isinstance(v, dict): return {str(k) for k in v}
    out = set()
    for x in v:
        out.add(str(x["code"]) if isinstance(x, dict) else str(x))
    return out

class Codebook:
    def __init__(self, path, expect_version=None, expect_sha12=None):
        raw = open(path, "rb").read()
        self.path, self.sha12 = path, sha12_bytes(raw)
        if expect_sha12 and self.sha12 != expect_sha12:
            raise CodebookError("sha12 mismatch: got %s want %s" % (self.sha12, expect_sha12))
        text = raw.decode("utf-8")
        if path.endswith(".json"):
            d = json.loads(text)
        else:
            import yaml
            d = yaml.safe_load(text)
        if not isinstance(d, dict) or "version" not in d:
            raise CodebookError("codebook has no version")
        self.version = str(d["version"])
        if expect_version and self.version != expect_version:
            raise CodebookError("version mismatch: got %s want %s" % (self.version, expect_version))
        self.verbs = _names(d.get("verbs"))
        self.lanes = _names(d.get("lanes")) | _names(d.get("clients"))
        self.lanes.add(DEFAULT_LANE)
        self.agents = _names(d.get("agents"))
        icx = d.get("icx") or {}
        self.icx = _names(icx.get("codes") if isinstance(icx, dict) else icx)
        self.paths = {str(k): str(v) for k, v in (d.get("paths") or {}).items()}
        sc = d.get("shortcuts") or {}
        self.shortcuts = {str(k): v for k, v in sc.items()}
        if not self.verbs: raise CodebookError("codebook has no verbs")

# --- line grammar (v1.1 input). Hop ">ICOM>" optional; PRI, LANE, ticket optional (implied). ---
HEAD = re.compile(r"^@([A-Z0-9]+)>(?:([A-Z0-9]+)>)?([A-Z0-9]+(?:,[A-Z0-9]+)*)$")
TICKET = re.compile(r"^(?:#iro-([0-9a-f]{8})|#([0-9a-f]{8})|([0-9a-f]{4}#[0-9]{1,6})|(\^[a-z0-9]{4,8}))$")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
KV = re.compile(r"^[a-z][a-z0-9_.-]*=\S*$")

class Thread:
    """Implied-header memory: key = sorted parties; remembers ticket, pri, lane."""
    def __init__(self, path=None):
        self.path, self.d = path, {}
        if path and os.path.exists(path):
            try: self.d = json.load(open(path))
            except Exception: self.d = {}
    @staticmethod
    def key(frm, tos): return ",".join(sorted(set([frm] + tos)))
    def get(self, k): return self.d.get(k) or {}
    def put(self, k, v):
        self.d[k] = v
        if self.path:
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f: json.dump(self.d, f, sort_keys=True)
            os.chmod(tmp, 0o600); os.replace(tmp, self.path)

def expand_paths(tok, cb):
    k, v = tok.split("=", 1)
    for alias, root in cb.paths.items():
        a = alias.rstrip("/") + "/"
        if v.startswith(a): v = root.rstrip("/") + "/" + v[len(a):]
    return k + "=" + v

def expand(line, cb, thread=None):
    """Return canonical v1 line or raise Nak."""
    thread = thread or Thread()
    if line is None or not line.strip(): raise Nak("empty")
    lines = [l for l in line.splitlines() if l.strip()]
    if len(lines) > 1: raise Nak("multiline")
    s = lines[0].strip()
    if not s.startswith("@"): raise Nak("no-header")
    if EMAIL.search(s): raise Nak("email")
    toks = s.split()
    m = HEAD.match(toks[0])
    if not m: raise Nak("no-header")
    frm, hop, tos = m.group(1), m.group(2), m.group(3).split(",")
    if hop is not None and hop != "ICOM": raise Nak("bad-route", hop)
    if cb.agents:
        bad = [a for a in [frm] + tos if a not in cb.agents]
        if bad: raise Nak("bad-agent", ",".join(bad))
    i, key = 1, Thread.key(frm, tos)
    st = thread.get(key)
    pri = lane = ticket = None
    if i < len(toks) and re.match(r"^P\d$", toks[i]):
        if toks[i] not in PRIS: raise Nak("bad-pri", toks[i])
        pri = toks[i]; i += 1
    if i < len(toks) and re.match(r"^[A-Z0-9]{3,4}$", toks[i]) and toks[i] not in cb.verbs:
        if toks[i] not in cb.lanes: raise Nak("bad-lane", toks[i])
        lane = toks[i]; i += 1
    if i < len(toks) and TICKET.match(toks[i]):
        t = TICKET.match(toks[i])
        ticket = "#iro-" + (t.group(1) or t.group(2)) if (t.group(1) or t.group(2)) else toks[i]
        i += 1
    ticket = ticket or st.get("ticket")
    if not ticket: raise Nak("bad-ticket")
    pri = pri or st.get("pri") or DEFAULT_PRI
    lane = lane or st.get("lane") or DEFAULT_LANE
    rest = toks[i:]
    if not rest: raise Nak("bad-verb", "-")
    cbtok = [t for t in rest if t.startswith("cb=")]
    if cbtok and cbtok[0][3:] != cb.version: raise Nak("cb-mismatch", cbtok[0][3:])
    head = rest[0]
    if head.startswith("$"):
        name = head[1:]
        if name not in cb.shortcuts: raise Nak("unk-shortcut", name)
        if not cbtok: raise Nak("cb-required", name)
        sc = cb.shortcuts[name]
        exp = str(sc["expand"]).split()
        user_kv = rest[1:]
        ukeys = {t.split("=", 1)[0] for t in user_kv if "=" in t}
        body = [t for t in exp if not ("=" in t and t.split("=", 1)[0] in ukeys)] + user_kv
        if sc.get("pri") and not re.search(r"(^| )P\d( |$)", " ".join(toks[1:i])): pri = sc["pri"]
    else:
        body = rest
    verb = body[0]
    if verb not in cb.verbs: raise Nak("bad-verb", verb)
    j = 1
    if verb == "REC" and len(body) > 1 and body[1] in cb.verbs: j = 2
    if len(body) <= j or "=" in body[j]: raise Nak("bad-icx")
    obj = body[j]
    tail = body[j + 1:]
    bare = [t for t in tail if not KV.match(t)]
    if bare: raise Nak("prose", bare[0])
    if pri == "P0":
        why = [t.split("=", 1)[1] for t in tail if t.startswith("why=")]
        if lane == DEFAULT_LANE or not why or not any(w.split(".")[0].split(",")[0] in P0_WHY for w in why):
            raise Nak("p0-misuse")
    tail = [expand_paths(t, cb) if t.startswith("f=") else t for t in tail]
    out = "@%s>ICOM>%s %s %s %s %s" % (frm, ",".join(tos), pri, lane, ticket, " ".join(body[:j] + [obj] + tail))
    if ticket.startswith("#iro-"):
        thread.put(key, {"ticket": ticket, "pri": pri, "lane": lane})
    return out

def _tok(s, n=24): return re.sub(r"[^A-Za-z0-9._,-]", "?", str(s))[:n] or "-"

def nak_line(line, nak, cb):
    """autoNAK back to sender, relay nak_line shape (+ cb= token)."""
    m = re.match(r"^@([A-Z0-9]+)", (line or "").strip())
    to = m.group(1) if m else "UNK"
    t = re.search(r"#iro-[0-9a-f]{8}\b", line or "")
    tk = t.group(0) if t else "#icom-nak"
    out = "@ICOM>ICOM>%s P2 INT0 %s NAK org.proto why=%s" % (to, tk, nak.code)
    if nak.det: out += " det=" + _tok(nak.det)
    return out + " cb=" + cb.version

def process(line, cb, thread=None):
    """Return (ok, output_line)."""
    try: return True, expand(line, cb, thread)
    except Nak as n: return False, nak_line(line, n, cb)

def main(argv=None):
    ap = argparse.ArgumentParser(description="ICOM v1.1 expander + autoNAK")
    ap.add_argument("--codebook", required=True)
    ap.add_argument("--expect-version"); ap.add_argument("--expect-sha12")
    ap.add_argument("--state", help="thread state json for implied headers (0600)")
    ap.add_argument("lines", nargs="*")
    a = ap.parse_args(argv)
    try: cb = Codebook(a.codebook, a.expect_version, a.expect_sha12)
    except (CodebookError, OSError, ValueError) as e:
        print("CODEBOOK-ERROR %s" % e, file=sys.stderr); return 2
    th = Thread(a.state)
    src = a.lines or [l.rstrip("\n") for l in sys.stdin if l.strip()]
    rc = 0
    for l in src:
        ok, out = process(l, cb, th); print(out); rc |= (0 if ok else 1)
    return rc

if __name__ == "__main__":
    sys.exit(main())
