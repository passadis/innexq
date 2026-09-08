"""Narrow proposal contract: no executable authority or financial result fields."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RunRequest(ClosedModel):
    run_id: UUID
    correlation_id: UUID
    contract_id: Literal["CON-FAB-2025-001"]


class Citation(ClosedModel):
    source_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    excerpt: str = Field(min_length=1, max_length=10000)
    url: str = Field(min_length=1, max_length=2048)


class Proposal(ClosedModel):
    summary: str = Field(min_length=1, max_length=4000)
    citations: list[Citation] = Field(min_length=1, max_length=12)
