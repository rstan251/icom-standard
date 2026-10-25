#!/usr/bin/env python3
"""Validate ICOM public spec examples, producer fixtures, and sig vectors.

Copyright (c) 2026 Robert Stanley / Iron Noodle Technologies. MIT License.

Usage: python3 scripts/validate_schemas.py
Exit 0 = all checks passed. Needs: pip install -r scripts/requirements.txt
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
from pathlib import Path

try:
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import ValidationError
except ImportError:
    sys.stderr.write(
        "validate_schemas: install jsonschema first "
        "(pip install -r scripts/requirements.txt)\n"
    )
    sys.exit(2)

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )
    from cryptography.hazmat.primitives import serialization
except ImportError:
    sys.stderr.write(
        "validate_schemas: install cryptography first "
        "(pip install -r scripts/requirements.txt)\n"
    )
    sys.exit(2)

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"
EXAMPLES = SCHEMAS / "examples"
FIXTURES = SCHEMAS / "fixtures"
TEAM = FIXTURES / "team-notify"
NEGATIVE = FIXTURES / "negative"
NEG_FRAME = FIXTURES / "negative-frame"
VECTORS = SCHEMAS / "vectors" / "icom-sig-v1.json"

BUZZ_SCHEMA = SCHEMAS / "buzz-event.schema.json"
FRAME_SCHEMA = SCHEMAS / "icom-bc-frame.schema.json"

MAX_LINE_OCTETS = 1024
MID_HEX = 16

TS_RE = re.compile(
    r"^(?![\s\S]*[\r\n])\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
PEM_RE = re.compile(r"-----BEGIN [A-Z ]*(?:PRIVATE KEY|CERTIFICATE)-----")
KEY_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9]{8,}|gh[pousr]_[A-Za-z0-9]{8,}"
    r"|xox[abprs]-[A-Za-z0-9-]{8,}|AKIA[0-9A-Z]{12,})\b"
)
LONG_TOKEN_RE = re.compile(r"\b[A-Za-z0-9_+-]{40,}={0,2}")
ED25519_TAIL_RE = re.compile(r"ed25519:[0-9a-f]{12}:[A-Za-z0-9_-]{86}")
PUB43_RE = re.compile(r"\b[A-Za-z0-9_-]{43}\b")
BARE_SIG_RE = re.compile(r"\b[A-Za-z0-9_-]{86}\b")
# Tracker-style IDs that are not the public T-<digits> placeholder.
TICKET_ID_RE = re.compile(r"\b(?!T-\d+\b)[A-Z]{2,4}-\d+\b")
PUBLIC_ID_ALLOW = {"SHA-256", "UTF-8"}
# Lowercase 2-5 letter prefix, hyphen, eight hex digits. Allowlist is
# empty: no public file in this tree needs that form.
HEX_ID_RE = re.compile(r"\b[a-z]{2,5}-[0-9a-f]{8}\b")
HEX_ID_ALLOW: set[str] = set()
EMAIL_RE = re.compile(r"[\w.*+-]+@[\w-]+(?:\.[\w-]+)+")
ALLOW_EMAIL_DOMAIN = re.compile(r"@(?:example|invalid|test)\.(?:com|org|net)\b", re.I)
INTERNAL_DOMAIN_RE = re.compile(
    r"(?i)\b[\w-]+\.(?:internal|local|lan|corp)\b"
)
VENDOR_RE = re.compile(
    r"(?i)\b(?:cursor|openai|anthropic|claude|chatgpt|gpt-[0-9]|grok|"
    r"gemini|copilot|midjourney|llama-?[0-9]|mistral)\b"
)
ALLOW_DOMAIN_LINE = re.compile(
    r"example\.(?:com|org|net)|json-schema\.org|github\.com", re.I
)

HASH_TYPE = {
    "icom": "icom",
    "gauntlet": "gauntlet",
    "gauntlet-verdict": "gauntlet",
    "ticket-migration": "ticket-migration",
    "migration": "ticket-migration",
    "icom-alert": "icom-alert",
}


def load_json(path: Path):
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def validator_for(schema_path: Path) -> Draft202012Validator:
    schema = load_json(schema_path)
    checker = Draft202012Validator.FORMAT_CHECKER
    return Draft202012Validator(schema, format_checker=checker)


def check_schema(label: str, schema_path: Path, example_path: Path) -> str | None:
    inst = load_json(example_path)
    try:
        validator_for(schema_path).validate(inst)
    except ValidationError as exc:
        return "%s: %s: %s" % (label, example_path.name, exc.message)
    return None


def expect_schema_fail(schema_path: Path, example_path: Path) -> str | None:
    inst = load_json(example_path)
    try:
        validator_for(schema_path).validate(inst)
    except ValidationError:
        return None
    return "negative %s unexpectedly passed" % example_path.name


def frame_wire(inst: dict) -> str:
    hop = inst.get("hop", 0)
    kind = inst.get("kind")
    if kind == "single":
        hop_tok = ("h=%d " % hop) if hop else ""
        return "IC1 S " + hop_tok + inst["line"]
    if kind == "fragment":
        return "IC1 F %s %d/%d h=%d %s" % (
            inst["msgid"],
            inst["index"],
            inst["total"],
            hop,
            inst["chunk"],
        )
    raise ValueError("unknown kind")


def walk_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for value in obj.values():
            yield from walk_strings(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from walk_strings(value)


def check_wire(example_path: Path) -> str | None:
    inst = load_json(example_path)
    wire = inst.get("wire")
    if not wire:
        return None
    if "\n" in wire or "\r" in wire:
        return "%s: wire contains a newline" % example_path.name
    try:
        expect = frame_wire(inst)
    except (KeyError, ValueError) as exc:
        return "%s: %s" % (example_path.name, exc)
    if wire != expect:
        return "%s: wire != frame mapping" % example_path.name
    return None


def check_octets(example_path: Path) -> str | None:
    inst = load_json(example_path)
    for s in walk_strings(inst):
        if "\n" in s or "\r" in s:
            return "%s: string contains CR/LF" % example_path.name
    for key in ("line", "chunk"):
        if key not in inst:
            continue
        n = len(inst[key].encode("utf-8"))
        if n > MAX_LINE_OCTETS:
            return "%s: %s is %d octets (cap %d)" % (
                example_path.name, key, n, MAX_LINE_OCTETS
            )
    if inst.get("kind") == "fragment":
        if "hop" not in inst:
            return "%s: fragment missing hop" % example_path.name
        if inst["index"] > inst["total"]:
            return "%s: index > total" % example_path.name
        if re.search(r"(?:^| )hop=", inst.get("chunk", "")):
            return "%s: hop leaked into chunk" % example_path.name
    line = inst.get("line", "")
    if re.search(r"(?:^| )hop=", line):
        return "%s: hop= on signed ICOM line" % example_path.name
    return None


def check_buzz_coverage() -> str | None:
    types: set[str] = set()
    saw_text = False
    for path in sorted(EXAMPLES.glob("buzz-event-*.json")):
        inst = load_json(path)
        if "text" in inst:
            saw_text = True
        if "event" in inst:
            types.add(inst["event"]["type"])
    need_any = [
        {"icom"},
        {"gauntlet", "gauntlet-verdict"},
        {"ticket-migration", "migration"},
        {"icom-alert"},
    ]
    for group in need_any:
        if types.isdisjoint(group):
            return "buzz examples missing type family %s" % sorted(group)
    if not saw_text:
        return "buzz examples missing text branch"
    return None


def check_timestamps() -> str | None:
    paths = list(EXAMPLES.glob("buzz-event-*.json")) + list(TEAM.glob("*.json"))
    for path in paths:
        inst = load_json(path)
        ev = inst.get("event")
        if not ev:
            continue
        ts = ev.get("ts", "")
        if not TS_RE.match(ts):
            return "%s: ts is not RFC 3339 (Z or offset)" % path.name
    return None


def check_fragment_pair() -> str | None:
    groups: dict[str, list] = {}
    for path in sorted(EXAMPLES.glob("icom-bc-fragment*.json")):
        inst = load_json(path)
        groups.setdefault(inst["msgid"], []).append(inst)
    if len(groups) < 2:
        return "expected at least two fragment pairs"
    saw_qc = False
    saw_h5 = False
    for msgid, items in groups.items():
        items.sort(key=lambda row: row["index"])
        totals = {row["total"] for row in items}
        if len(totals) != 1:
            return "fragment msgid %s total mismatch" % msgid
        total = items[0]["total"]
        if {row["index"] for row in items} != set(range(1, total + 1)):
            return "fragment msgid %s incomplete index set" % msgid
        line = "".join(row["chunk"] for row in items)
        if "\n" in line or "\r" in line:
            return "reassembled fragment contains a newline"
        expect = hashlib.sha256(line.encode()).hexdigest()[:MID_HEX]
        if msgid != expect:
            return "fragment msgid %s != SHA-256(line)[:%d]" % (msgid, MID_HEX)
        if not line.startswith("@"):
            return "reassembled fragment is not an ICOM line"
        if line.startswith("@QC>ICOM>LEAD "):
            saw_qc = True
        if items[-1]["chunk"].startswith("h=5"):
            saw_h5 = True
            if " h=5 " not in line:
                return "h=5 fixture line missing h=5 token"
    if not saw_qc:
        return "missing QC ASK fragment pair"
    if not saw_h5:
        return "missing split-before-h=5 fragment pair"
    return None


def check_id_hashes() -> list[str]:
    hits: list[str] = []
    manifest = load_json(FIXTURES / "id-checks.json")
    for row in manifest:
        path = SCHEMAS / row["file"]
        inst = load_json(path)
        ev = inst["event"]
        expect = hashlib.sha256(
            ("%s|%s" % (row["hash_type"], row["key"])).encode()
        ).hexdigest()[:20]
        if ev["id"] != expect:
            hits.append(
                "%s: id %s != sha256(%s|%s)[:20] = %s"
                % (path.name, ev["id"], row["hash_type"], row["key"], expect)
            )
        hashed = HASH_TYPE.get(ev["type"])
        if hashed and hashed != row["hash_type"]:
            hits.append(
                "%s: hash_type %s does not match event type %s"
                % (path.name, row["hash_type"], ev["type"])
            )
    return hits


def b64url_decode(s: str) -> bytes:
    pad = "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode(s + pad)


def check_vectors() -> list[str]:
    hits: list[str] = []
    doc = load_json(VECTORS)
    if doc.get("test") is not True:
        hits.append("vectors: missing test=true")
    roles = doc["roles"]
    for role, meta in roles.items():
        seed = hashlib.sha256(("ICOM-BC-TEST-ONLY-%s" % role).encode()).digest()
        key = Ed25519PrivateKey.from_private_bytes(seed)
        pub = key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        kid = hashlib.sha256(pub).hexdigest()[:12]
        pub_b64 = base64.urlsafe_b64encode(pub).rstrip(b"=").decode("ascii")
        if kid != meta["kid"]:
            hits.append("vectors: role %s kid mismatch" % role)
        if pub_b64 != meta["pub"]:
            hits.append("vectors: role %s pub mismatch" % role)
    for vec in doc["vectors"]:
        role = vec["role"]
        seed = hashlib.sha256(("ICOM-BC-TEST-ONLY-%s" % role).encode()).digest()
        key = Ed25519PrivateKey.from_private_bytes(seed)
        pub = key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        M = vec["domain"].encode() + b"\x00" + vec["joined"].encode()
        try:
            Ed25519PublicKey.from_public_bytes(pub).verify(
                b64url_decode(vec["sig"]), M
            )
        except InvalidSignature:
            hits.append("vectors: %s verify failed" % vec["id"])
        if vec["sig"] not in vec["line"]:
            hits.append("vectors: %s sig not on line" % vec["id"])
        if "msgid" in vec:
            mid = hashlib.sha256(vec["line"].encode()).hexdigest()[:MID_HEX]
            if mid != vec["msgid"]:
                hits.append("vectors: %s msgid mismatch" % vec["id"])
        if re.search(r"(?:^|\s)hop=", vec["line"]) or re.search(
            r"(?:^|\s)hop=", vec["joined"]
        ):
            hits.append("vectors: %s hop= on signed line" % vec["id"])
    return hits


def check_hnc_order() -> str | None:
    path = EXAMPLES / "icom-bc-single-hub-hnc.json"
    line = load_json(path)["line"]
    if " hnc=" not in line:
        return "hub-hnc example missing hnc="
    if " hsig=" not in line:
        return "hub-hnc example missing hsig="
    if line.find(" hnc=") > line.find(" hsig="):
        return "hnc= must precede hsig="
    return None


def check_nak_shape() -> str | None:
    line = load_json(EXAMPLES / "icom-bc-nak.json")["line"]
    if "cb=" not in line:
        return "NAK example missing cb="
    if "hsig=" not in line:
        return "NAK example missing hsig="
    if "ts=" not in line:
        return "NAK example missing ts="
    if "sts=" in line or " nc=" in line or " sig=" in line:
        return "NAK example still has agent sig tokens"
    if re.search(r"(?:^|\s)hop=", line):
        return "NAK example has hop= on the line"
    return None


def check_producer_alerts() -> str | None:
    p1 = load_json(TEAM / "09-icom-alert-upper-p1.json")["event"]
    p3 = load_json(TEAM / "10-icom-alert-upper-p3.json")["event"]
    dash = load_json(TEAM / "11-dash-fallback.json")["event"]
    if p1.get("severity") is not None:
        return "09-icom-alert-upper-p1 must omit severity"
    if p1.get("status") != "P1" or p1.get("verb") != "HUB-KEY-FAIL-CLOSED":
        return "09-icom-alert-upper-p1 is not the producer uppercase/P1 form"
    if p3.get("severity") is not None:
        return "10-icom-alert-upper-p3 must omit severity"
    if p3.get("status") != "P3" or p3.get("verb") != "HUB-KEY-RESTORED":
        return "10-icom-alert-upper-p3 is not the producer uppercase/P3 form"
    for key in ("from", "to", "ticket", "verb"):
        if dash.get(key) != "-":
            return "11-dash-fallback %s is not -" % key
    return None


def extra_deny_terms() -> list[str]:
    raw = os.environ.get("ICOM_HYGIENE_DENY", "")
    return [term.strip() for term in raw.split(",") if term.strip()]


def check_hygiene() -> list[str]:
    hits: list[str] = []
    roots = [
        ROOT / "spec",
        ROOT / "README.md",
        ROOT / "scripts",
        ROOT / ".github",
        SCHEMAS,
    ]
    files: list[Path] = []
    for root in roots:
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            files.extend(sorted(p for p in root.rglob("*") if p.is_file()))
    deny_terms = extra_deny_terms()
    for path in files:
        if "hygiene-negative" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT)
        in_vectors = "vectors" in path.parts
        skip_long = "negative" in path.parts or path.name.endswith("-too-long.json")
        skip_vendor = path.name == "validate_schemas.py"
        for i, line in enumerate(text.splitlines(), 1):
            if IPV4_RE.search(line):
                hits.append("%s:%d ipv4" % (rel, i))
            if PEM_RE.search(line):
                hits.append("%s:%d pem" % (rel, i))
            if KEY_RE.search(line):
                hits.append("%s:%d key-prefix" % (rel, i))
            for m in TICKET_ID_RE.finditer(line):
                if m.group(0) not in PUBLIC_ID_ALLOW:
                    hits.append("%s:%d ticket-id %s" % (rel, i, m.group(0)))
            for m in HEX_ID_RE.finditer(line):
                if m.group(0) not in HEX_ID_ALLOW:
                    hits.append("%s:%d hex-id %s" % (rel, i, m.group(0)))
            for m in EMAIL_RE.finditer(line):
                if not ALLOW_EMAIL_DOMAIN.search(m.group(0)):
                    hits.append("%s:%d email %s" % (rel, i, m.group(0)))
            cleaned = ALLOW_DOMAIN_LINE.sub(" ", line)
            if INTERNAL_DOMAIN_RE.search(cleaned):
                hits.append("%s:%d internal-domain" % (rel, i))
            if not skip_vendor and VENDOR_RE.search(line):
                hits.append("%s:%d vendor-or-model" % (rel, i))
            for term in deny_terms:
                if term.lower() in line.lower():
                    hits.append("%s:%d deny-term" % (rel, i))
            stripped = ED25519_TAIL_RE.sub(" ", line)
            stripped = BARE_SIG_RE.sub(" ", stripped)
            if in_vectors:
                stripped = PUB43_RE.sub(" ", stripped)
            if not skip_long and LONG_TOKEN_RE.search(stripped):
                hits.append("%s:%d long-token" % (rel, i))
    return hits


def check_hygiene_negatives() -> str | None:
    path = FIXTURES / "hygiene-negative" / "01-prefix-8hex.txt"
    if not path.is_file():
        return "missing hygiene-negative prefix-8hex fixture"
    if not HEX_ID_RE.search(path.read_text(encoding="utf-8")):
        return "hex-id pattern missed hygiene-negative fixture"
    sample = "-".join(("tkt", "ab" * 4))
    if not HEX_ID_RE.search(sample):
        return "hex-id pattern missed constructed prefix-8hex"
    return None


def main() -> int:
    errors: list[str] = []
    checks = 0

    buzz_examples = sorted(EXAMPLES.glob("buzz-event-*.json"))
    frame_examples = sorted(EXAMPLES.glob("icom-bc-*.json"))
    team_fix = sorted(TEAM.glob("*.json"))
    neg_fix = sorted(NEGATIVE.glob("*.json"))
    neg_frame = sorted(NEG_FRAME.glob("*.json"))

    for path in buzz_examples + team_fix:
        checks += 1
        err = check_schema("buzz", BUZZ_SCHEMA, path)
        if err:
            errors.append(err)
    for path in frame_examples:
        checks += 1
        err = check_schema("frame", FRAME_SCHEMA, path)
        if err:
            errors.append(err)
        checks += 1
        err = check_wire(path)
        if err:
            errors.append(err)
        checks += 1
        err = check_octets(path)
        if err:
            errors.append(err)
    for path in neg_fix:
        checks += 1
        err = expect_schema_fail(BUZZ_SCHEMA, path)
        if err:
            errors.append(err)
    for path in neg_frame:
        checks += 1
        err = expect_schema_fail(FRAME_SCHEMA, path)
        if err:
            errors.append(err)

    for fn in (
        check_buzz_coverage,
        check_timestamps,
        check_fragment_pair,
        check_nak_shape,
        check_hnc_order,
        check_producer_alerts,
        check_hygiene_negatives,
    ):
        checks += 1
        err = fn()
        if err:
            errors.append(err)

    id_hits = check_id_hashes()
    checks += max(1, len(load_json(FIXTURES / "id-checks.json")))
    errors.extend(id_hits)

    vec_hits = check_vectors()
    checks += 1 + len(load_json(VECTORS)["vectors"])
    errors.extend(vec_hits)

    checks += 1
    errors.extend(check_hygiene())

    passed = checks - len(errors)
    for err in errors:
        print("FAIL", err)
    print("validate_schemas: TOTAL=%d PASS=%d FAIL=%d" % (checks, passed, len(errors)))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
