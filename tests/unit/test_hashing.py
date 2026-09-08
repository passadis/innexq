from __future__ import annotations

from uuid import UUID

import pytest
from innexq_contracts import (
    ApprovalBindingError,
    Decision,
    approval_matches_current_version,
    canonical_json_bytes,
    compute_brief_hash,
    version_brief,
)

from tests.unit.factories import RUN_ID, approval, brief, manifest


def test_canonical_json_is_independent_of_object_key_order() -> None:
    first = {"z": ["one", "two"], "a": {"second": "2", "first": "1"}}
    second = {"a": {"first": "1", "second": "2"}, "z": ["one", "two"]}
    assert canonical_json_bytes(first) == canonical_json_bytes(second)


def test_canonical_json_rejects_binary_floating_point() -> None:
    with pytest.raises(TypeError, match="floating-point"):
        canonical_json_bytes({"price": 1.1})


def test_hash_is_stable_and_changes_with_brief_or_action() -> None:
    baseline = compute_brief_hash(brief(), manifest())
    assert baseline == compute_brief_hash(brief(), manifest())
    assert baseline != compute_brief_hash(brief("Changed recommendation"), manifest())
    assert baseline != compute_brief_hash(brief(), manifest("other@example.invalid"))


def test_hash_rejects_mismatched_run_version_and_manifest_reference() -> None:
    with pytest.raises(ApprovalBindingError, match="same Run"):
        compute_brief_hash(brief(), manifest().model_copy(update={"run_id": UUID(int=9)}))
    with pytest.raises(ApprovalBindingError, match="versions"):
        compute_brief_hash(brief(), manifest().model_copy(update={"brief_version": 2}))
    with pytest.raises(ApprovalBindingError, match="supplied manifest"):
        compute_brief_hash(
            brief().model_copy(update={"action_manifest_id": UUID(int=8)}), manifest()
        )


def test_versioning_ignores_untrusted_input_versions_and_invalidates_approval() -> None:
    v1 = version_brief(
        brief().model_copy(update={"brief_version": 77}),
        manifest().model_copy(update={"brief_version": 77}),
    )
    approved_v1 = approval(v1)
    assert v1.brief.brief_version == 1
    assert v1.action_manifest.brief_version == 1
    assert approval_matches_current_version(approved_v1, v1)

    v2 = version_brief(brief("Edited after review"), manifest(), previous=v1)
    assert v2.brief.brief_version == 2
    assert v2.brief_hash != v1.brief_hash
    assert not approval_matches_current_version(approved_v1, v2)


def test_versioning_cannot_move_to_another_run() -> None:
    v1 = version_brief(brief(), manifest())
    other_run = UUID("90000000-0000-4000-8000-000000000001")
    with pytest.raises(ApprovalBindingError, match="cannot change its Run"):
        version_brief(
            brief().model_copy(update={"run_id": other_run}),
            manifest().model_copy(update={"run_id": other_run}),
            previous=v1,
        )


def test_nonapproval_or_insufficient_authority_does_not_match() -> None:
    current = version_brief(brief(), manifest())
    rejected = approval(current).model_copy(update={"decision": Decision.REJECT})
    assert not approval_matches_current_version(rejected, current)


def test_run_id_is_part_of_approval_binding() -> None:
    current = version_brief(brief(), manifest())
    wrong_run = approval(current).model_copy(update={"run_id": UUID(int=7)})
    assert not approval_matches_current_version(wrong_run, current)
    assert current.brief.run_id == RUN_ID
