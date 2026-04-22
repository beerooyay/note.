import { getCurrentWindow, LogicalSize } from "@tauri-apps/api/window";
import { getCurrentWebviewWindow } from "@tauri-apps/api/webviewWindow";
import React from "react";

export const win = getCurrentWindow();
export const wv = getCurrentWebviewWindow();

export const resize = (dir: string) => (e: React.PointerEvent) => {
  e.preventDefault();
  (win as any).startResizeDragging(dir).catch(() => null);
};

export const expand = async (minH = 500) => {
  try {
    const s = await win.innerSize();
    const f = await win.scaleFactor();
    const w = s.width / f;
    const h = s.height / f;
    if (h < minH) await win.setSize(new LogicalSize(Math.max(w, 380), minH));
  } catch {}
};

export const setWindowSize = async (w: number, h: number) => {
  try { await win.setSize(new LogicalSize(w, h)); } catch {}
};
