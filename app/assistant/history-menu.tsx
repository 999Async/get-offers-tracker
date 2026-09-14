import { useEffect, useRef } from "react";
import { Check, ChevronDown, CircleAlert, MessageSquarePlus } from "lucide-react";
import type { Conversation } from "./history";

export default function HistoryMenu({ entries, currentId, disabled, loading, error, hasMore, unauthorized, onOpen, onNew, onMore, onRetry }: {
  entries: Conversation[]; currentId: string; disabled: boolean; loading: boolean; error: string; hasMore: boolean; unauthorized: boolean;
  onOpen: (id: string) => void; onNew: () => void; onMore: () => void; onRetry: () => void;
}) {
  const menu = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const close = (event: PointerEvent) => { if (!menu.current?.contains(event.target as Node) && menu.current) menu.current.open = false; };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape" && menu.current?.open) { menu.current.open = false; menu.current.querySelector("summary")?.focus(); } };
    document.addEventListener("pointerdown", close); document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("pointerdown", close); document.removeEventListener("keydown", escape); };
  }, []);
  function choose(action: () => void) { if (menu.current) menu.current.open = false; action(); }
  return <details className="assistant-history-menu" ref={menu}>
    <summary aria-label={unauthorized ? "岗位助手，历史对话，请先登陆" : "岗位助手，历史对话"}>
      岗位助手<ChevronDown className="assistant-history-chevron" size={15} />
      {unauthorized && <span className="assistant-login-warning" data-tooltip="请先登陆" aria-hidden="true"><CircleAlert size={16} /></span>}
    </summary>
    <div className="assistant-history-popover" aria-label="历史对话">
      <button className="assistant-history-new" aria-label="新对话" disabled={disabled} onClick={() => choose(onNew)}><MessageSquarePlus size={16} />新对话</button>
      {error ? <div className="assistant-history-notice"><span>{error}</span><button onClick={onRetry}>重试</button></div> : null}
      {!entries.length && <p>{loading ? "正在读取…" : "暂无历史对话"}</p>}
      <div className="assistant-history-list">{entries.map(entry => <button key={entry.id} aria-label={entry.title} disabled={disabled} aria-current={entry.id === currentId ? "true" : undefined} onClick={() => choose(() => onOpen(entry.id))}>
        <span><strong>{entry.title}</strong><time dateTime={entry.updatedAt}>{new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(entry.updatedAt))}</time></span>
        {entry.id === currentId && <Check size={15} />}
      </button>)}</div>
      {hasMore && <button className="assistant-history-more" disabled={loading} onClick={onMore}>更早的对话</button>}
    </div>
  </details>;
}
