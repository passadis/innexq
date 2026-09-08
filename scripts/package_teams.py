"""Build a private Teams app ZIP without credentials or cloud operations."""

from __future__ import annotations

import argparse
import json
import struct
import zlib
from pathlib import Path
from string import Template
from urllib.parse import urlsplit
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]


def icon_png(size: int, *, outline: bool) -> bytes:
    """Original geometric Q mark. White transparent outline / teal color badge."""
    pixels = bytearray()
    for y in range(size):
        pixels.append(0)  # PNG scanline filter.
        for x in range(size):
            nx, ny = (x + 0.5) / size, (y + 0.5) / size
            ring = 0.12 < (nx - 0.5) ** 2 + (ny - 0.46) ** 2 < 0.19
            tail = 0.56 < nx < 0.83 and abs(ny - nx + 0.04) < 0.06
            if ring or tail:
                rgba = (255, 255, 255, 255)
            else:
                rgba = (0, 0, 0, 0) if outline else (21, 55, 71, 255)
            pixels.extend(rgba)

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(pixels)))
        + chunk(b"IEND", b"")
    )


def build_package(bot_client_id: str, api_base_url: str, output: Path) -> Path:
    bot_client_id = str(UUID(bot_client_id))
    url = urlsplit(api_base_url)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path not in ("", "/")
        or url.port not in (None, 443)
    ):
        raise ValueError("API URL must be an HTTPS origin without credentials, query or path")
    base = f"https://{url.hostname}"
    template = Template((ROOT / "teams/manifest.template.json").read_text(encoding="utf-8"))
    # JSON Schema's $schema is a literal, not a template variable.
    rendered = template.safe_substitute(
        BOT_CLIENT_ID=bot_client_id, API_BASE_URL=base, API_HOST=url.hostname
    )
    manifest = json.loads(rendered)
    if "${" in rendered:
        raise ValueError("manifest contains unresolved placeholders")
    if output.exists():
        raise FileExistsError("choose a new output path; packages are not overwritten")
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "x", compression=ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))
        archive.writestr("color.png", icon_png(192, outline=False))
        archive.writestr("outline.png", icon_png(32, outline=True))
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bot-client-id", required=True)
    parser.add_argument("--api-base-url", required=True)
    parser.add_argument("--output", type=Path, default=ROOT / ".azure/innexq-teams.zip")
    args = parser.parse_args()
    print(build_package(args.bot_client_id, args.api_base_url, args.output))


if __name__ == "__main__":
    main()
