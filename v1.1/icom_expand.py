#!/usr/bin/env python3
"""ICOM v1.1 script expander + autoNAK (engine only).

Copyright (c) 2026 Robert Stanley / Iron Noodle Technologies.

Loads an EXTERNAL codebook file (YAML or JSON) by path, optionally pins its
version and sha256 first-12, then expands v1.1 shorthand lines to canonical v1
form or emits one autoNAK line. Deterministic, no network, no model calls.
v1 canonical lines pass through unchanged (backward compatible).

Usage:
  icom_expand.py --codebook PATH [--expect-version V] [--expect-sha12 H]
                 [--state FILE] [--clients PATH] [--outbound]
                 [LINE ...]        (lines from stdin if none)
Exit: 0 all lines OK, 1 one or more NAKs, 2 codebook load/pin error.
v1.3 accepts CO.CLIENT (CM.ABC, IN.INT0) and full company codes; bare
legacy lane codes (WST, INT0, LAP, …) stay valid during the transition.
"""
import argparse, hashlib, json, os, re, sys

ENGINE_VERSION = "1.3.0"
DEFAULT_PRI = "P2"
DEFAULT_LANE = "INT0"          # transition default; prefer IN.INT0 (Rule 14a)
INTERNAL_CLIENT = "INT0"
DEFAULT_CLIENT_COMPANY = "CM"
PRIS = ("P0", "P1", "P2", "P3")
P0_WHY = ("down", "outage", "sec", "money")       # P0 = client-down / outage / security / money at risk
OUTBOUND_KEYS = ("co", "cl", "topic", "icx")
CO_SHORT = re.compile(r"^[A-Z]{2}$")
CO_FULL = re.compile(r"^[A-Z]-(?:[A-Z]{2}|TBD)-(?:\d{4}|XXXX)$")
CL_SEG = re.compile(r"^[A-Z][A-Z0-9]{0,5}$")
LEGACY_LANE = re.compile(r"^[A-Z0-9]{3,4}$")
# Public company shorthand → full code (letter-STATE-XXXX). Codebook may overlay.
DEFAULT_COMPANIES = {
    "IN": {"short": "IN", "full": "I-MD-XXXX", "name": "Iron Noodle LLC", "words": "iron-noodle"},
    "CM": {"short": "CM", "full": "C-TBD-XXXX", "name": "Cogent Marketing LLC", "words": "cogent-marketing"},
    "CD": {"short": "CD", "full": "C-TBD-XXXX", "name": "Cogent Digital LLC", "words": "cogent-digital"},
}

# --- NAK reason codes (stable; relay-compatible spelling: lowercase, hyphen) ---
NAK_CODES = {
    "empty": "empty line", "multiline": "more than one line", "no-header": "line does not start with @",
    "bad-route": "hop other than ICOM", "bad-agent": "unknown FROM/TO agent", "bad-pri": "priority not P0-P3",
    "bad-lane": "unknown lane/client code", "bad-ticket": "no ticket and none implied by thread",
    "bad-verb": "verb not in codebook", "bad-icx": "missing object after verb", "prose": "bare words after object",
    "email": "full email address (use initial@domain, no TLD)", "unk-shortcut": "shortcut not in codebook",
    "cb-mismatch": "cb= token differs from loaded codebook version", "cb-required": "shortcut used without cb= token",
    "p0-misuse": "P0 needs a client lane and why=down|outage|sec|money",
    "icx.co.unk": "unknown company shorthand or bare C (not unique)",
    "icx.cl.unk": "unknown client shorthand (registry loaded)",
    "icx.ext.tok": "outbound line missing co= cl= topic= icx=",
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

def _load_companies(raw):
    """Public company book: 2-letter short → full (L-ST-XXXX). Defaults from ICX 1.2.0."""
    book = {k: dict(v) for k, v in DEFAULT_COMPANIES.items()}
    if not raw:
        return book
    items = []
    if isinstance(raw, dict):
        for k, meta in raw.items():
            rec = dict(meta) if isinstance(meta, dict) else {}
            rec.setdefault("short", str(k))
            rec.setdefault("full", rec.get("code") or rec.get("short"))
            items.append(rec)
    elif isinstance(raw, list):
        for meta in raw:
            if isinstance(meta, dict):
                items.append(dict(meta))
    for rec in items:
        short = str(rec.get("short") or "")
        if CO_SHORT.match(short) and rec.get("full"):
            book[short] = rec
    return book

def _read_mapping(path):
    raw = open(path, "rb").read().decode("utf-8")
    if path.endswith(".json"):
        return json.loads(raw)
    try:
        import yaml
    except ImportError:
        raise CodebookError("YAML registry requires PyYAML")
    return yaml.safe_load(raw)

def load_customers(path):
    """Private customer registry: short → {id, short, company, name}.

    Numeric id is canonical and must not appear on the public wire.
    Duplicate short or id is a load error.
    """
    data = _read_mapping(path) or {}
    raw = data.get("clients", data)
    items = []
    if isinstance(raw, dict):
        for k, meta in raw.items():
            rec = dict(meta) if isinstance(meta, dict) else {}
            rec.setdefault("short", str(k))
            items.append(rec)
    elif isinstance(raw, list):
        items = [dict(x) for x in raw if isinstance(x, dict)]
    else:
        raise CodebookError("clients registry must be a mapping or a list")
    by_short, by_id = {}, set()
    for rec in items:
        short = rec.get("short") or rec.get("code")
        cid = rec.get("id")
        if short is None or cid is None:
            raise CodebookError("client missing id or short")
        short, cid_s = str(short), str(cid).strip()
        if not re.fullmatch(r"\d+", cid_s):
            raise CodebookError("client id must be numeric")
        if short in by_short:
            raise CodebookError("duplicate client shorthand: %s" % short)
        if cid_s in by_id:
            raise CodebookError("duplicate client id")
        by_id.add(cid_s)
        by_short[short] = {
            "id": cid_s,
            "short": short,
            "company": str(rec.get("company") or DEFAULT_CLIENT_COMPANY),
            "name": rec.get("name"),
        }
    return by_short

def is_company_form(token):
    return bool(token) and bool(CO_FULL.match(token))

def is_internal_slot(slot):
    """INT0 or CO.INT0 (any company) is the no-client lane."""
    if not slot:
        return True
    if slot == INTERNAL_CLIENT:
        return True
    if "." in slot and slot.rsplit(".", 1)[-1] == INTERNAL_CLIENT:
        return True
    return False

def _company_lookup(token, cb):
    """Return (short, full) or (None, None) if token is not a known company."""
    if token in cb.companies:
        rec = cb.companies[token]
        return token, rec.get("full")
    for short, rec in cb.companies.items():
        if rec.get("full") == token:
            return short, token
    return None, None

def looks_like_slot(tok, cb):
    """True if tok is a CO.CLIENT / company / legacy-lane candidate, not a verb/ticket."""
    if not tok or tok in cb.verbs or tok.startswith("$") or tok.startswith("#"):
        return False
    if "." in tok:
        return True
    if is_company_form(tok):
        return True
    if re.match(r"^[A-Z]$", tok):          # bare C — not unique
        return True
    if CO_SHORT.match(tok):
        return True
    if LEGACY_LANE.match(tok):
        return True
    if CL_SEG.match(tok):
        return True
    return False

def check_slot(slot, cb):
    """Accept CO.CLIENT, full company form, or a bare legacy lane. Raise Nak."""
    if "." in slot:
        parts = slot.split(".")
        if len(parts) != 2:
            raise Nak("icx.cl.unk", slot)
        company, client = parts
        if len(company) == 1 or company == "C":
            raise Nak("icx.co.unk", company)
        c_short, _c_full = _company_lookup(company, cb)
        if not c_short and not is_company_form(company):
            raise Nak("icx.co.unk", company)
        if not c_short and is_company_form(company):
            raise Nak("icx.co.unk", company)
        if client == INTERNAL_CLIENT:
            return slot
        if not CL_SEG.match(client):
            raise Nak("icx.cl.unk", client)
        if cb.customers is not None:
            rec = cb.customers.get(client)
            if rec is None:
                raise Nak("icx.cl.unk", client)
            parent = rec.get("company") or DEFAULT_CLIENT_COMPANY
            p_short, p_full = _company_lookup(parent, cb)
            if c_short and p_short and c_short != p_short:
                raise Nak("icx.cl.unk", client)
            if not c_short and p_full and company != p_full:
                raise Nak("icx.cl.unk", client)
        return slot
    if len(slot) == 1 or slot == "C":
        raise Nak("icx.co.unk", slot)
    c_short, _c_full = _company_lookup(slot, cb)
    if c_short:
        return slot
    if CO_SHORT.match(slot):
        raise Nak("icx.co.unk", slot)
    if is_company_form(slot):
        # full code with no matching public short (should not happen for I/C-*)
        if _company_lookup(slot, cb)[0]:
            return slot
        raise Nak("icx.co.unk", slot)
    if slot == INTERNAL_CLIENT or slot in cb.lanes:
        return slot
    if cb.customers is not None:
        if slot in cb.customers:
            return slot
        if CL_SEG.match(slot):
            raise Nak("icx.cl.unk", slot)
    raise Nak("bad-lane", slot)

class Codebook:
    def __init__(self, path, expect_version=None, expect_sha12=None, clients_path=None):
        raw = open(path, "rb").read()
        self.path, self.sha12 = path, sha12_bytes(raw)
        if expect_sha12 and self.sha12 != expect_sha12:
            raise CodebookError("sha12 mismatch: got %s want %s" % (self.sha12, expect_sha12))
        text = raw.decode("utf-8")
        if path.endswith(".json"):
            d = json.loads(text)
        else:
            try:
                import yaml
            except ImportError:
                raise CodebookError("YAML codebook requires PyYAML")
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
        self.external = _names(d.get("external")) or {"EXT"}
        self.companies = _load_companies(d.get("companies"))
        self.customers = None   # optional private registry; numeric id stays here
        icx = d.get("icx") or {}
        self.icx = _names(icx.get("codes") if isinstance(icx, dict) else icx)
        self.paths = {str(k): str(v) for k, v in (d.get("paths") or {}).items()}
        sc = d.get("shortcuts") or {}
        self.shortcuts = {str(k): v for k, v in sc.items()}
        if not self.verbs: raise CodebookError("codebook has no verbs")
        if clients_path:
            self.bind_customers(clients_path)

    def bind_customers(self, path):
        self.customers = load_customers(path)

# --- line grammar (v1.1 input). Hop ">ICOM>" optional; PRI, CO.CLIENT/LANE, ticket optional (implied). ---
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

def expand(line, cb, thread=None, outbound=False):
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
    if i < len(toks) and looks_like_slot(toks[i], cb):
        lane = check_slot(toks[i], cb); i += 1
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
        if is_internal_slot(lane) or not why or not any(w.split(".")[0].split(",")[0] in P0_WHY for w in why):
            raise Nak("p0-misuse")
    if outbound or any(t in cb.external for t in tos):
        kv = {t.split("=", 1)[0]: t.split("=", 1)[1] for t in tail if "=" in t}
        if any(not kv.get(k) for k in OUTBOUND_KEYS):
            raise Nak("icx.ext.tok")
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

def process(line, cb, thread=None, outbound=False):
    """Return (ok, output_line)."""
    try: return True, expand(line, cb, thread, outbound=outbound)
    except Nak as n: return False, nak_line(line, n, cb)

def main(argv=None):
    ap = argparse.ArgumentParser(description="ICOM v1.1 expander + autoNAK")
    ap.add_argument("--codebook", required=True)
    ap.add_argument("--expect-version"); ap.add_argument("--expect-sha12")
    ap.add_argument("--state", help="thread state json for implied headers (0600)")
    ap.add_argument("--clients", default=os.environ.get("ICOM_CLIENTS") or os.environ.get("ICX_CLIENTS"),
                    help="private customer registry (YAML/JSON). Also ICOM_CLIENTS / ICX_CLIENTS.")
    ap.add_argument("--outbound", action="store_true",
                    help="require co= cl= topic= icx= (why=icx.ext.tok); also required when TO includes EXT")
    ap.add_argument("lines", nargs="*")
    a = ap.parse_args(argv)
    try: cb = Codebook(a.codebook, a.expect_version, a.expect_sha12, clients_path=a.clients)
    except (CodebookError, OSError, ValueError) as e:
        print("CODEBOOK-ERROR %s" % e, file=sys.stderr); return 2
    th = Thread(a.state)
    src = a.lines or [l.rstrip("\n") for l in sys.stdin if l.strip()]
    rc = 0
    for l in src:
        ok, out = process(l, cb, th, outbound=a.outbound); print(out); rc |= (0 if ok else 1)
    return rc

if __name__ == "__main__":
    sys.exit(main())
