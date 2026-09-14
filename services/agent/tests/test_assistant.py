"""ReAct contract tests: scripted transport, real retrieval/runtime, no quality claims."""

import asyncio
import json
from decimal import Decimal
from uuid import uuid4

import pytest
from test_career_discovery import SECRET_QUOTE, user
from test_career_discovery import setup as career_setup  # noqa: F401

from getoffers_agent.assistant.contracts import ChatRequest
from getoffers_agent.assistant.provider import ChatProvider, ModelConfig
from getoffers_agent.assistant.service import AssistantService, ChatTurn
from getoffers_agent.domain.contracts import digest


@pytest.fixture(name="setup")
def assistant_setup(career_setup):  # noqa: F811 - pytest injects the imported fixture
    return career_setup


def security(name="alice"):
    return user(name).model_copy(update={"capabilities": frozenset({"assistant:read:self"})})


def request(doc=None, **changes):
    return ChatRequest.model_validate(
        {
            "request_id": str(uuid4()),
            "messages": [{"role": "user", "content": "请梳理我的 Python RAG 项目"}],
            "materials": [doc] if doc else [],
            **changes,
        }
    )


def response(answer=None, tool=None):
    message = {"content": json.dumps(answer, ensure_ascii=False)}
    if tool:
        name, args = tool
        message = {
            "content": None,
            "tool_calls": [
                {
                    "id": "call",
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(args),
                    },
                }
            ],
        }
    return {
        "choices": [{"finish_reason": "tool_calls" if tool else "stop", "message": message}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 40},
    }


def provider(transport, **prices):
    return ChatProvider(
        ModelConfig("https://model.example/v1", "test-tool-model", "private-key", **prices),
        transport,
    )


def collect(service, chat, owner=None):
    async def run():
        return [item async for item in service.chat(chat, owner or security())]

    return asyncio.run(run())


def test_react_observes_real_evidence_and_keeps_private_audit_redacted(setup, tmp_path):
    _, ports, doc = setup
    calls = []

    def model(payload):
        calls.append(payload)
        assert payload["parallel_tool_calls"] is False
        assert payload["store"] is False
        assert "private-key" not in json.dumps(payload)
        assert {t["function"]["name"] for t in payload["tools"]} == {
            "get_candidate_state",
            "retrieve_evidence",
            "search_jobs",
            "get_job",
            "read_target_jd",
        }
        observations = [
            json.loads(m["content"])["data"] for m in payload["messages"] if m["role"] == "tool"
        ]
        if not observations:
            return response(tool=("get_candidate_state", {}))
        if len(observations) == 1:
            return response(tool=("retrieve_evidence", {"query": "Python RAG"}))
        ref = observations[-1]["evidence"][0]
        assert SECRET_QUOTE in ref["quote"]
        return response(
            {
                "answer": "请补充实际负责的范围。",
                "evidence_ids": [ref["evidence_id"]],
                "draft": {
                    "kind": "project",
                    "title": "项目梳理",
                    "content": ref["quote"],
                    "evidence_ids": [ref["evidence_id"]],
                },
            }
        )

    chat = request(
        doc,
        messages=[
            {"role": "user", "content": "前一轮口述"},
            {"role": "assistant", "content": "前一轮追问"},
            {"role": "user", "content": "继续梳理私密项目"},
        ],
    )
    service = AssistantService(provider(model), ports, tmp_path / "audit")
    events = collect(service, chat)
    assert events[-1]["type"] == "done", events
    assert len(calls) == 3
    assert any(m["content"] == "前一轮追问" for m in calls[-1]["messages"])
    assert events[-1]["message"]["citations"][0]["document_id"] == doc["document_id"]
    assert events[-1]["usage"] == {"input_tokens": 360, "output_tokens": 120, "cost_usd": None}
    assert ports.writes == 0
    raw = next((tmp_path / "audit").glob("*.json")).read_text()
    for private in (SECRET_QUOTE, "继续梳理私密项目", "前一轮追问", "private-key", "项目梳理"):
        assert private not in raw
    audit = json.loads(raw)
    assert len(audit["manifests"]) == 3
    assert len({m["context_hash"] for m in audit["manifests"]}) == 3
    assert "cost" not in audit["spans"][3]["attributes"]


@pytest.mark.parametrize(
    "name,args",
    [
        ("create_application", {"company": "伪造公司"}),
        ("retrieve_evidence", {"query": "Python", "document_ids": ["foreign"]}),
    ],
)
def test_unregistered_write_or_scope_injection_never_executes(setup, name, args):
    _, ports, doc = setup
    events = collect(
        AssistantService(provider(lambda p: response(tool=(name, args))), ports), request(doc)
    )
    assert events[-1]["type"] == "error", events
    assert ports.writes == 0


def test_foreign_material_and_forged_citation_fail_closed(setup):
    _, ports, doc = setup
    calls = []

    def model(payload):
        calls.append(payload)
        return response({"answer": "伪造引用", "evidence_ids": ["made-up"]})

    service = AssistantService(provider(model), ports)
    assert collect(service, request(doc), security("bob"))[-1]["error"] == "MATERIAL_CHANGED"
    assert not calls
    assert collect(service, request(doc))[-1]["error"] == "INVALID_CITATION"


def test_changed_material_during_generation_is_not_returned(setup):
    _, ports, doc = setup

    def model(payload):
        ports.knowledge(user(), "delete", {"document_id": doc["document_id"]})
        return response({"answer": "材料已变更后生成的回答"})

    events = collect(AssistantService(provider(model), ports), request(doc))
    assert events[-1]["error"] == "MATERIAL_CHANGED"
    assert not any(e["type"] == "done" for e in events)


def test_search_respects_natural_city_and_supplies_actual_job(setup):
    _, ports, doc = setup

    def model(payload):
        observations = [
            json.loads(m["content"])["data"] for m in payload["messages"] if m["role"] == "tool"
        ]
        if not observations:
            return response(tool=("search_jobs", {"query": "北京 Python 算法岗位"}))
        jobs = observations[-1]["jobs"]
        assert jobs and all(j["cities"] == ["北京"] for j in jobs)
        return response(
            {
                "answer": "找到北京的岗位，请核对 CUDA 要求。",
                "job_version_ids": [jobs[0]["version_id"]],
            }
        )

    events = collect(AssistantService(provider(model), ports), request(doc))
    assert events[-1]["type"] == "done", events
    assert events[-1]["message"]["jobs"][0]["cities"] == ["北京"]


def test_jd_tool_and_interview_draft_without_claimed_experience(setup):
    _, ports, _ = setup

    def model(payload):
        observations = [
            json.loads(m["content"])["data"] for m in payload["messages"] if m["role"] == "tool"
        ]
        if not observations:
            return response(tool=("read_target_jd", {}))
        assert observations[-1]["jd"] == "需要 Python RAG evaluation"
        return response(
            {
                "answer": "先准备技术问题；请补充项目经历。",
                "draft": {
                    "kind": "interview",
                    "title": "面试问题",
                    "content": "如何评估检索召回率？",
                },
            }
        )

    result = collect(
        AssistantService(provider(model), ports), request(jd="需要 Python RAG evaluation")
    )
    assert result[-1]["type"] == "done", result


@pytest.mark.parametrize("kind", ["project", "resume"])
def test_unreferenced_experience_drafts_are_rejected(setup, kind):
    _, ports, _ = setup

    def model(payload):
        return response(
            {"answer": "草稿", "draft": {"kind": kind, "title": "草稿", "content": "编造经历"}}
        )

    assert (
        collect(AssistantService(provider(model), ports), request())[-1]["error"]
        == "UNGROUNDED_DRAFT"
    )


@pytest.mark.parametrize("fault", ["length", "missing_usage", "parallel", "malformed"])
def test_provider_failures_never_become_success(setup, fault):
    _, ports, _ = setup

    def model(payload):
        value = response({"answer": "answer"})
        if fault == "length":
            value["choices"][0]["finish_reason"] = "length"
        if fault == "missing_usage":
            value.pop("usage")
        if fault == "parallel":
            value = response(tool=("read_target_jd", {}))
            value["choices"][0]["message"]["tool_calls"] *= 2
        if fault == "malformed":
            value["choices"][0]["message"]["content"] = "plain text"
        return value

    events = collect(AssistantService(provider(model), ports), request())
    assert events[-1]["type"] == "error"


def test_step_limit_and_unavailable_read_service(setup):
    _, ports, _ = setup
    calls = []

    def loop(payload):
        calls.append(payload)
        return response(tool=("search_jobs", {"query": f"Python {len(calls)}"}))

    result = collect(AssistantService(provider(loop), ports), request())
    assert result[-1]["type"] == "error" and len(calls) == 8

    def unavailable(*args):
        raise OSError("private server details")

    ports.search = unavailable

    def recover(payload):
        obs = [m for m in payload["messages"] if m["role"] == "tool"]
        if not obs:
            return response(tool=("search_jobs", {"query": "Python"}))
        assert json.loads(obs[-1]["content"])["data"]["unavailable"] is True
        assert "private server details" not in obs[-1]["content"]
        return response({"answer": "岗位服务暂不可用，可以先梳理求职方向。"})

    assert collect(AssistantService(provider(recover), ports), request())[-1]["type"] == "done"


def test_audit_failure_releases_owner_and_cost_is_measured(setup, tmp_path):
    _, ports, _ = setup
    invalid_dir = tmp_path / "file"
    invalid_dir.write_text("not a directory")
    service = AssistantService(
        provider(
            lambda p: response({"answer": "请描述项目。"}),
            input_price=Decimal("1"),
            output_price=Decimal("2"),
        ),
        ports,
        invalid_dir,
    )
    first = collect(service, request())
    assert first[-1]["type"] == "done" and Decimal(first[-1]["usage"]["cost_usd"]) == Decimal(
        "0.000200"
    )
    assert not service.active
    assert collect(service, request())[-1]["type"] == "done"


def test_cancellation_releases_owner_and_does_not_call_next_tool(setup):
    _, ports, _ = setup

    async def check():
        entered = asyncio.Event()

        class Waiting:
            version = tokenizer_version = "test-wait"

            async def complete(self, request):
                entered.set()
                await asyncio.Event().wait()

        service = AssistantService(Waiting(), ports)
        stream = service.chat(request(), security())

        async def consume():
            async for _ in stream:
                pass

        task = asyncio.create_task(consume())
        await entered.wait()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await stream.aclose()
        assert not service.active
        assert ports.writes == 0

    asyncio.run(check())


def test_confirmed_fact_revision_and_context_fingerprints(setup):
    _, ports, doc = setup
    turn = ChatTurn(request(doc), security(), ports)
    state = turn.get_candidate_state({})
    ref = state["facts"][0]
    fact = ports.knowledge(user(), "facts", {})["facts"][0]
    ports.knowledge(
        user(),
        "review",
        {
            "fact_id": fact["fact_id"],
            "expected_revision": fact["revision"],
            "action": "correct",
            "corrected_value": "修正后的事实",
        },
    )
    with pytest.raises(ValueError, match="MATERIAL_CHANGED"):
        turn.validate_answer(json.dumps({"answer": "answer", "evidence_ids": [ref["evidence_id"]]}))
    assert state["state_hash"] != digest(turn.facts())


def test_followup_accepts_full_answer_and_edited_draft_within_total_budget():
    chat = request(
        messages=[
            {"role": "assistant", "content": "答" * 12000 + "\n\n" + "稿" * 16000},
            {"role": "user", "content": "请缩短这份草稿"},
        ]
    )
    assert len(chat.messages[0].content) == 28002
