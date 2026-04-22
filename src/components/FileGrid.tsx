import { memo } from "react";
import { X } from "lucide-react";
import { convertFileSrc } from "@tauri-apps/api/core";
import type { FileCard } from "../hooks/useDragDrop";

type Props = {
  cards: FileCard[];
  status: Record<string, string>;
  convertFor: string | null;
  busy: boolean;
  onDismiss: (id: string) => void;
  onCompress: (c: FileCard) => void;
  onStartConvert: (c: FileCard) => void;
};

const CONVERTIBLE = new Set(["image", "pdf", "text", "office", "audio", "video"]);
const COMPRESSIBLE = new Set(["image", "pdf", "audio", "video"]);

export const FileGrid = memo(function FileGrid({
  cards, status, convertFor, busy,
  onDismiss, onCompress, onStartConvert,
}: Props) {
  return (
    <div className="file-grid">
      {cards.map((c) => {
        const isImage = c.type === "image";
        const canConvert = CONVERTIBLE.has(c.type);
        const canCompress = COMPRESSIBLE.has(c.type);
        const st = status[c.id];
        return (
          <div key={c.id} className="file-card">
            <button className="file-x" onClick={() => onDismiss(c.id)} aria-label="dismiss"><X size={12} /></button>
            {isImage && c.path ? (
              <img className="file-thumbnail img" src={convertFileSrc(c.path)} alt={c.name} />
            ) : (
              <div className="file-thumbnail">{c.name.split(".").pop()}</div>
            )}
            <div className="file-name" title={c.name}>{c.name}</div>
            <div className="file-meta">{Math.round(c.size / 1024)}kb · {c.type}</div>
            {st && <div className="file-status">{st}</div>}
            <div className="file-card-actions">
              <button
                className="action-button"
                disabled={!canConvert || busy}
                onClick={() => onStartConvert(c)}
              >{convertFor === c.id ? "pick format" : "convert"}</button>
              <button
                className="action-button"
                disabled={!canCompress || busy}
                onClick={() => onCompress(c)}
              >compress</button>
            </div>
          </div>
        );
      })}
    </div>
  );
});
