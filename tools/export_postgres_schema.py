"""Export the hosted PostgreSQL snapshot from an empty, synthetic SQLite store.

Run from the checkout: python tools/export_postgres_schema.py [--check].
No configured store, environment file, network, or database server is accessed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import runpy
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aiqa.store.postgres_schema import build_manifest, compile_sqlite_schema, render_schema


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify generated artifacts without changing files")
    args = parser.parse_args()
    environment = runpy.run_path(str(ROOT / "migrations/env.py"))
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys=ON")
    environment["ensure_history"](connection)
    revisions = environment["revisions"]()
    for _, apply in revisions:
        apply(connection)
    statements = compile_sqlite_schema(connection)
    manifest = build_manifest(connection, statements, revisions[-1][0])
    outputs = {
        ROOT / "src/aiqa/store/sql/hosted_v1.sql": render_schema(statements),
        ROOT / "src/aiqa/store/sql/hosted_v1.json": json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    }
    connection.close()
    for path, content in outputs.items():
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != content:
                raise SystemExit(f"snapshot differs: {path.relative_to(ROOT)}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8", newline="\n") as output:
                output.write(content)
    print(json.dumps(manifest["counts"], sort_keys=True))


if __name__ == "__main__":
    main()
