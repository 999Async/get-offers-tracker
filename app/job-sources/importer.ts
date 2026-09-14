import { extractAttributedText, parseJsonp, parseSheetResponse } from "./tencent-wire.mjs";

export type SourceJob = { id: string; company: string; position: string; positions: string[]; location: string; cities: string[]; companyTypes: string[]; recruitmentTypes: string[]; referralCode: string; link: string; expiryAt: string; createdAt: string; updatedAt: string; source: string; sourceKey: string; sourceUrl: string };
export function sourceUrl(raw: string) {
  let url: URL;
  try { url = new URL(raw.trim()); } catch { throw Error("请输入完整的数据源链接"); }
  if (url.protocol !== "https:" || url.username || url.password || url.port || url.hostname !== "docs.qq.com" || !/^\/(doc|sheet)\/[A-Za-z0-9_-]+\/?$/.test(url.pathname)) throw Error("目前支持腾讯文档和腾讯表格的公开分享链接");
  const tab = url.searchParams.get("tab"); url.search = ""; url.hash = "";
  if (tab && /^[a-zA-Z0-9_-]{1,80}$/.test(tab)) url.searchParams.set("tab", tab);
  return url.href;
}
// Tencent wire text contains intentional control delimiters.
// eslint-disable-next-line no-control-regex
const clean = (value: string) => value.replace(/[\u0000-\u001f]/g, " ").replace(/\s+/g, " ").trim();
const httpUrl = (value: string) => { try { const u = new URL(value); return ["http:", "https:"].includes(u.protocol) && !u.username && !u.password ? u.href : ""; } catch { return ""; } };
export function jobsFromRows(rows: string[][], id: string, title: string, url: string): SourceJob[] {
  const aliases: Record<string, string[]> = { company: ["公司", "公司名称", "企业名称", "企业"], position: ["岗位", "岗位名称", "招聘岗位", "职位", "职位名称", "岗位详情", "招聘岗位详情", "备注/补充"], location: ["城市", "地点", "工作地点", "工作城市"], link: ["链接", "投递链接", "网申链接", "申请链接", "招聘链接", "投递/内推链接"], detailsLink: ["招聘详情", "详情链接"], companyTypes: ["公司类别", "企业性质"], recruitmentTypes: ["招聘对象", "招聘类型", "招聘批次", "招聘项目"], referralCode: ["内推码", "推荐码"], expiryAt: ["截止时间", "截止日期"], updatedAt: ["更新日期", "更新时间", "日期"] };
  let columns: Record<string, number> = {}, start = -1;
  for (let i = 0; i < Math.min(rows.length, 30); i++) {
    const candidate: Record<string, number> = {};
    for (const [field, names] of Object.entries(aliases)) { const col = rows[i].findIndex(cell => names.includes(clean(cell || "").replace(/[:：*\s]/g, ""))); if (col >= 0) candidate[field] = col; }
    if (candidate.company !== undefined && (candidate.position !== undefined || candidate.link !== undefined)) { columns = candidate; start = i + 1; break; }
  }
  if (start < 0) throw Error("未识别表头，请使用“公司、岗位、投递链接”等列名");
  const jobs: SourceJob[] = [];
  for (const row of rows.slice(start)) {
    const cell = (name: string) => clean(row[columns[name]] || "").slice(0, 1000);
    const company = cell("company"), position = cell("position"), link = httpUrl(cell("link")) || httpUrl(cell("detailsLink"));
    if (!company || (!position && !link) || aliases.company.includes(company)) continue;
    jobs.push({ id: "", company, position: position || "招聘岗位（详见原文）", positions: position ? [position] : [], location: cell("location"), cities: [], companyTypes: cell("companyTypes") ? [cell("companyTypes")] : [], recruitmentTypes: cell("recruitmentTypes") ? [cell("recruitmentTypes")] : [], referralCode: cell("referralCode"), link, expiryAt: cell("expiryAt"), createdAt: "", updatedAt: cell("updatedAt"), source: title, sourceKey: id, sourceUrl: url });
  }
  return jobs;
}
async function limitedText(response: Response) {
  if (!response.ok || !response.body) throw Error("无法读取链接，请确认文档允许公开访问");
  const reader = response.body.getReader(), decoder = new TextDecoder(); let raw = "", bytes = 0;
  for (;;) { const { done, value } = await reader.read(); if (done) break; bytes += value.byteLength; if (bytes > 8_000_000) { await reader.cancel(); throw Error("文档过大，请拆分数据源"); } raw += decoder.decode(value, { stream: true }); }
  return raw + decoder.decode();
}
export async function importSource(id: string, title: string, rawUrl: string, fetcher: typeof fetch = fetch): Promise<SourceJob[]> {
  const url = sourceUrl(rawUrl), signal = AbortSignal.timeout(90_000);
  async function get(address: string, cookie = "") {
    const endpoint = new URL(address);
    // Only the document provider can be contacted, including URLs found in its HTML.
    if (endpoint.origin !== "https://docs.qq.com" || endpoint.username || endpoint.password) throw Error("数据源跳转到不支持的地址");
    const response = await fetcher(endpoint, { signal, redirect: "manual", headers: { "User-Agent": "Mozilla/5.0", Referer: url, ...(cookie ? { Cookie: cookie } : {}) } });
    if (response.status >= 300 && response.status < 400) throw Error("数据源发生跳转，请使用可公开读取的原始文档链接");
    return response;
  }
  const page = await get(url);
  const cookies = page.headers.getSetCookie?.().map(value => value.split(";", 1)[0]).join("; ") || "";
  const html = await limitedText(page);
  const match = html.match(/(?:href|src)=["']([^"']*\/dop-api\/opendoc\?[^"']+)["']/i);
  if (!match) throw Error("无法读取文档，请检查分享权限或链接是否有效");
  const endpoint = new URL(match[1].replaceAll("&amp;", "&").replaceAll("&#x2F;", "/"), url);
  let jobs: SourceJob[];
  if (new URL(url).pathname.startsWith("/sheet/")) {
    const rows: string[][] = [];
    for (let start = 0; start < 5120; start += 256) {
      for (const [key, value] of Object.entries({ block_start_row: start, block_end_row: start + 255, block_start_col: 0, block_end_col: 63, startrow: start, endrow: start + 60 })) endpoint.searchParams.set(key, String(value));
      const block = parseSheetResponse(await limitedText(await get(endpoint.href, cookies)));
      rows.push(...block.rows);
      if (start + 256 >= block.maxRow) break;
      if (start === 4864) throw Error("表格超过 5120 行，请拆分数据源");
    }
    jobs = jobsFromRows(rows, id, title, url);
  } else {
    const text = extractAttributedText(parseJsonp(await limitedText(await get(endpoint.href, cookies))));
    // Tencent rich text uses these control bytes to delimit hyperlink fields.
    // eslint-disable-next-line no-control-regex
    const rows = [...text.matchAll(/\u0007([^\u0006\u0007\r\u001b]{1,100})\r\u0007([^\u0006\u0007\r\u001b]{0,100})\r\u0007\u0013HYPERLINK\s+(https?:\/\/[^\s\u0014]+)/g)].map(match => [clean(match[1]), clean(match[2]), match[3]]);
    jobs = jobsFromRows([["公司", "内推码", "投递链接"], ...rows], id, title, url);
  }
  if (!jobs.length) throw Error("未识别到岗位，上次数据已保留；请检查分享权限和表格结构");
  const unique = new Map<string, SourceJob>();
  for (const job of jobs) {
    const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(`${id}|${job.company}|${job.position}|${job.link}`));
    job.id = `source-${Array.from(new Uint8Array(hash)).map(byte => byte.toString(16).padStart(2, "0")).join("").slice(0, 32)}`;
    unique.set(job.id, job);
  }
  const result = [...unique.values()];
  if (new TextEncoder().encode(JSON.stringify(result)).length > 8_000_000) throw Error("岗位数据过大，请拆分数据源");
  return result;
}
