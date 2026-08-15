"""CI secret-scan entrypoint: exit 0 when the tracked tree is clean.

Usage: python scripts/secret_scan.py [--verbose]
"""

from __future__ import annotations

import sys
from pathlib import Path

# Run from a fresh checkout without an editable install: repo root on path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pakhi.ws4.secret_scan import scan_tree

verbose = "--verbose" in sys.argv
findings = scan_tree()
if not findings:
    print("secret scan: clean")
    sys.exit(0)

for f in findings:
    print(f"[{f.rule}] {f.path}:{f.line}  {f.snippet}")
print(f"secret scan: {len(findings)} finding(s)")
sys.exit(1)
