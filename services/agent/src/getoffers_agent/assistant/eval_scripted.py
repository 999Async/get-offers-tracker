"""Explicit offline harness check. Never selected by the assistant server or live evaluation."""

import json

from getoffers_agent.domain.contracts import ModelResponse, ToolRequest, Usage


class ScriptedProvider:
    version = "scripted-assistant-contract-v1"
    tokenizer_version = "none-no-model"

    def __init__(self, case, dataset):
        self.case, self.dataset = case, dataset

    async def complete(self, request):
        session = next(b.content for b in request.blocks if b.kind == "session")
        history = session["history"]
        index = len(history)
        usage = Usage(source="synthetic", pricing_version="none-no-inference")
        if index < len(self.case.required_tools):
            name = self.case.required_tools[index]
            args = (
                {"query": "北京 Python RAG 算法岗位"}
                if name == "search_jobs"
                else {"query": "Python RAG 项目"}
                if name == "retrieve_evidence"
                else {}
            )
            return ModelResponse(tool=ToolRequest(name=name, arguments=args), usage=usage)
        observations = {h["tool"]["name"]: h["result"]["value"]["data"] for h in history}
        evidence = observations.get("retrieve_evidence", {}).get("evidence", [])
        refs = [evidence[0]["evidence_id"]] if evidence and self.case.require_citations else []
        jobs = observations.get("search_jobs", {}).get("jobs", [])
        answer = {
            "answer": "合成流程检查：请进一步核对职责和岗位要求。",
            "evidence_ids": refs,
            "job_version_ids": [j["version_id"] for j in jobs] if self.case.require_jobs else [],
            "draft": {
                "kind": self.case.draft_kind,
                "title": "合成检查草稿",
                "content": self.dataset.corrected_fact,
                "evidence_ids": refs,
            }
            if self.case.draft_kind
            else None,
        }
        return ModelResponse(answer=json.dumps(answer, ensure_ascii=False), usage=usage)
