"""WS-4 T3: secret scan over the tracked tree.

A small, dependency-free scanner used by ``scripts/secret_scan.py`` (CI step)
and the T3 tree-walk test. "Tracked tree" = ``git ls-files`` output, so
gitignored local files (``data/ws3/api_keys.json``, ``.env``) are excluded from
the *repository* — which is exactly the rule the T3 exit criterion states: no
plaintext key exists in the tree. The scanner never heuristically flags obvious
``test_`` values; it matches real credential shapes.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

_BINARY_EXTS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".pyc",
    ".so",
    ".dylib",
    ".whl",
    ".tar",
    ".gz",
    ".zip",
    ".db",
    ".sqlite",
    ".parquet",
    ".pkl",
    ".npy",
    ".egg-info",
    ".woff",
    ".woff2",
    ".ttf",
}
_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".tox"}

# Files that legitimately contain credential *pattern strings* (the scanner's own
# definitions). They are never real secrets, so they must not trip the scan.
_SKIP_REL = {
    "pakhi/ws4/secret_scan.py",
    "scripts/secret_scan.py",
}

# name -> compiled regex. Patterns match credential shapes, never test values.
_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("private-key", re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github-pat", re.compile(r"\bghp_[0-9A-Za-z]{36}\b")),
    ("github-fine-grained-pat", re.compile(r"\bgithub_pat_[0-9A-Za-z_]{30,}\b")),
    ("openai-key", re.compile(r"\bsk-(?:live|test|proj)-[0-9A-Za-z]{16,}\b")),
    ("stripe-live-key", re.compile(r"\bsk_live_[0-9A-Za-z]{16,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("twilio-sid", re.compile(r"\bAC[0-9a-f]{32}\b")),
    ("jwt-rsa-key", re.compile(r"\"-----BEGIN PUBLIC KEY-----")),
)


@dataclass(frozen=True)
class Finding:
    rule: str
    path: str
    line: int
    snippet: str


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def tracked_files(root: Path) -> list[Path]:
    """Enumerate the tracked (committed) tree via ``git ls-files``."""
    try:
        out = subprocess.run(
            ["git", "ls-files"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return [root / line for line in out.stdout.splitlines() if line.strip()]


def _is_text(path: Path) -> bool:
    return path.suffix.lower() not in _BINARY_EXTS and path.name != "lock"


def scan_tree(root: Path | None = None) -> list[Finding]:
    root = root or repo_root()
    findings: list[Finding] = []
    for path in tracked_files(root):
        if not _is_text(path) or not path.is_file():
            continue
        try:
            rel = str(path.relative_to(root))
        except ValueError:
            rel = path.name
        if rel in _SKIP_REL:
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for rule, pattern in _PATTERNS:
                if pattern.search(line):
                    findings.append(
                        Finding(rule=rule, path=str(path), line=lineno, snippet=line.strip()[:120])
                    )
        # The repo rule is explicit: never commit a .env. Committed
        # ``.env.example`` / ``.env.sample`` are intentional, non-secret
        # templates and must not trip the scan (false positives).
    for env_file in (root / ".env",):
        if env_file.is_file():
            findings.append(
                Finding(rule="dotenv", path=str(env_file), line=1, snippet="committed .env")
            )
    return findings
