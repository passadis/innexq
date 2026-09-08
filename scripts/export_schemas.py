"""Write or verify the committed InnexQ v1 JSON schemas."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from innexq_contracts.schema_export import schema_documents

SCHEMA_DIRECTORY = Path("src/contracts/schemas/v1")


def rendered_schemas() -> dict[str, str]:
    """Render schemas in their canonical repository format."""

    return {
        filename: json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        for filename, document in schema_documents().items()
    }


def write_schemas() -> None:
    SCHEMA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    for filename, content in rendered_schemas().items():
        (SCHEMA_DIRECTORY / filename).write_text(content, encoding="utf-8", newline="\n")


def schemas_are_current() -> bool:
    return all(
        (SCHEMA_DIRECTORY / filename).is_file()
        and (SCHEMA_DIRECTORY / filename).read_text(encoding="utf-8") == content
        for filename, content in rendered_schemas().items()
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if schemas need regeneration")
    args = parser.parse_args()

    if args.check:
        if not schemas_are_current():
            print("JSON schemas are missing or stale; run scripts/export_schemas.py")
            return 1
        print("JSON schemas are current")
        return 0

    write_schemas()
    print(f"Wrote {len(rendered_schemas())} schemas to {SCHEMA_DIRECTORY}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
