"""Acceptance evidence checks are offline-tested; this is not live acceptance."""

import asyncio
from typing import Any

import pytest

from scripts.live_run import verify_run
from tests.unit.test_controller import approve, awaiting


def test_acceptance_requires_ordered_approved_execution(system: Any) -> None:
    c, store, _, _, _ = system
    pending = awaiting(c)
    with pytest.raises(ValueError):
        verify_run(pending, store.events(pending.run.run_id))
    approve(c, pending)
    final = asyncio.run(c.execute(pending.run.run_id))
    events = store.events(final.run.run_id)
    verify_run(final, events)
    with pytest.raises(ValueError, match="sequence"):
        verify_run(final, events[1:])
    with pytest.raises(ValueError, match="receipts"):
        verify_run(final.model_copy(update={"receipts": {}}), events)
    changed = list(events)
    changed[2] = changed[2].model_copy(update={"event_type": "unverified.tool"})
    with pytest.raises(ValueError, match="sequence"):
        verify_run(final, changed)
