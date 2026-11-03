"use client";

import { useState } from "react";
import { InlineScript } from "./inline-script";

const KEY = "finn:done";

function readDone(): string[] {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? "[]");
  } catch {
    return [];
  }
}

function writeDone(ids: string[]) {
  try {
    localStorage.setItem(KEY, JSON.stringify(ids));
  } catch {}
}

/**
 * One card the user can mark done (and undo). The state lives in localStorage;
 * DoneRestorer marks finished cards before paint, and the lazy initializer reads
 * the same key, so server HTML, DOM and React agree without a flash.
 */
export function CardShell({ id, label, children }: { id: string; label: string; children: React.ReactNode }) {
  const [done, setDone] = useState(() => typeof window !== "undefined" && readDone().includes(id));

  function set(value: boolean) {
    const ids = new Set(readDone());
    if (value) ids.add(id);
    else ids.delete(id);
    writeDone([...ids]);
    setDone(value);
  }

  return (
    <article className="card" data-card={id} data-done={done ? "" : undefined} suppressHydrationWarning>
      <div className="card-body">
        {children}
        <div className="card-actions">
          <button type="button" className="done-button" onClick={() => set(true)}>
            Done
          </button>
        </div>
      </div>
      <div className="card-collapsed">
        <span className="tick" aria-hidden="true">✓</span>
        <span className="collapsed-label">{label}</span>
        <button type="button" className="undo-button" onClick={() => set(false)}>
          Undo
        </button>
      </div>
    </article>
  );
}

export function DoneRestorer() {
  return (
    <InlineScript
      html={`(function(){try{var d=JSON.parse(localStorage.getItem("${KEY}")||"[]");d.forEach(function(id){var el=document.querySelector('[data-card="'+CSS.escape(id)+'"]');if(el)el.setAttribute("data-done","")})}catch(e){}})()`}
    />
  );
}
