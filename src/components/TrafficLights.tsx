import { X, Minus, Maximize2 } from "lucide-react";
import { win } from "../lib/tauri";

export function TrafficLights() {
  return (
    <div className="traffic-lights">
      <button className="tl" onClick={() => win.close()} aria-label="close"><X size={8} /></button>
      <button className="tl" onClick={() => win.minimize()} aria-label="minimize"><Minus size={8} /></button>
      <button className="tl" onClick={() => win.toggleMaximize()} aria-label="zoom"><Maximize2 size={7} /></button>
    </div>
  );
}
