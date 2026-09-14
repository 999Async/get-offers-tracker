"""Tool specification, execution and authorization are independent responsibilities."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from getoffers_agent.domain.contracts import (
    ErrorCategory,
    PolicyDecision,
    Reconciliation,
    RuntimeFault,
    ToolContext,
    ToolRequest,
    ToolResult,
    ToolSpec,
    digest,
)


@dataclass(frozen=True)
class ToolPolicy:
    capability: str
    stages: frozenset[str]
    version: str = "capability-policy-v1"

    def authorize(self, context: ToolContext, spec: ToolSpec) -> PolicyDecision:
        return PolicyDecision(
            allowed=self.capability in context.security.capabilities
            and context.stage in self.stages,
            requires_approval=spec.effect != "read",
        )


@dataclass(frozen=True)
class ToolHandler:
    execute: Callable[[ToolContext, dict], Awaitable[ToolResult]]
    reconcile: Callable[[ToolContext], Awaitable[Reconciliation]] | None = None


@dataclass(frozen=True)
class RegisteredTool:
    spec: ToolSpec
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    handler: ToolHandler
    policy: ToolPolicy

    @property
    def fingerprint(self) -> str:
        return digest(
            {
                "spec": self.spec.model_dump(mode="json"),
                "capability": self.policy.capability,
                "stages": sorted(self.policy.stages),
                "policy": self.policy.version,
            }
        )


class ToolRegistry:
    def __init__(self, tools: list[RegisteredTool]):
        self._tools = {tool.spec.name: tool for tool in tools}
        if len(self._tools) != len(tools):
            raise ValueError("duplicate tool registration")
        for tool in tools:
            if (
                tool.spec.input_schema != tool.input_model.model_json_schema()
                or tool.spec.output_schema != tool.output_model.model_json_schema()
                or tool.input_model.model_config.get("extra") != "forbid"
                or tool.output_model.model_config.get("extra") != "forbid"
            ):
                raise ValueError("tool schema must match its strict registered contract")
            if tool.spec.effect != "read" and tool.handler.reconcile is None:
                raise ValueError("write tools require read-only idempotency reconciliation")

    @property
    def fingerprint(self) -> str:
        return digest({name: tool.fingerprint for name, tool in sorted(self._tools.items())})

    def visible(self, context: ToolContext, allowed_names: frozenset[str]) -> tuple[ToolSpec, ...]:
        return tuple(
            tool.spec
            for name, tool in sorted(self._tools.items())
            if name in allowed_names
            and tool.spec.exposure != "hidden"
            and tool.policy.authorize(context, tool.spec).allowed
        )

    def resolve(
        self, request: ToolRequest, context: ToolContext, allowed_names: frozenset[str]
    ) -> tuple[RegisteredTool, ToolRequest]:
        tool = self._tools.get(request.name)
        if tool is None:
            raise RuntimeFault(ErrorCategory.UNKNOWN_TOOL)
        if tool.spec.exposure == "hidden" or request.name not in allowed_names:
            raise RuntimeFault(ErrorCategory.HIDDEN_TOOL)
        if not tool.policy.authorize(context, tool.spec).allowed:
            raise RuntimeFault(ErrorCategory.POLICY_DENIED)
        try:
            arguments = tool.input_model.model_validate(request.arguments, strict=True)
            normalized = arguments.model_dump(mode="json")
            # Reject NaN and non-JSON provider data before computing an approval binding.
            digest(normalized)
        except (ValidationError, ValueError, TypeError):
            raise RuntimeFault(ErrorCategory.INVALID_ARGUMENTS) from None
        return tool, ToolRequest(name=request.name, arguments=normalized)

    @staticmethod
    def validate_result(tool: RegisteredTool, result: ToolResult) -> ToolResult:
        try:
            parsed = tool.output_model.model_validate(result.value, strict=True)
            value = parsed.model_dump(mode="json")
            digest(value)
            return ToolResult(value=value)
        except (ValidationError, AttributeError, ValueError, TypeError):
            raise RuntimeFault(ErrorCategory.INVALID_OUTPUT) from None
