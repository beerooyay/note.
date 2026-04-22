import { memo, useEffect, useMemo, useRef, useState } from "react";
import { md } from "../lib/markdown";
import type { Msg } from "../lib/types";

const frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏";

function Spinner() {
  const [i, setI] = useState(0);
  useEffect(() => {
    const id = window.setInterval(() => setI((v) => (v + 1) % frames.length), 80);
    return () => window.clearInterval(id);
  }, []);
  return (
    <div className="thinking">
      <span>thinking</span>
      <span className="thinking-frame">{frames[i]}</span>
    </div>
  );
}

const Bubble = memo(function Bubble({ m }: { m: Msg }) {
  const html = useMemo(() => (m.role === "assistant" ? md(m.text) : ""), [m.role, m.text]);
  return (
    <div className={`bubble ${m.role}`}>
      {m.role === "assistant"
        ? <div className="md" dangerouslySetInnerHTML={{ __html: html }} />
        : m.text}
      {m.stats && (
        <div className="stats">
          {m.stats.inp}in · {m.stats.out}out · {m.stats.tps}tps · {m.stats.sec}s
        </div>
      )}
    </div>
  );
});

type Props = { messages: Msg[]; draft: string; busy: boolean };

export function Chatlog({ messages, draft, busy }: Props) {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, draft, busy]);

  return (
    <div className="chatlog" ref={ref}>
      {messages.map((m, i) => <Bubble key={i} m={m} />)}
      {draft.trim() && <div className="bubble assistant">{draft}</div>}
      {busy && !draft && <Spinner />}
    </div>
  );
}
