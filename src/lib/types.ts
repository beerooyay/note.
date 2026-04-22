export const modes = ["chat", "code", "search", "generate"] as const;
export type Mode = typeof modes[number];

export type Stats = { inp: number; out: number; tps: number; sec: number };
export type Msg = { role: "user" | "assistant"; text: string; stats?: Stats };
export type Settings = {
  model: string;
  models: string[];
  root: string;
  webmode: string;
  cmdmode: string;
  convoId: number;
  memchunks: number;
};
export type Convo = {
  id: number;
  title: string;
  model: string;
  updated: number;
  inp: number;
  out: number;
};
export type Panel = "none" | "settings" | "history";
