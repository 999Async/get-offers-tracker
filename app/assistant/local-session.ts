export type Connection = { local: boolean; connected: boolean; model?: string; models?: { id: string; name: string }[] };

export async function readLocalConnection(): Promise<Connection | null> {
  const response = await fetch("/api/local-assistant", { cache: "no-store" });
  if (response.status === 503) throw Error("Codex 暂不可用，请确认本机 CLI 已登录后重试。");
  if (!response.ok) return null; // Hosted mode has no local account adapter.
  return response.json() as Promise<Connection>;
}

let connecting: Promise<Connection | null> | null = null;
export function ensureLocalConnection(): Promise<Connection | null> {
  if (connecting) return connecting;
  connecting = (async () => {
    const current = await readLocalConnection();
    if (!current?.local || current.connected) return current;
    const response = await fetch("/api/local-assistant", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "connect" }) });
    if (!response.ok) throw Error("Codex 暂不可用，请确认本机 CLI 已登录后重试。");
    const connected = await readLocalConnection();
    if (!connected?.connected) throw Error("连接未完成，请重试。");
    window.dispatchEvent(new CustomEvent("getoffers-account-changed", { detail: { action: "connect" } }));
    return connected;
  })().finally(() => { connecting = null; });
  return connecting;
}
