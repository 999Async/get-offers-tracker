import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { snapshotForStorage, type Conversation, type Snapshot } from "./history";

const endpoint = "/api/assistant/conversations";
export function useHistory(snapshot: Snapshot, busy: boolean, active: boolean, restore: (snapshot: Snapshot) => void) {
  const [entries, setEntries] = useState<Conversation[]>([]);
  const [id, setId] = useState("");
  const [reload, setReload] = useState(0);
  const [ready, setReady] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [hasMore, setHasMore] = useState(false);
  const current = useRef(snapshot), restoreRef = useRef(restore), saved = useRef(""), revision = useRef(0), currentId = useRef(""), generation = useRef(0);
  const pending = useRef<Promise<boolean> | null>(null);
  useLayoutEffect(() => { current.current = snapshot; restoreRef.current = restore; });
  const adopt = useCallback((nextId: string, value: Snapshot, version: number) => {
    currentId.current = nextId; revision.current = version; saved.current = JSON.stringify(snapshotForStorage(value));
    current.current = value; restoreRef.current(value); setId(nextId); setError("");
  }, []);
  const flush = useCallback(async (): Promise<boolean> => {
    const epoch = generation.current;
    if (pending.current) await pending.current;
    if (epoch !== generation.current) return false;
    const value = snapshotForStorage(current.current), raw = JSON.stringify(value);
    if (raw === saved.current || (!value.messages.length && !value.jd && !value.input && !value.materials.length)) return true;
    const recordId = currentId.current || crypto.randomUUID(); currentId.current = recordId; setId(recordId);
    const operation = (async () => {
      try {
        const response = await fetch(endpoint, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: recordId, revision: revision.current, snapshot: value }) });
        if (!response.ok) throw Error(response.status === 409 ? "这段对话已在其他窗口更新。请复制未保存的内容后刷新。" : "对话未保存，请重试。");
        const record = await response.json() as Conversation;
        if (epoch !== generation.current) return false;
        revision.current = record.revision; saved.current = raw; setError("");
        setEntries(prior => [record, ...prior.filter(item => item.id !== record.id)]);
        return true;
      } catch (e) { if (epoch === generation.current) setError(e instanceof Error ? e.message : "对话未保存，请重试。"); return false; }
    })();
    pending.current = operation;
    try { return await operation; } finally { if (pending.current === operation) pending.current = null; }
  }, []);
  const load = useCallback(async (recordId: string) => {
    const response = await fetch(`${endpoint}?id=${encodeURIComponent(recordId)}`, { cache: "no-store" });
    if (!response.ok) throw Error("暂时无法打开这段对话，请重试。");
    return await response.json() as Conversation & { snapshot: Snapshot };
  }, []);
  const open = async (recordId: string) => {
    if (!ready || busy || loading || recordId === currentId.current) return;
    setLoading(true); const epoch = generation.current;
    try {
      if (!await flush()) return;
      const record = await load(recordId);
      if (epoch === generation.current) adopt(record.id, record.snapshot, record.revision);
    } catch (e) { if (epoch === generation.current) setError((e as Error).message); }
    finally { if (epoch === generation.current) setLoading(false); }
  };
  const start = async (value: Snapshot) => {
    if (!ready || busy || loading) return false;
    setLoading(true); const epoch = generation.current;
    try { if (!await flush() || epoch !== generation.current) return false; adopt(crypto.randomUUID(), value, 0); return true; }
    finally { if (epoch === generation.current) setLoading(false); }
  };
  useEffect(() => {
    const reset = (event: Event) => {
      if ((event as CustomEvent<{ action: string }>).detail?.action === "model") return;
      generation.current++; currentId.current = ""; revision.current = 0; saved.current = "";
      setEntries([]); setId(""); setReady(false); setReload(value => value + 1); setLoading(false); setError("");
    };
    window.addEventListener("getoffers-account-changed", reset);
    return () => window.removeEventListener("getoffers-account-changed", reset);
  }, []);
  useEffect(() => {
    if (!active || ready) return;
    const epoch = generation.current; let cancelled = false;
    void (async () => {
      try {
        const response = await fetch(endpoint, { cache: "no-store" });
        if (response.status === 401) return;
        if (!response.ok) throw Error("历史对话读取失败，请重试。");
        const data = await response.json() as { conversations: Conversation[]; hasMore: boolean };
        const record = data.conversations[0] ? await load(data.conversations[0].id) : null;
        if (cancelled || epoch !== generation.current) return;
        setEntries(data.conversations); setHasMore(data.hasMore);
        if (record) adopt(record.id, record.snapshot, record.revision);
        setReady(true); setError("");
      } catch (e) { if (!cancelled && epoch === generation.current) setError((e as Error).message); }
      finally { if (!cancelled && epoch === generation.current) setLoading(false); }
    })();
    return () => { cancelled = true; };
  }, [active, ready, adopt, load, reload]);
  useEffect(() => {
    if (!ready || busy || loading) return;
    const timer = setTimeout(() => { void flush(); }, 600);
    return () => clearTimeout(timer);
  }, [snapshot, ready, busy, loading, flush]);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      const value = current.current;
      if (ready && (value.messages.length || value.input || value.jd || value.materials.length) && JSON.stringify(snapshotForStorage(value)) !== saved.current) { event.preventDefault(); event.returnValue = ""; }
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [ready]);
  async function more() {
    setLoading(true); const epoch = generation.current;
    try {
      const response = await fetch(`${endpoint}?offset=${entries.length}`); if (!response.ok) throw Error();
      const data = await response.json(); if (epoch !== generation.current) return;
      setEntries(prior => [...prior, ...data.conversations.filter((entry: Conversation) => !prior.some(item => item.id === entry.id))]); setHasMore(data.hasMore);
    } catch { setError("历史对话读取失败，请重试。"); }
    finally { if (epoch === generation.current) setLoading(false); }
  }
  return { entries, id, ready, loading: loading || (active && !ready && !error), error, hasMore, open, start, more, flush, retry: () => { if (ready) void flush(); else { setReady(false); setReload(value => value + 1); setError(""); } } };
}
