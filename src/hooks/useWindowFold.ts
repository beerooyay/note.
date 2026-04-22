import { useEffect, useRef, useState, RefObject } from "react";
import { LogicalSize } from "@tauri-apps/api/window";
import { win, wv } from "../lib/tauri";

export function useZoom() {
  const [zoom, setZoom] = useState<number>(() => {
    const v = parseFloat(localStorage.getItem("note.zoom") || "1");
    return isFinite(v) && v > 0 ? v : 1;
  });
  const baseline = useRef<{ w: number; h: number } | null>(null);
  const last = useRef<number>(zoom);

  useEffect(() => {
    localStorage.setItem("note.zoom", String(zoom));
    const prev = last.current;
    (async () => {
      try { await wv.setZoom(zoom); } catch {}
      if (prev === zoom) return;
      last.current = zoom;
      try {
        if (!baseline.current) {
          const s = await win.innerSize();
          const f = await win.scaleFactor();
          baseline.current = { w: s.width / f / prev, h: s.height / f / prev };
        }
        const b = baseline.current;
        await win.setSize(new LogicalSize(Math.max(360, b.w * zoom), Math.max(188, b.h * zoom)));
      } catch {}
    })();
  }, [zoom]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey)) return;
      if (e.key === "=" || e.key === "+") { e.preventDefault(); setZoom((z) => Math.min(1.6, +(z + 0.1).toFixed(2))); }
      else if (e.key === "-" || e.key === "_") { e.preventDefault(); setZoom((z) => Math.max(0.7, +(z - 0.1).toFixed(2))); }
      else if (e.key === "0") { e.preventDefault(); setZoom(1); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return zoom;
}

export function useFold(
  mastRef: RefObject<HTMLElement>,
  composerRef: RefObject<HTMLElement>,
  zoom: number
) {
  const [foldh, setFoldh] = useState(340);
  const [fold, setFold] = useState(false);

  useEffect(() => {
    const measure = () => {
      const m = mastRef.current;
      const c = composerRef.current;
      if (!m || !c) return;
      setFoldh(32 + 10 + m.offsetHeight + 12 + c.offsetHeight + 20);
    };
    measure();
    const ro = new ResizeObserver(measure);
    if (mastRef.current) ro.observe(mastRef.current);
    if (composerRef.current) ro.observe(composerRef.current);
    return () => ro.disconnect();
  }, [zoom, mastRef, composerRef]);

  useEffect(() => {
    const sync = async () => {
      try {
        await win.setMinSize(new LogicalSize(360, 188));
        const s = await win.innerSize();
        const f = await win.scaleFactor();
        setFold(s.height / f <= foldh);
      } catch {}
    };
    void sync();
    let off: (() => void) | undefined;
    win.onResized(async ({ payload }) => {
      try {
        const f = await win.scaleFactor();
        setFold(payload.height / f <= foldh);
      } catch {}
    }).then((u) => { off = u; }).catch(() => null);
    return () => off?.();
  }, [foldh]);

  return fold;
}
