import { resize } from "../lib/tauri";

export function ResizeEdges() {
  return (
    <>
      <div className="resize-edge left" onPointerDown={resize("West")} />
      <div className="resize-edge right" onPointerDown={resize("East")} />
      <div className="resize-edge bottom" onPointerDown={resize("South")} />
      <div className="resize-grip" onPointerDown={resize("SouthEast")} />
    </>
  );
}
