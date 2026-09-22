"""Background coverage execution runner: drives approved renewals to the executor."""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from innexq_api.coverage_controller import CoverageAuthorizationError
from innexq_api.coverage_runner import CoverageExecutionRunner
from innexq_api.store import Conflict
from innexq_contracts.coverage_renewal import CoverageRenewalState


class Rec:
    def __init__(self, state: CoverageRenewalState) -> None:
        self.state = state
        self.request_id = uuid4()


class FakeStore:
    def __init__(self, records: list[Rec], *, raise_on_list: bool = False) -> None:
        self._records = records
        self.raise_on_list = raise_on_list
        self.list_calls = 0

    def list_renewals(self) -> list[Rec]:
        self.list_calls += 1
        if self.raise_on_list:
            raise RuntimeError("scan failed")
        return list(self._records)


class FakeController:
    def __init__(self, fail_ids: set[UUID] | None = None) -> None:
        self.authorized: list[UUID] = []
        self.fail_ids = fail_ids or set()

    def authorize_execution(self, request_id: UUID) -> None:
        self.authorized.append(request_id)
        if request_id in self.fail_ids:
            raise CoverageAuthorizationError("not authorized")


class FakeExecutor:
    def __init__(self, raise_ids: dict[UUID, Exception] | None = None) -> None:
        self.executed: list[UUID] = []
        self.raise_ids = raise_ids or {}

    def execute(self, request_id: UUID) -> None:
        self.executed.append(request_id)
        error = self.raise_ids.get(request_id)
        if error is not None:
            raise error


def runner(
    records: list[Rec],
    *,
    store_kw: dict | None = None,
    controller_kw: dict | None = None,
    executor_kw: dict | None = None,
) -> tuple[CoverageExecutionRunner, FakeStore, FakeController, FakeExecutor]:
    store = FakeStore(records, **(store_kw or {}))
    controller = FakeController(**(controller_kw or {}))
    executor = FakeExecutor(**(executor_kw or {}))
    run = CoverageExecutionRunner(store, controller, executor, interval_seconds=0.0)  # type: ignore[arg-type]
    return run, store, controller, executor


def test_manager_approved_is_authorized_then_executed() -> None:
    rec = Rec(CoverageRenewalState.MANAGER_APPROVED)
    run, _, controller, executor = runner([rec])
    run._drain()
    assert controller.authorized == [rec.request_id]
    assert executor.executed == [rec.request_id]


def test_executing_record_is_resumed_without_reauthorizing() -> None:
    rec = Rec(CoverageRenewalState.EXECUTING)
    run, _, controller, executor = runner([rec])
    run._drain()
    assert controller.authorized == []
    assert executor.executed == [rec.request_id]


def test_pre_approval_states_are_ignored() -> None:
    rec = Rec(CoverageRenewalState.AWAITING_OPERATIONS_APPROVAL)
    run, _, controller, executor = runner([rec])
    run._drain()
    assert controller.authorized == [] and executor.executed == []


def test_authorization_error_is_swallowed_and_the_loop_continues() -> None:
    denied = Rec(CoverageRenewalState.MANAGER_APPROVED)
    good = Rec(CoverageRenewalState.MANAGER_APPROVED)
    run, _, _, executor = runner([denied, good], controller_kw={"fail_ids": {denied.request_id}})
    run._drain()
    assert executor.executed == [good.request_id]


def test_conflict_from_executor_is_swallowed_and_the_loop_continues() -> None:
    conflicted = Rec(CoverageRenewalState.EXECUTING)
    good = Rec(CoverageRenewalState.EXECUTING)
    run, _, _, executor = runner(
        [conflicted, good],
        executor_kw={"raise_ids": {conflicted.request_id: Conflict("busy")}},
    )
    run._drain()
    assert good.request_id in executor.executed


def test_unexpected_execution_error_is_logged_and_the_loop_continues() -> None:
    boom = Rec(CoverageRenewalState.EXECUTING)
    good = Rec(CoverageRenewalState.EXECUTING)
    run, _, _, executor = runner(
        [boom, good], executor_kw={"raise_ids": {boom.request_id: RuntimeError("x")}}
    )
    run._drain()
    assert good.request_id in executor.executed


def test_run_survives_scan_errors_and_is_cancellable() -> None:
    run, store, _, _ = runner([], store_kw={"raise_on_list": True})

    async def go() -> None:
        task = asyncio.create_task(run.run())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(go())
    assert store.list_calls >= 1
