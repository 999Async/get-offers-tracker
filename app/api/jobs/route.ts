import { sourceFeed } from "@/app/job-sources/store";
import { env } from "cloudflare:workers";

import { getChatGPTUser } from "@/app/chatgpt-auth";

export const dynamic = "force-dynamic";

const FEED_OBJECT_KEY = "resume-tracker/latest.json";
const MAX_FEED_BYTES = 5_000_000;
const MAX_JOBS = 5_000;

type JsonRecord = Record<string, unknown>;

function cleanText(value: unknown, max = 500): string {
  return typeof value === "string" ? value.trim().slice(0, max) : "";
}

function cleanTextList(value: unknown, maxItems = 50, maxLength = 300): string[] {
  if (!Array.isArray(value)) return [];
  return [...new Set(value.slice(0, maxItems).map((item) => cleanText(item, maxLength)).filter(Boolean))];
}

function cleanHttpUrl(value: unknown): string {
  const text = cleanText(value, 2_000);
  if (!text) return "";
  try {
    const url = new URL(text);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : "";
  } catch {
    return "";
  }
}

function cleanSource(value: unknown) {
  if (!value || typeof value !== "object") throw new Error("INVALID_SOURCE");
  const source = value as JsonRecord;
  const key = cleanText(source.key, 100);
  const title = cleanText(source.title, 300);
  if (!key || !title) throw new Error("INVALID_SOURCE");
  return {
    key,
    title,
    url: cleanHttpUrl(source.url),
    syncedAt: cleanText(source.syncedAt, 40),
  };
}

function cleanJob(value: unknown) {
  if (!value || typeof value !== "object") throw new Error("INVALID_JOB");
  const job = value as JsonRecord;
  const id = cleanText(job.id, 200);
  const company = cleanText(job.company, 300);
  const position = cleanText(job.position, 500);
  const sourceKey = cleanText(job.sourceKey, 100);
  if (!id || !company || !position || !sourceKey) throw new Error("INVALID_JOB");
  return {
    id,
    company,
    position,
    positions: cleanTextList(job.positions),
    location: cleanText(job.location, 500),
    cities: cleanTextList(job.cities),
    companyTypes: cleanTextList(job.companyTypes),
    recruitmentTypes: cleanTextList(job.recruitmentTypes),
    referralCode: cleanText(job.referralCode, 300),
    link: cleanHttpUrl(job.link),
    expiryAt: cleanText(job.expiryAt, 100),
    createdAt: cleanText(job.createdAt, 40),
    updatedAt: cleanText(job.updatedAt, 40),
    source: cleanText(job.source, 300),
    sourceKey,
    sourceUrl: cleanHttpUrl(job.sourceUrl),
  };
}

function cleanFeed(value: unknown) {
  if (!value || typeof value !== "object") throw new Error("INVALID_FEED");
  const feed = value as JsonRecord;
  const syncedAt = cleanText(feed.syncedAt, 40);
  if (!syncedAt || !Array.isArray(feed.sources) || !Array.isArray(feed.jobs)) {
    throw new Error("INVALID_FEED");
  }
  if (feed.jobs.length === 0 || feed.jobs.length > MAX_JOBS) throw new Error("INVALID_FEED");
  return {
    syncedAt,
    sources: feed.sources.slice(0, 20).map(cleanSource),
    jobs: feed.jobs.map(cleanJob),
    importedFrom: cleanText(feed.importedFrom, 300),
    upstreamCommit: cleanText(feed.upstreamCommit, 100),
  };
}

async function secretsMatch(actual: string, expected: string): Promise<boolean> {
  const encoder = new TextEncoder();
  const [actualHash, expectedHash] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(actual)),
    crypto.subtle.digest("SHA-256", encoder.encode(expected)),
  ]);
  const left = new Uint8Array(actualHash);
  const right = new Uint8Array(expectedHash);
  return left.every((byte, index) => byte === right[index]);
}

async function isSyncAuthorized(request: Request): Promise<boolean> {
  const expected = env.JOB_FEED_SYNC_SECRET;
  const authorization = request.headers.get("authorization") || "";
  if (!expected || !authorization.startsWith("Bearer ")) return false;
  return secretsMatch(authorization.slice(7), expected);
}

export async function GET() {
  const user = await getChatGPTUser();
  if (!user) return Response.json({ error: "UNAUTHORIZED" }, { status: 401 });
  try {
    const own = await sourceFeed(env.DB, user.userId);
    const object = env.JOB_FEEDS ? await env.JOB_FEEDS.get(FEED_OBJECT_KEY) : null;
    const base = object ? await object.json<{ syncedAt: string; sources: unknown[]; jobs: unknown[] }>() : { syncedAt: "", sources: [], jobs: [] };
    const syncedAt = [base.syncedAt, ...own.sources.map(source => source.syncedAt)].sort().at(-1) || "";
    return Response.json({ ...base, syncedAt, sources: [...base.sources, ...own.sources], jobs: [...base.jobs, ...own.jobs] }, { headers: { "Cache-Control": "no-store" } });
  } catch { return Response.json({ error: "JOB_FEED_UNAVAILABLE" }, { status: 503 }); }
}

export async function PUT(request: Request) {
  if (!(await isSyncAuthorized(request))) {
    return Response.json({ error: "UNAUTHORIZED" }, { status: 401 });
  }
  if (!env.JOB_FEEDS) return Response.json({ error: "JOB_FEED_STORAGE_UNAVAILABLE" }, { status: 503 });

  const declaredLength = Number(request.headers.get("content-length") || 0);
  if (declaredLength > MAX_FEED_BYTES) return Response.json({ error: "FEED_TOO_LARGE" }, { status: 413 });

  try {
    const source = await request.text();
    if (new TextEncoder().encode(source).byteLength > MAX_FEED_BYTES) {
      return Response.json({ error: "FEED_TOO_LARGE" }, { status: 413 });
    }
    const feed = cleanFeed(JSON.parse(source));
    const body = JSON.stringify(feed);
    await env.JOB_FEEDS.put(FEED_OBJECT_KEY, body, {
      httpMetadata: { contentType: "application/json; charset=utf-8" },
      customMetadata: {
        syncedAt: feed.syncedAt,
        upstreamCommit: feed.upstreamCommit,
      },
    });
    return Response.json({ syncedAt: feed.syncedAt, jobs: feed.jobs.length });
  } catch {
    return Response.json({ error: "INVALID_FEED" }, { status: 400 });
  }
}
