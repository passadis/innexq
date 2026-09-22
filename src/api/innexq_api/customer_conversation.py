"""Scoped interpretation, read-only answers and explicit customer intent confirmation."""

import re
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from innexq_contracts.customer_conversation import (
    CustomerCitation,
    CustomerInterpretation,
    CustomerMessage,
    CustomerMessageRecord,
    CustomerReply,
    CustomerRequestContext,
)
from innexq_gateway.certificates import evaluate_certificate

from innexq_api.certificates import EvidenceUnavailable
from innexq_api.controller import Denied
from innexq_api.store import Conflict

if TYPE_CHECKING:
    from innexq_api.certificate_runtime import CertificateApplication


class CustomerConversation:
    """All identity comes from verified claims. Model proposals confer no authority."""

    def __init__(self, app: "CertificateApplication") -> None:
        self.app = app

    def _read(self, tenant: UUID, actor: UUID, message_id: UUID) -> CustomerMessageRecord:
        customer = self.app._customer(tenant, actor)
        record = self.app.store.get_message(message_id)
        if (record.tenant_id, record.actor_user_id, record.customer_id) != (
            tenant,
            actor,
            customer,
        ):
            raise Denied("message unavailable")
        return record

    def message(self, tenant: UUID, actor: UUID, body: CustomerMessage) -> CustomerReply:
        customer = self.app._customer(tenant, actor)
        if not body.prompt.strip():
            raise Denied("message is empty")
        try:
            existing = self._read(tenant, actor, body.message_id)
        except KeyError:
            existing = None
        if existing is not None:
            if existing.input != body:
                raise Conflict("message identifier reused")
            return existing.reply
        # Do not attach a new conversation to an existing legacy certificate request.
        try:
            self.app.store.get(body.message_id)
        except KeyError:
            pass
        else:
            raise Conflict("identifier already used by a certificate request")
        messages: tuple[str, ...] = (body.prompt,)
        selected = body.equipment_id
        if body.parent_message_id is not None:
            parent = self._read(tenant, actor, body.parent_message_id)
            if self.app.now() >= parent.expires_at or len(parent.customer_messages) >= 6:
                raise Conflict("start a new conversation")
            messages = (*parent.customer_messages, body.prompt)
            selected = selected or parent.reply.equipment_id
        registry, _, _ = self.app.repository.registry()
        equipment_ids = [
            e.equipment_id for e in registry.catalog.equipment if e.customer_id == customer
        ]
        if self.app.coverage is not None:
            coverage_ids = [
                equipment_id
                for equipment_id in self.app.coverage.equipment(customer)
                if equipment_id not in equipment_ids
            ]
            equipment_ids = (equipment_ids + coverage_ids)[:10]
        if selected is not None and selected not in equipment_ids:
            raise Denied("equipment unavailable")
        proposal, response_id = self.app.team.interpret(
            {
                "mode": "customer_message",
                "request_id": str(body.message_id),
                "tenant_id": str(tenant),
                "customer_id": customer,
                "equipment_ids": equipment_ids,
                "selected_equipment_id": selected,
                "messages": list(messages),
            }
        )
        # Validate again at the controller boundary, even with an alternative adapter.
        proposal = CustomerInterpretation.model_validate(proposal.model_dump())
        if proposal.request_id != body.message_id or (
            proposal.equipment_id is not None and proposal.equipment_id not in equipment_ids
        ):
            raise EvidenceUnavailable("interpretation binding failed")
        # An explicit machine reference cannot silently be replaced by a dropdown or model.
        references = {
            value if value.startswith("DEMO-") else f"DEMO-{value}"
            for value in re.findall(r"\b(?:DEMO-)?[A-Z]{2,8}-\d{1,8}\b", body.prompt.upper())
        }
        conflict = bool(references) and (
            len(references) != 1
            or not references.issubset(set(equipment_ids))
            or proposal.equipment_id not in references
            or (body.equipment_id is not None and body.equipment_id not in references)
        )
        if conflict:
            reply = CustomerReply(
                message_id=body.message_id,
                intent="clarify",
                equipment_id=None,
                kind="clarification",
                message="Please choose one machine from your equipment and confirm what you need. "
                "The message and equipment selection must identify the same machine. "
                "Nothing was requested.",
            )
        else:
            reply = self._reply(tenant, customer, body, proposal)
        created = self.app.now()
        record = CustomerMessageRecord(
            tenant_id=tenant,
            actor_user_id=actor,
            customer_id=customer,
            input=body,
            customer_messages=messages,
            interpreter_response_id=response_id,
            reply=reply,
            created_at=created,
            expires_at=created + timedelta(minutes=15),
        )
        try:
            self.app.store.create_message(record)
        except Conflict:
            winner = self._read(tenant, actor, body.message_id)
            if winner.input != body:
                raise Conflict("message identifier reused") from None
            return winner.reply
        return reply

    def _reply(
        self, tenant: UUID, customer: str, body: CustomerMessage, proposal: CustomerInterpretation
    ) -> CustomerReply:
        intent, equipment = proposal.intent, proposal.equipment_id
        if intent == "service_request":
            return CustomerReply(
                message_id=body.message_id,
                intent=intent,
                equipment_id=equipment,
                kind="unsupported",
                message=(
                    "Service booking is not available in InnexQ yet. "
                    "No service job or approval was created. Please contact Operations to arrange "
                    "service. I can check the recorded service status."
                ),
            )
        if intent == "general":
            return CustomerReply(
                message_id=body.message_id,
                intent=intent,
                equipment_id=equipment,
                kind="answer",
                message=(
                    "I can check your equipment's recorded service or certificate status "
                    "and help request an existing certificate PDF. "
                    "A certificate records the machine's documented validity; "
                    "it is not a new inspection. Tell me the machine ID and what you need. "
                    "Service bookings and commercial changes are not available here."
                ),
            )
        if intent == "clarify" or equipment is None:
            return CustomerReply(
                message_id=body.message_id,
                intent=intent,
                equipment_id=equipment,
                kind="clarification",
                message=(
                    "Which of your machines do you mean, and would you like "
                    "a status check or the certificate PDF? "
                    "Nothing has been requested."
                ),
            )
        if intent in ("service_document_request", "coverage_renewal"):
            return self._coverage(customer, body, equipment)
        if intent == "certificate_request":
            return CustomerReply(
                message_id=body.message_id,
                intent=intent,
                equipment_id=equipment,
                kind="confirmation_required",
                can_confirm=True,
                message=(
                    f"Request the existing certificate PDF for {equipment}? "
                    "Confirm below to check ownership, certificate validity and service status. "
                    "If any check fails or cannot be verified, the request goes "
                    "to Operations without releasing a PDF."
                ),
            )
        return self._status(tenant, customer, body, proposal)

    def _coverage(self, customer: str, body: CustomerMessage, equipment: str) -> CustomerReply:
        """Read-only outcome check; only explicit confirmation starts a renewal."""

        coverage = self.app.coverage
        if coverage is None:
            return CustomerReply(
                message_id=body.message_id,
                intent="coverage_renewal",
                equipment_id=equipment,
                kind="unsupported",
                message=(
                    "Service coverage renewal is not available right now. "
                    "Please contact Operations. Nothing was requested."
                ),
            )
        outcome = coverage.outcome(customer, equipment)
        if outcome == "existing_pdf":
            return CustomerReply(
                message_id=body.message_id,
                intent="service_document_request",
                equipment_id=equipment,
                kind="answer",
                message=(
                    f"The service coverage document for {equipment} is current. "
                    "No renewal is needed at this time. "
                    "Contact Operations if you need a copy of the document."
                ),
            )
        if outcome == "renewal_required":
            return CustomerReply(
                message_id=body.message_id,
                intent="coverage_renewal",
                equipment_id=equipment,
                kind="confirmation_required",
                can_confirm=True,
                message=(
                    f"The service coverage for {equipment} is not current. "
                    "Confirm below to request a renewal: the recorded evidence is checked, "
                    "a quote is prepared from the price register, and both Operations and a "
                    "Manager must approve before any document is issued or anything is charged."
                ),
            )
        return CustomerReply(
            message_id=body.message_id,
            intent="coverage_renewal",
            equipment_id=equipment,
            kind="answer",
            message=(
                f"I could not verify the recorded coverage for {equipment}. "
                "The required evidence is missing, changed, unavailable or could not be "
                "verified. Please contact Operations. Nothing was requested or charged."
            ),
        )

    def _status(
        self, tenant: UUID, customer: str, body: CustomerMessage, proposal: CustomerInterpretation
    ) -> CustomerReply:
        equipment = proposal.equipment_id
        if equipment is None:
            raise EvidenceUnavailable("equipment not identified")
        try:
            evidence = self.app.evidence(body.message_id, body.prompt, proposal.intent).read(
                customer, equipment
            )
            now = self.app.now()
            decision = evaluate_certificate(customer, equipment, evidence, now)
            if proposal.intent == "service_status":
                checks = (decision.checks[0], decision.checks[2])
                service = evidence.service
                if (
                    service is None
                    or service.in_service is None
                    or any(c.verdict == "unknown" for c in checks)
                ):
                    raise EvidenceUnavailable("service evidence unavailable")
                current = all(c.verdict == "pass" for c in checks)
                until = (service.valid_until - timedelta(microseconds=1)).date().isoformat()
                message = (
                    f"{equipment}: recorded service is {'current' if current else 'not current'}. "
                    f"The service report covers through {until} (inclusive UTC date). "
                    "This is a status check, not a service booking or certificate release."
                )
            else:
                if any(c.verdict == "unknown" for c in decision.checks):
                    raise EvidenceUnavailable("certificate evidence unavailable")
                message = (
                    f"{equipment}: the recorded certificate and service checks "
                    + (
                        "pass at this time. "
                        if decision.outcome == "release_ready"
                        else "do not all pass. "
                    )
                    + "This is a status check only; no PDF was released "
                    "or Operations case created. "
                    "Ask to request the certificate if you want the checked fulfilment workflow."
                )
            # Only this customer's validated source facts; no URLs, hashes, notes or actor IDs.
            fields = evidence.investigation.fields if evidence.investigation else ()
            citations = tuple(
                dict.fromkeys(
                    CustomerCitation(
                        document_id=f.document_id,
                        document_version=f.document_version,
                        page=f.page,
                        label=f.label,
                        value=f.value,
                    )
                    for f in fields
                    if f.label in ("Issued on", "Valid until", "Next service due")
                )
            )
            return CustomerReply(
                message_id=body.message_id,
                intent=proposal.intent,
                equipment_id=equipment,
                kind="answer",
                message=message,
                as_of=now,
                citations=citations,
            )
        except EvidenceUnavailable:
            return CustomerReply(
                message_id=body.message_id,
                intent=proposal.intent,
                equipment_id=equipment,
                kind="answer",
                message=(
                    f"I could not verify the current status for {equipment}. "
                    "The required evidence is missing, changed, unavailable "
                    "or could not be verified. Please contact Operations. "
                    "No service job, certificate request or approval was created."
                ),
            )

    def confirm(self, tenant: UUID, actor: UUID, message_id: UUID) -> dict[str, str]:
        record = self._read(tenant, actor, message_id)
        reply = record.reply
        if reply.can_confirm and reply.intent == "coverage_renewal":
            return self._confirm_coverage(tenant, actor, record)
        if (
            not reply.can_confirm
            or reply.intent != "certificate_request"
            or reply.equipment_id is None
        ):
            raise Denied("this message is not a certificate request proposal")
        context = CustomerRequestContext(
            customer_messages=record.customer_messages,
            equipment_id=reply.equipment_id,
            interpreter_response_id=record.interpreter_response_id,
        )
        controller = self.app._controller(message_id, record.input.prompt, context)
        try:
            existing = self.app.store.get(message_id)
        except KeyError:
            existing = None
        # Identical retries remain available after proposal expiry once started.
        if existing is None and self.app.now() >= record.expires_at:
            raise Conflict("certificate proposal expired; ask again")
        controller.request(tenant, actor, reply.equipment_id, message_id)
        return controller.customer_status(tenant, actor, message_id)

    def _confirm_coverage(
        self, tenant: UUID, actor: UUID, record: CustomerMessageRecord
    ) -> dict[str, str]:
        coverage = self.app.coverage
        equipment = record.reply.equipment_id
        if coverage is None or equipment is None:
            raise Denied("coverage renewal is not available")
        customer = self.app._customer(tenant, actor)
        message_id = record.input.message_id
        try:
            # Identical retries remain available after proposal expiry once started.
            return coverage.progress(customer, message_id)
        except KeyError:
            pass
        if self.app.now() >= record.expires_at:
            raise Conflict("renewal proposal expired; ask again")
        return coverage.start(customer, equipment, message_id)
