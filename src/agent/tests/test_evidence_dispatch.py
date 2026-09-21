"""Packet routing cannot downgrade scoped evidence work to the legacy path."""

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agent_framework import Message
from pydantic import SecretStr

from certificate_team import CertificateTeamGuard
from evidence_dispatch import EvidenceDispatch, candidate_certificate_team
from evidence_team import EvidenceTeamGuard


class EvidenceDispatchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.dispatch = EvidenceDispatch("client", "credential", "endpoint", "project")
        self.assertIsInstance(self.dispatch.candidate, EvidenceTeamGuard)
        self.assertIsInstance(self.dispatch.legacy, CertificateTeamGuard)
        self.candidate = self.enterContext(
            patch.object(self.dispatch.candidate, "process", new_callable=AsyncMock)
        )
        self.legacy = self.enterContext(
            patch.object(self.dispatch.legacy, "process", new_callable=AsyncMock)
        )
        self.handles = self.enterContext(
            patch("evidence_dispatch.current_evidence_handles", return_value={})
        )
        self.next_call = AsyncMock()

    @staticmethod
    def context(packet):
        return SimpleNamespace(messages=[Message(role="user", contents=[json.dumps(packet)])])

    async def test_candidate_packet_routes_only_to_candidate_guard(self):
        context = self.context({"mode": "evidence_investigation"})
        await self.dispatch.process(context, self.next_call)
        self.candidate.assert_awaited_once_with(context, self.next_call)
        self.legacy.assert_not_awaited()
        self.next_call.assert_not_awaited()
        # Candidate guard itself must validate transport handles. Dispatch does
        # not take absence of handles as permission to downgrade to legacy.
        self.handles.assert_not_called()

    async def test_headerless_interpretation_and_legacy_investigation_keep_legacy_guard(self):
        for packet in ({"mode": "customer_message"}, {"request_id": "controller-owned"}):
            with self.subTest(packet=packet):
                context = self.context(packet)
                await self.dispatch.process(context, self.next_call)
                self.legacy.assert_awaited_with(context, self.next_call)
        self.assertEqual(self.legacy.await_count, 2)
        self.candidate.assert_not_awaited()
        self.next_call.assert_not_awaited()

    async def test_candidate_failure_or_cancellation_never_falls_back(self):
        for error in (ValueError("denied"), RuntimeError("unavailable"), asyncio.CancelledError()):
            with self.subTest(error=type(error).__name__):
                self.candidate.side_effect = error
                with self.assertRaises(type(error)):
                    await self.dispatch.process(
                        self.context({"mode": "evidence_investigation"}), self.next_call
                    )
        self.legacy.assert_not_awaited()
        self.next_call.assert_not_awaited()

    async def test_scoped_legacy_unknown_and_non_object_packets_cannot_downgrade(self):
        self.handles.return_value = {"document_analyst": SecretStr("offline-scope-placeholder")}
        for packet in ({"mode": "customer_message"}, {}, {"mode": "execute"}, [], None):
            with self.subTest(packet=packet):
                with self.assertRaisesRegex(ValueError, "cannot be used with legacy"):
                    await self.dispatch.process(self.context(packet), self.next_call)
        self.candidate.assert_not_awaited()
        self.legacy.assert_not_awaited()
        self.next_call.assert_not_awaited()

    async def test_no_multiple_oversize_or_malformed_user_packets_reach_either_guard(self):
        message = Message(role="user", contents=['{"mode":"evidence_investigation"}'])
        for messages in (
            [],
            [message, message],
            [Message(role="assistant", contents=["not a controller packet"])],
            [Message(role="user", contents=["x" * 50001])],
            [Message(role="user", contents=["{malformed-json"])],
        ):
            with self.subTest(messages=len(messages)):
                with self.assertRaises(ValueError):
                    await self.dispatch.process(SimpleNamespace(messages=messages), self.next_call)
        self.candidate.assert_not_awaited()
        self.legacy.assert_not_awaited()
        self.next_call.assert_not_awaited()

    async def test_unknown_headerless_mode_is_still_rejected_by_real_legacy_validation(self):
        dispatch = EvidenceDispatch("client", "credential", "endpoint", "project")
        with self.assertRaises(ValueError):
            await dispatch.process(self.context({"mode": "execute"}), self.next_call)
        self.next_call.assert_not_awaited()

    async def test_real_candidate_rejects_missing_transport_handles_without_legacy_fallback(self):
        dispatch = EvidenceDispatch("client", "credential", "endpoint", "project")
        with patch.object(dispatch.legacy, "process", new_callable=AsyncMock) as legacy:
            with self.assertRaisesRegex(ValueError, "fresh scoped"):
                await dispatch.process(
                    self.context({"mode": "evidence_investigation"}), self.next_call
                )
        legacy.assert_not_awaited()
        self.next_call.assert_not_awaited()

    def test_factory_installs_dispatch_without_shared_tools_or_storage(self):
        with patch("evidence_dispatch.Agent") as agent:
            result = candidate_certificate_team("client", "credential", "endpoint", "project")
        self.assertIs(result, agent.return_value)
        options = agent.call_args.kwargs
        self.assertEqual(options["name"], "innexq-request-coordinator")
        self.assertEqual(options["default_options"], {"store": False})
        self.assertNotIn("tools", options)
        dispatch = options["middleware"][0]
        self.assertIsInstance(dispatch, EvidenceDispatch)
        self.assertEqual(dispatch.candidate.client, "client")
        self.assertEqual(dispatch.candidate.credential, "credential")
        self.assertEqual(dispatch.candidate.endpoint, "endpoint")
        self.assertEqual(dispatch.candidate.project_endpoint, "project")
