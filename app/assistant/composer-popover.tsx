"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { X } from "lucide-react";

export default function ComposerPopover({ id, label, title = label, icon, open, onToggle, children, marked = false, menu = false, compact }: {
  id: string; label: string; title?: string; icon: ReactNode; open: boolean; onToggle: (open: boolean) => void; children: ReactNode; marked?: boolean; menu?: boolean; compact?: "materials" | "editor";
}) {
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const panel = root.current?.querySelector<HTMLElement>("[data-panel]");
    (panel?.querySelector<HTMLElement>("textarea, input, select") ?? panel?.querySelector<HTMLElement>("button"))?.focus();
    const close = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) onToggle(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") { onToggle(false); trigger.current?.focus(); } };
    document.addEventListener("pointerdown", close); document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("pointerdown", close); document.removeEventListener("keydown", escape); };
  }, [open, onToggle]);
  return <div ref={root} className={`assistant-tool${menu ? " assistant-tool--menu" : compact ? ` assistant-tool--${compact}` : ""}`}>
    <button ref={trigger} type="button" className="assistant-tool-trigger" aria-label={label} title={label} aria-expanded={open} aria-controls={id} aria-haspopup={menu ? "menu" : undefined} onClick={() => onToggle(!open)}>{icon}{marked && <span className="assistant-tool-dot" />}</button>
    {open && <section id={id} data-panel className="assistant-tool-panel" aria-label={title}>
      {!menu && !compact && <header><strong>{title}</strong><button type="button" aria-label={`收起${title}`} onClick={() => { onToggle(false); trigger.current?.focus(); }}><X size={16} /></button></header>}
      {children}
    </section>}
  </div>;
}
