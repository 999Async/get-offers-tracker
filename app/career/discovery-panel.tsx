"use client";

import { useEffect, useRef, useState } from "react";
import ResumePicker from "../knowledge/resume-picker";
import type { ResumeReference } from "../knowledge/files";

type Job = {
  job_id: string; version_id: string; company: string; title: string; cities: string[]; source_url: string;
  requirements: string[]; gaps: string[]; application_id?: string;
  evidence: { evidence_id: string; quote: string; path: string[]; confirmed_facts: string[] }[];
};
type Approval = { action_id: string; arguments_hash: string; expires_at: string;
  plan: { company: string; role: string; resume: string; sourceJobUrl: string } };
type Run = { run_id: string; status: string; stage: string; jobs?: Job[]; approval?: Approval | null;
  task?: { query: string; document_id: string; version_id: string };
  unavailable?: boolean; plan_id?: string; outcome?: { status: string; answer: string; reason?: string } };
const storageKey = "getoffers-career-session-v1";
const stages: Record<string, string> = { candidate: "正在读取简历…", search: "正在查找岗位…", evidence: "正在核对经历…", applications: "正在检查投递记录…", propose: "等待确认", done: "已加入待投递" };

async function call(action: string, payload: object): Promise<Run> {
  const response = await fetch("/api/career", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action, payload }) });
  if (!response.ok) throw new Error(response.status === 401 ? "请先登录。" : response.status === 403 ? "无法读取此任务。" : response.status === 400 ? "任务已变化或正在处理中，请重新读取。" : "暂时无法匹配岗位，请稍后重试。");
  return response.json();
}

export default function DiscoveryPanel({ onSaved, onViewApplications }: { onSaved: () => void; onViewApplications: () => void }) {
  const [query, setQuery] = useState("");
  const [resume, setResume] = useState<ResumeReference>({ resume: "", resumeDocumentId: "", resumeVersionId: "" });
  const [discovery, setDiscovery] = useState<Run | null>(null);
  const [active, setActive] = useState<Run | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [clock, setClock] = useState(0);
  const ids = useRef<{ discovery?: string; active?: string }>({});
  const savedCallback = useRef(onSaved);
  useEffect(() => { savedCallback.current = onSaved; }, [onSaved]);
  useEffect(() => {
    let mounted = true;
    try { ids.current = JSON.parse(sessionStorage.getItem(storageKey) || "{}"); } catch { ids.current = {}; }
    if (ids.current.discovery) {
      setBusy(true);
      void Promise.all([call("get", { run_id: ids.current.discovery }), ids.current.active && ids.current.active !== ids.current.discovery ? call("get", { run_id: ids.current.active }) : Promise.resolve(null)])
        .then(([result, selection]) => { if (mounted) { setDiscovery(selection?.unavailable ? { ...result, jobs: [], unavailable: true } : result); setActive(selection ?? result); if (result.task) { setQuery(result.task.query); setResume({ resume: "", resumeDocumentId: result.task.document_id, resumeVersionId: result.task.version_id }); } if (selection?.plan_id) savedCallback.current(); } })
        .catch((e) => { if (mounted) setError(e.message); })
        .finally(() => { if (mounted) setBusy(false); });
    }
    const timer = setInterval(() => setClock(Date.now()), 1000);
    return () => { mounted = false; clearInterval(timer); };
  }, []);
  useEffect(() => {
    if (!busy) return;
    let mounted = true;
    const timer = setInterval(() => {
      const runId = ids.current.active;
      if (runId) void call("status", { run_id: runId }).then((result) => {
        if (mounted) setActive((previous) => previous?.run_id === result.run_id ? { ...previous, status: result.status, stage: result.stage } : previous);
      }).catch(() => {});
    }, 1500);
    return () => { mounted = false; clearInterval(timer); };
  }, [busy]);
  function persist(next: { discovery?: string; active?: string }) {
    ids.current = next;
    sessionStorage.setItem(storageKey, JSON.stringify(next));
  }
  function clearResults() { setDiscovery(null); setActive(null); setError(""); persist({}); }
  async function perform(action: string, payload: object, isDiscovery = false) {
    setBusy(true); setError("");
    try {
      const result = await call(action, payload);
      setActive(result);
      if (isDiscovery) setDiscovery(result);
      else if (result.unavailable) setDiscovery((previous) => previous ? { ...previous, jobs: [], unavailable: true } : previous);
      persist({ discovery: isDiscovery ? result.run_id : ids.current.discovery, active: result.run_id });
      if (result.plan_id) savedCallback.current();
    } catch (e) { setError(e instanceof Error ? e.message : "操作失败，请重试。"); }
    finally { setBusy(false); }
  }
  const approval = active?.approval;
  const expired = !!approval && clock > Date.parse(approval.expires_at);
  async function start(event: React.FormEvent) {
    event.preventDefault();
    if (!query.trim() || !resume.resumeDocumentId) return;
    const id = crypto.randomUUID();
    persist({ discovery: id, active: id });
    setDiscovery(null); setActive({ run_id: id, status: "running", stage: "search" });
    await perform("start", { run_id: id, task: { query: query.trim(), document_id: resume.resumeDocumentId, version_id: resume.resumeVersionId } }, true);
  }
  const completed = active?.outcome;
  return <section className="career-discovery">
    <form className="panel career-form" onSubmit={(e) => void start(e)}>
      <fieldset className="career-fields" disabled={busy || !!approval}>
      <ResumePicker currentOnly value={resume} onChange={(next) => { setResume(next); clearResults(); }} />
      <label className="career-query"><span>想找什么岗位</span><input maxLength={1000} value={query} onChange={(e) => { setQuery(e.target.value); clearResults(); }} placeholder="例如：北京的 Python 算法岗位" required /></label>
      <button className="primary-button" disabled={busy || !!approval || !resume.resumeDocumentId || !query.trim()}>查找岗位</button>
      </fieldset>
    </form>
    {(busy || active?.status === "running" || active?.status === "cancelling") && <div className="career-progress" role="status"><span>{busy ? stages[active?.stage ?? "search"] || "正在处理…" : active?.status === "cancelling" ? "正在停止…" : "任务尚未完成"}</span>
      {active?.run_id && <button type="button" className="secondary-button" onClick={() => { void call("cancel", { run_id: ids.current.active }).then(setActive).catch((e) => setError(e.message)); }}>停止</button>}
    </div>}
    {error && <div className="career-message" role="alert">{error} <button type="button" disabled={busy} onClick={() => { if (ids.current.active) void perform("get", { run_id: ids.current.active }, ids.current.active === ids.current.discovery); }}>重新读取</button></div>}
    {!busy && active && ["running", "awaiting_reconciliation", "cancelling"].includes(active.status) && <button className="secondary-button" onClick={() => void perform("resume", { run_id: active.run_id }, active.run_id === ids.current.discovery)}>继续任务</button>}
    {active?.unavailable && <p className="career-message" role="alert">简历或岗位依据已变化，请重新查找。</p>}
    {completed && completed.status !== "success" && <p className="career-message" role="status">{completed.status === "rejected" ? "已取消加入。" : completed.status === "cancelled" ? "已停止。" : "任务未完成，请重新查找。"}</p>}
    {active?.plan_id && !active.unavailable && <div className="career-message" role="status">已加入待投递。<button onClick={onViewApplications}>查看投递记录</button></div>}
    {approval && <section className="panel career-approval" aria-label="确认加入待投递">
      <h3>加入待投递</h3><p>{approval.plan.company} · {approval.plan.role}</p>
      <dl><dt>简历</dt><dd>{approval.plan.resume}</dd><dt>状态</dt><dd>待投递</dd></dl>
      <p className="career-muted">此操作只保存记录，不会向公司投递。</p>
      {expired && <p role="alert">确认已过期，请取消后重新查找。</p>}
      <div className="career-actions"><button className="secondary-button" disabled={busy} onClick={() => void perform("decide", { run_id: active.run_id, approval: { action_id: approval.action_id, arguments_hash: approval.arguments_hash, decision: "reject" } })}>取消</button><button className="primary-button" disabled={busy || expired} onClick={() => void perform("decide", { run_id: active.run_id, approval: { action_id: approval.action_id, arguments_hash: approval.arguments_hash, decision: "grant" } })}>确认加入</button></div>
    </section>}
    {discovery?.outcome?.status === "success" && !discovery.unavailable && !discovery.jobs?.length && <div className="empty-card"><h3>未找到符合条件的岗位</h3><p>可调整岗位方向或城市后重试。</p></div>}
    {!!discovery?.jobs?.length && <p className="career-muted">按岗位要求关联简历原文，是否符合要求需逐项核对。</p>}
    <div className="career-results">{discovery?.jobs?.map((job) => <article className="panel career-result" key={job.version_id}>
      <div className="career-result-heading"><div><h3>{job.title}</h3><p>{job.company} · {job.cities.join(" / ") || "地点未注明"}</p></div><a href={job.source_url} target="_blank" rel="noreferrer">原岗位 ↗</a></div>
      <details><summary>岗位要求</summary><ul>{job.requirements.map((item, i) => <li key={i}>{item}</li>)}</ul></details>
      <h4>相关经历</h4>
      {job.evidence.length ? job.evidence.map((item) => <div className="career-evidence" key={item.evidence_id}><blockquote>{item.quote}</blockquote><small>{item.path.join(" / ")}{item.confirmed_facts.includes(item.quote) && <span className="career-confirmed"> · 已确认</span>}</small>{item.confirmed_facts.filter((fact) => fact !== item.quote).map((fact, index) => <p key={index}><span className="career-confirmed">已确认</span> {fact}</p>)}</div>) : <p className="career-muted">所选简历中未找到相关依据。</p>}
      {!!job.gaps.length && <details><summary>未找到依据的要求 · {job.gaps.length}</summary><ul>{job.gaps.map((gap, index) => <li key={index}>{gap}</li>)}</ul></details>}
      <button className="secondary-button job-add" disabled={busy || !!approval || !!job.application_id || (!!active?.plan_id && !!active?.jobs?.some((j) => j.job_id === job.job_id))} onClick={() => void perform("propose", { run_id: discovery.run_id, job_version_id: job.version_id })}>{job.application_id || active?.plan_id && active?.jobs?.some((j) => j.job_id === job.job_id) ? "已在投递中" : "加入待投递"}</button>
    </article>)}</div>
  </section>;
}
