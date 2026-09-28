from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ModelRequest:
    operation: str
    instructions: str
    input_sha256: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ModelProposal:
    provider: str
    model: str
    proposed_json: str
    request_id: str | None


class ModelProvider(Protocol):
    def propose(self, request: ModelRequest) -> ModelProposal: ...

