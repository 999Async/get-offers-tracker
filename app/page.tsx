"use client";
import SourcesPanel from "./job-sources/panel";

import DeveloperPanel from "./developer/panel";
import LocalConnection from "./assistant/local-connection";
import { ensureLocalConnection } from "./assistant/local-session";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import KnowledgePanel from "./knowledge/knowledge-panel";
import ResumePicker from "./knowledge/resume-picker";
import DiscoveryPanel from "./career/discovery-panel";
import ChatPanel from "./assistant/chat-panel";
import {
  Activity,
  ArrowRight,
  BriefcaseBusiness,
  CalendarClock,
  CalendarDays,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Cloud,
  Columns3,
  Download,
  Ellipsis,
  ExternalLink,
  FileText,
  HomeIcon,
  LayoutList,
  ListFilter,
  MapPin,
  MessageSquareText,
  Plus,
  Radar,
  Search,
  Settings,
  Trophy,
  Trash2,
  Upload,
  X,
  type LucideIcon,
} from "lucide-react";

type Status = "pending" | "applied" | "written" | "interview1" | "interview2" | "interview3" | "hr" | "offer" | "rejected";
type View = "home" | "applications" | "calendar" | "jobs" | "assistant" | "knowledge" | "settings";

type ProgressEntry = {
  id: string;
  status: Exclude<Status, "pending" | "rejected">;
  at: string;
  note: string;
};

type Application = {
  id: string;
  company: string;
  role: string;
  platform: string;
  status: Status;
  progressHistory: ProgressEntry[];
  salary: string;
  appliedAt: string;
  note: string;
  resume: string;
  resumeDocumentId: string;
  resumeVersionId: string;
  sourceJobId: string;
  sourceJobUrl: string;
  createdAt: string;
};

type Job = {
  id: string;
  company: string;
  position: string;
  positions: string[];
  location: string;
  cities: string[];
  companyTypes: string[];
  recruitmentTypes: string[];
  referralCode: string;
  link: string;
  expiryAt: string;
  createdAt: string;
  updatedAt: string;
  source: string;
  sourceKey: string;
  sourceUrl: string;
};

type JobFeed = {
  syncedAt: string;
  sources: { key: string; title: string; url: string; syncedAt: string }[];
  jobs: Job[];
};

type JobRefresh = { owner: string; refreshedAt: string; jobs: Job[] };


const statusMeta: Record<Status, { label: string; tone: string }> = {
  pending: { label: "待投递", tone: "gray" },
  applied: { label: "已投递", tone: "blue" },
  written: { label: "笔试", tone: "violet" },
  interview1: { label: "一面", tone: "amber" },
  interview2: { label: "二面", tone: "amber" },
  interview3: { label: "三面", tone: "amber" },
  hr: { label: "HR 面", tone: "violet" },
  offer: { label: "Offer", tone: "green" },
  rejected: { label: "已结束", tone: "red" },
};

const initialApplications: Application[] = [];

const navItems: { id: View; label: string; icon: LucideIcon }[] = [
  { id: "home", label: "概览", icon: HomeIcon },
  { id: "applications", label: "投递", icon: BriefcaseBusiness },
  { id: "calendar", label: "日历", icon: CalendarDays },
  { id: "jobs", label: "岗位雷达", icon: Radar },
  { id: "assistant", label: "岗位助手", icon: MessageSquareText },
  { id: "knowledge", label: "个人档案", icon: FileText },
  { id: "settings", label: "设置", icon: Settings },
];

function dateLabel(value: string) {
  if (!value) return "—";
  const date = new Date(value);
  return `${date.getMonth() + 1}月${date.getDate()}日`;
}

function dateTimeLabel(value: string) {
  if (!value) return "暂无安排";
  const date = new Date(value);
  return `${date.getMonth() + 1}月${date.getDate()}日 ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

type JobFilters = {
  companyType: string;
  industry: string;
  recruitmentType: string;
  updatedWithin: "all" | "7" | "30" | "90" | "unknown";
};

const emptyJobFilters: JobFilters = { companyType: "all", industry: "all", recruitmentType: "all", updatedWithin: "all" };

const industryRules: { label: string; keywords: string[] }[] = [
  { label: "人工智能与芯片", keywords: ["人工智能", "大模型", "机器学习", "算法", "芯片", "半导体", "集成电路"] },
  { label: "互联网与软件", keywords: ["互联网", "软件", "云计算", "信息技术", "电商", "游戏", "网络安全", "数据平台"] },
  { label: "汽车与交通", keywords: ["汽车", "自动驾驶", "出行", "轨道", "交通", "航空", "航天", "船舶"] },
  { label: "通信与电子", keywords: ["通信", "电子", "光电", "光学", "传感器", "5G", "无线"] },
  { label: "工业与智能制造", keywords: ["制造", "工业", "机器人", "自动化", "机械", "仪器", "材料"] },
  { label: "金融", keywords: ["银行", "证券", "保险", "基金", "金融", "投资", "资本", "信托"] },
  { label: "医疗与生物", keywords: ["医疗", "医药", "生物", "健康", "制药"] },
  { label: "教育与科研", keywords: ["教育", "大学", "学院", "科研", "研究所", "实验室"] },
  { label: "能源与化工", keywords: ["能源", "电力", "石油", "化工", "光伏", "电池"] },
  { label: "消费与零售", keywords: ["消费", "零售", "食品", "服饰", "家电"] },
];

function facetValues(values: string[]) {
  return values.flatMap(value => value.split(/[、,，/|；;]/)).map(value => value.trim()).filter(Boolean);
}

function jobIndustry(job: Job) {
  const companyText = `${job.company} ${job.companyTypes.join(" ")}`.toLowerCase();
  const companyMatch = industryRules.find(rule => rule.keywords.some(keyword => companyText.includes(keyword.toLowerCase())));
  if (companyMatch) return companyMatch.label;
  const positionText = `${job.position} ${job.positions.join(" ")}`.toLowerCase();
  return industryRules.find(rule => rule.keywords.some(keyword => positionText.includes(keyword.toLowerCase())))?.label || "其他";
}

function jobDate(value: string, now: Date) {
  const full = value.match(/(20\d{2})\D{0,3}(\d{1,2})\D{0,3}(\d{1,2})/);
  if (full) return new Date(Number(full[1]), Number(full[2]) - 1, Number(full[3]));
  const short = value.match(/(?:^|\D)(\d{1,2})(?:月|\/|\.|-)(\d{1,2})(?:日|\D|$)/);
  if (short) {
    let date = new Date(now.getFullYear(), Number(short[1]) - 1, Number(short[2]));
    if (date.getTime() - now.getTime() > 31 * 86400000) date = new Date(now.getFullYear() - 1, Number(short[1]) - 1, Number(short[2]));
    return date;
  }
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? new Date(parsed) : null;
}

function facetOptions(jobs: Job[], valuesFor: (job: Job) => string[]) {
  const counts = new Map<string, number>();
  jobs.forEach(job => {
    const values = valuesFor(job);
    (values.length ? values : ["未注明"]).forEach(value => counts.set(value, (counts.get(value) || 0) + 1));
  });
  return [...counts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "zh-CN"));
}

function uid() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

const progressStages: ProgressEntry["status"][] = ["applied", "written", "interview1", "interview2", "interview3", "hr", "offer"];
const interviewStages: Status[] = ["interview1", "interview2", "interview3", "hr"];

function localDateTimeNow() {
  const date = new Date(Date.now() - new Date().getTimezoneOffset() * 60000);
  return date.toISOString().slice(0, 16);
}

type LegacyApplication = Omit<Partial<Application>, "status" | "progressHistory"> & {
  status?: Status | "interview";
  nextStage?: ProgressEntry["status"] | "pending" | "interview" | "";
  nextAt?: string;
  progressHistory?: ProgressEntry[];
};

function normalizeApplication(raw: LegacyApplication): Application {
  const legacyStatus = raw.status === "interview" ? "interview1" : raw.status;
  const status = legacyStatus && Object.prototype.hasOwnProperty.call(statusMeta, legacyStatus) ? legacyStatus as Status : "pending";
  const legacyNextStage = raw.nextStage === "interview" ? "interview1" : raw.nextStage;
  const terminal = status === "offer" || status === "rejected";
  let history = Array.isArray(raw.progressHistory)
    ? raw.progressHistory.filter((entry) => entry && progressStages.includes(entry.status)).map((entry) => ({ id: entry.id || uid(), status: entry.status, at: entry.at || "", note: entry.note || "" }))
    : [];
  if (!history.length && raw.appliedAt) history.push({ id: uid(), status: "applied", at: `${raw.appliedAt}T09:00`, note: "完成投递" });
  if (progressStages.includes(status as ProgressEntry["status"]) && !history.some((entry) => entry.status === status)) {
    history.push({ id: uid(), status: status as ProgressEntry["status"], at: raw.createdAt?.slice(0, 16) || (raw.appliedAt ? `${raw.appliedAt}T09:00` : ""), note: "" });
  }
  if (!terminal && raw.nextAt && legacyNextStage && progressStages.includes(legacyNextStage as ProgressEntry["status"]) && !history.some((entry) => entry.at === raw.nextAt && entry.status === legacyNextStage)) {
    history.push({ id: uid(), status: legacyNextStage as ProgressEntry["status"], at: raw.nextAt, note: "" });
  }
  if (terminal) history = history.filter((entry) => !entry.at || Date.parse(entry.at) <= Date.now());
  return {
    id: raw.id || uid(), company: raw.company || "", role: raw.role || "", platform: raw.platform || "",
    status, progressHistory: history.sort((a, b) => a.at.localeCompare(b.at)), salary: raw.salary || "", appliedAt: raw.appliedAt || "",
    note: raw.note || "", resume: raw.resume || "", resumeDocumentId: raw.resumeDocumentId || "", resumeVersionId: raw.resumeVersionId || "", sourceJobId: raw.sourceJobId || "", sourceJobUrl: raw.sourceJobUrl || "",
    createdAt: raw.createdAt || new Date().toISOString(),
  };
}

function getNextProgress(app: Application) {
  return app.progressHistory
    .filter((entry) => entry.at && Date.parse(entry.at) > Date.now())
    .sort((a, b) => a.at.localeCompare(b.at))[0] || null;
}

function StatusPill({ status }: { status: Status }) {
  const meta = statusMeta[status];
  return <span className={`status-pill status-pill--${meta.tone}`}><i />{meta.label}</span>;
}

export default function Home() {
  const [view, setView] = useState<View>("home");
  const [historyTarget, setHistoryTarget] = useState<HTMLDivElement | null>(null);
  const [applications, setApplications] = useState<Application[]>(initialApplications);
  const [jobFeedRecord, setJobFeedRecord] = useState<{ owner: string; feed: JobFeed | null } | null>(null);
  const [jobRefreshRecord, setJobRefreshRecord] = useState<JobRefresh | null>(null);
  const [syncStatus, setSyncStatus] = useState<"loading" | "synced" | "saving" | "error">("loading");
  const [localMode, setLocalMode] = useState(false);
  const [account, setAccount] = useState({ displayName: "当前账号", email: "" });
  const jobFeed = jobFeedRecord?.owner === account.email ? jobFeedRecord.feed : null;
  const latestJobRefresh = jobRefreshRecord?.owner === account.email ? jobRefreshRecord : null;
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<Status | "all">("all");
  const [display, setDisplay] = useState<"list" | "board">("list");
  const [jobQuery, setJobQuery] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Application | null>(null);
  const [toast, setToast] = useState("");
  const [calendarCursor, setCalendarCursor] = useState(new Date());
  const [selectedDay, setSelectedDay] = useState(() => new Date().toISOString().slice(0, 10));
  const importRef = useRef<HTMLInputElement>(null);

  const loadApplications = useCallback(() => {
    return fetch("/api/applications", { cache: "no-store" }).then(async response => {
      if (response.status === 401) { setApplications([]); setAccount({ displayName: "未登录", email: "" }); }
      if (!response.ok) throw new Error("LOAD_FAILED");
      const data = await response.json() as { applications: LegacyApplication[]; user: { displayName: string; email: string } };
      setApplications(data.applications.map(normalizeApplication));
      setAccount(data.user);
      setSyncStatus("synced");
    }).catch(() => { setSyncStatus("error"); });
  }, []);

  useEffect(() => {
    void ensureLocalConnection().then(value => setLocalMode(value?.local === true)).catch(() => {});
    const changed = () => { setSyncStatus("loading"); setJobFeedRecord(null); setJobRefreshRecord(null); void loadApplications(); };
    window.addEventListener("getoffers-account-changed", changed);
    return () => window.removeEventListener("getoffers-account-changed", changed);
  }, [loadApplications]);

  useEffect(() => {
    void loadApplications();
  }, [loadApplications]);

  useEffect(() => {
    let active = true;
    const reload = async () => {
      try { const response = await fetch("/api/jobs", { cache: "no-store" }); const body = response.ok ? await response.json() : null; if (active) setJobFeedRecord({ owner: account.email, feed: body }); }
      catch { if (active) setJobFeedRecord({ owner: account.email, feed: null }); }
    };
    void reload();
    const timer = view === "jobs" ? setInterval(() => void reload(), 60000) : null;
    return () => { active = false; if (timer) clearInterval(timer); };
  }, [account.email, view]);

  useEffect(() => {
    const refresh = () => {
      if (document.visibilityState === "visible") void loadApplications();
    };
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [loadApplications]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 2600);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const filtered = useMemo(() => applications.filter((item) => {
    const haystack = `${item.company} ${item.role} ${item.platform}`.toLowerCase();
    return (statusFilter === "all" || item.status === statusFilter) && haystack.includes(query.toLowerCase());
  }), [applications, query, statusFilter]);

  const stats = useMemo(() => ({
    total: applications.length,
    active: applications.filter((item) => ["applied", "written", ...interviewStages].includes(item.status)).length,
    interview: applications.filter((item) => interviewStages.includes(item.status)).length,
    offer: applications.filter((item) => item.status === "offer").length,
  }), [applications]);

  const upcoming = useMemo(() => applications
    .flatMap((app) => app.progressHistory.filter((entry) => entry.at && Date.parse(entry.at) > Date.now()).map((entry) => ({ app, entry })))
    .sort((a, b) => a.entry.at.localeCompare(b.entry.at))
    .slice(0, 4), [applications]);

  const showToast = (message: string) => setToast(message);

  function openCreate(prefill?: Partial<Application>) {
    setEditing({
      id: "", company: prefill?.company || "", role: prefill?.role || "", platform: prefill?.platform || "官网",
      status: prefill?.status || "pending", progressHistory: [], salary: "", appliedAt: "", note: "",
      resume: "", resumeDocumentId: "", resumeVersionId: "", sourceJobId: prefill?.sourceJobId || "", sourceJobUrl: prefill?.sourceJobUrl || "",
      createdAt: new Date().toISOString(),
    });
    setModalOpen(true);
  }

  async function saveApplication(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editing?.company.trim() || !editing.role.trim()) return;
    const isEditing = Boolean(editing.id);
    const normalized = normalizeApplication({ ...editing, id: editing.id || uid() });
    setSyncStatus("saving");
    try {
      const response = await fetch("/api/applications", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(normalized),
      });
      if (!response.ok) {
        const problem = await response.json().catch(() => ({}));
        if (problem.error === "INVALID_RESUME_REFERENCE") throw new Error("简历文件不可用，请重新选择。");
        if (problem.error === "KNOWLEDGE_UNAVAILABLE") throw new Error("无法核验简历文件，请稍后重试。");
        throw new Error("保存失败，请稍后重试");
      }
      const data = await response.json() as { application: LegacyApplication };
      const saved = normalizeApplication(data.application);
      setApplications((items) => [saved, ...items.filter((item) => item.id !== saved.id)]);
      setSyncStatus("synced");
      showToast(isEditing ? "投递记录已同步" : "投递已同步到云端");
      setModalOpen(false);
    } catch (error) {
      setSyncStatus("error");
      showToast(error instanceof Error ? error.message : "保存失败，请稍后重试");
    }
  }

  async function removeApplication(id: string) {
    setSyncStatus("saving");
    try {
      const response = await fetch("/api/applications", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id }),
      });
      if (!response.ok) throw new Error("DELETE_FAILED");
      setApplications((items) => items.filter((item) => item.id !== id));
      setModalOpen(false);
      setSyncStatus("synced");
      showToast("记录已删除");
    } catch {
      setSyncStatus("error");
      showToast("删除失败，请稍后重试");
    }
  }

  function exportData() {
    const blob = new Blob([JSON.stringify({ applications }, null, 2)], { type: "application/json" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `get-offers-${new Date().toISOString().slice(0, 10)}.json`;
    link.click();
    URL.revokeObjectURL(link.href);
    showToast("数据已导出");
  }

  function importData(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = async () => {
      try {
        const value = JSON.parse(String(reader.result));
        if (!Array.isArray(value.applications)) throw new Error();
        const imported = value.applications.map(normalizeApplication);
        setSyncStatus("saving");
        const response = await fetch("/api/applications", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ applications: imported }),
        });
        if (!response.ok) throw new Error();
        await loadApplications();
        showToast(`已导入 ${imported.length} 条记录`);
      } catch { showToast("文件格式不正确"); }
      finally { event.target.value = ""; }
    };
    reader.readAsText(file);
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <button className="brand" onClick={() => setView("home")} aria-label="返回概览">
          <span className="brand-mark" aria-hidden="true">GO</span><span>GetOffers</span>
        </button>
        <nav className="sidebar-nav" aria-label="主导航">
          {navItems.map((item) => (
            <button key={item.id} className={`nav-item ${view === item.id ? "is-active" : ""}`} aria-current={view === item.id ? "page" : undefined} onClick={() => setView(item.id)}>
              <span className="nav-icon" aria-hidden="true"><item.icon size={16} strokeWidth={1.7} /></span>{item.label}
              {item.id === "applications" && <span className="nav-count">{applications.length}</span>}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="profile">
            <span className="avatar">{(account.displayName || account.email || "我").slice(0, 1).toUpperCase()}<span className={`profile-status profile-status--${syncStatus}`} role="status" aria-label={{ loading: "正在读取数据", synced: localMode ? "本机数据已就绪" : "数据已同步", saving: "正在保存", error: "连接异常" }[syncStatus]} title={{ loading: "正在读取数据", synced: localMode ? "本机数据已就绪" : "数据已同步", saving: "正在保存", error: "连接异常" }[syncStatus]} /></span>
            <span><strong title={account.displayName}>{account.displayName}</strong>{account.email && account.email !== account.displayName && <small title={account.email}>{account.email}</small>}{syncStatus === "error" && <small className="profile-error">连接异常</small>}</span>
          </div>
        </div>
      </aside>

      <main className="main">
        <header className={`topbar${view === "assistant" ? " topbar--assistant" : ""}`}>
          <div className="breadcrumb"><h1 key={view} className={view === "assistant" ? "visually-hidden" : "page-title"}>{navItems.find((item) => item.id === view)?.label}</h1>{view === "applications" && <span className="page-count">{applications.length} 条</span>}{view === "assistant" && <div id="assistant-history-slot" ref={setHistoryTarget} />}</div>
          {view !== "knowledge" && view !== "settings" && view !== "assistant" && <div className="top-actions">
            <button className="icon-button" title="快捷搜索" aria-label="快捷搜索" onClick={() => { setView("applications"); setTimeout(() => document.querySelector<HTMLInputElement>("#application-search")?.focus(), 20); }}><Search size={16} /></button>
            <button className="primary-button primary-button--small" onClick={() => openCreate()}><Plus size={15} /> 新增投递</button>
          </div>}
        </header>

        <div className={`content${view === "assistant" ? " content--assistant" : ""}`}>
          {view === "home" && <div className="view-stage"><HomeView applications={applications} latestJobRefresh={latestJobRefresh} stats={stats} upcoming={upcoming} onEdit={(item) => { setEditing(item); setModalOpen(true); }} onNavigate={setView} /></div>}
          {view === "applications" && <div className="view-stage"><ApplicationsView applications={filtered} query={query} setQuery={setQuery} statusFilter={statusFilter} setStatusFilter={setStatusFilter} display={display} setDisplay={setDisplay} onEdit={(item) => { setEditing(item); setModalOpen(true); }} /></div>}
          {view === "calendar" && <div className="view-stage"><CalendarView applications={applications} cursor={calendarCursor} setCursor={setCalendarCursor} selectedDay={selectedDay} setSelectedDay={setSelectedDay} /></div>}
          {view === "jobs" && <div className="view-stage"><JobsView onSaved={() => void loadApplications()} onViewApplications={() => setView("applications")} onFeedRefresh={(addedJobs) => { if (addedJobs !== undefined) setJobRefreshRecord({ owner: account.email, refreshedAt: new Date().toISOString(), jobs: addedJobs }); void fetch("/api/jobs", { cache: "no-store" }).then(async response => { if (response.ok) setJobFeedRecord({ owner: account.email, feed: await response.json() }); }).catch(() => {}); }} feed={jobFeed} query={jobQuery} setQuery={setJobQuery} applications={applications} onAdd={(job) => openCreate({ company: job.company, role: job.position, platform: job.source, status: "pending", sourceJobId: job.id, sourceJobUrl: job.link })} /></div>}
          <div className="view-stage" hidden={view !== "assistant"}><ChatPanel historyTarget={historyTarget} active={view === "assistant"} onKnowledge={() => setView("knowledge")} onAddJob={(job) => openCreate({ company: job.company, role: job.title, status: "pending", sourceJobId: job.job_id, sourceJobUrl: job.source_url })} /></div>
          {view === "knowledge" && <div className="view-stage"><KnowledgePanel /></div>}
          {view === "settings" && <div className="view-stage"><SettingsView exportData={exportData} importData={() => importRef.current?.click()} account={account} syncStatus={syncStatus} localMode={localMode} /></div>}
        </div>
      </main>

      <nav className="mobile-nav" aria-label="移动端导航">
        {navItems.map((item) => <button key={item.id} className={view === item.id ? "is-active" : ""} aria-current={view === item.id ? "page" : undefined} onClick={() => setView(item.id)}><item.icon size={18} strokeWidth={1.7} />{item.label}</button>)}
      </nav>

      <input ref={importRef} className="visually-hidden" type="file" accept="application/json" onChange={importData} />
      {modalOpen && editing && <ApplicationModal value={editing} setValue={setEditing} onClose={() => setModalOpen(false)} onSave={saveApplication} onDelete={editing.id ? () => removeApplication(editing.id) : undefined} />}
      {toast && <div className="toast" role="status" aria-live="polite"><span><Check size={11} strokeWidth={2.4} /></span>{toast}</div>}
    </div>
  );
}

function HomeView({ applications, latestJobRefresh, stats, upcoming, onEdit, onNavigate }: { applications: Application[]; latestJobRefresh: JobRefresh | null; stats: { total: number; active: number; interview: number; offer: number }; upcoming: { app: Application; entry: ProgressEntry }[]; onEdit: (app: Application) => void; onNavigate: (view: View) => void }) {
  const rate = stats.total ? Math.round((stats.offer / stats.total) * 100) : 0;
  const stages = [
    { label: "全部记录", value: stats.total, width: 100 },
    { label: "推进流程", value: applications.filter((a) => ["written", ...interviewStages, "offer"].includes(a.status)).length, width: 72 },
    { label: "进入面试", value: applications.filter((a) => [...interviewStages, "offer"].includes(a.status)).length, width: 48 },
    { label: "获得 Offer", value: stats.offer, width: 26 },
  ];
  return <>
    <section className="dashboard-summary" aria-label="投递摘要"><p>{stats.total} 条投递 · {stats.active} 条进行中 · {stats.interview} 条处于面试阶段</p><button className="text-button" onClick={() => onNavigate("applications")}>全部记录<ArrowRight size={15} /></button></section>

    <section className="metric-grid">
      <article><div className="metric-head"><span>全部投递</span><i className="metric-icon"><BriefcaseBusiness size={13} /></i></div><strong>{stats.total}</strong></article>
      <article><div className="metric-head"><span>进行中</span><i className="metric-icon metric-icon--blue"><Activity size={13} /></i></div><strong>{stats.active}</strong></article>
      <article><div className="metric-head"><span>面试阶段</span><i className="metric-icon metric-icon--amber"><MessageSquareText size={13} /></i></div><strong>{stats.interview}</strong></article>
      <article><div className="metric-head"><span>Offer 转化</span><i className="metric-icon metric-icon--dark"><Trophy size={13} /></i></div><strong>{rate}%</strong><p>共 {stats.offer} 个 Offer</p></article>
    </section>

    <div className="dashboard-grid">
      <section className="panel schedule-panel">
        <div className="panel-head"><h2>接下来 7 天</h2><button className="text-button" onClick={() => onNavigate("calendar")}>打开日历<ArrowRight size={13} /></button></div>
        <div className="schedule-list">{upcoming.length ? upcoming.map(({ app, entry }, index) => <button className="schedule-row" key={`${app.id}-${entry.id}`} onClick={() => onEdit(app)}><div className="date-tile"><strong>{dateLabel(entry.at).replace(/月.*/, "")}</strong><span>{dateLabel(entry.at).replace(/.*月/, "").replace("日", "")}</span></div><div className="schedule-line" aria-hidden="true"><i className={`schedule-dot schedule-dot--${statusMeta[entry.status].tone}`} />{index < upcoming.length - 1 && <b />}</div><div className="schedule-copy"><strong>{app.company} · {app.role}</strong><span>{dateTimeLabel(entry.at)} · {statusMeta[entry.status].label}</span></div><ChevronRight className="row-arrow" size={17} /></button>) : <EmptyMini text="暂时没有安排" />}</div>
      </section>
      <section className="panel funnel-panel">
        <div className="panel-head"><h2>投递漏斗</h2></div>
        <div className="funnel">{stages.map((stage, index) => <div className="funnel-row" key={stage.label}><div><span>{stage.label}</span><strong>{stage.value}</strong></div><div className="funnel-track"><i style={{ width: `${Math.max(stage.value ? stage.width : 3, 3)}%` }} /></div>{index > 0 && <small>{stats.total ? Math.round(stage.value / stats.total * 100) : 0}%</small>}</div>)}</div>
      </section>
    </div>

    <section className="panel recent-panel">
      <div className="panel-head"><h2>最近更新</h2><button className="text-button" onClick={() => onNavigate("jobs")}>全部岗位<ArrowRight size={13} /></button></div>
      {!latestJobRefresh
        ? <div className="compact-empty-state recent-empty"><Radar size={20} strokeWidth={1.5} /><strong>暂无新增岗位</strong></div>
        : latestJobRefresh.jobs.length
          ? <RecentJobTable jobs={latestJobRefresh.jobs.slice(0, 5)} />
          : <div className="recent-empty"><Check size={20} strokeWidth={1.5} /><strong>已完成岗位刷新</strong><p>本次刷新没有新增岗位。</p></div>}
    </section>
  </>;
}

function ApplicationsView({ applications, query, setQuery, statusFilter, setStatusFilter, display, setDisplay, onEdit }: { applications: Application[]; query: string; setQuery: (value: string) => void; statusFilter: Status | "all"; setStatusFilter: (value: Status | "all") => void; display: "list" | "board"; setDisplay: (value: "list" | "board") => void; onEdit: (app: Application) => void }) {
  return <>
    <div className="toolbar">
      <label className="search-box"><Search size={15} /><input id="application-search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜索公司、岗位或平台" /></label>
      <div className="filter-tabs"><button className={statusFilter === "all" ? "is-active" : ""} onClick={() => setStatusFilter("all")}>全部</button>{(Object.keys(statusMeta) as Status[]).map((status) => <button key={status} className={statusFilter === status ? "is-active" : ""} onClick={() => setStatusFilter(status)}>{statusMeta[status].label}</button>)}</div>
      <div className="view-switch"><button aria-label="列表视图" className={display === "list" ? "is-active" : ""} onClick={() => setDisplay("list")}><LayoutList size={15} /></button><button aria-label="看板视图" className={display === "board" ? "is-active" : ""} onClick={() => setDisplay("board")}><Columns3 size={15} /></button></div>
    </div>
    {applications.length === 0 ? <div className="empty-card"><Search size={28} strokeWidth={1.4} /><h3>没有找到匹配记录</h3><p>换个关键词或清除筛选条件试试。</p></div> : display === "list" ? <section className="panel application-list-panel"><ApplicationTable applications={applications} onEdit={onEdit} /></section> : <Kanban applications={applications} onEdit={onEdit} />}
  </>;
}

function ApplicationTable({ applications, onEdit, compact = false }: { applications: Application[]; onEdit: (app: Application) => void; compact?: boolean }) {
  return <div className="table-scroll"><table className="data-table"><thead><tr><th>公司与岗位</th><th>状态</th><th>投递日期</th><th>下个安排</th>{!compact && <th>简历版本</th>}<th /></tr></thead><tbody>{applications.map((app) => { const next = getNextProgress(app); return <tr key={app.id} onClick={() => onEdit(app)}><td><span className="company-cell"><i>{app.company.slice(0, 1)}</i><span><strong>{app.company}</strong><small>{app.role}</small></span></span></td><td><StatusPill status={app.status} /></td><td className="muted-cell">{dateLabel(app.appliedAt)}</td><td><span className={next ? "next-date" : "muted-cell"}>{next ? `${statusMeta[next.status].label} · ${dateTimeLabel(next.at)}` : "—"}</span></td>{!compact && <td className="muted-cell">{app.resume || "—"}</td>}<td><button className="more-button" aria-label={`编辑 ${app.company}`}><Ellipsis size={15} /></button></td></tr>; })}</tbody></table></div>;
}

function RecentJobTable({ jobs }: { jobs: Job[] }) {
  return <div className="table-scroll"><table className="data-table recent-job-table"><thead><tr><th>公司与岗位</th><th>地点</th><th>招聘类型</th><th>数据源</th><th /></tr></thead><tbody>{jobs.map(job => <tr key={job.id}><td><span className="company-cell"><i>{job.company.slice(0, 1)}</i><span><strong>{job.company}</strong><small>{job.position}</small></span></span></td><td className="muted-cell">{job.location || job.cities.join(" / ") || "—"}</td><td className="muted-cell">{job.recruitmentTypes.join(" / ") || "—"}</td><td className="muted-cell">{job.source || "—"}</td><td>{(job.link || job.sourceUrl) && <a className="recent-job-link" href={job.link || job.sourceUrl} target="_blank" rel="noreferrer">查看<ExternalLink size={12} /></a>}</td></tr>)}</tbody></table></div>;
}

function Kanban({ applications, onEdit }: { applications: Application[]; onEdit: (app: Application) => void }) {
  const columns: Status[] = ["pending", "applied", "written", "interview1", "interview2", "interview3", "hr", "offer"];
  return <div className="kanban">{columns.map((status) => { const items = applications.filter((item) => item.status === status); return <section className={`kanban-column ${items.length ? "" : "is-empty"}`} key={status}><div className="kanban-head"><span><i className={`dot dot--${statusMeta[status].tone}`} />{statusMeta[status].label}</span><b>{items.length}</b></div><div className="kanban-cards">{items.map((app) => { const next = getNextProgress(app); return <button className="kanban-card" key={app.id} onClick={() => onEdit(app)}><span className="mini-logo">{app.company[0]}</span><span className="kanban-card-main"><strong>{app.company}</strong><small>{app.role}</small></span><ChevronRight className="kanban-card-arrow" size={16} /><span className="kanban-card-meta">{next ? <><b>{statusMeta[next.status].label}</b>{dateTimeLabel(next.at)}</> : app.platform}</span></button>; })}{!items.length && <span className="kanban-empty">暂无记录</span>}</div></section>; })}</div>;
}

function CalendarView({ applications, cursor, setCursor, selectedDay, setSelectedDay }: { applications: Application[]; cursor: Date; setCursor: (value: Date) => void; selectedDay: string; setSelectedDay: (value: string) => void }) {
  const year = cursor.getFullYear(); const month = cursor.getMonth();
  const firstDay = new Date(year, month, 1).getDay(); const days = new Date(year, month + 1, 0).getDate(); const previousDays = new Date(year, month, 0).getDate();
  const cells = Array.from({ length: 42 }, (_, i) => { const day = i - firstDay + 1; const date = day < 1 ? new Date(year, month - 1, previousDays + day) : day > days ? new Date(year, month + 1, day - days) : new Date(year, month, day); return { date, current: day >= 1 && day <= days }; });
  const keyFor = (date: Date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  const eventsFor = (key: string) => applications.flatMap((app) => app.progressHistory.filter((entry) => entry.at.slice(0, 10) === key).map((entry) => ({ app, entry })));
  const selectedEvents = eventsFor(selectedDay);
  return <>
    <div className="calendar-layout">
      <section className="panel calendar-panel">
        <div className="calendar-title"><div><button aria-label="上个月" onClick={() => setCursor(new Date(year, month - 1, 1))}><ChevronLeft size={16} /></button><button aria-label="下个月" onClick={() => setCursor(new Date(year, month + 1, 1))}><ChevronRight size={16} /></button></div><h2>{year} 年 {month + 1} 月</h2><button className="secondary-button secondary-button--small" onClick={() => { const today = new Date(); setCursor(today); setSelectedDay(keyFor(today)); }}>今天</button></div>
        <div className="weekdays">{["日", "一", "二", "三", "四", "五", "六"].map((d) => <span key={d}>{d}</span>)}</div>
        <div className="calendar-grid">{cells.map(({ date, current }) => { const key = keyFor(date); const events = eventsFor(key); const today = keyFor(new Date()); return <button key={key} className={`${current ? "" : "is-other"} ${selectedDay === key ? "is-selected" : ""} ${key === today ? "is-today" : ""}`} onClick={() => setSelectedDay(key)}><span>{date.getDate()}</span><div>{events.slice(0, 2).map(({ app, entry }) => <i key={`${app.id}-${entry.id}`} className={`calendar-event calendar-event--${statusMeta[entry.status].tone}`}>{app.company} · {statusMeta[entry.status].label}</i>)}</div></button>; })}</div>
      </section>
      <aside className="panel day-panel"><h2>{dateLabel(selectedDay)}</h2><div className="day-events">{selectedEvents.length ? selectedEvents.map(({ app, entry }) => <div key={`${app.id}-${entry.id}`}><i className={`dot dot--${statusMeta[entry.status].tone}`} /><span><strong>{app.company} · {statusMeta[entry.status].label}</strong><small>{dateTimeLabel(entry.at).split(" ").at(-1)} · {app.role}{entry.note ? ` · ${entry.note}` : ""}</small></span></div>) : <EmptyMini text="当天没有流程节点" />}</div></aside>
    </div>
  </>;
}

function JobsView({ onFeedRefresh, feed, query, setQuery, applications, onAdd, onSaved, onViewApplications }: { onFeedRefresh: (addedJobs?: Job[]) => void; onSaved: () => void; onViewApplications: () => void; feed: JobFeed | null; query: string; setQuery: (value: string) => void; applications: Application[]; onAdd: (job: Job) => void }) {
  const [mode, setMode] = useState<"directory" | "discovery" | "sources">("directory");
  const [visibleLimit, setVisibleLimit] = useState(50);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [filters, setFilters] = useState<JobFilters>(emptyJobFilters);
  const jobs = useMemo(() => feed?.jobs || [], [feed?.jobs]);
  const companyTypeOptions = useMemo(() => facetOptions(jobs, job => facetValues(job.companyTypes)), [jobs]);
  const recruitmentTypeOptions = useMemo(() => facetOptions(jobs, job => facetValues(job.recruitmentTypes)), [jobs]);
  const industryOptions = useMemo(() => facetOptions(jobs, job => [jobIndustry(job)]), [jobs]);
  const sourceSyncedAt = useMemo(() => new Map((feed?.sources || []).map(source => [source.key, source.syncedAt])), [feed?.sources]);
  const activeFilterCount = Object.values(filters).filter(value => value !== "all").length;
  const now = new Date();
  const filteredJobs = jobs.filter((job) => {
    const matchesQuery = `${job.company} ${job.position} ${job.location} ${job.referralCode} ${job.recruitmentTypes.join(" ")}`.toLowerCase().includes(query.toLowerCase());
    const companyTypes = facetValues(job.companyTypes);
    const recruitmentTypes = facetValues(job.recruitmentTypes);
    const matchesCompanyType = filters.companyType === "all" || (filters.companyType === "未注明" ? companyTypes.length === 0 : companyTypes.includes(filters.companyType));
    const matchesIndustry = filters.industry === "all" || jobIndustry(job) === filters.industry;
    const matchesRecruitmentType = filters.recruitmentType === "all" || (filters.recruitmentType === "未注明" ? recruitmentTypes.length === 0 : recruitmentTypes.includes(filters.recruitmentType));
    const updated = jobDate(job.updatedAt || job.createdAt || sourceSyncedAt.get(job.sourceKey) || "", now);
    const age = updated ? now.getTime() - updated.getTime() : null;
    const matchesUpdatedAt = filters.updatedWithin === "all"
      || (filters.updatedWithin === "unknown" ? !updated : age !== null && age >= -86400000 && age <= Number(filters.updatedWithin) * 86400000);
    return matchesQuery && matchesCompanyType && matchesIndustry && matchesRecruitmentType && matchesUpdatedAt;
  });
  const updateFilter = <Key extends keyof JobFilters>(key: Key, value: JobFilters[Key]) => {
    setFilters(current => ({ ...current, [key]: value }));
    setVisibleLimit(50);
  };
  const clearFilters = () => { setFilters(emptyJobFilters); setVisibleLimit(50); };
  return <>
    <div className="career-tabs" role="group" aria-label="岗位浏览方式"><button aria-pressed={mode === "directory"} onClick={() => setMode("directory")}>岗位目录</button><button aria-pressed={mode === "discovery"} onClick={() => setMode("discovery")}>简历匹配</button><button aria-pressed={mode === "sources"} onClick={() => setMode("sources")}>数据源</button></div>
    {mode === "sources" ? <SourcesPanel onUpdated={onFeedRefresh} /> : mode === "discovery" ? <DiscoveryPanel onSaved={onSaved} onViewApplications={onViewApplications} /> : <>
    <div className="jobs-toolbar">
      <label className="search-box"><Search size={15} /><input value={query} onChange={(e) => { setQuery(e.target.value); setVisibleLimit(50); }} placeholder="搜索公司、岗位、城市或内推码" /></label>
      <div className="jobs-toolbar-summary">
        <span aria-live="polite">{filteredJobs.length} / {feed?.jobs.length || 0} 个岗位{feed?.syncedAt ? ` · 更新于 ${dateTimeLabel(feed.syncedAt)}` : ""}</span>
        <button className={`job-filter-trigger${filtersOpen ? " is-open" : ""}${activeFilterCount ? " has-filters" : ""}`} aria-label={activeFilterCount ? `筛选岗位，已选 ${activeFilterCount} 项` : "筛选岗位"} aria-expanded={filtersOpen} aria-controls="job-filter-panel" onClick={() => setFiltersOpen(open => !open)}><ListFilter size={16} />{activeFilterCount > 0 && <b>{activeFilterCount}</b>}</button>
      </div>
    </div>
    {filtersOpen && <section id="job-filter-panel" className="job-filter-panel" aria-label="岗位筛选条件">
      <div className="job-filter-head"><div><strong>筛选岗位</strong><small>行业根据公司与岗位关键词归类；时间优先使用岗位记录，缺失时使用数据源更新时间。</small></div><button aria-label="关闭筛选" onClick={() => setFiltersOpen(false)}><X size={16} /></button></div>
      <div className="job-filter-grid">
        <label><span>公司类型</span><select value={filters.companyType} onChange={event => updateFilter("companyType", event.target.value)}><option value="all">全部公司类型</option>{companyTypeOptions.map(([value, count]) => <option key={value} value={value}>{value}（{count}）</option>)}</select></label>
        <label><span>行业</span><select value={filters.industry} onChange={event => updateFilter("industry", event.target.value)}><option value="all">全部行业</option>{industryOptions.map(([value, count]) => <option key={value} value={value}>{value}（{count}）</option>)}</select></label>
        <label><span>招聘类型</span><select value={filters.recruitmentType} onChange={event => updateFilter("recruitmentType", event.target.value)}><option value="all">全部招聘类型</option>{recruitmentTypeOptions.map(([value, count]) => <option key={value} value={value}>{value}（{count}）</option>)}</select></label>
        <label><span>信息更新时间</span><select value={filters.updatedWithin} onChange={event => updateFilter("updatedWithin", event.target.value as JobFilters["updatedWithin"])}><option value="all">全部时间</option><option value="7">最近 7 天</option><option value="30">最近 30 天</option><option value="90">最近 90 天</option><option value="unknown">时间未注明</option></select></label>
      </div>
      <div className="job-filter-foot"><button className="text-button" disabled={!activeFilterCount} onClick={clearFilters}>清除条件</button><button className="secondary-button secondary-button--small" onClick={() => setFiltersOpen(false)}>查看 {filteredJobs.length} 个岗位</button></div>
    </section>}
    {!feed ? <div className="empty-card"><h3>岗位数据加载失败</h3><p>刷新页面后重试。</p></div> : !filteredJobs.length ? <div className="empty-card"><ListFilter size={28} strokeWidth={1.4} /><h3>没有符合条件的岗位</h3><p>调整筛选条件，或清除搜索与筛选后重试。</p><button className="secondary-button secondary-button--small" onClick={() => { setQuery(""); clearFilters(); }}>清除搜索与筛选</button></div> : <div className="job-grid">{filteredJobs.slice(0, visibleLimit).map((job) => { const added = applications.some((app) => app.sourceJobId === job.id || (app.company === job.company && app.role === job.position)); return <article className="job-card" key={job.id}><div className="job-card-head"><span className="job-logo">{job.company[0]}</span><span className="job-tag">{job.recruitmentTypes.join(" · ") || job.source}</span></div><h3>{job.company}</h3><p>{job.position}</p><div className="job-meta"><span><MapPin size={12} />{job.location || "地点未注明"}</span><span><CalendarClock size={12} />截止 {job.expiryAt || "招满即止"}</span></div>{job.referralCode && <div className="referral"><span>内推码</span><code>{job.referralCode}</code><button onClick={() => navigator.clipboard?.writeText(job.referralCode)}>复制</button></div>}<div className="job-source"><span>{job.source}</span>{job.updatedAt && <span>更新 {job.updatedAt}</span>}<a href={job.link || job.sourceUrl} target="_blank" rel="noreferrer">查看原岗位<ExternalLink size={11} /></a></div><button className={added ? "added-button" : "secondary-button job-add"} onClick={() => !added && onAdd(job)} disabled={added}>{added ? <><Check size={14} />已在投递中</> : <>加入待投递<ArrowRight size={14} /></>}</button></article>; })}</div>}
    {filteredJobs.length > visibleLimit && <button className="secondary-button" onClick={() => setVisibleLimit(limit => limit + 50)}>加载更多</button>}
    </>}
  </>;
}

function SettingsView({ exportData, importData, account, syncStatus, localMode }: { localMode: boolean; exportData: () => void; importData: () => void; account: { displayName: string; email: string }; syncStatus: "loading" | "synced" | "saving" | "error" }) {
  return <>
    <div className="settings-layout">
      <LocalConnection />
      <DeveloperPanel key={account.email} />
      <section className="panel settings-section">
        <div className="settings-heading"><span className="settings-icon"><Download size={17} /></span><div><h2>数据管理</h2></div></div>
        <div className="setting-actions"><button onClick={exportData}><span><Download size={15} /></span><div><strong>导出数据</strong><small>JSON 备份</small></div><ChevronRight size={15} /></button><button onClick={importData}><span><Upload size={15} /></span><div><strong>导入数据</strong><small>写入当前账号</small></div><ChevronRight size={15} /></button></div>
      </section>
      <section className="panel settings-section security-card">
        <div className="settings-heading"><span className="settings-icon"><Cloud size={17} /></span><div><h2>{localMode ? "账号与存储" : "账号与同步"}</h2></div></div>
        <div className="security-status"><span><i className={syncStatus === "error" ? "is-error" : ""} /> {{ loading: "正在读取数据", synced: localMode ? "投递记录保存在本机" : "投递记录已在多端同步", saving: "正在保存", error: "连接异常，请刷新重试" }[syncStatus]}</span><code>{account.email || account.displayName}</code></div>
      </section>
    </div>
  </>;
}

function ApplicationModal({ value, setValue, onClose, onSave, onDelete }: { value: Application; setValue: (value: Application) => void; onClose: () => void; onSave: (event: React.FormEvent<HTMLFormElement>) => void; onDelete?: () => void }) {
  const [detailsOpen, setDetailsOpen] = useState(!value.id);
  const [now, setNow] = useState(() => Date.now());
  const backdrop = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = backdrop.current;
    const dismiss = (event: MouseEvent) => { if (event.target === node) onClose(); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    node?.addEventListener("mousedown", dismiss); node?.addEventListener("keydown", escape);
    return () => { node?.removeEventListener("mousedown", dismiss); node?.removeEventListener("keydown", escape); };
  }, [onClose]);
  const focusTarget = useRef<HTMLInputElement & HTMLTextAreaElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    focusTarget.current?.focus();
    const timer = setInterval(() => setNow(Date.now()), 60000);
    return () => { clearInterval(timer); previous?.focus(); };
  }, []);
  const set = <K extends keyof Application>(key: K, next: Application[K]) => setValue({ ...value, [key]: next });
  const updateStatus = (status: Status) => {
    if (status === value.status) return;
    const now = localDateTimeNow();
    let history = progressStages.includes(status as ProgressEntry["status"])
      ? [...value.progressHistory, { id: uid(), status: status as ProgressEntry["status"], at: now, note: "" }]
      : value.progressHistory;
    const terminal = status === "offer" || status === "rejected";
    if (terminal) history = history.filter((entry) => !entry.at || Date.parse(entry.at) <= Date.now());
    setValue({ ...value, status, appliedAt: status === "applied" && !value.appliedAt ? now.slice(0, 10) : value.appliedAt, progressHistory: history });
  };
  const updateProgress = (id: string, patch: Partial<ProgressEntry>) => setValue({ ...value, progressHistory: value.progressHistory.map((entry) => entry.id === id ? { ...entry, ...patch } : entry) });
  const addProgress = () => {
    const currentIndex = progressStages.indexOf(value.status as ProgressEntry["status"]);
    const nextStatus = progressStages[Math.min(Math.max(currentIndex + 1, 0), progressStages.length - 1)];
    setValue({ ...value, progressHistory: [...value.progressHistory, { id: uid(), status: nextStatus, at: localDateTimeNow(), note: "" }] });
  };
  const basicFields = <div className="form-grid basic-form-grid">
    <label><span>公司名称 *</span><input ref={!value.id ? focusTarget : undefined} required value={value.company} onChange={(e) => set("company", e.target.value)} placeholder="例如：字节跳动" /></label>
    <label><span>岗位名称 *</span><input required value={value.role} onChange={(e) => set("role", e.target.value)} placeholder="例如：产品经理" /></label>
    <label><span>投递平台</span><input value={value.platform} onChange={(e) => set("platform", e.target.value)} placeholder="官网 / 内推 / Boss" /></label>
    <label><span>投递日期</span><input type="date" value={value.appliedAt} onChange={(e) => set("appliedAt", e.target.value)} /></label>
    <label><span>薪资范围</span><input value={value.salary} onChange={(e) => set("salary", e.target.value)} placeholder="例如：20–30K" /></label>
    <ResumePicker value={value} onChange={(reference) => setValue({ ...value, ...reference })} />
  </div>;

  return <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={value.id ? "更新进展" : "新增投递"} tabIndex={-1} ref={backdrop}>
    <form className="modal progress-modal" onSubmit={onSave}>
      <div className="modal-head"><div><h2>{value.id ? `${value.company || "投递"} · 更新进展` : "新增投递"}</h2>{value.id && <p className="modal-subtitle">{value.role}</p>}</div><button type="button" onClick={onClose} aria-label="关闭"><X size={17} /></button></div>

      {!value.id && basicFields}

      <section className="quick-update">
        <div className="section-heading"><div><div><h3>当前进展</h3><p>点击阶段会自动记入时间线。</p></div></div><StatusPill status={value.status} /></div>
        <div className="stage-picker" role="group" aria-label="选择当前投递阶段">
          {(Object.keys(statusMeta) as Status[]).map((status) => <button type="button" key={status} className={value.status === status ? "is-active" : ""} aria-pressed={value.status === status} onClick={() => updateStatus(status)}><i className={`dot dot--${statusMeta[status].tone}`} />{statusMeta[status].label}</button>)}
        </div>
        <label className="update-note"><span>本次备注</span><textarea ref={value.id ? focusTarget : undefined} value={value.note} onChange={(e) => set("note", e.target.value)} placeholder="记录面试重点、反馈或下一步准备…" /></label>
      </section>

      <section className="progress-editor">
        <div className="section-heading"><div><div><h3>流程时间线</h3><p>未来时间的节点会显示在首页、投递卡片和日历。</p></div></div><button type="button" className="add-progress" onClick={addProgress}><Plus size={13} />添加流程节点</button></div>
        <div className="timeline-editor">
          {value.progressHistory.length ? [...value.progressHistory].sort((a, b) => a.at.localeCompare(b.at)).map((entry, index, sortedHistory) => <div className={`timeline-entry ${entry.at && Date.parse(entry.at) > now ? "is-planned" : ""}`} key={entry.id}>
            <div className="timeline-rail"><i className={`dot dot--${statusMeta[entry.status].tone}`} />{index < sortedHistory.length - 1 && <b />}</div>
            <div className="timeline-entry-fields">
              <select aria-label="节点类型" value={entry.status} onChange={(e) => updateProgress(entry.id, { status: e.target.value as ProgressEntry["status"] })}>{progressStages.map((status) => <option key={status} value={status}>{statusMeta[status].label}</option>)}</select>
              <input aria-label="节点时间" type="datetime-local" value={entry.at} onChange={(e) => updateProgress(entry.id, { at: e.target.value })} />
              <input aria-label="节点备注" value={entry.note} onChange={(e) => updateProgress(entry.id, { note: e.target.value })} placeholder="填写反馈或复盘" />
              <button type="button" aria-label={`删除${statusMeta[entry.status].label}节点`} onClick={() => setValue({ ...value, progressHistory: value.progressHistory.filter((item) => item.id !== entry.id) })}><X size={14} /></button>
            </div>
          </div>) : <div className="timeline-empty"><span><Plus size={15} /></span><div><strong>还没有流程记录</strong><p>更新当前阶段，或手动添加第一个节点。</p></div></div>}
        </div>
      </section>

      {value.id && <section className="basic-details"><button type="button" onClick={() => setDetailsOpen((open) => !open)} aria-expanded={detailsOpen}><span><span><strong>基础信息</strong><small>公司、岗位、平台、薪资、简历文件</small></span></span>{detailsOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}</button>{detailsOpen && basicFields}</section>}

      {value.sourceJobUrl && <a className="source-job-link" href={value.sourceJobUrl} target="_blank" rel="noreferrer">查看岗位原始页面<ExternalLink size={12} /></a>}

      <div className="modal-foot">{onDelete ? <button type="button" className="delete-button" onClick={onDelete}><Trash2 size={13} />删除记录</button> : <span />}<div><button type="button" className="secondary-button secondary-button--small" onClick={onClose}>取消</button><button className="primary-button primary-button--small">{value.id ? "保存进展" : "加入投递计划"}</button></div></div>
    </form>
  </div>;
}

function EmptyMini({ text }: { text: string }) { return <div className="compact-empty-state empty-mini"><CalendarClock size={20} strokeWidth={1.5} /><p>{text}</p></div>; }
