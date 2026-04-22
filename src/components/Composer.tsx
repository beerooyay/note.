import { forwardRef, MutableRefObject, useEffect, useState } from "react";
import { Plus, ImageIcon, ArrowUp, ChevronDown } from "lucide-react";
import { modes, type Mode } from "../lib/types";

type Props = {
  fold: boolean;
  input: string;
  setInput: (v: string) => void;
  mode: Mode;
  setMode: (m: Mode) => void;
  onSend: () => void;
  onPickFiles: () => void;
  busy: boolean;
  convertFor: string | null;
  convertTargets: string[];
  onRunConvert: (target: string) => void;
  onCancelConvert: () => void;
  textareaRef: MutableRefObject<HTMLTextAreaElement | null>;
};

export const Composer = forwardRef<HTMLDivElement, Props>(function Composer(
  {
    fold, input, setInput, mode, setMode,
    onSend, onPickFiles, busy,
    convertFor, convertTargets, onRunConvert, onCancelConvert,
    textareaRef,
  },
  ref
) {
  const [modeOpen, setModeOpen] = useState(false);

  useEffect(() => {
    if (!modeOpen) return;
    const h = () => setModeOpen(false);
    window.addEventListener("pointerdown", h);
    return () => window.removeEventListener("pointerdown", h);
  }, [modeOpen]);

  return (
    <div className={`composer${fold ? " hidden" : ""}`} aria-hidden={fold} ref={ref}>
      <div className="composer-top">
        <textarea
          ref={textareaRef}
          value={input}
          rows={1}
          onChange={(e) => {
            setInput(e.target.value);
            const el = e.currentTarget;
            el.style.height = "auto";
            el.style.height = Math.min(el.scrollHeight, 72) + "px";
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onSend(); }
          }}
          placeholder="to explore, type /note"
        />
      </div>
      <div className="composer-bottom">
        <div className="mode-wrap">
          {convertFor ? (
            <>
              <button
                className="model-select converting"
                onClick={(e) => { e.stopPropagation(); setModeOpen((v) => !v); }}
                aria-expanded={modeOpen}
              >convert to <ChevronDown size={16} /></button>
              {modeOpen && (
                <div className="mode-menu" onPointerDown={(e) => e.stopPropagation()}>
                  {convertTargets.length === 0 && <div className="mode-item muted">no targets</div>}
                  {convertTargets.map((t) => (
                    <button
                      key={t}
                      className="mode-item"
                      onClick={() => { setModeOpen(false); onRunConvert(t); }}
                    >{t}</button>
                  ))}
                  <button
                    className="mode-item muted"
                    onClick={() => { setModeOpen(false); onCancelConvert(); }}
                  >cancel</button>
                </div>
              )}
            </>
          ) : (
            <>
              <button
                className="model-select"
                onClick={(e) => { e.stopPropagation(); setModeOpen((v) => !v); }}
                aria-expanded={modeOpen}
              >{mode} <ChevronDown size={16} /></button>
              {modeOpen && (
                <div className="mode-menu" onPointerDown={(e) => e.stopPropagation()}>
                  {modes.map((m) => (
                    <button
                      key={m}
                      className={`mode-item ${m === mode ? "active" : ""}`}
                      onClick={() => { setMode(m); setModeOpen(false); }}
                    >{m}</button>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
        <div className="input-buttons">
          <button className="icon-button" onClick={onPickFiles} aria-label="attach files"><Plus size={16} /></button>
          <button className="icon-button" aria-label="image (soon)" disabled><ImageIcon size={16} /></button>
          <button
            className="icon-button sendicon"
            onClick={onSend}
            aria-label="send"
            disabled={busy || !input.trim()}
          ><ArrowUp size={16} /></button>
        </div>
      </div>
    </div>
  );
});
