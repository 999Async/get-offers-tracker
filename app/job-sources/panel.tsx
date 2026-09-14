"use client";
import { useEffect, useState } from "react";
import { ExternalLink, Link as LinkIcon, Plus, RefreshCw, Trash2 } from "lucide-react";
import type { RadarSource } from "./store";
import type { SourceJob } from "./importer";
const time = (value: string | number) => value ? new Date(value).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "尚未更新";
export default function SourcesPanel({ onUpdated }: { onUpdated: (addedJobs?: SourceJob[]) => void }) {
  const [sources, setSources] = useState<RadarSource[]>([]), [name, setName] = useState(""), [url, setUrl] = useState("");
  const [busy, setBusy] = useState(""), [error, setError] = useState(""), [loading, setLoading] = useState(true);
  const [removing, setRemoving] = useState("");
  function load(silent = false) {
    return fetch("/api/job-sources").then(async response => {
      const body = await response.json(); if (!response.ok) throw Error(body.error);
      setSources(body.sources); if (!silent) setError("");
    }).catch(() => { if (!silent) setError("暂时无法读取数据源，请重试"); })
      .finally(() => { if (!silent) setLoading(false); });
  }
  useEffect(() => { void load(); const timer = window.setInterval(() => void load(true), 60_000); return () => window.clearInterval(timer); }, []);
  async function change(action: string, id = "", enabled?: boolean) {
    if (busy) return;
    setBusy(id || "add"); setError("");
    try {
      const response = await fetch("/api/job-sources", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action, id, ...(action === "add" ? { name, url } : {}), ...(enabled !== undefined ? { enabled } : {}) }) });
      const body = await response.json(); if (!response.ok) throw Error(body.error);
      setSources(body.sources); setRemoving(""); if (action === "add") { setName(""); setUrl(""); }
      onUpdated((action === "add" || action === "refresh") && body.refreshSucceeded === true ? body.addedJobs || [] : undefined);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "操作失败，请重试"); } finally { setBusy(""); }
  }
  return <section className="panel radar-sources" aria-label="岗位数据源">
    <form className="radar-source-form" onSubmit={event => { event.preventDefault(); void change("add"); }}>
      <label><span>名称</span><input value={name} maxLength={100} required placeholder="如：校招岗位汇总" onChange={event => setName(event.target.value)} /></label>
      <label><span>链接</span><input value={url} type="url" maxLength={2000} required placeholder="https://docs.qq.com/sheet/…" onChange={event => setUrl(event.target.value)} /></label>
      <button className="primary-button" disabled={!!busy || !name.trim() || !url.trim()}><Plus size={15} />{busy === "add" ? "正在读取…" : "添加"}</button>
    </form>
    <p className="radar-source-help">支持公开可读的腾讯文档和表格。添加后每日更新；本机运行时需保持服务启动。</p>
    {error && <p className="assistant-error" role="alert">{error} <button type="button" onClick={() => void load()}>重试</button></p>}
    {loading ? <p role="status">正在读取…</p> : !sources.length && <p className="radar-source-empty">暂无自定义数据源</p>}
    {sources.map(source => <article className="radar-source-row" key={source.id}>
      <div className="radar-source-info"><a href={source.url} target="_blank" rel="noreferrer"><LinkIcon size={15} /><strong>{source.name}</strong><ExternalLink size={12} /></a>
        <p>{source.count} 个岗位 · {source.last_success ? `更新于 ${time(source.last_success)}` : "尚未成功更新"}{source.enabled ? ` · 下次 ${time(source.next_run)}` : " · 已暂停"}</p>
        {source.error && <p className="radar-source-error" role="alert">{source.error}</p>}
      </div>
      <div className="radar-source-actions"><label><input type="checkbox" checked={!!source.enabled} disabled={!!busy} onChange={event => void change("schedule", source.id, event.target.checked)} />每日更新</label>
        <button type="button" disabled={!!busy} onClick={() => void change("refresh", source.id)}><RefreshCw size={14} />{busy === source.id ? "处理中…" : "刷新"}</button>
        {removing === source.id ? <><button type="button" disabled={!!busy} onClick={() => void change("remove", source.id)}>确认移除</button><button type="button" onClick={() => setRemoving("")}>取消</button></> : <button type="button" aria-label={`移除${source.name}`} title="移除数据源" disabled={!!busy} onClick={() => setRemoving(source.id)}><Trash2 size={14} /></button>}
      </div>
    </article>)}
  </section>;
}
