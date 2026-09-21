"""Publish exact synthetic source PDFs, create-only; never OCR or approval results."""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
from azure.identity import AzureCliCredential
from innexq_api.certificate_repository import CertificateRegistry, PrivateCertificateRepository
from innexq_contracts.certificates import CertificateArtifact
from innexq_contracts.enterprise import EnterpriseDemoCatalog


def packet(directory: Path) -> tuple[CertificateRegistry, dict[str, bytes]]:
    directory = directory.resolve(strict=True)
    catalog = EnterpriseDemoCatalog.model_validate_json((directory / "catalog.json").read_bytes())
    manifest: dict[str, Any] = json.loads((directory / "manifest.json").read_bytes())
    if manifest.get("synthetic") is not True or manifest.get("as_of") != str(catalog.as_of):
        raise ValueError("a matching synthetic source manifest is required")
    files = {item["filename"]: item for item in manifest["documents"]}
    if len(files) != len(manifest["documents"]) or set(files) != {
        d.filename for d in catalog.documents
    }:
        raise ValueError("source manifest must identify every PDF once")
    artifacts = {}
    blobs = {}
    for document in catalog.documents:
        path = (directory / document.filename).resolve(strict=True)
        if not path.is_relative_to(directory):
            raise ValueError("source PDF escapes the selected packet directory")
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if (
            not content.startswith(b"%PDF-")
            or len(content) > 10_000_000
            or files[document.filename]["sha256"] != digest
            or files[document.filename]["bytes"] != len(content)
        ):
            raise ValueError("source PDF does not match its manifest")
        artifacts[document.document_id] = CertificateArtifact(
            document_id=document.document_id, document_version=digest, sha256=digest
        )
        blobs[f"pdf/{digest}.pdf"] = content
    registry = CertificateRegistry(
        date_convention="UTC-inclusive-calendar-date",
        catalog=catalog,
        artifacts=artifacts,
        # Explicit fictional source records. These values are authored here, not
        # inferred from OCR, used as model outcomes, or defaults for missing facts.
        revoked={d.document_id: False for d in catalog.documents if d.kind == "certificate"},
        in_service={e.equipment_id: True for e in catalog.equipment},
    )
    return registry, blobs


def upload(directory: Path, endpoint: str, tenant_id: str) -> int:
    registry, blobs = packet(directory)
    with AzureCliCredential(tenant_id=tenant_id) as credential:
        repository = PrivateCertificateRepository(endpoint, "certificate-sources", credential)
        token = credential.get_token("https://storage.azure.com/.default").token
        # Registry last: an interrupted publication cannot point to missing PDFs.
        blobs["registry.json"] = registry.model_dump_json().encode()
        with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
            for path, content in blobs.items():
                response = client.put(
                    f"{repository.origin}/{path}",
                    content=content,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "x-ms-version": "2023-11-03",
                        "x-ms-blob-type": "BlockBlob",
                        "If-None-Match": "*",
                        "Content-Type": "application/json"
                        if path == "registry.json"
                        else "application/pdf",
                    },
                )
                if response.status_code == 412:
                    existing, _ = repository._get(path, 10_000_000)
                    if existing != content:
                        raise ValueError("existing source differs; never overwrite a demo reset")
                elif response.status_code != 201:
                    raise ValueError(f"source upload failed: HTTP {response.status_code}")
    return len(blobs) - 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--upload", action="store_true", help="write new private source blobs")
    parser.add_argument("--endpoint")
    parser.add_argument("--tenant-id")
    args = parser.parse_args()
    registry, blobs = packet(args.directory)
    if args.upload:
        if not args.endpoint or not args.tenant_id:
            parser.error("upload requires the reviewed endpoint and tenant ID")
        count = upload(args.directory, args.endpoint, args.tenant_id)
        print(
            json.dumps({"source_pdfs_uploaded_or_verified": count, "extraction_performed": False})
        )
    else:
        print(
            json.dumps(
                {
                    "source_pdfs_validated": len(blobs),
                    "as_of": str(registry.catalog.as_of),
                    "uploaded": False,
                    "extraction_performed": False,
                }
            )
        )


if __name__ == "__main__":
    main()
