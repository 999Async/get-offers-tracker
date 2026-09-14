import type { KnowledgeFile } from "../knowledge/files";

export type Source = { evidence_id: string; document_id: string; version_id: string; quote: string; path: string[]; status: string };
export type Job = { job_id: string; version_id: string; company: string; title: string; cities: string[]; source_url: string; responsibilities: string[]; requirements: string[] };
export type Draft = { kind: string; title: string; content: string; evidence_ids: string[] };
export type Result = { answer: string; draft: Draft | null; citations: Source[]; jobs: Job[] };
export type Message = { id: string; role: "user" | "assistant"; content: string; result?: Result };
export type Snapshot = { messages: Message[]; materials: KnowledgeFile[]; jd: string; input: string };
export type Conversation = { id: string; title: string; revision: number; updatedAt: string };

// Stored answers are user history, not freshly validated model evidence. Raw source quotes
// stay in the knowledge base and are deliberately excluded from conversation snapshots.
export function snapshotForStorage(value: Snapshot): Snapshot {
  return { ...value, messages: value.messages.map(message => message.result ? { ...message, result: { ...message.result, citations: [] } } : message) };
}
export function validSnapshot(value: unknown): value is Snapshot {
  const object = (x: unknown): x is Record<string, unknown> => !!x && typeof x === "object" && !Array.isArray(x);
  const text = (x: unknown, max: number): x is string => typeof x === "string" && x.length <= max;
  if (!object(value) || Object.keys(value).some(k => !["messages", "materials", "jd", "input"].includes(k)) || !text(value.jd, 24000) || !text(value.input, 12000)) return false;
  if (!Array.isArray(value.materials) || value.materials.length > 10 || !value.materials.every(f => object(f) && text(f.documentId, 100) && text(f.versionId, 100) && text(f.label, 500) && text(f.filename, 300))) return false;
  if (!Array.isArray(value.messages) || value.messages.length > 200 || !value.messages.every(m => {
    if (!object(m) || !text(m.id, 100) || !["user", "assistant"].includes(String(m.role)) || !text(m.content, 32000)) return false;
    if (m.result === undefined) return true;
    const r = m.result;
    if (!object(r) || !text(r.answer, 12000) || !Array.isArray(r.citations) || r.citations.length > 30 || !Array.isArray(r.jobs) || r.jobs.length > 5) return false;
    if (!r.jobs.every(j => object(j) && ["job_id", "version_id", "company", "title", "source_url"].every(k => text(j[k], 2000)) && ["cities", "responsibilities", "requirements"].every(k => Array.isArray(j[k]) && (j[k] as unknown[]).every(s => text(s, 8000))))) return false;
    return r.draft === null || (object(r.draft) && ["project", "resume", "interview"].includes(String(r.draft.kind)) && text(r.draft.title, 120) && text(r.draft.content, 16000) && Array.isArray(r.draft.evidence_ids) && r.draft.evidence_ids.every(id => text(id, 200)));
  })) return false;
  return true;
}
