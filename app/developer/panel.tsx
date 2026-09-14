"use client";

import { useEffect, useRef, useState } from "react";
import { Activity, ChevronDown, RefreshCw } from "lucide-react";
import "./panel.css";
import { formatCost } from "./format";
import { PairedReviews, ReviewResults, reviewStatus, type CaseReview, type Review, type ReviewComparison } from "./review";

type Span = { name: string; status: string; duration_ms: number | null; input_tokens: number | null; output_tokens: number | null; error_category: string | null };
type Run = { synthetic: boolean; id: string; run_id: string; created_at: string | null; status: string; failure: string | null; duration_ms: number | null; input_tokens: number | null; output_tokens: number | null; cost_usd: number | null; config_hash: string | null; spans?: Span[] };
type Case = { case_id: string; review: CaseReview | null; passed: boolean; checks: { name: string; passed: boolean }[]; duration_ms: number | null; model_duration_ms: number | null; tool_duration_ms: number | null; input_tokens: number | null; output_tokens: number | null; cost_usd: number | null; failure: string | null };
type Evaluation = { review: Review; id: string; report_hash: string; dataset_hash: string; source_hash: string; workflow_hash: string; dependency_lock_hash: string; created_at: string | null; mode: string; total: number; passed: number; cases?: Case[] };
type Catalog<T> = { items: T[]; invalid: number; truncated: boolean };
type Comparison = ReviewComparison & { paired_cases: number; changed_factors: string[]; contract_regression: boolean; contract_pass_delta: number; duration_delta_ms: number };
const labels: Record<string, string> = { success: "完成", partial: "部分完成", failed: "失败", rejected: "已拒绝", cancelled: "已取消", incomplete: "未完成", pending: "未结束", completed: "完成", workflow: "工作流", agent: "Agent", step: "步骤", model: "模型", tool: "工具", approval: "审批", service_accepted: "服务完成", required_tools: "必需工具", forbidden_tools_absent: "禁用工具", only_registered_read_tools: "工具权限", draft_kind: "草稿类型", citations_present: "引用存在", jobs_present: "岗位结果", city_constraint: "城市约束", forbidden_draft_fragments_absent: "禁用表述", foreign_canary_absent: "租户隔离", trace_present: "运行记录" };
const text = (value: string) => labels[value] || value;
const metric = (value: number | null | undefined, suffix = "") => value == null ? "未知" : `${value.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}${suffix}`;
const time = (value: string | null) => value ? new Date(value).toLocaleString("zh-CN") : "时间未知";
async function request<T>(params: Record<string, string>, signal: AbortSignal): Promise<T> {
  const response = await fetch(`/api/developer-observability?${new URLSearchParams(params)}`, { cache: "no-store", signal });
  if (!response.ok) throw new Error(response.status === 403 || response.status === 404 ? "ACCESS_DENIED" : "记录无法读取或两组实验不满足配对条件。请检查本地服务与报告后重试。");
  return response.json() as Promise<T>;
}

export default function DeveloperPanel() {
  const [enabled, setEnabled] = useState(false), [open, setOpen] = useState(false);
  const [tab, setTab] = useState<"runs" | "evaluations">("runs");
  const [runs, setRuns] = useState<Catalog<Run>>({ items: [], invalid: 0, truncated: false });
  const [evaluations, setEvaluations] = useState<Catalog<Evaluation>>({ items: [], invalid: 0, truncated: false });
  const [run, setRun] = useState<Run | null>(null), [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [baseline, setBaseline] = useState(""), [challenger, setChallenger] = useState("");
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [status, setStatus] = useState("all"), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const active = useRef<AbortController | null>(null);
  useEffect(() => {
    let check = new AbortController();
    const probe = (controller: AbortController) => {
      void request<{ capabilities: string[] }>({ action: "capabilities" }, controller.signal).then(value => {
        if (!controller.signal.aborted) setEnabled(["metrics:read", "trace:read:redacted", "evaluation:read"].every(c => value.capabilities.includes(c)));
      }).catch(() => {});
    };
    const discover = () => {
      check.abort(); active.current?.abort(); setEnabled(false); setOpen(false); setRun(null); setEvaluation(null); setComparison(null);
      setRuns({ items: [], invalid: 0, truncated: false }); setEvaluations({ items: [], invalid: 0, truncated: false });
      setBaseline(""); setChallenger(""); setBusy(false); setError("");
      check = new AbortController(); probe(check);
    };
    // An explicit account event invalidates all visible developer data immediately.
    const changed = (event: Event) => { if ((event as CustomEvent).detail?.action !== "model") discover(); };
    probe(check);
    window.addEventListener("getoffers-account-changed", changed);
    return () => { check.abort(); active.current?.abort(); window.removeEventListener("getoffers-account-changed", changed); };
  }, []);
  async function perform(work: (signal: AbortSignal) => Promise<void>) {
    active.current?.abort(); const controller = new AbortController(); active.current = controller;
    setBusy(true); setError("");
    try { await work(controller.signal); }
    catch (cause) { if (!controller.signal.aborted) { if ((cause as Error).message === "ACCESS_DENIED") { setEnabled(false); setOpen(false); setRun(null); setEvaluation(null); setComparison(null); } else setError((cause as Error).message); } }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  function refresh() {
    setRun(null); setEvaluation(null); setComparison(null);
    void perform(async signal => {
      const [r, e] = await Promise.all([request<Catalog<Run>>({ action: "runs" }, signal), request<Catalog<Evaluation>>({ action: "evaluations" }, signal)]);
      if (!signal.aborted) { setRuns(r); setEvaluations(e); setBaseline(""); setChallenger(""); }
    });
  }
  function inspect(id: string) {
    setRun(null); setEvaluation(null);
    void perform(async signal => {
      if (tab === "runs") { const value = await request<Run>({ action: "run", id }, signal); if (!signal.aborted) setRun(value); }
      else { const value = await request<Evaluation>({ action: "evaluation", id }, signal); if (!signal.aborted) setEvaluation(value); }
    });
  }
  if (!enabled) return null;
  const catalog = tab === "runs" ? runs : evaluations;
  const filtered = runs.items.filter(r => status === "all" || r.status === status);
  return <section className="panel settings-section developer-panel" aria-label="运行与评测">
    <div className="settings-heading"><span className="settings-icon"><Activity size={17} /></span><h2>运行与评测</h2></div>
    <button className="secondary-button secondary-button--small developer-toggle" aria-expanded={open} aria-controls="developer-inspector" onClick={() => { setOpen(!open); if (!open) refresh(); }}> {open ? "收起记录" : "查看记录"}<ChevronDown size={15} /></button>
    {open && <div id="developer-inspector" className="developer-inspector" aria-busy={busy}>
      <div className="developer-toolbar"><div role="group" aria-label="记录类型">{(["runs", "evaluations"] as const).map(t => <button key={t} className="secondary-button secondary-button--small" aria-pressed={tab === t} onClick={() => { active.current?.abort(); setBusy(false); setTab(t); setRun(null); setEvaluation(null); setError(""); }}>{t === "runs" ? "运行记录" : "评测实验"}</button>)}</div><button className="text-button" disabled={busy} onClick={refresh}><RefreshCw size={14} />刷新</button></div>
      {error && <p role="alert" className="developer-error">{error} <button className="text-button" onClick={refresh}>重新读取</button></p>}
      {busy && <p role="status">正在读取并校验记录…</p>}
      {(catalog.invalid > 0 || catalog.truncated) && <p role="status" className="developer-note">{catalog.invalid > 0 && `${catalog.invalid} 份记录损坏、缺失或格式不受支持，已跳过。`}{catalog.truncated && "已达到本次读取上限，当前列表不完整。"}</p>}
      {tab === "runs" ? <>
        <label className="developer-filter">运行状态<select value={status} onChange={e => setStatus(e.target.value)}><option value="all">全部状态</option>{["success", "partial", "failed", "rejected", "cancelled", "incomplete"].map(s => <option key={s} value={s}>{text(s)}</option>)}</select></label>
        {!busy && !filtered.length && <p className="developer-empty">{runs.items.length ? "没有符合该状态的运行。" : "暂无运行记录。完成一次岗位助手对话后，在这里刷新。"}</p>}
        <div className="developer-list">{filtered.map(item => <button key={item.id} className="developer-row" aria-pressed={run?.run_id === item.run_id} onClick={() => inspect(item.id)}><span><time>{time(item.created_at)}</time><code>{item.run_id.slice(0, 8)}</code></span><span>{item.synthetic ? "合成运行 · " : ""}{text(item.status)} · {metric(item.duration_ms, " ms")}</span></button>)}</div>
        {run && <section className="developer-detail" aria-label="运行详情"><h3>运行详情</h3><p className="developer-note">{run.synthetic ? "合成运行；用量不代表真实模型调用。" : "状态来自 Runtime；不代表生成内容已通过质量审核。"}</p><p className="developer-note">配置 <code>{run.config_hash || "未知"}</code></p><p>输入 {metric(run.input_tokens)} / 输出 {metric(run.output_tokens)} token · 费用 {`${formatCost(run.cost_usd)}${run.cost_usd == null ? "" : " USD"}`}{run.failure && ` · ${run.failure}`}</p>
          <div className="developer-table" role="region" aria-label="阶段时间线，可横向滚动" tabIndex={0}><table><caption>阶段时间线（父阶段包含子阶段耗时）</caption><thead><tr><th>阶段</th><th>状态</th><th>耗时</th><th>输入 / 输出 token</th><th>失败类别</th></tr></thead><tbody>{run.spans?.map((s, i) => <tr key={i}><th scope="row">{text(s.name)}</th><td>{text(s.status)}</td><td>{metric(s.duration_ms, " ms")}</td><td>{s.name === "model" ? `${metric(s.input_tokens)} / ${metric(s.output_tokens)}` : "—"}</td><td>{s.error_category || "—"}</td></tr>)}</tbody></table></div>
        </section>}
      </> : <>
        <p className="developer-note">自动契约检查不代表回答质量。审核表可用于查看人工评分；生产发布仍未评估。</p>
        {!busy && !evaluations.items.length && <div className="developer-empty"><p>暂无有效评测。先运行本地合成评测，再刷新。</p><code>npm run assistant:eval -- run --mode scripted --out .agent-data/assistant-eval/first-run</code><p>每次使用新的输出目录。</p></div>}
        <div className="developer-list">{evaluations.items.map(item => <button key={item.id} className="developer-row" aria-pressed={evaluation?.report_hash === item.report_hash} onClick={() => inspect(item.id)}><span><time>{time(item.created_at)}</time><small>{item.mode === "scripted" ? "脚本模型 · 合成用例" : "真实模型 · 合成用例"} · {item.report_hash.slice(0, 8)}</small></span><span>{item.passed} / {item.total} 契约通过 · {reviewStatus(item.review)}</span></button>)}</div>
        {evaluation && <section className="developer-detail" aria-label="评测详情"><h3>评测详情</h3><dl className="developer-identities">{[["报告", evaluation.report_hash], ["数据集", evaluation.dataset_hash], ["代码", evaluation.source_hash], ["工作流", evaluation.workflow_hash], ["依赖", evaluation.dependency_lock_hash]].map(([label, hash]) => <div key={label}><dt>{label}</dt><dd><code>{hash}</code></dd></div>)}</dl><div className="developer-table" role="region" aria-label="逐例结果，可横向滚动" tabIndex={0}><table><caption>逐例结果（序号对应报告中的用例顺序）</caption><thead><tr><th>用例</th><th>检查</th><th>总耗时</th><th>模型 / 工具</th><th>输入 / 输出 token</th><th>费用 USD</th></tr></thead><tbody>{evaluation.cases?.map(c => <tr key={c.case_id}><th scope="row">{c.case_id}</th><td>{c.passed ? "通过" : "未通过"}{c.checks.filter(k => !k.passed).map(k => <small className="developer-error" key={k.name}>{text(k.name)}</small>)}{c.failure && <small>{c.failure}</small>}</td><td>{metric(c.duration_ms, " ms")}</td><td>{metric(c.model_duration_ms)} / {metric(c.tool_duration_ms)} ms</td><td>{metric(c.input_tokens)} / {metric(c.output_tokens)}</td><td>{formatCost(c.cost_usd)}</td></tr>)}</tbody></table></div><ReviewResults review={evaluation.review} cases={evaluation.cases || []} /></section>}
        {evaluations.items.length > 1 && <section className="developer-detail" aria-label="配对比较"><h3>配对比较</h3><p className="developer-note">同一数据集、用例、依赖、评分器与执行模式才能比较。差值为候选减基线。</p><div className="developer-compare">{([["基线", baseline, setBaseline], ["候选", challenger, setChallenger]] as const).map(([label, value, setter]) => <label key={label}>{label}<select disabled={busy} value={value} onChange={e => { setter(e.target.value); setComparison(null); }}><option value="">选择实验</option>{evaluations.items.map(e => <option key={e.id} value={e.id}>{time(e.created_at)} · {e.report_hash.slice(0, 8)}</option>)}</select></label>)}<button className="secondary-button secondary-button--small" disabled={busy || !baseline || !challenger || baseline === challenger} onClick={() => { setComparison(null); void perform(async signal => { const value = await request<Comparison>({ action: "compare", baseline, challenger }, signal); if (!signal.aborted) setComparison(value); }); }}>比较</button></div>{comparison && <div role="status"><p>{comparison.paired_cases} 条配对 · {comparison.contract_regression ? "存在契约回退" : "未发现契约回退"}</p><p>通过数变化 {comparison.contract_pass_delta} · 平均耗时变化 {metric(comparison.duration_delta_ms, " ms")}</p><p className="developer-note">变化因素：{comparison.changed_factors.join("、") || "无"}。单次采样不能证明显著提升；真实场景质量与发布结论保持未评估。</p><PairedReviews comparison={comparison} /></div>}</section>}
      </>}
    </div>}
  </section>;
}
