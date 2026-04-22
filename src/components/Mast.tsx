import { forwardRef } from "react";
import { FolderOpen, Search, Clock, Plus, MoreHorizontal, ChevronDown } from "lucide-react";

type Props = {
  fold: boolean;
  showExpand: boolean;
  onPickFolder: () => void;
  onSearch: () => void;
  onHistory: () => void;
  onReset: () => void;
  onSettings: () => void;
  onExpand: () => void;
};

export const Mast = forwardRef<HTMLDivElement, Props>(function Mast(
  { fold, showExpand, onPickFolder, onSearch, onHistory, onReset, onSettings, onExpand },
  ref
) {
  return (
    <div className="mast" data-tauri-drag-region ref={ref}>
      <div className="wordmark" data-tauri-drag-region>
        <img src="/note.svg" alt="note" draggable={false} />
      </div>
      <div className="toolbar">
        <div className="tools">
          <button className="tool" onClick={onPickFolder} aria-label="root"><FolderOpen className="icon" /></button>
          <button className="tool" onClick={onSearch} aria-label="search" title="search"><Search className="icon" /></button>
          <button className="tool" onClick={onHistory} aria-label="history"><Clock className="icon" /></button>
          <button className="tool" onClick={onReset} aria-label="new chat"><Plus className="icon" /></button>
          <button className="tool" onClick={onSettings} aria-label="settings"><MoreHorizontal className="icon" /></button>
          <button
            className={`tool tool-expand${fold && showExpand ? " visible" : ""}`}
            onClick={onExpand}
            aria-label="expand chat"
            tabIndex={fold && showExpand ? 0 : -1}
          ><ChevronDown className="icon" /></button>
        </div>
      </div>
    </div>
  );
});
