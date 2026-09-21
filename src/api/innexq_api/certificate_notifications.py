"""Durable, conservative Operations notification delivery; never an approval."""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from starlette.concurrency import run_in_threadpool

from innexq_api.certificate_store import CosmosCertificateStore
from innexq_api.store import Conflict


class OperationsSender(Protocol):
    async def notify_operations(self, request_id: UUID, case_id: UUID) -> str: ...


class CertificateNotifications:
    def __init__(
        self,
        store: CosmosCertificateStore,
        sender: OperationsSender,
        tenant_id: UUID,
        operations_id: UUID,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.store, self.sender, self.now = store, sender, now
        self.tenant_id, self.operations_id = tenant_id, operations_id

    async def dispatch_once(self) -> None:
        now = self.now()
        await run_in_threadpool(
            self.store.recover_stale_claims,
            now - timedelta(minutes=5),
            now,
            self.tenant_id,
            self.operations_id,
        )
        pending = await run_in_threadpool(self.store.pending_notifications)
        for notification in pending:
            if (notification.tenant_id, notification.assigned_user_id) != (
                self.tenant_id,
                self.operations_id,
            ):
                # Never route an outbox belonging to another authority context.
                continue
            try:
                claimed = await run_in_threadpool(
                    self.store.claim_notification, notification.request_id, self.now()
                )
            except Conflict:
                continue
            if claimed is None or claimed.attempt_id is None:
                continue
            try:
                if (
                    claimed.request_id != notification.request_id
                    or claimed.tenant_id != self.tenant_id
                    or claimed.assigned_user_id != self.operations_id
                ):
                    raise ValueError("notification claim binding mismatch")
                record = await run_in_threadpool(self.store.get, claimed.request_id)
                case = record.operations_case
                if (
                    case is None
                    or case.case_id != claimed.case_id
                    or case.assigned_user_id != self.operations_id
                    or record.tenant_id != self.tenant_id
                ):
                    raise ValueError("case binding mismatch")
                receipt = await asyncio.wait_for(
                    self.sender.notify_operations(claimed.request_id, claimed.case_id), timeout=30
                )
                await run_in_threadpool(
                    self.store.mark_delivered,
                    claimed.request_id,
                    claimed.attempt_id,
                    receipt,
                    self.now(),
                )
            except Exception:
                # A timeout may happen after Teams accepted the message. Keep the
                # case visible and require reconciliation, never a blind re-send.
                try:
                    await run_in_threadpool(
                        self.store.mark_ambiguous,
                        claimed.request_id,
                        claimed.attempt_id,
                        self.now(),
                    )
                except Conflict:
                    pass
                logging.getLogger("innexq.audit").warning(
                    "certificate_notification_ambiguous",
                    extra={"request_id": str(claimed.request_id)},
                )

    async def run(self) -> None:
        while True:
            try:
                await self.dispatch_once()
            except Exception:
                logging.getLogger("innexq.audit").warning("certificate_outbox_unavailable")
            await asyncio.sleep(5)
