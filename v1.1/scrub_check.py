#!/usr/bin/env python3
"""Scrub check for the public export: reports any IPs, hostnames, server ids,
absolute filesystem paths, keys/tokens, emails, phone numbers, short-id
shapes, or denylisted names/codes. Exit 0 = 0 hits, 1 = hits found.

Copyright (c) 2026 Robert Stanley / Iron Noodle Technologies. MIT License.

Usage: scrub_check.py [--deny FILE] [DIR]
  --deny FILE  private denylist kept OUTSIDE the export, lines "code:XYZ"
               (case-sensitive whole token) or "name:word" (case-insensitive).
Allowed by design: RFC 2606 reserved example domains, line-1 shebangs,
public tkt- ticket placeholders.
"""
import os, re, sys

PATTERNS = [
    ("ipv4", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("ipv6", re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){3,7}[0-9a-fA-F]{1,4}\b")),
    ("email", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}\b")),
    ("hostname", re.compile(r"\b(?:[a-z0-9-]+\.)+(?:com|net|org|io|ai|dev|app|cloud|co|us|local|internal|lan|host|xyz|tech|sh)\b", re.I)),
    ("url", re.compile(r"\b(?:https?|ssh|ftp)://", re.I)),
    ("srv-id", re.compile(r"\b(?:srv|vps|host|node)[-_]?\d{2,}\b", re.I)),
    ("abs-path", re.compile(r"(?<![\w~.)\]])/(?:[A-Za-z0-9._-]+/)+[A-Za-z0-9._-]*")),
    ("home-path", re.compile(r"~/[A-Za-z0-9._-]")),
    ("key-prefix", re.compile(r"\b(?:sk-[A-Za-z0-9]{8,}|gh[pousr]_[A-Za-z0-9]{8,}|xox[abprs]-[A-Za-z0-9-]{8,}|AKIA[0-9A-Z]{12,}|AIza[0-9A-Za-z_-]{20,}|pit-[A-Za-z0-9-]{8,})")),
    ("pem", re.compile(r"-----BEGIN [A-Z ]*(?:PRIVATE KEY|CERTIFICATE)-----")),
    ("secret-assign", re.compile(r"(?i)\b(?:api[_-]?key|secret|password|passwd|bearer|auth[_-]?token|access[_-]?token)\b\s*[:=]\s*['\"]?[A-Za-z0-9_\-./+]{8,}")),
    ("long-hex/b64", re.compile(r"\b[A-Za-z0-9_\-+/]{40,}={0,2}")),
    ("phone", re.compile(r"(?<![\w#.-])(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b")),
    ("ticket-shape", re.compile(r"\b[a-z]{2,5}-[0-9a-f]{8}\b")),
]
ALLOW_DOMAINS = re.compile(r"\bexample\.(?:com|org|net)\b|\.(?:test|invalid|example)\b", re.I)
ALLOW_TICKET_SHAPE = re.compile(r"\btkt-[0-9a-f]{8}\b")  # public placeholder only

def load_deny(path):
    codes, names = [], []
    if path:
        for l in open(path, encoding="utf-8"):
            l = l.strip()
            if l.startswith("code:"): codes.append(re.escape(l[5:]))
            elif l.startswith("name:"): names.append(re.escape(l[5:]))
    out = []
    if codes: out.append(("deny-code", re.compile(r"(?<![A-Za-z0-9])(?:%s)(?![A-Za-z0-9])" % "|".join(codes))))
    if names: out.append(("deny-name", re.compile(r"(?i)(?<![A-Za-z0-9])(?:%s)(?![A-Za-z0-9])" % "|".join(names))))
    return out

def scan(root, pats):
    hits, files = [], 0
    for dp, dn, fn in os.walk(root):
        dn[:] = sorted(d for d in dn if d not in (".work", "__pycache__", ".git"))
        for f in sorted(fn):
            p = os.path.join(dp, f); rel = os.path.relpath(p, root); files += 1
            hits += [(rel, 0, "filename", m.group(0)) for n, rx in pats if n.startswith("deny") for m in rx.finditer(f)]
            try: text = open(p, encoding="utf-8").read()
            except UnicodeDecodeError: hits.append((rel, 0, "binary", "-")); continue
            for i, line in enumerate(text.splitlines(), 1):
                if i == 1 and line.startswith("#!"): continue
                clean = ALLOW_TICKET_SHAPE.sub(" ", ALLOW_DOMAINS.sub(" ", line))
                for name, rx in pats:
                    for m in rx.finditer(clean): hits.append((rel, i, name, m.group(0)))
    return files, hits

def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv); deny = None
    if "--deny" in a: i = a.index("--deny"); deny = a[i + 1]; del a[i:i + 2]
    root = a[0] if a else os.path.dirname(os.path.abspath(__file__))
    pats = PATTERNS + load_deny(deny)
    files, hits = scan(root, pats)
    for rel, ln, name, val in hits: print("HIT %s:%d %s %r" % (rel, ln, name, val[:60]))
    print("scrub_check: files=%d patterns=%d denylist=%s hits=%d" % (files, len(pats), "yes" if deny else "no", len(hits)))
    return 1 if hits else 0

if __name__ == "__main__":
    sys.exit(main())
