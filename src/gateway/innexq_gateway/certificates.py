"""Deterministic certificate-release policy. No model, storage or external writes."""

from datetime import datetime

from innexq_contracts.certificates import (
    CertificateArtifact,
    CertificateCheck,
    CertificateDecision,
    CertificateSources,
    CheckName,
    CheckVerdict,
    HoldReason,
    SourceStamp,
)


def evaluate_certificate(
    customer_id: str, equipment_id: str, sources: CertificateSources, now: datetime
) -> CertificateDecision:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("evaluation requires a timezone-aware clock")

    def check(name: CheckName, reason: HoldReason) -> CertificateCheck:
        verdict: CheckVerdict = (
            "pass"
            if reason == "passed"
            else ("unknown" if reason in ("missing_evidence", "stale_evidence") else "fail")
        )
        return CertificateCheck(name=name, verdict=verdict, reason=reason)

    def freshness(source: SourceStamp | None) -> HoldReason:
        if source is None:
            return "missing_evidence"
        if not source.observed_at <= now < source.fresh_until:
            return "stale_evidence"
        return "passed"

    ownership = sources.ownership
    owner_reason = freshness(ownership)
    if (
        owner_reason == "passed"
        and ownership is not None
        and (ownership.customer_id != customer_id or ownership.equipment_id != equipment_id)
    ):
        owner_reason = "ownership_mismatch"

    certificate = sources.certificate
    cert_reason = freshness(certificate)
    if cert_reason == "passed" and certificate is not None:
        if certificate.accessible is not True:
            cert_reason = "document_unavailable"
        elif (
            ownership is None
            or certificate.customer_id != customer_id
            or certificate.equipment_id != equipment_id
            or certificate.serial_number != ownership.serial_number
        ):
            cert_reason = "document_mismatch"
        elif not certificate.valid_from <= now < certificate.valid_until:
            cert_reason = "certificate_outside_validity"
        elif certificate.revoked is not False:
            cert_reason = "revoked_or_unknown"

    service = sources.service
    service_reason = freshness(service)
    if service_reason == "passed" and service is not None:
        if (
            ownership is None
            or service.customer_id != customer_id
            or service.equipment_id != equipment_id
            or service.serial_number != ownership.serial_number
        ):
            service_reason = "service_mismatch"
        elif service.in_service is not True or not service.valid_from <= now < service.valid_until:
            service_reason = "service_not_current"

    checks = (
        check("ownership", owner_reason),
        check("certificate_validity", cert_reason),
        check("service_status", service_reason),
    )
    passed = all(item.verdict == "pass" for item in checks)
    artifact = None
    if passed and certificate is not None:
        artifact = CertificateArtifact(
            document_id=certificate.document_id,
            document_version=certificate.document_version,
            sha256=certificate.sha256,
        )
    return CertificateDecision(
        evaluated_at=now,
        sources=sources,
        checks=checks,
        outcome="release_ready" if passed else "operations_required",
        artifact=artifact,
    )
