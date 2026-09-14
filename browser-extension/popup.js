/* global chrome */

let profile;
let lastDiagnostic;
let hasScanned = false;

const profileFile = document.querySelector("#profile-file");
const profileState = document.querySelector("#profile-state");
const copyProfilePromptButton = document.querySelector("#copy-profile-prompt");
const clearProfileButton = document.querySelector("#clear-profile");
const scanButton = document.querySelector("#scan");
const fillButton = document.querySelector("#fill");
const copyDiagnosticsButton = document.querySelector("#copy-diagnostics");
const summary = document.querySelector("#summary");
const results = document.querySelector("#results");

initialise();

async function initialise() {
  const saved = await chrome.storage.local.get("recruitmentProfile");
  if (saved.recruitmentProfile) {
    try {
      globalThis.RecruitmentAutofillProfileUtils.validateProfile(saved.recruitmentProfile);
      setProfile(saved.recruitmentProfile, "已从当前浏览器恢复资料");
    } catch {
      await chrome.storage.local.remove("recruitmentProfile");
      profileState.textContent = "旧资料格式无效，请重新生成并导入 profile.json";
    }
  }
  updateButtons();
}

profileFile.addEventListener("change", async () => {
  const file = profileFile.files?.[0];
  if (!file) return;
  try {
    const parsed = JSON.parse(await file.text());
    globalThis.RecruitmentAutofillProfileUtils.validateProfile(parsed);
    await chrome.storage.local.set({ recruitmentProfile: parsed });
    setProfile(parsed, `已导入：${file.name}`);
  } catch (error) {
    profileState.textContent = `导入失败：${error.message}`;
  }
});

copyProfilePromptButton.addEventListener("click", async () => {
  try {
    const response = await fetch(chrome.runtime.getURL("profile-generation-prompt.txt"));
    if (!response.ok) throw new Error("提示词读取失败");
    await navigator.clipboard.writeText(await response.text());
    copyProfilePromptButton.textContent = "已复制，去上传简历";
    profileState.textContent = "请向可信 AI 同时上传 PDF/Word 简历和空白模板，再粘贴提示词";
  } catch (error) {
    profileState.textContent = `复制失败：${error.message}`;
  }
});

clearProfileButton.addEventListener("click", async () => {
  await chrome.storage.local.remove("recruitmentProfile");
  profile = undefined;
  hasScanned = false;
  lastDiagnostic = undefined;
  profileFile.value = "";
  profileState.textContent = "已清除本机资料";
  summary.hidden = true;
  results.replaceChildren();
  copyDiagnosticsButton.disabled = true;
  updateButtons();
});

scanButton.addEventListener("click", () => run("scan"));
fillButton.addEventListener("click", () => run("fill-safe"));
copyDiagnosticsButton.addEventListener("click", copyDiagnostics);

async function run(type) {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id || !profile) return;
  try {
    const response = await globalThis.RecruitmentAutofillBridge.sendToPage(chrome, tab.id, { type, profile });
    lastDiagnostic = {
      extensionVersion: chrome.runtime.getManifest().version,
      page: safePagePath(tab.url),
      context: response?.context,
      summary: response?.summary,
      plan: response?.plan
    };
    hasScanned = true;
    copyDiagnosticsButton.disabled = false;
    render(response, type);
  } catch (error) {
    lastDiagnostic = {
      extensionVersion: chrome.runtime.getManifest().version,
      page: safePagePath(tab.url),
      error: error.message
    };
    copyDiagnosticsButton.disabled = false;
    summary.hidden = false;
    summary.textContent = `当前页面无法扫描：${friendlyError(error)}`;
  } finally {
    updateButtons();
  }
}

async function copyDiagnostics() {
  if (!lastDiagnostic) return;
  await navigator.clipboard.writeText(JSON.stringify(lastDiagnostic, null, 2));
  copyDiagnosticsButton.textContent = "已复制，可粘贴到 Issue 中";
}

function setProfile(nextProfile, message) {
  profile = nextProfile;
  hasScanned = false;
  profileState.textContent = message;
  updateButtons();
}

function updateButtons() {
  scanButton.disabled = !profile;
  fillButton.disabled = !profile || !hasScanned;
  clearProfileButton.hidden = !profile;
}

function render(response, type) {
  if (!response?.ok) return;
  const s = response.summary;
  const context = response.context || {};
  const hints = [];
  if (context.state === "auth-required") hints.push("这是登录或验证码页面，请登录后刷新申请页再试。");
  if (context.pagination?.currentPage) hints.push(`当前是分页表单“${context.pagination.currentPage}”，请逐页操作。`);
  if (type === "fill-safe") hints.push(`已尝试填写 ${s.safe} 个绿色字段，请逐项复核。`);
  hints.push(`共扫描 ${s.total} 个控件：绿色 ${s.safe}，黄色 ${s.review}，资料缺失 ${s.missingData}，未识别 ${s.unmatched}。`);
  summary.hidden = false;
  summary.textContent = hints.join(" ");
  results.replaceChildren(...response.plan.map(renderItem));
}

function renderItem(item) {
  const row = document.createElement("div");
  row.className = "result";
  const badge = document.createElement("span");
  badge.className = `badge ${item.status}`;
  badge.textContent = ({ safe: "可填", review: "人工", unmatched: "未知", "missing-data": "缺值" })[item.status];
  const detail = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = item.field.label || "无标签字段";
  const path = document.createElement("div");
  path.className = "path";
  path.textContent = item.path || item.reason;
  detail.append(title, path);
  const score = document.createElement("span");
  score.textContent = item.score ? String(Math.round(item.score * 100)) : "—";
  row.append(badge, detail, score);
  return row;
}

function safePagePath(url) {
  try {
    const parsed = new URL(url);
    return parsed.origin + parsed.pathname;
  } catch {
    return "unknown";
  }
}

function friendlyError(error) {
  const message = error?.message || String(error);
  if (/Cannot access|chrome:\/\/|edge:\/\//i.test(message)) {
    return "浏览器设置页不允许扩展运行，请先打开招聘申请页面";
  }
  return message;
}
