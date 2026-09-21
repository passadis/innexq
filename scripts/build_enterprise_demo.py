"""Emit validated source records and escaped HTML for the offline PDF seed renderer."""

import argparse
import json
from datetime import date

from innexq_gateway.demo_catalog import build_demo_catalog
from innexq_gateway.demo_documents import render_demo_document


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", required=True, type=date.fromisoformat)
    args = parser.parse_args()
    catalog = build_demo_catalog(args.as_of)
    print(
        json.dumps(
            {
                "catalog": catalog.model_dump(mode="json"),
                "documents": [
                    {"filename": item.filename, "html": render_demo_document(catalog, item)}
                    for item in catalog.documents
                ],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
