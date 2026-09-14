"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CircleAlert, CircleCheck, Clock3, Download, FileText, FileUp, History, LoaderCircle, RotateCw, Trash2, Upload, Check, X, type LucideIcon } from "lucide-react";
import "./knowledge.css";

type Version = { version_id: string; status: string; error: string | null; extension: string; created_at: string };
type Doc = { document_id: string; name: string; status: string; active_version: string | null; versions: Version[]; deletion: { stage: string; error: string | null } | null };
type Locator = { page: number | null; line_start: number | null; line_end: number | null; node_id: string };
type Fact = { fact_id: string; document_id: string; value: string; status: string; revision: number; evidence_ids: string[] };
const labels: Record<string, string> = { uploaded: "等待处理", processing: "正在处理", active: "已处理", failed: "处理失败", superseded: "历史版本", deleting: "正在删除", proposed: "待确认", user_confirmed: "已确认", user_corrected: "已修正", rejected: "已拒绝" };
const errors: Record<string, string> = { KNOWLEDGE_UNAVAILABLE: "知识库暂不可用，请稍后重试。", UNAUTHORIZED: "请先登录。", parser_unavailable_or_document_invalid: "无法解析文件，请另存为 TXT 或 Markdown 后重试。", fact_revision_conflict: "内容已更新，请刷新后重试。", document_not_active: "材料尚未处理完成。", empty_or_oversized_file: "请选择非空且不超过 5 MB 的文件。", utf8_required: "文本文件需要使用 UTF-8 编码。" };

async function api<T>(action: string, payload: object = {}): Promise<T> {
  const response = await fetch("/api/knowledge", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action, payload }) });
  const body = await response.json();
  if (!response.ok) throw new Error(errors[body.error] ?? "操作未完成，请检查文件或稍后重试。");
  return body as T;
}

function location(locator: Locator) {
  return locator.page ? `第 ${locator.page} 页` : locator.line_start ? `第 ${locator.line_start}–${locator.line_end} 行` : "文档段落";
}

const documentStatusIcons: Record<string, { icon: LucideIcon; tone: string }> = {
  uploaded: { icon: Clock3, tone: "pending" },
  processing: { icon: LoaderCircle, tone: "pending" },
  active: { icon: CircleCheck, tone: "ready" },
  failed: { icon: CircleAlert, tone: "error" },
  superseded: { icon: History, tone: "muted" },
  deleting: { icon: LoaderCircle, tone: "pending" },
};

function DocumentStatus({ status }: { status: string }) {
  const meta = documentStatusIcons[status] ?? documentStatusIcons.uploaded;
  const Icon = meta.icon;
  const label = labels[status] ?? status;
  return <span className={`kb-document-status kb-document-status--${meta.tone}`} role="img" aria-label={`材料状态：${label}`} title={label}><Icon size={16} strokeWidth={1.8} /></span>;
}

export default function KnowledgePanel() {
  const [docs, setDocs] = useState<Doc[]>([]);
  const [facts, setFacts] = useState<Fact[]>([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<Doc | null>(null);
  const [preview, setPreview] = useState<{ title: string; text: string; quote: string; document_id: string; version_id: string } | null>(null);
  const [edit, setEdit] = useState<Fact | null>(null);
  const [replacement, setReplacement] = useState<string | undefined>();
  const input = useRef<HTMLInputElement>(null);
  const pendingFacts = facts.filter((fact) => fact.status === "proposed");
  const refresh = useCallback(async () => {
    const [documents, claims] = await Promise.all([api<{ documents: Doc[] }>("list"), api<{ facts: Fact[] }>("facts")]);
    setDocs(documents.documents); setFacts(claims.facts);
    const isCurrent = (item: { document_id: string; version_id: string }) => documents.documents.some((doc) => doc.document_id === item.document_id && doc.status === "active" && doc.active_version === item.version_id);
    setPreview((current) => current && isCurrent(current) ? current : null);
  }, []);
  useEffect(() => { void Promise.resolve().then(refresh).catch((e: Error) => setError(e.message)); }, [refresh]);
  async function run(name: string, work: () => Promise<void>) {
    setBusy(name); setError(""); setMessage("");
    try { await work(); } catch (e) { setError(e instanceof Error ? e.message : "操作未完成"); }
    finally { setBusy(""); await refresh().catch(() => {}); }
  }
  async function upload(file: File) {
    await run("上传并处理", async () => {
      if (!file.size || file.size > 5 * 1024 * 1024) throw new Error("请选择非空且不超过 5 MB 的文件。");
      const extension = file.name.split(".").pop()?.toLowerCase();
      const mimes: Record<string, string> = { md: "text/markdown", txt: "text/plain", pdf: "application/pdf", docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" };
      if (!extension || !mimes[extension]) throw new Error("支持 TXT、Markdown、PDF 和 DOCX。");
      const bytes = new Uint8Array(await file.arrayBuffer());
      let binary = "";
      for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
      const added = await api<{ document_id: string; version_id: string }>("upload", { filename: file.name, mime: mimes[extension], content_base64: btoa(binary), ...(replacement ? { document_id: replacement } : {}) });
      setPreview(null);
      await refresh();
      await api("process", added);
      setMessage("材料已处理。");
      setReplacement(undefined);
    });
    if (input.current) input.current.value = "";
  }
  async function cite(id: string) {
    await run("打开引用", async () => {
      const result = await api<{ evidence: { text: string; locator: Locator; document_id: string; version_id: string }; source_node: { text: string } }>("citation", { evidence_id: id });
      setPreview({ title: `来源 · ${location(result.evidence.locator)}`, text: result.source_node.text, quote: result.evidence.text, document_id: result.evidence.document_id, version_id: result.evidence.version_id });
    });
  }
  async function review(fact: Fact, action: string, value?: string) {
    await run("保存审核", async () => {
      await api("review", { fact_id: fact.fact_id, expected_revision: fact.revision, action, ...(value ? { corrected_value: value } : {}) });
      setFacts((current) => current.filter((item) => item.fact_id !== fact.fact_id));
      setEdit(null); setMessage("已保存。");
    });
  }
  async function download(doc: Doc, version: Version) {
    await run("打开原文件", async () => {
      const result = await api<{ content_base64: string; extension: string }>("source", { document_id: doc.document_id, version_id: version.version_id });
      const data = Uint8Array.from(atob(result.content_base64), (c) => c.charCodeAt(0));
      const url = URL.createObjectURL(new Blob([data], { type: "application/octet-stream" }));
      const link = document.createElement("a"); link.href = url; link.download = doc.name; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
  }
  return <section className="kb-shell" aria-label="个人档案">

    <input ref={input} type="file" hidden accept=".txt,.md,.pdf,.docx" onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(file); }} />
    {error && <div className="kb-notice kb-error" role="alert">{error}</div>}
    {(busy || message) && <div className="kb-notice" role="status">{busy ? `${busy}中…` : message}</div>}
    <section className="kb-panel"><div className="kb-section-title"><h2>我的材料 <small>{docs.length}</small></h2><div className="kb-section-actions"><button className="primary-button" disabled={!!busy} onClick={() => { setReplacement(undefined); input.current?.click(); }}><Upload size={16} />上传材料</button><button aria-label="刷新材料" className="icon-button" disabled={!!busy} onClick={() => void run("刷新", refresh)}><RotateCw size={15} /></button></div></div>
      <p className="kb-muted">PDF、DOCX、TXT、Markdown · 每份不超过 5 MB</p>
      {!docs.length && <div className="compact-empty-state kb-empty"><FileText size={20} strokeWidth={1.5} /><p>暂无材料</p></div>}
      {docs.map((doc) => <article className="kb-document" key={doc.document_id}>
        <div className="kb-document-title"><span className="kb-document-icon"><FileText size={18} /></span><strong>{doc.name}</strong><div className="kb-document-tools"><DocumentStatus status={doc.status} /><button className="icon-button kb-document-tool" title="上传新版本" aria-label={`为 ${doc.name} 上传新版本`} disabled={!!busy || doc.status === "deleting"} onClick={() => { setReplacement(doc.document_id); input.current?.click(); }}><FileUp size={16} /></button><button className="icon-button kb-document-tool kb-document-tool--danger" title={doc.status === "deleting" ? "重试删除" : "删除材料"} aria-label={`${doc.status === "deleting" ? "重试删除" : "删除"} ${doc.name}`} disabled={!!busy} onClick={() => setDeleteTarget(doc)}><Trash2 size={16} /></button></div></div>
        <details><summary>{doc.versions.length} 个版本</summary>{doc.versions.map((version, index) => <div key={version.version_id} className="kb-version"><span>版本 {doc.versions.length - index} · {labels[version.status]}</span><div className="kb-version-actions"><button className="icon-button kb-version-download" title="下载原文件" aria-label={`下载 ${doc.name} 版本 ${doc.versions.length - index}`} disabled={!!busy || doc.status === "deleting"} onClick={() => void download(doc, version)}><Download size={15} /></button>{["uploaded", "failed", "processing"].includes(version.status) && <button disabled={!!busy} onClick={() => void run("处理文档", async () => { await api("process", { document_id: doc.document_id, version_id: version.version_id }); })}>重新处理</button>}</div>{version.error && <p className="kb-inline-error">{errors[version.error] ?? "处理失败，请重试或更换格式。"}</p>}</div>)}</details>
        {doc.deletion?.error && <p className="kb-inline-error">删除未完成，请重试。</p>}
      </article>)}
    </section>
    {pendingFacts.length > 0 && <section className="kb-panel kb-facts"><h2>核对事实 <small>{pendingFacts.length} 条待确认</small></h2>{pendingFacts.map((fact) => <article className="kb-fact" key={fact.fact_id}><div><span className="kb-badge">{labels[fact.status]}</span><p>{fact.value}</p><button disabled={!!busy} onClick={() => void cite(fact.evidence_ids[0])}>核对来源</button></div><div className="kb-fact-actions"><button disabled={!!busy} onClick={() => void review(fact, "confirm")}><Check size={14} />确认</button><button disabled={!!busy} onClick={() => setEdit(fact)}>修正</button><button disabled={!!busy} onClick={() => void review(fact, "reject")}><X size={14} />拒绝</button></div></article>)}</section>}
    {(preview || deleteTarget || edit) && <div className="kb-overlay"><section role="dialog" aria-modal="true" aria-label={preview ? "引用原文" : deleteTarget ? "删除材料" : "修正事实"} className="kb-dialog"><button aria-label="关闭对话框" className="kb-close icon-button" onClick={() => { setPreview(null); setDeleteTarget(null); setEdit(null); }}><X size={18} /></button>
      {preview && <><h2>{preview.title}</h2><blockquote>{preview.quote}</blockquote>{preview.text !== preview.quote && <pre>{preview.text}</pre>}</>}
      {deleteTarget && <><h2>删除「{deleteTarget.name}」？</h2><p>所有版本将被删除，无法恢复。投递记录保留，文件链接将失效。</p><button className="primary-button" disabled={!!busy} onClick={() => { const target = deleteTarget; setDeleteTarget(null); void run("删除材料", async () => { const result = await api<{ verified: boolean }>("delete", { document_id: target.document_id }); setMessage(result.verified ? "已删除。" : "删除未完成，请重试。"); }); }}>确认删除</button></>}
      {edit && <><h2>修正事实</h2><label htmlFor="fact-value">事实内容</label><textarea id="fact-value" rows={6} maxLength={2000} value={edit.value} onChange={(event) => setEdit({ ...edit, value: event.target.value })} /><button className="primary-button" disabled={!!busy || !edit.value.trim()} onClick={() => void review(edit, "correct", edit.value)}>保存修正</button></>}
    </section></div>}
  </section>;
}
