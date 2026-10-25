#!/usr/bin/env python3
"""Validate ICOM public spec examples against their JSON Schemas.

Copyright (c) 2026 Robert Stanley / Iron Noodle Technologies. MIT License.

Usage: python3 scripts/validate_schemas.py
Exit 0 = all checks passed. Needs: pip install -r scripts/requirements.txt
"""
from __future__ import annotations

import json
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

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"
EXAMPLES = SCHEMAS / "examples"

BUZZ_SCHEMA = SCHEMAS / "buzz-event.schema.json"
FRAME_SCHEMA = SCHEMAS / "icom-bc-frame.schema.json"

BUZZ_EXAMPLES = [
    EXAMPLES / "buzz-event-icom.json",
    EXAMPLES / "buzz-event-gauntlet-verdict.json",
    EXAMPLES / "buzz-event-plt19-migration.json",
]
FRAME_EXAMPLES = [
    EXAMPLES / "icom-bc-single-fyi.json",
    EXAMPLES / "icom-bc-single-signed.json",
    EXAMPLES / "icom-bc-fragment-1.json",
    EXAMPLES / "icom-bc-fragment-2.json",
]

TS_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)
IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
PEM_RE = re.compile(r"-----BEGIN [A-Z ]*(?:PRIVATE KEY|CERTIFICATE)-----")
KEY_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9]{8,}|gh[pousr]_[A-Za-z0-9]{8,}"
    r"|xox[abprs]-[A-Za-z0-9-]{8,}|AKIA[0-9A-Z]{12,})\b"
)
LONG_TOKEN_RE = re.compile(r"\b[A-Za-z0-9_\-+/]{40,}={0,2}")


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


def check_wire(example_path: Path) -> str | None:
    inst = load_json(example_path)
    wire = inst.get("wire")
    if not wire:
        return None
    if "\n" in wire or "\r" in wire:
        return "%s: wire contains a newline" % example_path.name
    kind = inst.get("kind")
    if kind == "single":
        expect = "IC1 S " + inst["line"]
        if wire != expect:
            return "%s: wire != 'IC1 S ' + line" % example_path.name
        return None
    if kind == "fragment":
        expect = "IC1 F %s %d/%d %s" % (
            inst["msgid"],
            inst["index"],
            inst["total"],
            inst["chunk"],
        )
        if wire != expect:
            return "%s: wire != IC1 F mapping" % example_path.name
        return None
    return "%s: unknown kind" % example_path.name


def check_buzz_types() -> str | None:
    seen = set()
    for path in BUZZ_EXAMPLES:
        seen.add(load_json(path)["event"]["type"])
    need = {"icom", "gauntlet-verdict", "plt19-migration"}
    missing = need - seen
    if missing:
        return "buzz examples missing types: %s" % ", ".join(sorted(missing))
    extra = seen - need
    if extra:
        return "buzz examples have unexpected types: %s" % ", ".join(sorted(extra))
    return None


def check_buzz_timestamps() -> str | None:
    for path in BUZZ_EXAMPLES:
        ts = load_json(path)["event"]["ts"]
        if not TS_RE.match(ts):
            return "%s: ts is not UTC date-time" % path.name
    return None


def check_fragment_pair() -> str | None:
    a = load_json(EXAMPLES / "icom-bc-fragment-1.json")
    b = load_json(EXAMPLES / "icom-bc-fragment-2.json")
    if a["msgid"] != b["msgid"] or a["total"] != b["total"]:
        return "fragment pair msgid/total mismatch"
    if {a["index"], b["index"]} != {1, 2}:
        return "fragment pair index set is not {1,2}"
    line = a["chunk"] + b["chunk"]
    if not line.startswith("@QC>ICOM>LEAD "):
        return "reassembled fragment is not an ICOM line"
    if "\n" in line or "\r" in line:
        return "reassembled fragment contains a newline"
    if "sig=" in line and not line.rstrip().endswith("<b64url-86>"):
        return "example signature placeholder drifted"
    return None


def check_hygiene() -> list[str]:
    hits: list[str] = []
    roots = [ROOT / "spec", EXAMPLES]
    for root in roots:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            rel = path.relative_to(ROOT)
            for i, line in enumerate(text.splitlines(), 1):
                if IPV4_RE.search(line):
                    hits.append("%s:%d ipv4" % (rel, i))
                if PEM_RE.search(line):
                    hits.append("%s:%d pem" % (rel, i))
                if KEY_RE.search(line):
                    hits.append("%s:%d key-prefix" % (rel, i))
                if LONG_TOKEN_RE.search(line):
                    hits.append("%s:%d long-token" % (rel, i))
    return hits


def main() -> int:
    errors: list[str] = []
    checks = 0

    for path in BUZZ_EXAMPLES:
        checks += 1
        err = check_schema("buzz", BUZZ_SCHEMA, path)
        if err:
            errors.append(err)
    for path in FRAME_EXAMPLES:
        checks += 1
        err = check_schema("frame", FRAME_SCHEMA, path)
        if err:
            errors.append(err)
        checks += 1
        err = check_wire(path)
        if err:
            errors.append(err)

    for fn in (check_buzz_types, check_buzz_timestamps, check_fragment_pair):
        checks += 1
        err = fn()
        if err:
            errors.append(err)

    checks += 1
    errors.extend(check_hygiene())

    passed = checks - len(errors)
    for err in errors:
        print("FAIL", err)
    print("validate_schemas: TOTAL=%d PASS=%d FAIL=%d" % (checks, passed, len(errors)))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
