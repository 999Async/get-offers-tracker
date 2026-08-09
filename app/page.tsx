"use client";

import { useEffect, useMemo, useRef, useState } from "react";

type Status = "pending" | "applied" | "written" | "interview1" | "interview2" | "interview3" | "hr" | "offer" | "rejected";
type View = "home" | "applications" | "calendar" | "jobs" | "settings";

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
  createdAt: string;
};

type Job = {
  id: string;
  company: string;
  role: string;
  location: string;
  tag: string;
  deadline: string;
  referral?: string;
};

const STORAGE_KEY = "get-offers-applications-v1";
const RESUME_KEY = "get-offers-resumes-v1";

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

const initialApplications: Application[] = [
  { id: "1", company: "字节跳动", role: "产品经理（AI 方向）", platform: "官网", status: "interview1", salary: "25–35K", appliedAt: "2026-08-02", note: "准备 AI 产品案例与数据指标", resume: "产品经理 v3", createdAt: "2026-08-02T08:00:00.000Z", progressHistory: [{ id: "1-a", status: "applied", at: "2026-08-02T10:20", note: "官网投递" }, { id: "1-b", status: "written", at: "2026-08-05T19:00", note: "完成在线测评" }, { id: "1-c", status: "interview1", at: "2026-08-08T15:30", note: "业务一面通过" }, { id: "1-d", status: "interview2", at: "2026-08-10T14:00", note: "" }] },
  { id: "2", company: "腾讯", role: "云产品策划", platform: "内推", status: "applied", salary: "22–32K", appliedAt: "2026-08-04", note: "在线测评，90 分钟", resume: "产品经理 v3", createdAt: "2026-08-04T08:00:00.000Z", progressHistory: [{ id: "2-a", status: "applied", at: "2026-08-04T11:00", note: "内推投递" }, { id: "2-b", status: "written", at: "2026-08-11T19:00", note: "在线测评，90 分钟" }] },
  { id: "3", company: "小红书", role: "商业产品经理", platform: "Boss 直聘", status: "applied", salary: "20–30K", appliedAt: "2026-08-06", note: "已联系招聘经理", resume: "产品经理 v2", createdAt: "2026-08-06T08:00:00.000Z", progressHistory: [{ id: "3-a", status: "applied", at: "2026-08-06T09:40", note: "已联系招聘经理" }] },
  { id: "4", company: "美团", role: "到店产品运营", platform: "官网", status: "pending", salary: "18–28K", appliedAt: "", note: "完善项目经历后投递", resume: "产品运营 v1", createdAt: "2026-08-07T08:00:00.000Z", progressHistory: [{ id: "4-a", status: "applied", at: "2026-08-13T20:00", note: "计划投递" }] },
  { id: "5", company: "阿里巴巴", role: "用户产品经理", platform: "实习僧", status: "rejected", salary: "20–30K", appliedAt: "2026-07-22", note: "流程结束，复盘业务面问题", resume: "产品经理 v2", createdAt: "2026-07-22T08:00:00.000Z", progressHistory: [{ id: "5-a", status: "applied", at: "2026-07-22T10:00", note: "完成投递" }, { id: "5-b", status: "interview1", at: "2026-07-29T14:00", note: "业务面" }] },
  { id: "6", company: "得物 App", role: "增长产品经理", platform: "内推", status: "offer", salary: "24–34K", appliedAt: "2026-07-18", note: "Offer 沟通", resume: "增长产品 v2", createdAt: "2026-07-18T08:00:00.000Z", progressHistory: [{ id: "6-a", status: "applied", at: "2026-07-18T11:30", note: "内推" }, { id: "6-b", status: "interview1", at: "2026-07-25T14:00", note: "业务面" }, { id: "6-c", status: "interview2", at: "2026-07-30T16:00", note: "交叉面" }, { id: "6-d", status: "hr", at: "2026-08-05T11:00", note: "薪资沟通" }, { id: "6-e", status: "offer", at: "2026-08-07T18:00", note: "收到口头 Offer" }] },
];

const jobs: Job[] = [
  { id: "j1", company: "快手", role: "商业化产品经理", location: "北京", tag: "27 届校招", deadline: "08.18", referral: "KS2027" },
  { id: "j2", company: "网易", role: "AI 产品经理", location: "杭州", tag: "提前批", deadline: "08.21", referral: "NE2027" },
  { id: "j3", company: "哔哩哔哩", role: "社区产品经理", location: "上海", tag: "27 届校招", deadline: "08.25" },
  { id: "j4", company: "百度", role: "大模型产品经理", location: "北京", tag: "秋招正式批", deadline: "08.30", referral: "BD2027" },
  { id: "j5", company: "携程", role: "国际化产品经理", location: "上海", tag: "27 届校招", deadline: "09.02" },
  { id: "j6", company: "滴滴", role: "平台产品经理", location: "北京", tag: "秋招正式批", deadline: "09.05", referral: "DD2027" },
];

const navItems: { id: View; label: string; icon: string }[] = [
  { id: "home", label: "概览", icon: "⌂" },
  { id: "applications", label: "投递", icon: "▤" },
  { id: "calendar", label: "日历", icon: "□" },
  { id: "jobs", label: "岗位雷达", icon: "◎" },
  { id: "settings", label: "设置", icon: "⚙" },
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
    note: raw.note || "", resume: raw.resume || "", createdAt: raw.createdAt || new Date().toISOString(),
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
  const [applications, setApplications] = useState<Application[]>(initialApplications);
  const [resumes, setResumes] = useState(["产品经理 v3", "产品经理 v2", "产品运营 v1", "增长产品 v2"]);
  const [ready, setReady] = useState(false);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<Status | "all">("all");
  const [display, setDisplay] = useState<"list" | "board">("list");
  const [jobQuery, setJobQuery] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Application | null>(null);
  const [toast, setToast] = useState("");
  const [calendarCursor, setCalendarCursor] = useState(new Date(2026, 7, 1));
  const [selectedDay, setSelectedDay] = useState("2026-08-10");
  const importRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      const savedResumes = localStorage.getItem(RESUME_KEY);
      if (saved) setApplications(JSON.parse(saved).map(normalizeApplication));
      if (savedResumes) setResumes(JSON.parse(savedResumes));
    } catch {}
    setReady(true);
  }, []);

  useEffect(() => {
    if (!ready) return;
    localStorage.setItem(STORAGE_KEY, JSON.stringify(applications));
    localStorage.setItem(RESUME_KEY, JSON.stringify(resumes));
  }, [applications, ready, resumes]);

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
      resume: resumes[0] || "", createdAt: new Date().toISOString(),
    });
    setModalOpen(true);
  }

  function saveApplication(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editing?.company.trim() || !editing.role.trim()) return;
    const normalized = normalizeApplication(editing);
    if (editing.id) {
      setApplications((items) => items.map((item) => item.id === editing.id ? normalized : item));
      showToast("投递记录已更新");
    } else {
      setApplications((items) => [{ ...normalized, id: uid() }, ...items]);
      showToast("已加入投递计划");
    }
    setModalOpen(false);
  }

  function removeApplication(id: string) {
    setApplications((items) => items.filter((item) => item.id !== id));
    setModalOpen(false);
    showToast("记录已删除");
  }

  function exportData() {
    const blob = new Blob([JSON.stringify({ applications, resumes }, null, 2)], { type: "application/json" });
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
    reader.onload = () => {
      try {
        const value = JSON.parse(String(reader.result));
        if (!Array.isArray(value.applications)) throw new Error();
        setApplications(value.applications.map(normalizeApplication));
        if (Array.isArray(value.resumes)) setResumes(value.resumes);
        showToast("数据导入成功");
      } catch { showToast("文件格式不正确"); }
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
            <button key={item.id} className={`nav-item ${view === item.id ? "is-active" : ""}`} onClick={() => setView(item.id)}>
              <span className="nav-icon" aria-hidden="true">{item.icon}</span>{item.label}
              {item.id === "applications" && <span className="nav-count">{applications.length}</span>}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="sync-chip"><span className="sync-dot" /> 数据已保存</div>
          <div className="profile"><span className="avatar">X</span><span><strong>本机数据</strong><small>仅此浏览器</small></span></div>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div className="mobile-brand"><span className="brand-mark" aria-hidden="true">GO</span> GetOffers</div>
          <div className="breadcrumb"><strong>{navItems.find((item) => item.id === view)?.label}</strong></div>
          <div className="top-actions">
            <button className="icon-button" title="快捷搜索" onClick={() => { setView("applications"); setTimeout(() => document.querySelector<HTMLInputElement>("#application-search")?.focus(), 20); }}>⌕</button>
            <button className="primary-button primary-button--small" onClick={() => openCreate()}><span>＋</span> 新增投递</button>
          </div>
        </header>

        <div className="content">
          {view === "home" && <HomeView applications={applications} stats={stats} upcoming={upcoming} onCreate={() => openCreate()} onEdit={(item) => { setEditing(item); setModalOpen(true); }} onNavigate={setView} />}
          {view === "applications" && <ApplicationsView applications={filtered} allCount={applications.length} query={query} setQuery={setQuery} statusFilter={statusFilter} setStatusFilter={setStatusFilter} display={display} setDisplay={setDisplay} onCreate={() => openCreate()} onEdit={(item) => { setEditing(item); setModalOpen(true); }} />}
          {view === "calendar" && <CalendarView applications={applications} cursor={calendarCursor} setCursor={setCalendarCursor} selectedDay={selectedDay} setSelectedDay={setSelectedDay} />}
          {view === "jobs" && <JobsView query={jobQuery} setQuery={setJobQuery} applications={applications} onAdd={(job) => openCreate({ company: job.company, role: job.role, status: "pending" })} />}
          {view === "settings" && <SettingsView resumes={resumes} setResumes={setResumes} exportData={exportData} importData={() => importRef.current?.click()} resetData={() => { setApplications(initialApplications); showToast("示例数据已恢复"); }} />}
        </div>
      </main>

      <nav className="mobile-nav" aria-label="移动端导航">
        {navItems.slice(0, 4).map((item) => <button key={item.id} className={view === item.id ? "is-active" : ""} onClick={() => setView(item.id)}><span>{item.icon}</span>{item.label}</button>)}
      </nav>

      <input ref={importRef} className="visually-hidden" type="file" accept="application/json" onChange={importData} />
      {modalOpen && editing && <ApplicationModal value={editing} setValue={setEditing} resumes={resumes} onClose={() => setModalOpen(false)} onSave={saveApplication} onDelete={editing.id ? () => removeApplication(editing.id) : undefined} />}
      {toast && <div className="toast"><span>✓</span>{toast}</div>}
    </div>
  );
}

function PageIntro({ title, action }: { title: string; action?: React.ReactNode }) {
  return <div className="page-intro"><h1>{title}</h1>{action}</div>;
}

function HomeView({ applications, stats, upcoming, onCreate, onEdit, onNavigate }: { applications: Application[]; stats: { total: number; active: number; interview: number; offer: number }; upcoming: { app: Application; entry: ProgressEntry }[]; onCreate: () => void; onEdit: (app: Application) => void; onNavigate: (view: View) => void }) {
  const rate = stats.total ? Math.round((stats.offer / stats.total) * 100) : 0;
  const stages = [
    { label: "全部记录", value: stats.total, width: 100 },
    { label: "推进流程", value: applications.filter((a) => ["written", ...interviewStages, "offer"].includes(a.status)).length, width: 72 },
    { label: "进入面试", value: applications.filter((a) => [...interviewStages, "offer"].includes(a.status)).length, width: 48 },
    { label: "获得 Offer", value: stats.offer, width: 26 },
  ];
  return <>
    <section className="dashboard-intro"><div><h1>概览</h1><p>{stats.total} 条投递 · {stats.active} 条进行中 · {stats.interview} 条处于面试阶段</p></div><div className="hero-actions"><button className="primary-button" onClick={onCreate}>＋ 新增投递</button><button className="secondary-button" onClick={() => onNavigate("applications")}>全部记录</button></div></section>

    <section className="metric-grid">
      <article><div className="metric-head"><span>全部投递</span><i className="metric-icon">↗</i></div><strong>{stats.total}</strong></article>
      <article><div className="metric-head"><span>进行中</span><i className="metric-icon metric-icon--blue">●</i></div><strong>{stats.active}</strong></article>
      <article><div className="metric-head"><span>面试阶段</span><i className="metric-icon metric-icon--amber">◈</i></div><strong>{stats.interview}</strong></article>
      <article><div className="metric-head"><span>Offer 转化</span><i className="metric-icon metric-icon--dark">✓</i></div><strong>{rate}%</strong><p>共 {stats.offer} 个 Offer</p></article>
    </section>

    <div className="dashboard-grid">
      <section className="panel schedule-panel">
        <div className="panel-head"><h2>接下来 7 天</h2><button className="text-button" onClick={() => onNavigate("calendar")}>打开日历 →</button></div>
        <div className="schedule-list">{upcoming.length ? upcoming.map(({ app, entry }, index) => <button className="schedule-row" key={`${app.id}-${entry.id}`} onClick={() => onEdit(app)}><div className="date-tile"><strong>{dateLabel(entry.at).replace(/月.*/, "")}</strong><span>{dateLabel(entry.at).replace(/.*月/, "").replace("日", "")}</span></div><div className="schedule-line" aria-hidden="true"><i className={`schedule-dot schedule-dot--${statusMeta[entry.status].tone}`} />{index < upcoming.length - 1 && <b />}</div><div className="schedule-copy"><strong>{app.company} · {app.role}</strong><span>{dateTimeLabel(entry.at)} · {statusMeta[entry.status].label}</span></div><span className="row-arrow">›</span></button>) : <EmptyMini text="暂时没有安排" />}</div>
      </section>
      <section className="panel funnel-panel">
        <div className="panel-head"><h2>投递漏斗</h2></div>
        <div className="funnel">{stages.map((stage, index) => <div className="funnel-row" key={stage.label}><div><span>{stage.label}</span><strong>{stage.value}</strong></div><div className="funnel-track"><i style={{ width: `${Math.max(stage.value ? stage.width : 3, 3)}%` }} /></div>{index > 0 && <small>{stats.total ? Math.round(stage.value / stats.total * 100) : 0}%</small>}</div>)}</div>
      </section>
    </div>

    <section className="panel recent-panel">
      <div className="panel-head"><h2>最近更新</h2><button className="text-button" onClick={() => onNavigate("applications")}>全部记录 →</button></div>
      <ApplicationTable applications={applications.slice(0, 5)} onEdit={onEdit} compact />
    </section>
  </>;
}

function ApplicationsView({ applications, allCount, query, setQuery, statusFilter, setStatusFilter, display, setDisplay, onCreate, onEdit }: { applications: Application[]; allCount: number; query: string; setQuery: (value: string) => void; statusFilter: Status | "all"; setStatusFilter: (value: Status | "all") => void; display: "list" | "board"; setDisplay: (value: "list" | "board") => void; onCreate: () => void; onEdit: (app: Application) => void }) {
  return <>
    <PageIntro title={`投递记录（${allCount}）`} action={<button className="primary-button" onClick={onCreate}>＋ 新增投递</button>} />
    <div className="toolbar">
      <label className="search-box"><span>⌕</span><input id="application-search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜索公司、岗位或平台" /></label>
      <div className="filter-tabs"><button className={statusFilter === "all" ? "is-active" : ""} onClick={() => setStatusFilter("all")}>全部</button>{(Object.keys(statusMeta) as Status[]).map((status) => <button key={status} className={statusFilter === status ? "is-active" : ""} onClick={() => setStatusFilter(status)}>{statusMeta[status].label}</button>)}</div>
      <div className="view-switch"><button className={display === "list" ? "is-active" : ""} onClick={() => setDisplay("list")}>☷</button><button className={display === "board" ? "is-active" : ""} onClick={() => setDisplay("board")}>▦</button></div>
    </div>
    {applications.length === 0 ? <div className="empty-card"><span>⌕</span><h3>没有找到匹配记录</h3><p>换个关键词或清除筛选条件试试。</p></div> : display === "list" ? <section className="panel application-list-panel"><ApplicationTable applications={applications} onEdit={onEdit} /></section> : <Kanban applications={applications} onEdit={onEdit} />}
  </>;
}

function ApplicationTable({ applications, onEdit, compact = false }: { applications: Application[]; onEdit: (app: Application) => void; compact?: boolean }) {
  return <div className="table-scroll"><table className="data-table"><thead><tr><th>公司与岗位</th><th>状态</th><th>投递日期</th><th>下个安排</th>{!compact && <th>简历版本</th>}<th /></tr></thead><tbody>{applications.map((app) => { const next = getNextProgress(app); return <tr key={app.id} onClick={() => onEdit(app)}><td><span className="company-cell"><i>{app.company.slice(0, 1)}</i><span><strong>{app.company}</strong><small>{app.role}</small></span></span></td><td><StatusPill status={app.status} /></td><td className="muted-cell">{dateLabel(app.appliedAt)}</td><td><span className={next ? "next-date" : "muted-cell"}>{next ? `${statusMeta[next.status].label} · ${dateTimeLabel(next.at)}` : "—"}</span></td>{!compact && <td className="muted-cell">{app.resume || "—"}</td>}<td><button className="more-button" aria-label={`编辑 ${app.company}`}>•••</button></td></tr>; })}</tbody></table></div>;
}

function Kanban({ applications, onEdit }: { applications: Application[]; onEdit: (app: Application) => void }) {
  const columns: Status[] = ["pending", "applied", "written", "interview1", "interview2", "interview3", "hr", "offer"];
  return <div className="kanban">{columns.map((status) => { const items = applications.filter((item) => item.status === status); return <section className={`kanban-column ${items.length ? "" : "is-empty"}`} key={status}><div className="kanban-head"><span><i className={`dot dot--${statusMeta[status].tone}`} />{statusMeta[status].label}</span><b>{items.length}</b></div><div className="kanban-cards">{items.map((app) => { const next = getNextProgress(app); return <button className="kanban-card" key={app.id} onClick={() => onEdit(app)}><span className="mini-logo">{app.company[0]}</span><span className="kanban-card-main"><strong>{app.company}</strong><small>{app.role}</small></span><span className="kanban-card-arrow">›</span><span className="kanban-card-meta">{next ? <><b>{statusMeta[next.status].label}</b>{dateTimeLabel(next.at)}</> : app.platform}</span></button>; })}{!items.length && <span className="kanban-empty">暂无记录</span>}</div></section>; })}</div>;
}

function CalendarView({ applications, cursor, setCursor, selectedDay, setSelectedDay }: { applications: Application[]; cursor: Date; setCursor: (value: Date) => void; selectedDay: string; setSelectedDay: (value: string) => void }) {
  const year = cursor.getFullYear(); const month = cursor.getMonth();
  const firstDay = new Date(year, month, 1).getDay(); const days = new Date(year, month + 1, 0).getDate(); const previousDays = new Date(year, month, 0).getDate();
  const cells = Array.from({ length: 42 }, (_, i) => { const day = i - firstDay + 1; const date = day < 1 ? new Date(year, month - 1, previousDays + day) : day > days ? new Date(year, month + 1, day - days) : new Date(year, month, day); return { date, current: day >= 1 && day <= days }; });
  const keyFor = (date: Date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  const eventsFor = (key: string) => applications.flatMap((app) => app.progressHistory.filter((entry) => entry.at.slice(0, 10) === key).map((entry) => ({ app, entry })));
  const selectedEvents = eventsFor(selectedDay);
  return <>
    <PageIntro title="日历" />
    <div className="calendar-layout">
      <section className="panel calendar-panel">
        <div className="calendar-title"><div><button onClick={() => setCursor(new Date(year, month - 1, 1))}>‹</button><button onClick={() => setCursor(new Date(year, month + 1, 1))}>›</button></div><h2>{year} 年 {month + 1} 月</h2><button className="secondary-button secondary-button--small" onClick={() => { setCursor(new Date(2026, 7, 1)); setSelectedDay("2026-08-09"); }}>今天</button></div>
        <div className="weekdays">{["日", "一", "二", "三", "四", "五", "六"].map((d) => <span key={d}>{d}</span>)}</div>
        <div className="calendar-grid">{cells.map(({ date, current }) => { const key = keyFor(date); const events = eventsFor(key); return <button key={key} className={`${current ? "" : "is-other"} ${selectedDay === key ? "is-selected" : ""} ${key === "2026-08-09" ? "is-today" : ""}`} onClick={() => setSelectedDay(key)}><span>{date.getDate()}</span><div>{events.slice(0, 2).map(({ app, entry }) => <i key={`${app.id}-${entry.id}`} className={`calendar-event calendar-event--${statusMeta[entry.status].tone}`}>{app.company} · {statusMeta[entry.status].label}</i>)}</div></button>; })}</div>
      </section>
      <aside className="panel day-panel"><h2>{dateLabel(selectedDay)}</h2><div className="day-events">{selectedEvents.length ? selectedEvents.map(({ app, entry }) => <div key={`${app.id}-${entry.id}`}><i className={`dot dot--${statusMeta[entry.status].tone}`} /><span><strong>{app.company} · {statusMeta[entry.status].label}</strong><small>{dateTimeLabel(entry.at).split(" ").at(-1)} · {app.role}{entry.note ? ` · ${entry.note}` : ""}</small></span></div>) : <EmptyMini text="当天没有流程节点" />}</div></aside>
    </div>
  </>;
}

function JobsView({ query, setQuery, applications, onAdd }: { query: string; setQuery: (value: string) => void; applications: Application[]; onAdd: (job: Job) => void }) {
  const filteredJobs = jobs.filter((job) => `${job.company} ${job.role} ${job.location} ${job.referral || ""}`.toLowerCase().includes(query.toLowerCase()));
  return <>
    <PageIntro title="岗位目录" />
    <div className="jobs-toolbar"><label className="search-box"><span>⌕</span><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜索公司、岗位、城市或内推码" /></label><span>{filteredJobs.length} 个岗位</span></div>
    <div className="job-grid">{filteredJobs.map((job) => { const added = applications.some((app) => app.company === job.company && app.role === job.role); return <article className="job-card" key={job.id}><div className="job-card-head"><span className="job-logo">{job.company[0]}</span><span className="job-tag">{job.tag}</span></div><h3>{job.company}</h3><p>{job.role}</p><div className="job-meta"><span>⌖ {job.location}</span><span>截止 {job.deadline}</span></div>{job.referral && <div className="referral"><span>内推码</span><code>{job.referral}</code><button onClick={() => navigator.clipboard?.writeText(job.referral || "")}>复制</button></div>}<button className={added ? "added-button" : "secondary-button job-add"} onClick={() => !added && onAdd(job)} disabled={added}>{added ? "✓ 已在投递中" : "加入待投递 →"}</button></article>; })}</div>
  </>;
}

function SettingsView({ resumes, setResumes, exportData, importData, resetData }: { resumes: string[]; setResumes: (items: string[]) => void; exportData: () => void; importData: () => void; resetData: () => void }) {
  const [draft, setDraft] = useState("");
  return <>
    <PageIntro title="设置" />
    <div className="settings-layout"><section className="panel settings-section"><div className="settings-heading"><span className="settings-icon">▧</span><div><h2>简历版本</h2><p>新增投递时可选择对应版本。</p></div></div><div className="resume-list">{resumes.map((resume, index) => <div key={`${resume}-${index}`}><span className="doc-icon">DOC</span><strong>{resume}</strong>{index === 0 && <span className="default-chip">默认</span>}<button onClick={() => setResumes(resumes.filter((_, i) => i !== index))}>移除</button></div>)}</div><form className="resume-add" onSubmit={(e) => { e.preventDefault(); if (draft.trim()) { setResumes([...resumes, draft.trim()]); setDraft(""); } }}><input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="例如：AI 产品经理 v1" /><button className="primary-button primary-button--small">＋ 添加版本</button></form></section><section className="panel settings-section"><div className="settings-heading"><span className="settings-icon">↕</span><div><h2>数据管理</h2></div></div><div className="setting-actions"><button onClick={exportData}><span>↓</span><div><strong>导出数据</strong><small>JSON 备份</small></div><b>›</b></button><button onClick={importData}><span>↑</span><div><strong>导入数据</strong><small>从 JSON 恢复</small></div><b>›</b></button><button onClick={resetData}><span>↻</span><div><strong>恢复示例数据</strong></div><b>›</b></button></div></section><section className="panel settings-section security-card"><div className="settings-heading"><span className="settings-icon">⌁</span><div><h2>数据存储</h2><p>数据仅保存在当前浏览器。</p></div></div><div className="security-status"><span><i /> 浏览器存储正常</span></div></section></div>
  </>;
}

function ApplicationModal({ value, setValue, resumes, onClose, onSave, onDelete }: { value: Application; setValue: (value: Application) => void; resumes: string[]; onClose: () => void; onSave: (event: React.FormEvent<HTMLFormElement>) => void; onDelete?: () => void }) {
  const [detailsOpen, setDetailsOpen] = useState(!value.id);
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
    <label><span>公司名称 *</span><input autoFocus={!value.id} required value={value.company} onChange={(e) => set("company", e.target.value)} placeholder="例如：字节跳动" /></label>
    <label><span>岗位名称 *</span><input required value={value.role} onChange={(e) => set("role", e.target.value)} placeholder="例如：产品经理" /></label>
    <label><span>投递平台</span><input value={value.platform} onChange={(e) => set("platform", e.target.value)} placeholder="官网 / 内推 / Boss" /></label>
    <label><span>投递日期</span><input type="date" value={value.appliedAt} onChange={(e) => set("appliedAt", e.target.value)} /></label>
    <label><span>薪资范围</span><input value={value.salary} onChange={(e) => set("salary", e.target.value)} placeholder="例如：20–30K" /></label>
    <label><span>简历版本</span><select value={value.resume} onChange={(e) => set("resume", e.target.value)}><option value="">未指定</option>{resumes.map((resume) => <option key={resume}>{resume}</option>)}</select></label>
  </div>;

  return <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <form className="modal progress-modal" onSubmit={onSave}>
      <div className="modal-head"><div><h2>{value.id ? `${value.company || "投递"} · 更新进展` : "新增投递"}</h2>{value.id && <p className="modal-subtitle">{value.role}</p>}</div><button type="button" onClick={onClose} aria-label="关闭">×</button></div>

      {!value.id && basicFields}

      <section className="quick-update">
        <div className="section-heading"><div><div><h3>当前进展</h3><p>点击阶段会自动记入时间线。</p></div></div><StatusPill status={value.status} /></div>
        <div className="stage-picker" role="group" aria-label="选择当前投递阶段">
          {(Object.keys(statusMeta) as Status[]).map((status) => <button type="button" key={status} className={value.status === status ? "is-active" : ""} aria-pressed={value.status === status} onClick={() => updateStatus(status)}><i className={`dot dot--${statusMeta[status].tone}`} />{statusMeta[status].label}</button>)}
        </div>
        <label className="update-note"><span>本次备注</span><textarea autoFocus={!!value.id} value={value.note} onChange={(e) => set("note", e.target.value)} placeholder="记录面试重点、反馈或下一步准备…" /></label>
      </section>

      <section className="progress-editor">
        <div className="section-heading"><div><div><h3>流程时间线</h3><p>未来时间的节点会显示在首页、投递卡片和日历。</p></div></div><button type="button" className="add-progress" onClick={addProgress}>＋ 添加流程节点</button></div>
        <div className="timeline-editor">
          {value.progressHistory.length ? [...value.progressHistory].sort((a, b) => a.at.localeCompare(b.at)).map((entry, index, sortedHistory) => <div className={`timeline-entry ${entry.at && Date.parse(entry.at) > Date.now() ? "is-planned" : ""}`} key={entry.id}>
            <div className="timeline-rail"><i className={`dot dot--${statusMeta[entry.status].tone}`} />{index < sortedHistory.length - 1 && <b />}</div>
            <div className="timeline-entry-fields">
              <select aria-label="节点类型" value={entry.status} onChange={(e) => updateProgress(entry.id, { status: e.target.value as ProgressEntry["status"] })}>{progressStages.map((status) => <option key={status} value={status}>{statusMeta[status].label}</option>)}</select>
              <input aria-label="节点时间" type="datetime-local" value={entry.at} onChange={(e) => updateProgress(entry.id, { at: e.target.value })} />
              <input aria-label="节点备注" value={entry.note} onChange={(e) => updateProgress(entry.id, { note: e.target.value })} placeholder="填写反馈或复盘" />
              <button type="button" aria-label={`删除${statusMeta[entry.status].label}节点`} onClick={() => setValue({ ...value, progressHistory: value.progressHistory.filter((item) => item.id !== entry.id) })}>×</button>
            </div>
          </div>) : <div className="timeline-empty"><span>＋</span><div><strong>还没有流程记录</strong><p>更新当前阶段，或手动添加第一个节点。</p></div></div>}
        </div>
      </section>

      {value.id && <section className="basic-details"><button type="button" onClick={() => setDetailsOpen((open) => !open)} aria-expanded={detailsOpen}><span><span><strong>基础信息</strong><small>公司、岗位、平台、薪资、简历版本</small></span></span><i>{detailsOpen ? "−" : "+"}</i></button>{detailsOpen && basicFields}</section>}

      <div className="modal-foot">{onDelete ? <button type="button" className="delete-button" onClick={onDelete}>删除记录</button> : <span />}<div><button type="button" className="secondary-button secondary-button--small" onClick={onClose}>取消</button><button className="primary-button primary-button--small">{value.id ? "保存进展" : "加入投递计划"}</button></div></div>
    </form>
  </div>;
}

function EmptyMini({ text }: { text: string }) { return <div className="empty-mini"><span>◇</span><p>{text}</p></div>; }
