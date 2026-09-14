import { deflateSync, inflateSync } from "node:zlib";
export interface SourceDatabase {
  prepare(sql: string): { bind(...values: unknown[]): { first<T = Record<string, unknown>>(): Promise<T | null>; all<T = Record<string, unknown>>(): Promise<{ results: T[] }>; run(): Promise<unknown> } };
}
import { importSource, sourceUrl, type SourceJob } from "./importer";
export type RadarSource = { id: string; name: string; url: string; enabled: number; last_success: string; last_attempt: string; next_run: number; error: string; count: number; lease_until: number };
export type SourceRefreshResult = { addedJobs: SourceJob[]; succeeded: boolean };
const fields = "id, name, url, enabled, last_success, last_attempt, next_run, error, count, lease_until";
export async function listSources(db: SourceDatabase, user: string) {
  return (await db.prepare(`SELECT ${fields} FROM radar_sources WHERE user_id = ? ORDER BY created_at DESC`).bind(user).all<RadarSource>()).results;
}
export async function createSource(db: SourceDatabase, user: string, name: string, url: string) {
  const id = crypto.randomUUID(), normalized = sourceUrl(url);
  if (!name.trim() || name.length > 100) throw Error("请填写 100 字以内的数据源名称");
  const row = await db.prepare("INSERT INTO radar_sources (user_id,id,name,url,created_at,next_run) SELECT ?,?,?,?,?,? WHERE (SELECT COUNT(*) FROM radar_sources WHERE user_id = ?) < 20 ON CONFLICT(user_id,url) DO NOTHING RETURNING id").bind(user, id, name.trim(), normalized, new Date().toISOString(), Date.now(), user).first();
  if (!row) throw Error("链接已添加，或已达到 20 个数据源上限");
  return id;
}
export async function refreshSource(db: SourceDatabase, user: string, id: string, importer = importSource, now = Date.now(), dueOnly = false) {
  const lease = crypto.randomUUID();
  const source = await db.prepare(`UPDATE radar_sources SET lease_token=?, lease_until=?, last_attempt=? WHERE user_id=? AND id=? AND lease_until <= ? AND (?=0 OR (enabled=1 AND next_run<=?)) RETURNING ${fields}, jobs_json`).bind(lease, now + 180000, new Date(now).toISOString(), user, id, now, dueOnly ? 1 : 0, now).first<RadarSource & { jobs_json: string }>();
  if (!source) return false;
  try {
    const jobs = await importer(id, source.name, source.url);
    let previousJobs: SourceJob[] = [];
    if (source.jobs_json) {
      try { previousJobs = JSON.parse(inflateSync(Buffer.from(source.jobs_json, "base64"), { maxOutputLength: 8_000_000 }).toString("utf8")); }
      catch { previousJobs = []; }
    }
    const previousIds = new Set(previousJobs.map(job => job.id));
    const addedJobs = jobs.filter(job => !previousIds.has(job.id));
    await db.prepare("UPDATE radar_sources SET jobs_json=?, count=?, last_success=?, next_run=?, error='', lease_token='', lease_until=0 WHERE user_id=? AND id=? AND lease_token=?").bind(deflateSync(JSON.stringify(jobs)).toString("base64"), jobs.length, new Date(now).toISOString(), now + 86400000, user, id, lease).run();
    return { addedJobs, succeeded: true } satisfies SourceRefreshResult;
  } catch (error) {
    console.error("job_source_refresh_failed", error instanceof Error ? { name: error.name, message: error.message } : { name: "unknown" });
    const message = error instanceof Error && /^[\u4e00-\u9fff]/.test(error.message) ? error.message.slice(0, 250) : "更新失败，请稍后重试或检查文档格式";
    await db.prepare("UPDATE radar_sources SET error=?, next_run=?, lease_token='', lease_until=0 WHERE user_id=? AND id=? AND lease_token=?").bind(message, now + 3600000, user, id, lease).run();
    return { addedJobs: [], succeeded: false } satisfies SourceRefreshResult;
  }
}
export async function refreshDue(db: SourceDatabase) {
  const now = Date.now();
  const rows = await db.prepare("SELECT user_id,id FROM radar_sources WHERE enabled=1 AND next_run<=? AND lease_until<=? ORDER BY next_run LIMIT 5").bind(now, now).all<{ user_id: string; id: string }>();
  for (const row of rows.results) await refreshSource(db, row.user_id, row.id, importSource, now, true);
  return rows.results.length;
}
export async function sourceFeed(db: SourceDatabase, user: string) {
  const rows = await db.prepare("SELECT id,name,url,last_success,jobs_json FROM radar_sources WHERE user_id=? AND last_success<>''").bind(user).all<{ id: string; name: string; url: string; last_success: string; jobs_json: string }>();
  return { sources: rows.results.map(row => ({ key: row.id, title: row.name, url: row.url, syncedAt: row.last_success })), jobs: rows.results.flatMap(row => JSON.parse(inflateSync(Buffer.from(row.jobs_json, "base64"), { maxOutputLength: 8_000_000 }).toString("utf8")) as SourceJob[]) };
}
