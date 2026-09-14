"use client";

import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Cpu, SlidersHorizontal } from "lucide-react";
import ComposerPopover from "./composer-popover";
import { ensureLocalConnection, readLocalConnection, type Connection } from "./local-session";

export default function LocalConnection({ disabled = false, compact = false, open = false, onToggle = () => {} }: { disabled?: boolean; compact?: boolean; open?: boolean; onToggle?: (open: boolean) => void }) {
  const [connection, setConnection] = useState<Connection | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const settingsTrigger = useRef<HTMLButtonElement>(null);
  function closeSelection() {
    if (compact) onToggle(false);
    else { setSettingsOpen(false); settingsTrigger.current?.focus(); }
  }
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    const load = async (initial = false) => {
      try {
        const value = await (initial ? ensureLocalConnection() : readLocalConnection());
        if (active) { setConnection(value); setError(""); }
      } catch (cause) { if (active) { setConnection({ local: true, connected: false }); setError((cause as Error).message); } }
    };
    const changed = () => { void load(); };
    void load(true); window.addEventListener("getoffers-account-changed", changed);
    return () => { active = false; window.removeEventListener("getoffers-account-changed", changed); };
  }, []);
  async function update(model?: string) {
    if (pending || disabled) return;
    setPending(true); setError("");
    try {
      if (model) {
        const response = await fetch("/api/local-assistant", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "model", model }) });
        if (!response.ok) throw Error("模型切换失败，请重试。");
        setConnection(await readLocalConnection());
        window.dispatchEvent(new CustomEvent("getoffers-account-changed", { detail: { action: "model" } }));
        closeSelection();
      } else setConnection(await ensureLocalConnection());
    } catch (cause) { setError((cause as Error).message); }
    finally { setPending(false); }
  }
  if (!connection?.local) return null;
  const controls = <>
    {connection.connected ? <div className="assistant-model-list" role="menu" tabIndex={-1} aria-label="选择模型" aria-busy={pending} onKeyDown={event => {
      if (event.key === "Escape") closeSelection();
      const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>("button:not(:disabled)"));
      const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
      let next: number | undefined;
      if (event.key === "ArrowDown") next = (index + 1) % buttons.length;
      if (event.key === "ArrowUp") next = (index - 1 + buttons.length) % buttons.length;
      if (event.key === "Home") next = 0;
      if (event.key === "End") next = buttons.length - 1;
      if (next !== undefined) { event.preventDefault(); buttons[next]?.focus(); }
    }}>
      {connection.models?.map(model => <button type="button" key={model.id} role="menuitemradio" aria-checked={model.id === connection.model} disabled={disabled || pending} onClick={() => model.id === connection.model ? closeSelection() : void update(model.id)}><span>{model.name}</span>{model.id === connection.model && <Check size={15} />}</button>)}
      {!connection.models?.length && <p>暂无可用模型。</p>}
    </div> : <button className="assistant-model-retry" type="button" disabled={disabled || pending} onClick={() => void update()}>{pending ? "正在连接…" : "重新连接"}</button>}
    {error && <p role="alert">{error}</p>}
  </>;
  return compact ? <ComposerPopover menu id="assistant-model" label={connection.connected ? `选择模型：${connection.models?.find(model => model.id === connection.model)?.name || connection.model || "本地 Codex"}` : "连接模型"} title="选择模型" icon={<SlidersHorizontal size={19} />} open={open} onToggle={onToggle}>{controls}</ComposerPopover> : <section className="panel settings-section settings-model" aria-label="模型设置">
    <div className="settings-heading"><span className="settings-icon"><SlidersHorizontal size={17} /></span><div><h2>模型设置</h2></div></div>
    <div className="setting-actions"><button ref={settingsTrigger} type="button" aria-expanded={settingsOpen} aria-controls="settings-model-options" onClick={() => setSettingsOpen(value => !value)}><span><Cpu size={15} /></span><div><strong>本地 Codex</strong><small>{connection.connected ? connection.models?.find(model => model.id === connection.model)?.name || connection.model : error ? "连接异常" : "正在连接…"}</small></div><ChevronDown size={15} /></button></div>
    {settingsOpen && <div id="settings-model-options" className="settings-model-options">{controls}</div>}
  </section>;
}
