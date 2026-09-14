import { env } from "cloudflare:workers";
import { knowledgeFiles, type KnowledgeDocument, type ResumeReference } from "@/app/knowledge/files";

export async function userResumeFiles(userId: string) {
  if (!env.AGENT_KNOWLEDGE_URL || !env.AGENT_KNOWLEDGE_TOKEN) throw new Error("KNOWLEDGE_UNAVAILABLE");
  const endpoint = new URL("/knowledge", env.AGENT_KNOWLEDGE_URL);
  if (endpoint.protocol !== "https:" && !(endpoint.protocol === "http:" && ["127.0.0.1", "localhost"].includes(endpoint.hostname))) throw new Error("KNOWLEDGE_UNAVAILABLE");
  const response = await fetch(endpoint, { method: "POST", redirect: "manual", signal: AbortSignal.timeout(15_000),
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${env.AGENT_KNOWLEDGE_TOKEN}` },
    body: JSON.stringify({ actor_id: userId, tenant_id: userId, action: "list", payload: {} }),
  }).catch(() => { throw new Error("KNOWLEDGE_UNAVAILABLE"); });
  if (!response.ok) throw new Error("KNOWLEDGE_UNAVAILABLE");
  const result = await response.json() as { documents: KnowledgeDocument[] };
  return knowledgeFiles(result.documents);
}

export async function validateResumeReference(next: ResumeReference, previous: ResumeReference | undefined, loadFiles: () => ReturnType<typeof userResumeFiles>) {
  if (Boolean(next.resumeDocumentId) !== Boolean(next.resumeVersionId)) throw new Error("INVALID_RESUME_REFERENCE");
  if (!next.resumeDocumentId) return;
  // An unchanged historical reference survives file deletion and service downtime.
  if (previous?.resumeDocumentId === next.resumeDocumentId && previous.resumeVersionId === next.resumeVersionId) {
    next.resume = previous.resume;
    return;
  }
  const file = (await loadFiles()).find((item) => item.documentId === next.resumeDocumentId && item.versionId === next.resumeVersionId);
  if (!file) throw new Error("INVALID_RESUME_REFERENCE");
  next.resume = file.label;
}
