import { and, desc, eq } from "drizzle-orm";

import { getChatGPTUser } from "@/app/chatgpt-auth";
import { getDb } from "@/db";
import { applications } from "@/db/schema";
import { userResumeFiles, validateResumeReference } from "./resume-reference";

export const dynamic = "force-dynamic";

const statuses = new Set([
  "pending", "applied", "written", "interview1", "interview2",
  "interview3", "hr", "offer", "rejected",
]);
const progressStatuses = new Set([
  "applied", "written", "interview1", "interview2", "interview3", "hr", "offer",
]);

type IncomingApplication = {
  id?: unknown;
  company?: unknown;
  role?: unknown;
  platform?: unknown;
  status?: unknown;
  progressHistory?: unknown;
  salary?: unknown;
  appliedAt?: unknown;
  note?: unknown;
  resume?: unknown;
  resumeDocumentId?: unknown;
  resumeVersionId?: unknown;
  sourceJobId?: unknown;
  sourceJobUrl?: unknown;
  createdAt?: unknown;
};

function text(value: unknown, max = 500): string {
  return typeof value === "string" ? value.trim().slice(0, max) : "";
}

function cleanApplication(raw: IncomingApplication) {
  for (const reference of [raw.resumeDocumentId, raw.resumeVersionId]) {
    if (reference !== undefined && (typeof reference !== "string" || reference.length > 100)) throw new Error("INVALID_RESUME_REFERENCE");
  }
  const id = text(raw.id, 100) || crypto.randomUUID();
  const company = text(raw.company, 200);
  const role = text(raw.role, 300);
  const status = text(raw.status, 30);
  if (!company || !role || !statuses.has(status)) {
    throw new Error("INVALID_APPLICATION");
  }

  const history = Array.isArray(raw.progressHistory)
    ? raw.progressHistory.slice(0, 50).flatMap((entry) => {
        if (!entry || typeof entry !== "object") return [];
        const value = entry as Record<string, unknown>;
        const entryStatus = text(value.status, 30);
        if (!progressStatuses.has(entryStatus)) return [];
        return [{
          id: text(value.id, 100) || crypto.randomUUID(),
          status: entryStatus,
          at: text(value.at, 40),
          note: text(value.note, 2000),
        }];
      })
    : [];

  const createdAt = text(raw.createdAt, 40) || new Date().toISOString();
  return {
    id,
    company,
    role,
    platform: text(raw.platform, 200),
    status,
    progressHistory: JSON.stringify(history),
    salary: text(raw.salary, 100),
    appliedAt: text(raw.appliedAt, 40),
    note: text(raw.note, 5000),
    resume: text(raw.resume, 300),
    resumeDocumentId: text(raw.resumeDocumentId, 100),
    resumeVersionId: text(raw.resumeVersionId, 100),
    sourceJobId: text(raw.sourceJobId, 200),
    sourceJobUrl: text(raw.sourceJobUrl, 2000),
    createdAt,
    updatedAt: new Date().toISOString(),
  };
}

function publicApplication(row: typeof applications.$inferSelect) {
  let progressHistory: unknown[] = [];
  try {
    const parsed = JSON.parse(row.progressHistory);
    if (Array.isArray(parsed)) progressHistory = parsed;
  } catch { /* Keep legacy records readable when their history is malformed. */ }
  return { ...row, userId: undefined, progressHistory };
}

async function currentUser() {
  const user = await getChatGPTUser();
  if (!user) return null;
  return user;
}

export async function GET() {
  const user = await currentUser();
  if (!user) return Response.json({ error: "UNAUTHORIZED" }, { status: 401 });
  const rows = await getDb().select().from(applications)
    .where(eq(applications.userId, user.userId))
    .orderBy(desc(applications.updatedAt));
  return Response.json({
    applications: rows.map(publicApplication),
    user: { displayName: user.displayName, email: user.email },
  }, { headers: { "Cache-Control": "no-store" } });
}

export async function POST(request: Request) {
  const user = await currentUser();
  if (!user) return Response.json({ error: "UNAUTHORIZED" }, { status: 401 });
  try {
    const clean = cleanApplication(await request.json());
    const [previous] = await getDb().select().from(applications)
      .where(and(eq(applications.userId, user.userId), eq(applications.id, clean.id))).limit(1);
    await validateResumeReference(clean, previous, () => userResumeFiles(user.userId));
    await getDb().insert(applications).values({ userId: user.userId, ...clean })
      .onConflictDoUpdate({
        target: [applications.userId, applications.id],
        set: { ...clean, id: undefined, createdAt: undefined },
      });
    const [saved] = await getDb().select().from(applications)
      .where(and(eq(applications.userId, user.userId), eq(applications.id, clean.id)))
      .limit(1);
    return Response.json({ application: publicApplication(saved) });
  } catch (error) {
    const reason = error instanceof Error ? error.message : "";
    const status = ["INVALID_APPLICATION", "INVALID_RESUME_REFERENCE"].includes(reason) ? 400 : reason === "KNOWLEDGE_UNAVAILABLE" ? 503 : 500;
    return Response.json({ error: status === 400 || status === 503 ? reason : "SAVE_FAILED" }, { status });
  }
}

export async function PUT(request: Request) {
  const user = await currentUser();
  if (!user) return Response.json({ error: "UNAUTHORIZED" }, { status: 401 });
  try {
    const body = await request.json() as { applications?: IncomingApplication[] };
    if (!Array.isArray(body.applications) || body.applications.length > 1000) {
      return Response.json({ error: "INVALID_IMPORT" }, { status: 400 });
    }
    const cleanRows = body.applications.map(cleanApplication);
    const db = getDb();
    const existing = await db.select().from(applications).where(eq(applications.userId, user.userId));
    const previousById = new Map(existing.map((row) => [row.id, row]));
    let files: ReturnType<typeof userResumeFiles> | undefined;
    for (const clean of cleanRows) {
      await validateResumeReference(clean, previousById.get(clean.id), () => files ??= userResumeFiles(user.userId));
    }
    for (const clean of cleanRows) {
      await db.insert(applications).values({ userId: user.userId, ...clean })
        .onConflictDoUpdate({
          target: [applications.userId, applications.id],
          set: { ...clean, id: undefined, createdAt: undefined },
        });
    }
    return Response.json({ imported: cleanRows.length });
  } catch (error) {
    const reason = error instanceof Error ? error.message : "";
    const status = ["INVALID_APPLICATION", "INVALID_RESUME_REFERENCE"].includes(reason) ? 400 : reason === "KNOWLEDGE_UNAVAILABLE" ? 503 : 500;
    return Response.json({ error: status === 400 || status === 503 ? reason : "IMPORT_FAILED" }, { status });
  }
}

export async function DELETE(request: Request) {
  const user = await currentUser();
  if (!user) return Response.json({ error: "UNAUTHORIZED" }, { status: 401 });
  const body = await request.json().catch(() => ({})) as { id?: unknown };
  const id = text(body.id, 100);
  if (!id) return Response.json({ error: "INVALID_ID" }, { status: 400 });
  await getDb().delete(applications).where(
    and(eq(applications.userId, user.userId), eq(applications.id, id)),
  );
  return Response.json({ deleted: true });
}
