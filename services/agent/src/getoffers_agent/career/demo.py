"""A tiny workflow demonstrating the seam; not a real job recommendation system."""

from pydantic import Field

from getoffers_agent.adapters.fakes import FakeModelProvider, ProductPort, synthetic_usage
from getoffers_agent.domain.contracts import Contract, ModelResponse, ToolRequest, ToolSpec
from getoffers_agent.runtime.context import Workflow
from getoffers_agent.runtime.tools import RegisteredTool, ToolHandler, ToolPolicy, ToolRegistry


class ReadArguments(Contract):
    pass


class CandidateState(Contract):
    skills: list[str]
    state_version: str


class PlanArguments(Contract):
    job_id: str = Field(min_length=1, max_length=100)
    note: str = Field(default="", max_length=2000)


class ApplicationPlan(PlanArguments):
    plan_id: str


DEMO_WORKFLOW = Workflow(
    version="demo-workflow-v1",
    instructions="Read synthetic candidate state, propose one Application Plan, then summarize.",
    initial_stage="discover",
    tools_by_stage={
        "discover": frozenset({"get_candidate_state"}),
        "propose": frozenset({"create_application_plan"}),
        "summarize": frozenset(),
    },
    transitions={
        ("discover", "get_candidate_state"): "propose",
        ("propose", "create_application_plan"): "summarize",
    },
)


def demo_tools(product: ProductPort) -> ToolRegistry:
    return ToolRegistry(
        [
            RegisteredTool(
                ToolSpec(
                    name="get_candidate_state",
                    description="Read synthetic candidate state",
                    version="1",
                    input_schema=ReadArguments.model_json_schema(),
                    output_schema=CandidateState.model_json_schema(),
                    effect="read",
                ),
                ReadArguments,
                CandidateState,
                ToolHandler(product.get_candidate_state),
                ToolPolicy("candidate:read:self", frozenset({"discover"})),
            ),
            RegisteredTool(
                ToolSpec(
                    name="create_application_plan",
                    description="Propose an exact plan for approval",
                    version="1",
                    input_schema=PlanArguments.model_json_schema(),
                    output_schema=ApplicationPlan.model_json_schema(),
                    effect="write",
                ),
                PlanArguments,
                ApplicationPlan,
                ToolHandler(product.create_application_plan, product.lookup_application_plan),
                ToolPolicy("application_plan:create:self", frozenset({"propose"})),
            ),
        ]
    )


def demo_responses() -> list[ModelResponse]:
    return [
        ModelResponse(
            tool=ToolRequest(name="get_candidate_state", arguments={}), usage=synthetic_usage()
        ),
        ModelResponse(
            tool=ToolRequest(
                name="create_application_plan",
                arguments={"job_id": "synthetic-job-001", "note": "Review JD"},
            ),
            usage=synthetic_usage(),
        ),
        ModelResponse(
            answer="Synthetic Application Plan created after approval.", usage=synthetic_usage()
        ),
    ]


def demo_provider() -> FakeModelProvider:
    return FakeModelProvider(demo_responses())
