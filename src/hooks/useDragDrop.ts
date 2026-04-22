import { useEffect, useState } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";

export type FileCard = {
  id: string;
  name: string;
  path: string;
  size: number;
  type: string;
};

type DropByPaths = (paths: string[]) => Promise<FileCard[] | void> | FileCard[] | void;

export const useDragDrop = (ondrop?: DropByPaths) => {
  const [isDragging, setIsDragging] = useState(false);
  const [fileCards, setFileCards] = useState<FileCard[]>([]);
  const [windowMode, setWindowMode] = useState<"compact" | "expanded">("compact");

  useEffect(() => {
    const win = getCurrentWindow();
    let unlisten: (() => void) | undefined;
    (async () => {
      unlisten = await win.onDragDropEvent(async (event) => {
        const p = event.payload as { type: string; paths?: string[] };
        if (p.type === "enter" || p.type === "over") {
          setIsDragging(true);
          setWindowMode("expanded");
        } else if (p.type === "leave") {
          setIsDragging(false);
        } else if (p.type === "drop") {
          setIsDragging(false);
          const paths = p.paths || [];
          if (!paths.length) return;
          const next = (await ondrop?.(paths)) || [];
          if (next.length) {
            setWindowMode("expanded");
            setFileCards((prev) => [...prev, ...next]);
          }
        }
      });
    })();
    return () => { if (unlisten) unlisten(); };
  }, [ondrop]);

  return { isDragging, fileCards, setFileCards, windowMode, setWindowMode };
};
