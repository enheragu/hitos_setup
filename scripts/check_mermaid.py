#!/usr/bin/env python3
"""Lightweight Mermaid sanity check (no rendering / no chromium).

Catches the failure class that crashes GitHub's renderer with
"Cannot set properties of undefined (setting 'style')": a `linkStyle N ...`
that references an edge index >= the number of edges in that diagram.

Counts edges per ```mermaid``` block (handling `A & B --> C & D` fan-outs and
`A --> B --> C` chains) and flags any out-of-range linkStyle index.

Usage: python3 scripts/check_mermaid.py <file.md> [more.md ...]
"""
import re
import sys

ARROW = re.compile(r'-\.->|==>|-->|--x|--o|-\.-|===|---')

def count_edges(line):
    line = re.sub(r'\|[^|]*\|', '', line)              # drop edge labels |...|
    segs = ARROW.split(line)
    if len(segs) < 2:
        return 0
    counts = [len([t for t in s.split('&') if t.strip()]) for s in segs]
    return sum(a * b for a, b in zip(counts, counts[1:]))

def check_block(body, label):
    edges = 0
    refs = []   # (linkStyle index, line-in-block)
    for ln, raw in enumerate(body.splitlines(), 1):
        s = raw.strip()
        if s.startswith('linkStyle'):
            for m in re.findall(r'\d+', s.split('stroke')[0].replace('linkStyle', '', 1)):
                refs.append((int(m), ln))
            continue
        if s.startswith(('subgraph', 'end', 'style ', 'classDef', 'class ', 'direction',
                         '%%', 'flowchart', 'graph', 'linkStyle')) or not s:
            continue
        edges += count_edges(s)
    bad = [r for r in refs if r[0] >= edges]
    status = 'OK' if not bad else 'FAIL'
    print(f"  [{status}] {label}: {edges} edges, linkStyle max ref = "
          f"{max((r[0] for r in refs), default='-')}")
    for idx, ln in bad:
        print(f"        linkStyle {idx} (block line {ln}) is out of range (only 0..{edges-1})")
    return not bad

ok = True
for path in sys.argv[1:]:
    text = open(path).read()
    blocks = re.findall(r'```mermaid\n(.*?)```', text, re.S)
    print(f"{path}: {len(blocks)} mermaid block(s)")
    for i, b in enumerate(blocks, 1):
        ok &= check_block(b, f"block #{i}")
sys.exit(0 if ok else 1)
