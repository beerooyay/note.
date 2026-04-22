import { useState } from "react";
import { X, Pencil, Trash2, Check } from "lucide-react";
import type { Convo, Settings } from "../lib/types";
import { ago } from "../lib/time";

type HistoryProps = {
  convos: Convo[];
  onSelect: (id: number) => void;
  onRename: (id: number, title: string) => void;
  onDelete: (id: number) => void;
  onClose: () => void;
};

export function HistoryPanel({ convos, onSelect, onRename, onDelete, onClose }: HistoryProps) {
  const [editId, setEditId] = useState<number | null>(null);
  const [editText, setEditText] = useState("");
  const [confirmId, setConfirmId] = useState<number | null>(null);

  const startRename = (c: Convo) => { setEditId(c.id); setEditText(c.title || ""); setConfirmId(null); };
  const commitRename = () => {
    if (editId == null) return;
    const t = editText.trim();
    if (t) onRename(editId, t);
    setEditId(null);
    setEditText("");
  };

  return (
    <div className="panel">
      <div className="panel-head">
        <span>conversations</span>
        <button className="panel-close" onClick={onClose}><X size={14} /></button>
      </div>
      <div className="panel-body">
        {convos.length === 0 && <div className="panel-empty">no chats yet</div>}
        {convos.map((c) => (
          <div key={c.id} className="convo-row">
            <div className="convo-main" onClick={() => { if (editId !== c.id) onSelect(c.id); }}>
              {editId === c.id ? (
                <input
                  autoFocus
                  className="convo-edit"
                  value={editText}
                  onChange={(e) => setEditText(e.target.value)}
                  onClick={(e) => e.stopPropagation()}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") { e.preventDefault(); commitRename(); }
                    if (e.key === "Escape") { setEditId(null); setEditText(""); }
                  }}
                  onBlur={commitRename}
                />
              ) : (
                <div className="convo-title">{c.title || "untitled"}</div>
              )}
              <div className="convo-meta">{c.inp + c.out} tok · {c.model} · {ago(c.updated)}</div>
            </div>
            <div className="convo-actions" onClick={(e) => e.stopPropagation()}>
              {confirmId === c.id ? (
                <>
                  <button className="convo-act danger" onClick={() => { onDelete(c.id); setConfirmId(null); }} aria-label="confirm"><Check size={14} /></button>
                  <button className="convo-act" onClick={() => setConfirmId(null)} aria-label="cancel"><X size={14} /></button>
                </>
              ) : editId === c.id ? (
                <button className="convo-act" onClick={commitRename} aria-label="save"><Check size={14} /></button>
              ) : (
                <>
                  <button className="convo-act" onClick={() => startRename(c)} aria-label="rename"><Pencil size={14} /></button>
                  <button className="convo-act" onClick={() => { setConfirmId(c.id); setEditId(null); }} aria-label="delete"><Trash2 size={14} /></button>
                </>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

type SettingsProps = {
  settings: Settings;
  onSet: (key: string, value: string) => void;
  onPickFolder: () => void;
  onClose: () => void;
};

export function SettingsPanel({ settings, onSet, onPickFolder, onClose }: SettingsProps) {
  return (
    <div className="panel">
      <div className="panel-head">
        <span>settings</span>
        <button className="panel-close" onClick={onClose}><X size={14} /></button>
      </div>
      <div className="panel-body">
        <div className="setting-row">
          <label>model</label>
          <select value={settings.model} onChange={(e) => onSet("model", e.target.value)}>
            {settings.models.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </div>
        <div className="setting-row">
          <label>root</label>
          <div className="setting-val" title={settings.root}>{settings.root}</div>
          <button className="setting-btn" onClick={onPickFolder}>change</button>
        </div>
        <div className="setting-row">
          <label>web</label>
          <select value={settings.webmode} onChange={(e) => onSet("webmode", e.target.value)}>
            <option value="auto">auto</option>
            <option value="brave">brave</option>
            <option value="bing">bing</option>
          </select>
        </div>
        <div className="setting-row">
          <label>shell</label>
          <select value={settings.cmdmode} onChange={(e) => onSet("cmdmode", e.target.value)}>
            <option value="strict">strict</option>
            <option value="open">open</option>
          </select>
        </div>
        <div className="setting-row">
          <label>memory</label>
          <div className="setting-val">{settings.memchunks} chunks</div>
        </div>
      </div>
    </div>
  );
}
