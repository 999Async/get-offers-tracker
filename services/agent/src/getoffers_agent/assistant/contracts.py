from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from getoffers_agent.domain.contracts import Contract


class Message(Contract):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=32000)


class Material(Contract):
    document_id: str = Field(min_length=1, max_length=100)
    version_id: str = Field(min_length=1, max_length=100)


class ChatRequest(Contract):
    request_id: UUID
    messages: tuple[Message, ...] = Field(min_length=1, max_length=24)
    materials: tuple[Material, ...] = Field(default=(), max_length=10)
    jd: str = Field(default="", max_length=24000)

    @model_validator(mode="after")
    def bounded_history(self):
        if self.messages[-1].role != "user":
            raise ValueError("last_message_must_be_user")
        if sum(len(m.content) for m in self.messages) + len(self.jd) > 80000:
            raise ValueError("conversation_too_large")
        if len({m.document_id for m in self.materials}) != len(self.materials):
            raise ValueError("duplicate_material")
        return self


class RetrieveArguments(Contract):
    query: str = Field(min_length=1, max_length=2000)


class SearchArguments(RetrieveArguments):
    cities: list[str] = Field(default_factory=list, max_length=10)
    excluded_terms: list[str] = Field(default_factory=list, max_length=10)


class JobArguments(Contract):
    version_id: str = Field(min_length=1, max_length=100)


class ToolData(Contract):
    data: dict


class Draft(Contract):
    kind: Literal["project", "resume", "interview"]
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=16000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=30)


class Answer(Contract):
    answer: str = Field(min_length=1, max_length=12000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=30)
    job_version_ids: list[str] = Field(default_factory=list, max_length=5)
    draft: Draft | None = None
