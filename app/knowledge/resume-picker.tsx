"use client";

import { useEffect, useState } from "react";
import { knowledgeFiles, type KnowledgeDocument, type KnowledgeFile, type ResumeReference } from "./files";

export default function ResumePicker({ value, onChange, currentOnly = false }: { value: ResumeReference; onChange: (next: ResumeReference) => void; currentOnly?: boolean }) {
  const [files, setFiles] = useState<KnowledgeFile[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error" | "unauthorized">("loading");
  const [error, setError] = useState("");
  const [downloading, setDownloading] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    void fetch("/api/knowledge", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "list" }), signal: controller.signal })
      .then(async (response) => {
        if (response.status === 401) { setStatus("unauthorized"); return; }
        if (!response.ok) throw new Error("load_failed");
        const result = await response.json() as { documents: KnowledgeDocument[] };
        setFiles(knowledgeFiles(result.documents).filter((file) => !currentOnly || result.documents.some((doc) => doc.status === "active" && doc.document_id === file.documentId && doc.active_version === file.versionId))); setStatus("ready");
      }).catch(() => { if (!controller.signal.aborted) setStatus("error"); });
    return () => controller.abort();
  }, [currentOnly]);
  const selected = files.find((file) => file.documentId === value.resumeDocumentId && file.versionId === value.resumeVersionId);
  const linked = Boolean(value.resumeDocumentId && value.resumeVersionId);
  const missing = linked && status === "ready" && !selected;
  const key = (file: KnowledgeFile) => `${file.documentId}/${file.versionId}`;
  const currentKey = linked ? `${value.resumeDocumentId}/${value.resumeVersionId}` : value.resume ? "legacy" : "";
  async function download() {
    setDownloading(true); setError("");
    try {
      const response = await fetch("/api/knowledge", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "source", payload: { document_id: value.resumeDocumentId, version_id: value.resumeVersionId } }) });
      if (!response.ok) throw new Error("download_failed");
      const result = await response.json() as { content_base64: string; extension: string };
      const bytes = Uint8Array.from(atob(result.content_base64), (c) => c.charCodeAt(0));
      const url = URL.createObjectURL(new Blob([bytes], { type: "application/octet-stream" }));
      const link = document.createElement("a"); link.href = url;
      link.download = selected?.filename ?? `resume.${result.extension}`; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch { setError("文件暂不可用。"); }
    finally { setDownloading(false); }
  }
  return <div className="resume-file-field">
    <label><span>简历文件</span><select value={currentKey} disabled={status === "loading"} onChange={(event) => {
      const file = files.find((item) => key(item) === event.target.value);
      if (event.target.value === "legacy" || (linked && !file && event.target.value === currentKey)) return;
      onChange({ resume: file?.label ?? "", resumeDocumentId: file?.documentId ?? "", resumeVersionId: file?.versionId ?? "" });
      setError("");
    }}>
      <option value="">{status === "loading" ? "正在读取文件…" : "未关联"}</option>
      {value.resume && !linked && <option value="legacy">{value.resume}（未关联文件）</option>}
      {linked && !selected && <option value={currentKey}>{value.resume || "已关联文件"}{missing ? "（不可用）" : ""}</option>}
      {files.map((file) => <option key={key(file)} value={key(file)}>{file.label}</option>)}
    </select></label>
    {status === "error" && <p role="alert">无法读取知识库文件，请重新打开后重试。</p>}
    {status === "unauthorized" && <p role="alert">请先登录。</p>}
    {status === "ready" && !files.length && !linked && <p>{currentOnly ? "请先在个人档案上传并处理简历。" : "请先在个人档案上传简历。"}</p>}
    {missing && <p>文件已删除或不可用，原关联记录保留。</p>}
    {linked && !missing && <button type="button" disabled={downloading} onClick={() => void download()}>{downloading ? "正在下载…" : "下载简历"}</button>}
    {error && <p role="alert">{error}</p>}
  </div>;
}
