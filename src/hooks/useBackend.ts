import { useEffect, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import type { Msg, Stats, Settings, Convo } from "../lib/types";

type Handlers = {
  onToken: (tok: string) => void;
  onDone: (text: string, stats?: Stats) => void;
  onError: (err: string) => void;
  onSettings: (s: Settings) => void;
  onConvos: (c: Convo[]) => void;
  onLoaded: (turns: Msg[]) => void;
};

export function useBackend(h: Handlers) {
  const ref = useRef(h);
  ref.current = h;

  useEffect(() => {
    invoke("start_chat_backend").catch((err) =>
      ref.current.onError(`backend start failed: ${String(err)}`)
    );
    let draft = "";
    let stats: Stats | undefined;

    const offs = Promise.all([
      listen<string>("chat:token", (e) => {
        draft += e.payload;
        ref.current.onToken(draft);
      }),
      listen<string>("chat:stats", (e) => {
        try { stats = JSON.parse(e.payload); } catch {}
      }),
      listen("chat:done", () => {
        const text = draft.trim();
        const s = stats;
        draft = "";
        stats = undefined;
        ref.current.onDone(text, s);
      }),
      listen<string>("chat:err", (e) => {
        if (e.payload.trim()) ref.current.onError(`backend: ${e.payload}`);
      }),
      listen<string>("chat:settings", (e) => {
        try { ref.current.onSettings(JSON.parse(e.payload)); } catch {}
      }),
      listen<string>("chat:convos", (e) => {
        try { ref.current.onConvos(JSON.parse(e.payload)); } catch {}
      }),
      listen<string>("chat:loaded", (e) => {
        try {
          const data = JSON.parse(e.payload);
          const turns: Msg[] = (data.turns || []).map((t: any) => ({ role: t.role, text: t.content }));
          ref.current.onLoaded(turns);
        } catch {}
      }),
    ]);
    return () => {
      offs.then((list) => list.forEach((u) => u()));
      invoke("stop_chat_backend").catch(() => null);
    };
  }, []);
}
