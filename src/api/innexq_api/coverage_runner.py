"""Background execution runner for approved coverage renewals (ADR-018).

The controller alone authorizes execution; this loop only schedules the isolated
executor for renewals a distinct Manager has approved, and relies on the
executor's idempotency for retries and crash recovery.
"""

from __future__ import annotations

import asyncio
import logging

from innexq_contracts.coverage_renewal import CoverageRenewalState

from innexq_api.coverage_controller import CoverageAuthorizationError, CoverageController
from innexq_api.coverage_executor import CoverageExecutor
from innexq_api.coverage_store import CosmosCoverageStore
from innexq_api.store import Conflict

logger = logging.getLogger(__name__)


class CoverageExecutionRunner:
    def __init__(
        self,
        store: CosmosCoverageStore,
        controller: CoverageController,
        executor: CoverageExecutor,
        *,
        interval_seconds: float = 2.0,
    ) -> None:
        self.store, self.controller, self.executor = store, controller, executor
        self.interval_seconds = interval_seconds

    async def run(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self._drain)
            except Exception:
                logger.exception("coverage execution scan failed")
            await asyncio.sleep(self.interval_seconds)

    def _drain(self) -> None:
        for record in self.store.list_renewals():
            try:
                if record.state == CoverageRenewalState.MANAGER_APPROVED:
                    self.controller.authorize_execution(record.request_id)
                    self.executor.execute(record.request_id)
                elif record.state == CoverageRenewalState.EXECUTING:
                    # Resume an execution interrupted before it committed COMPLETED.
                    self.executor.execute(record.request_id)
            except (CoverageAuthorizationError, Conflict):
                continue
            except Exception:
                logger.exception("coverage execution failed for %s", record.request_id)
