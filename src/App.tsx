import { useCallback, useRef, useState } from "react";
import "./App.css";
import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { LogicalSize } from "@tauri-apps/api/window";

import { win, expand } from "./lib/tauri";
import type { Mode, Msg, Settings, Convo, Panel } from "./lib/types";

import { useDragDrop, FileCard } from "./hooks/useDragDrop";
import { useBackend } from "./hooks/useBackend";
import { useZoom, useFold } from "./hooks/useWindowFold";

import { TrafficLights } from "./components/TrafficLights";
import { ResizeEdges } from "./components/ResizeEdges";
import { Mast } from "./components/Mast";
import { Chatlog } from "./components/Chatlog";
import { Composer } from "./components/Composer";
import { HistoryPanel, SettingsPanel } from "./components/Panels";
import { FileGrid } from "./components/FileGrid";

const peekh = 420;

export default function App() {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Msg[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<Mode>("chat");
  const [panel, setPanel] = useState<Panel>("none");
  const [settings, setSettings] = useState<Settings | null>(null);
  const [convos, setConvos] = useState<Convo[]>([]);
  const [convertFor, setConvertFor] = useState<string | null>(null);
  const [convertTargets, setConvertTargets] = useState<string[]>([]);
  const [cardStatus, setCardStatus] = useState<Record<string, string>>({});

  const taRef = useRef<HTMLTextAreaElement | null>(null);
  const mastRef = useRef<HTMLDivElement | null>(null);
  const composerRef = useRef<HTMLDivElement | null>(null);

  const zoom = useZoom();
  const fold = useFold(mastRef, composerRef, zoom);

  const { isDragging, fileCards, setFileCards, windowMode, setWindowMode } = useDragDrop(
    async (paths) => {
      if (!paths.length) return;
      try { return await invoke<FileCard[]>("ingest_files", { paths }); } catch { return; }
    }
  );

  useBackend({
    onToken: (d) => { setDraft(d); setBusy(true); },
    onDone: (text, stats) => {
      setDraft("");
      setBusy(false);
      if (text) setMessages((m) => [...m, { role: "assistant", text, stats }]);
    },
    onError: (err) => setMessages((m) => [...m, { role: "assistant", text: err }]),
    onSettings: setSettings,
    onConvos: setConvos,
    onLoaded: (turns) => {
      setMessages(turns);
      setPanel("none");
      setWindowMode("expanded");
      void expand();
    },
  });

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || busy) return;
    setMessages((m) => [...m, { role: "user", text }]);
    setInput("");
    if (taRef.current) taRef.current.style.height = "";
    setDraft("");
    setBusy(true);
    setWindowMode("expanded");
    void expand();
    try { await invoke("send_message", { message: text }); }
    catch (err) {
      setBusy(false);
      setMessages((m) => [...m, { role: "assistant", text: `send failed: ${String(err)}` }]);
    }
  }, [input, busy, setWindowMode]);

  const reset = useCallback(async () => {
    setInput("");
    setDraft("");
    setMessages([]);
    setFileCards([]);
    setWindowMode("compact");
    try { await invoke("new_convo"); } catch {}
  }, [setFileCards, setWindowMode]);

  const pickFolder = useCallback(async () => {
    try {
      const picked = await open({ directory: true, multiple: false });
      if (typeof picked === "string") await invoke("set_root", { path: picked });
    } catch {}
  }, []);

  const pickFiles = useCallback(async () => {
    try {
      const picked = await open({ multiple: true });
      if (!picked) return;
      const arr = Array.isArray(picked) ? picked : [picked];
      if (!arr.length) return;
      const next = await invoke<FileCard[]>("ingest_files", { paths: arr });
      if (next.length) { setFileCards((p) => [...p, ...next]); setWindowMode("expanded"); void expand(); }
    } catch {}
  }, [setFileCards, setWindowMode]);

  const openHistory = useCallback(async () => {
    setPanel("history");
    void expand(560);
    try { await invoke("list_convos"); } catch {}
  }, []);

  const openSettings = useCallback(async () => {
    setPanel("settings");
    void expand(560);
    try { await invoke("get_settings"); } catch {}
  }, []);

  const openChat = useCallback(async () => {
    setPanel("none");
    setWindowMode("expanded");
    try {
      const s = await win.innerSize();
      const f = await win.scaleFactor();
      const w = s.width / f;
      await win.setSize(new LogicalSize(Math.max(w, 380), peekh));
    } catch {}
  }, [setWindowMode]);

  const onSearch = useCallback(() => {
    setInput((v) => (v.startsWith("/search ") ? v : "/search " + v));
    taRef.current?.focus();
  }, []);

  const dismissCard = useCallback((id: string) => {
    setFileCards((p) => p.filter((c) => c.id !== id));
    if (convertFor === id) { setConvertFor(null); setConvertTargets([]); }
    setCardStatus((s) => { const { [id]: _, ...rest } = s; return rest; });
  }, [convertFor, setFileCards]);

  const compressCard = useCallback(async (c: FileCard) => {
    if (busy || !c.path) return;
    setCardStatus((s) => ({ ...s, [c.id]: "compressing..." }));
    try {
      const next = await invoke<FileCard[]>("run_compress", { files: [{ path: c.path, type: c.type }] });
      if (next.length) {
        setFileCards((p) => [...p, ...next]);
        setCardStatus((s) => ({ ...s, [c.id]: `done: ${next[0].name}` }));
      }
    } catch (err) {
      setCardStatus((s) => ({ ...s, [c.id]: `error: ${String(err)}` }));
    }
  }, [busy, setFileCards]);

  const startConvert = useCallback(async (c: FileCard) => {
    if (convertFor === c.id) { setConvertFor(null); setConvertTargets([]); return; }
    try {
      const targets = await invoke<string[]>("convert_targets", { kind: c.type });
      setConvertFor(c.id);
      setConvertTargets(targets);
    } catch {
      setConvertTargets([]);
    }
  }, [convertFor]);

  const runConvert = useCallback(async (target: string) => {
    const card = fileCards.find((c) => c.id === convertFor);
    if (!card) return;
    setConvertFor(null);
    setConvertTargets([]);
    setCardStatus((s) => ({ ...s, [card.id]: `converting to ${target}...` }));
    try {
      const next = await invoke<FileCard[]>("run_convert", { files: [{ path: card.path, type: card.type, target }] });
      if (next.length) {
        setFileCards((p) => [...p, ...next]);
        setCardStatus((s) => ({ ...s, [card.id]: `done: ${next[0].name}` }));
      }
    } catch (err) {
      setCardStatus((s) => ({ ...s, [card.id]: `error: ${String(err)}` }));
    }
  }, [convertFor, fileCards, setFileCards]);

  const cancelConvert = useCallback(() => {
    setConvertFor(null);
    setConvertTargets([]);
  }, []);

  const setSetting = useCallback(async (key: string, value: string) => {
    try { await invoke("set_setting", { key, value }); } catch {}
  }, []);

  const renameConvo = useCallback(async (id: number, title: string) => {
    try { await invoke("rename_convo", { id, title }); } catch {}
  }, []);

  const deleteConvo = useCallback(async (id: number) => {
    try { await invoke("delete_convo", { id }); } catch {}
  }, []);

  const selectConvo = useCallback(async (id: number) => {
    try { await invoke("load_convo", { id }); } catch {}
  }, []);

  const hasChat = messages.length > 0 || !!draft.trim();
  const hasFiles = fileCards.length > 0;
  const showExpand = fold && (hasChat || hasFiles);

  return (
    <div className="window-drag" data-mode={windowMode} data-fold={fold ? "yes" : "no"}>
      <div className="topbar" data-tauri-drag-region>
        <TrafficLights />
      </div>
      <ResizeEdges />
      {isDragging && <div className="drop-overlay"><div className="drop-hint">drop to note</div></div>}
      <div className="container" data-tauri-drag-region>
        <Mast
          ref={mastRef}
          fold={fold}
          showExpand={showExpand}
          onPickFolder={pickFolder}
          onSearch={onSearch}
          onHistory={openHistory}
          onReset={reset}
          onSettings={openSettings}
          onExpand={openChat}
        />
        {!fold && panel === "history" && (
          <HistoryPanel
            convos={convos}
            onSelect={selectConvo}
            onRename={renameConvo}
            onDelete={deleteConvo}
            onClose={() => setPanel("none")}
          />
        )}
        {!fold && panel === "settings" && settings && (
          <SettingsPanel
            settings={settings}
            onSet={setSetting}
            onPickFolder={pickFolder}
            onClose={() => setPanel("none")}
          />
        )}
        {!fold && panel === "none" && (hasChat || busy) && (
          <Chatlog messages={messages} draft={draft} busy={busy} />
        )}
        {hasFiles && (
          <FileGrid
            cards={fileCards}
            status={cardStatus}
            convertFor={convertFor}
            busy={busy}
            onDismiss={dismissCard}
            onCompress={compressCard}
            onStartConvert={startConvert}
          />
        )}
        <Composer
          ref={composerRef}
          textareaRef={taRef}
          fold={fold}
          input={input}
          setInput={setInput}
          mode={mode}
          setMode={setMode}
          onSend={send}
          onPickFiles={pickFiles}
          busy={busy}
          convertFor={convertFor}
          convertTargets={convertTargets}
          onRunConvert={runConvert}
          onCancelConvert={cancelConvert}
        />
      </div>
    </div>
  );
}
