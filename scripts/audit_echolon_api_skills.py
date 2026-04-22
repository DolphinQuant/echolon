#!/usr/bin/env python3
"""Audit every echolon public symbol imported by qorka's coding_agent.

Scans the qorka repo's modules/coding_agent/ and lib/agent_framework/
for `from echolon...` and `import echolon...` statements. Emits a
deduped list — one line per unique symbol — that Task 7 uses to know
which SKILL.md files to write.

Usage:
    python scripts/audit_echolon_api_skills.py \\
      --qorka-path /home/yzj/projects/quantitive_trading/qorka \\
      --output audit_output.txt
"""
import argparse
import ast
import sys
from pathlib import Path


def find_echolon_imports(qorka_path: Path) -> set[str]:
    """Walk the relevant qorka directories + collect every echolon-sourced symbol."""
    roots = [
        qorka_path / "modules" / "coding_agent",
        qorka_path / "lib" / "agent_framework",
        qorka_path / "orchestrator",
        qorka_path / "modules" / "indicators",
    ]
    symbols: set[str] = set()

    for root in roots:
        if not root.is_dir():
            continue
        for py in root.rglob("*.py"):
            try:
                tree = ast.parse(py.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError) as e:
                print(f"skip {py}: {e}", file=sys.stderr)
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.module and node.module.startswith("echolon"):
                        for alias in node.names:
                            symbols.add(f"{node.module}.{alias.name}")
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith("echolon"):
                            symbols.add(alias.name)
    return symbols


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qorka-path", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    symbols = sorted(find_echolon_imports(args.qorka_path))
    args.output.write_text("\n".join(symbols) + "\n")
    print(f"found {len(symbols)} unique echolon imports in qorka")
    for s in symbols:
        print(f"  {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
