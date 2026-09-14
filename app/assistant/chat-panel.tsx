"use client";

import { createPortal } from "react-dom";
import { useHistory } from "./use-history";
import HistoryMenu from "./history-menu";
import type { Draft, Job, Message, Snapshot } from "./history";

import LocalConnection from "./local-connection";
import ComposerPopover from "./composer-popover";

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowUp, Check, BriefcaseBusiness, Copy, Download, FileText, Paperclip, Square } from "lucide-react";
import { knowledgeFiles, type KnowledgeDocument, type KnowledgeFile } from "../knowledge/files";
import Markdown from "./markdown";

type Status = "loading" | "ready" | "unauthorized" | "unconfigured" | "unavailable";
const starters = [
  ["梳理项目", "帮我梳理所选材料中的项目：项目目标、我的职责、技术选择和实际结果。缺少的信息请逐步问我。"],
  ["找合适岗位", "结合我的经历帮我找合适的岗位。先确认求职方向和城市，再解释匹配依据与需要确认的要求。"],
  ["调整简历", "针对目标 JD，帮我重新组织简历内容。保留真实事实，给出可用草稿和必要的取舍说明。"],
  ["准备面试", "针对目标 JD 和我的项目经历，帮我准备面试问题、回答提纲与可能的追问。"],
];
const errors: Record<string, string> = {
  UNAUTHORIZED: "请先登录。", MODEL_NOT_CONFIGURED: "助手尚未启用。", ASSISTANT_UNAVAILABLE: "助手暂时不可用，请稍后重试。",
  ASSISTANT_INCOMPLETE: "这次回答未完成，请重试或缩小问题范围。", MATERIAL_CHANGED: "材料已更新或删除，请重新选择后开始新对话。",
  KNOWLEDGE_UNAVAILABLE: "暂时无法读取材料，请稍后重试。", INVALID_CITATION: "回答中的引用未通过核对，请重试。",
  CITATION_CHANGED: "引用材料已变化，请重新提问。", UNGROUNDED_DRAFT: "材料不足以支持这份草稿，请补充经历后重试。",
  MISSING_JD: "请提供目标 JD 后重试。", JOB_CHANGED: "岗位信息已变化，请重新查找。", INVALID_REQUEST: "内容过长或格式无效，请精简后重试。",
};

function DraftCard({ draft, onEdit }: { draft: Draft; onEdit: (content: string) => void }) {
  const [content, setContent] = useState(draft.content);
  const [editing, setEditing] = useState(false);
  const [notice, setNotice] = useState("");
  async function copy() {
    try { await navigator.clipboard.writeText(content); setNotice("已复制"); } catch { setNotice("复制失败，请选中文本复制。"); }
  }
  function download() {
    const url = URL.createObjectURL(new Blob([content], { type: "text/markdown;charset=utf-8" }));
    const link = document.createElement("a"); link.href = url; link.download = `${draft.title.replace(/[\\/:*?"<>|]/g, "_")}.md`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return <section className="assistant-draft" aria-label={draft.title}>
    <header><h3>{draft.title}</h3><span>草稿</span></header>
    {editing ? <textarea aria-label="编辑草稿" value={content} onChange={(e) => { setContent(e.target.value); onEdit(e.target.value); }} maxLength={16000} rows={14} /> : <Markdown text={content} />}
    <footer><button onClick={() => setEditing(!editing)}>{editing ? "完成编辑" : "编辑"}</button><button onClick={() => void copy()}><Copy size={14} />复制</button><button onClick={download}><Download size={14} />导出</button>{notice && <span role="status">{notice}</span>}</footer>
  </section>;
}

export default function ChatPanel({ active, historyTarget, onKnowledge, onAddJob }: { active: boolean; historyTarget: HTMLElement | null; onKnowledge: () => void; onAddJob: (job: Job) => void }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [jd, setJd] = useState("");
  const [filesLoaded, setFilesLoaded] = useState(false);
  const [files, setFiles] = useState<KnowledgeFile[]>([]);
  const [materials, setMaterials] = useState<KnowledgeFile[]>([]);
  const [openContext, setOpenContext] = useState<"materials" | "jd" | "model" | null>(null);
  const toggleMaterials = useCallback((open: boolean) => setOpenContext(open ? "materials" : null), []);
  const toggleJd = useCallback((open: boolean) => setOpenContext(open ? "jd" : null), []);
  const toggleModel = useCallback((open: boolean) => setOpenContext(open ? "model" : null), []);
  const [status, setStatus] = useState<Status>("loading");
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState("");
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [materialsError, setMaterialsError] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const selectedRef = useRef(materials);
  const history = useHistory({ messages, materials, jd, input }, busy, active, (value: Snapshot) => {
    selectedRef.current = value.materials; setMessages(value.messages); setMaterials(value.materials);
    setJd(value.jd); setInput(value.input); setError(""); setOpenContext(null);
  });
  const staleMaterials = filesLoaded && materials.some(selected => !files.some(file => file.documentId === selected.documentId && file.versionId === selected.versionId));
  useEffect(() => { selectedRef.current = materials; }, [materials]);
  useEffect(() => {
    if (!active) return;
    const abort = new AbortController();
    void fetch("/api/assistant", { signal: abort.signal }).then(async (response) => {
      if (response.status === 401) { setStatus("unauthorized"); setMessages([]); setMaterials([]); return; }
      if (!response.ok) { setStatus("unavailable"); return; }
      const data = await response.json(); setStatus(data.configured ? "ready" : "unconfigured");
    }).catch(() => { if (!abort.signal.aborted) setStatus("unavailable"); });
    void fetch("/api/knowledge", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "list" }), signal: abort.signal }).then(async (response) => {
      if (!response.ok) throw Error("unavailable");
      const data = await response.json() as { documents: KnowledgeDocument[] };
      const available = knowledgeFiles(data.documents).filter((file) => data.documents.some((doc) => doc.status === "active" && doc.document_id === file.documentId && doc.active_version === file.versionId));
      setFiles(available); setFilesLoaded(true); setMaterialsError(false);
      if (selectedRef.current.some((selected) => !available.some((file) => file.documentId === selected.documentId && file.versionId === selected.versionId))) {
        controller.current?.abort(); setError(errors.MATERIAL_CHANGED);
      }
    }).catch(() => { if (!abort.signal.aborted) { setMaterialsError(true); if (selectedRef.current.length) { controller.current?.abort(); } } });
    return () => abort.abort();
  }, [active, refresh]);
  useEffect(() => {
    const changed = (event: Event) => {
      if ((event as CustomEvent<{ action: string }>).detail?.action !== "model") {
        controller.current?.abort(); setMessages([]); setMaterials([]); setJd(""); setInput("");
      }
      setRefresh(value => value + 1);
    };
    window.addEventListener("getoffers-account-changed", changed);
    return () => window.removeEventListener("getoffers-account-changed", changed);
  }, []);
  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => { if (active) endRef.current?.scrollIntoView({ block: "nearest" }); }, [messages.length, progress, active]);

  async function newChat() {
    if (!await history.start({ messages: [], materials: [], jd: "", input: "" })) return;
    setError(""); setProgress(""); inputRef.current?.focus();
  }
  async function toggleMaterial(file: KnowledgeFile) {
    const selected = materials.some(item => item.documentId === file.documentId) ? materials.filter(item => item.documentId !== file.documentId) : [...materials, file].slice(0, 10);
    if (messages.length) { await history.start({ messages: [], materials: selected, jd, input }); }
    else setMaterials(selected);
    setError("");
  }
  function prepareJob(job: Job, kind: "resume" | "interview") {
    setJd(`${job.company} · ${job.title}\n\n职责\n${job.responsibilities.join("\n")}\n\n要求\n${job.requirements.join("\n")}`);
    setInput(kind === "resume" ? "针对这个 JD，帮我重新组织简历内容，保留事实并给出草稿。" : "针对这个 JD 和我的项目经历，帮我准备面试问题、回答提纲和追问。");
    setOpenContext("jd"); inputRef.current?.focus();
  }
  async function send(event?: React.FormEvent) {
    event?.preventDefault();
    const text = input.trim(); if (!text || busy || status !== "ready" || !history.ready || history.loading || staleMaterials || (materials.length > 0 && materialsError)) return;
    const userMessage: Message = { id: crypto.randomUUID(), role: "user", content: text };
    const next = [...messages, userMessage];
    const contextMessages = next.slice(-24).map((m) => ({ role: m.role, content: m.content + (m.result?.draft ? `\n\n${m.result.draft.content}` : "") }));
    if (contextMessages.reduce((sum, m) => sum + m.content.length, jd.length) > 80000) { setError("对话较长，请导出需要的内容后开始新对话。"); return; }
    setOpenContext(null); setMessages(next); setInput(""); setError(""); setBusy(true); setProgress("正在理解你的问题");
    const abort = new AbortController(); controller.current = abort;
    let received = false;
    try {
      const response = await fetch("/api/assistant", { method: "POST", headers: { "Content-Type": "application/json" }, signal: abort.signal,
        body: JSON.stringify({ request_id: crypto.randomUUID(), messages: contextMessages, jd, materials: materials.map((file) => ({ document_id: file.documentId, version_id: file.versionId })) }) });
      if (!response.ok || !response.body) { const body = await response.json().catch(() => ({})); throw Error(errors[body.error] || errors.ASSISTANT_UNAVAILABLE); }
      const reader = response.body.getReader(), decoder = new TextDecoder(); let buffer = "";
      for (;;) {
        const { done, value } = await reader.read(); buffer += decoder.decode(value, { stream: !done });
        let newline;
        while ((newline = buffer.indexOf("\n")) >= 0) {
          const line = buffer.slice(0, newline); buffer = buffer.slice(newline + 1); if (!line.trim()) continue;
          const item = JSON.parse(line);
          if (item.type === "progress") setProgress(item.label);
          if (item.type === "error") throw Error(errors[item.error] || errors.ASSISTANT_INCOMPLETE);
          if (item.type === "done" && !received) { received = true; setMessages((prior) => [...prior, { id: item.run_id, role: "assistant", content: item.message.answer, result: item.message }]); }
        }
        if (done) break;
      }
      if (!received) throw Error(errors.ASSISTANT_INCOMPLETE);
    } catch (e) {
      if (received) return;
      if (abort.signal.aborted) setError("已停止。");
      else { setError(e instanceof Error ? e.message : errors.ASSISTANT_UNAVAILABLE); setInput(text); }
      // Keep only completed turns in the model's follow-up context; retry won't duplicate the user turn.
      setMessages((prior) => prior.filter((m) => m.id !== userMessage.id));
    } finally { setBusy(false); setProgress(""); controller.current = null; }
  }
  const statusText = { loading: "正在连接…", unauthorized: "", unconfigured: "助手尚未启用。", unavailable: "助手暂时不可用。", ready: "" }[status];
  return <section className="assistant-page" aria-label="岗位助手">
    {historyTarget && createPortal(<HistoryMenu entries={history.entries} currentId={history.id} disabled={busy || history.loading || !history.ready} loading={history.loading} error={history.error} hasMore={history.hasMore} unauthorized={status === "unauthorized"} onOpen={id => void history.open(id)} onNew={() => void newChat()} onMore={() => void history.more()} onRetry={history.retry} />, historyTarget)}
    <div className="assistant-conversation" aria-label="对话记录">
      {!messages.length && <div className="assistant-start"><h2>从哪件事开始？</h2><div>{starters.map(([label, prompt]) => <button key={label} onClick={() => { setInput(prompt); inputRef.current?.focus(); }}>{label}<span aria-hidden="true">↗</span></button>)}</div></div>}
      {messages.map((message) => <article key={message.id} className={`assistant-message assistant-message--${message.role}`} aria-label={message.role === "user" ? "我的消息" : "助手回复"}>
        <Markdown text={message.content} />
        {message.result?.draft && <DraftCard draft={message.result.draft} onEdit={(content) => setMessages((prior) => prior.map((m) => m.id === message.id && m.result?.draft ? { ...m, result: { ...m.result, draft: { ...m.result.draft, content } } } : m))} />}
        {!!message.result?.citations.length && <details className="assistant-sources"><summary>依据 · {message.result.citations.length}</summary>{message.result.citations.map((source) => <blockquote key={source.evidence_id}><p>{source.quote}</p><footer>{files.find((file) => file.documentId === source.document_id)?.filename ?? "所选材料"} · {source.path.join(" / ")}{source.status !== "source" && <span><Check size={12} />已确认</span>}</footer></blockquote>)}</details>}
        {!!message.result?.jobs.length && <div className="assistant-jobs">{message.result.jobs.map((job) => <section key={job.version_id}><h3>{job.title}</h3><p>{job.company} · {job.cities.join(" / ") || "地点未注明"}</p><a href={job.source_url} target="_blank" rel="noreferrer">查看原岗位 ↗</a><div><button disabled={busy} onClick={() => prepareJob(job, "resume")}>调整简历</button><button disabled={busy} onClick={() => prepareJob(job, "interview")}>准备面试</button><button onClick={() => onAddJob(job)}>加入待投递</button></div></section>)}</div>}
      </article>)}
      {staleMaterials && <p className="assistant-error" role="alert">所选材料已更新或删除。可查看历史内容，请新建对话后选择有效材料。</p>}
      {history.error && <p className="assistant-error" role="alert">{history.error}<button type="button" onClick={history.retry}>重试</button></p>}
      {busy && <p className="assistant-progress" role="status"><span />{progress}</p>}
      {error && <p className="assistant-error" role="alert">{error}</p>}
      <div ref={endRef} />
    </div>
    <form className="assistant-composer" onSubmit={(e) => void send(e)}>
      {(materials.length > 0 || jd.trim()) && <div className="assistant-context-chips" aria-label="本次对话的参考内容">
        {materials.map(file => <button type="button" key={file.documentId} title={file.label} onClick={() => setOpenContext("materials")}><FileText size={13} /><span>{file.label}</span></button>)}
        {jd.trim() && <button type="button" onClick={() => setOpenContext("jd")}><BriefcaseBusiness size={13} /><span>目标 JD</span></button>}
      </div>}
      {statusText && <div className="assistant-connection" role="status">{statusText}{["unavailable", "unconfigured"].includes(status) && <button type="button" onClick={() => setRefresh((value) => value + 1)}>重新连接</button>}</div>}
      <textarea ref={inputRef} aria-label="发给岗位助手的消息" placeholder="描述你想解决的问题…" rows={3} maxLength={12000} value={input} disabled={busy || history.loading} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(); } }} />
      <footer><div className="assistant-composer-tools">
        <ComposerPopover compact="materials" id="assistant-materials" label="选择材料" title="参考材料" icon={<Paperclip size={19} />} open={openContext === "materials"} onToggle={toggleMaterials} marked={materials.length > 0}>
          <div className="assistant-material-options">
            {!materialsError && files.map(file => <label key={file.documentId} title={file.label}><input type="checkbox" disabled={busy || history.loading} checked={materials.some(item => item.documentId === file.documentId)} onChange={() => void toggleMaterial(file)} /><span>{file.label}</span></label>)}
            {(!files.length || materialsError) && <p>{materialsError ? "暂时无法读取材料。" : "暂无可用材料"}</p>}
          </div>
          {messages.length > 0 && files.length > 0 && !materialsError && <p className="assistant-material-notice">更换材料将开始新对话</p>}
          <div className="assistant-material-actions">{materialsError && <button type="button" onClick={() => setRefresh(value => value + 1)}>重试</button>}<button type="button" onClick={() => { setOpenContext(null); onKnowledge(); }}><FileText size={15} />个人档案</button></div>
        </ComposerPopover>
        <ComposerPopover compact="editor" id="assistant-jd" label="添加或编辑目标 JD" title="目标 JD" icon={<BriefcaseBusiness size={19} />} open={openContext === "jd"} onToggle={toggleJd} marked={!!jd.trim()}>
          <textarea aria-label="目标岗位描述" rows={4} maxLength={24000} placeholder="粘贴岗位职责和任职要求" value={jd} disabled={busy} onChange={event => setJd(event.target.value)} />
          <div className="assistant-jd-actions">{!!jd && <button type="button" disabled={busy} onClick={() => setJd("")}>清空</button>}<button type="button" onClick={() => { setOpenContext(null); inputRef.current?.focus(); }}>完成</button></div>
        </ComposerPopover>
        <LocalConnection disabled={busy} compact open={openContext === "model"} onToggle={toggleModel} />
      </div>{busy ? <button type="button" aria-label="停止回答" onClick={() => controller.current?.abort()}><Square size={15} /></button> : <button type="submit" aria-label="发送消息" disabled={!input.trim() || status !== "ready" || !history.ready || history.loading || staleMaterials || (materials.length > 0 && materialsError)}><ArrowUp size={19} /></button>}</footer>
    </form>
  </section>;
}
