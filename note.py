#!/usr/bin/env python3
import html
import glob
import json
import os
import re
import select
import shlex
import sqlite3
import subprocess
import sys
import termios
import threading
import time
import tty
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

import numpy as np

HOST = "127.0.0.1"
PORT = 8080
BASE = f"http://{HOST}:{PORT}"
APPROOT = os.path.dirname(os.path.abspath(__file__))
RUNTIMEDIR = os.path.join(APPROOT, ".note")
LOGDIR = os.path.join(RUNTIMEDIR, "logs")
MODELS = {
    "qwen": "mlx-community/Qwen3.6-35B-A3B-4bit",
    "gemma": "/Users/beerooyay/models/mlx/gemma-4-31b-it-mxfp4",
    "speed": "/Users/beerooyay/models/mlx/gemma-4-26b-a4b-it-4bit",
}
MODELORDER = ["qwen", "gemma", "speed"]
MODELKEY = "qwen"
MODEL = MODELS[MODELKEY]
LOG = os.path.join(LOGDIR, "note-server.log")
READMAX = 12000
OUTMAX = 14000
SERVERPY_CANDIDATES = [
    os.environ.get("GEMCHAT_PYTHON", ""),
    "/Library/Frameworks/Python.framework/Versions/3.12/Resources/Python.app/Contents/MacOS/Python",
    sys.executable,
    "python3.12",
    "python3",
]
MAXTOKENS = 500
MAXTOOLROUNDS = 8
MAXKV = 16384
CTXSOFT = 0.60
CTXHARD = 0.80
KEEPRECENT = 18
MEMMAXCHARS = 6000
MEMDB = os.path.join(RUNTIMEDIR, "memory.sqlite3")
EMBEDMODEL = "Qwen/Qwen3-Embedding-0.6B"
EMBEDBATCH = 32
MEMTOPK = 3
KVBITS = "4"
KVSCHEME = "turboquant"
KVSTART = "1024"
ALLOWROOT = APPROOT
WEBMODE = "auto"
CMDTIMEOUT = 30
CMDMODE = "strict"
CMDALLOW = {
    "git",
    "rg",
    "ls",
    "cat",
    "pwd",
    "echo",
    "head",
    "tail",
    "wc",
    "python",
    "python3",
    "pytest",
}

SYSTEM = (
    "your name is note, and your user's name is blaize. "
    "you stay lowercase. be concise, useful, and real. "
    "tone is chill + grounded with occasional hype when it fits. "
    "be conversational and curious, not lecture-y. "
    "for task execution, be agentic: plan lightly, act, verify, and report clearly. "
    "when steps help, use short numbered lists. keep walls of text out. "
    "for ambiguity, ask one sharp question only if needed.")

TOOLSPEC = (
    "you can use tools. if a tool is needed, reply with only one json object and no extra text.\n"
    "tool json formats:\n"
    '{"tool":"read","path":"<path>"}\n'
    '{"tool":"write","path":"<path>","content":"<text>","mode":"overwrite"}\n'
    '{"tool":"write","path":"<path>","content":"<text>","mode":"append"}\n'
    '{"tool":"list","path":"<dir>"}\n'
    '{"tool":"search","path":"<dir>","pattern":"<regex>","glob":"<optional glob>"}\n'
    '{"tool":"edit","path":"<path>","find":"<old text>","replace":"<new text>","all":false}\n'
    '{"tool":"websearch","query":"<query>","n":5,"source":"auto|brave|bing"}\n'
    '{"tool":"command","cmd":"<shell command>","cwd":"<optional dir>"}\n'
    "after a tool result is returned, continue normally."
)

SYSTEM = SYSTEM + "\n\n" + TOOLSPEC
BING_LINK_RE = re.compile(
    r'<li class="b_algo".*?<h2><a href="([^"]+)"[^>]*>(.*?)</a>',
    flags=re.IGNORECASE | re.DOTALL,
)
BING_RSS_ITEM_RE = re.compile(
    r"<item>.*?<title>(.*?)</title>.*?<link>(.*?)</link>.*?</item>",
    flags=re.IGNORECASE | re.DOTALL,
)
BRAVEKEY = os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()
USINGTTY = sys.stdout.isatty()
RESET = "\033[0m" if USINGTTY else ""
BOLD = "\033[1m" if USINGTTY else ""
ITALIC = "\033[3m" if USINGTTY else ""
DIM = "\033[2m" if USINGTTY else ""
GREY = "\033[90m" if USINGTTY else ""
CYAN = "\033[38;2;44;200;232m" if USINGTTY else ""
NOTEPREFIX = f"{BOLD}{CYAN}note{RESET} > "
YOUPREFIX = f"{BOLD}{CYAN}you{RESET} > "
MEMPREFIX = "conversation memory (condensed): "
RAGPREFIX = "relevant indexed memory: "
MEMAUTO = False
EMBEDDER = {"tok": None, "mdl": None}


def jget(path: str):
    req = urllib.request.Request(f"{BASE}{path}", method="GET")
    with urllib.request.urlopen(req, timeout=2) as r:
        return json.loads(r.read().decode("utf-8"))


def jpost(path: str, payload: dict):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read().decode("utf-8"))


def health():
    try:
        return jget("/health")
    except Exception:
        return None


def server_loaded_model():
    h = health()
    return h.get("loaded_model") if h and h.get("status") == "healthy" else None


def stop_server():
    try:
        pids = (
            subprocess.run(
                ["lsof", "-ti", f"tcp:{PORT}"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            .stdout.strip()
            .splitlines()
        )
        for pid in pids:
            if pid.strip():
                subprocess.run(["kill", pid.strip()], timeout=3)
    except Exception:
        pass


def pickserverpy():
    for cand in SERVERPY_CANDIDATES:
        if not cand:
            continue
        try:
            proc = subprocess.run(
                [cand, "-c", "import mlx_vlm; print('ok')"],
                capture_output=True,
                text=True,
                timeout=20,
            )
            if proc.returncode == 0:
                return cand
        except Exception:
            pass
    raise RuntimeError("no python with mlx_vlm found. set GEMCHAT_PYTHON to a valid interpreter")

def start_server_if_needed(showstatus=False):
    loaded = server_loaded_model()
    if loaded == MODEL:
        return
    if loaded and loaded != MODEL:
        stop_server()
        time.sleep(1)

    if showstatus:
        print("starting local mlx server...")
    os.makedirs(LOGDIR, exist_ok=True)
    subprocess.Popen(
        [
            pickserverpy(),
            "-m",
            "mlx_vlm.server",
            "--host",
            HOST,
            "--port",
            str(PORT),
            "--model",
            MODEL,
            "--max-kv-size",
            str(MAXKV),
            "--kv-bits",
            KVBITS,
            "--kv-quant-scheme",
            KVSCHEME,
            "--quantized-kv-start",
            KVSTART,
        ],
        stdout=open(LOG, "a"),
        stderr=subprocess.STDOUT,
    )

    for _ in range(90):
        if (h := health()) and h.get("status") == "healthy":
            return
        time.sleep(1)

    raise RuntimeError(f"server did not come up. check logs: {LOG}")


class spinner:
    def __init__(self, label="thinking", prefix=""):
        self.label = label
        self.prefix = prefix
        self.stop = threading.Event()
        self.t = None
        self.lastlen = 0

    def _run(self):
        frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        i = 0
        while not self.stop.is_set():
            txt = f"{self.prefix}{DIM}{GREY}{self.label}{RESET} {CYAN}{frames[i % len(frames)]}{RESET}"
            self.lastlen = len(f"{self.prefix}{self.label} {frames[i % len(frames)]}")
            sys.stdout.write(f"\r{txt}")
            sys.stdout.flush()
            i += 1
            time.sleep(0.08)
        sys.stdout.write("\r" + " " * max(40, self.lastlen) + "\r")
        sys.stdout.flush()

    def __enter__(self):
        self.t = threading.Thread(target=self._run, daemon=True)
        self.t.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.stop.set()
        if self.t:
            self.t.join(timeout=0.3)


class liveblock:
    def __init__(self):
        self.lines = 0

    def draw(self, rows):
        if not USINGTTY:
            print("\n".join(rows))
            self.lines = 0
            return
        if self.lines:
            for _ in range(self.lines - 1):
                sys.stdout.write("\033[F")
            sys.stdout.write("\r")
        for i, row in enumerate(rows):
            sys.stdout.write("\033[2K" + row)
            if i < len(rows) - 1:
                sys.stdout.write("\n")
        sys.stdout.flush()
        self.lines = len(rows)

    def done(self, gap=1):
        if USINGTTY:
            sys.stdout.write("\n" * max(0, int(gap)))
            sys.stdout.flush()
        else:
            print()
        self.lines = 0


def commandhelp():
    return [
        "commands:",
        "/tools - what i can do besides chat",
        "/models - change the model",
        "/today - timeline grounding (months/weeks/days to now)",
        "/search - web search (auto uses brave, fallback bing)",
        "/news - news search via brave",
        "/research - fan-out grounded research synthesis",
        "/suggest - brave query suggestions",
        "/spellcheck - brave query correction hint",
        "/webmode - choose web search source (auto|brave|bing)",
        "/memindex - embed files into sqlite memory (glob pattern)",
        "/memfind - semantic search in indexed memory",
        "/memauto - toggle auto memory retrieval (on|off)",
        "/memclear - clear indexed memory db",
        "/memstatus - memory db + retrieval status",
        "/project - quick project/runtime status",
        "/now - show local date + time",
        "/reset - clear the chat",
        "/system - show file access + command permissions",
        "/root - change the working directory root",
        "/quit - leave note",
    ]


def drawsplash(box, status, frame="", selected=None, compact=False):
    mark = f"{CYAN}{frame}{RESET}" if frame else f"{CYAN}•{RESET}"
    rows = [f"{mark} {status}"]
    if not compact:
        rows.append(f"{DIM}{GREY}select model:{RESET}")
    for name in MODELORDER:
        if name == selected:
            rows.append(f"{CYAN}{BOLD}> {name}{RESET}")
        else:
            rows.append(f"{GREY}  {name}{RESET}")
    if not compact:
        rows.append(f"{DIM}{GREY}use ↑/↓ then enter{RESET}")
    box.draw(rows)


def pickmodel(initial, compact=False):
    if not USINGTTY:
        return initial, liveblock()
    box = liveblock()
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    idx = MODELORDER.index(initial) if initial in MODELORDER else 0
    frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    tick = 0
    try:
        tty.setcbreak(fd)
        while True:
            status = "choose model" if compact else "opening note *"
            drawsplash(box, status, frames[tick % len(frames)], MODELORDER[idx], compact=compact)
            tick += 1
            ready, _, _ = select.select([sys.stdin], [], [], 0.08)
            if not ready:
                continue
            ch = os.read(fd, 1)
            if ch in (b"\r", b"\n"):
                pick = MODELORDER[idx]
                break
            if ch != b"\x1b":
                continue
            if not select.select([sys.stdin], [], [], 0.02)[0]:
                continue
            b2 = os.read(fd, 1)
            if b2 != b"[" or not select.select([sys.stdin], [], [], 0.02)[0]:
                continue
            b3 = os.read(fd, 1)
            if b3 == b"A":
                idx = (idx - 1) % len(MODELORDER)
            elif b3 == b"B":
                idx = (idx + 1) % len(MODELORDER)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return pick, box


def runwithstatus(box, task):
    if not USINGTTY:
        task()
        return
    done = threading.Event()
    err = []
    frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def worker():
        try:
            task()
        except Exception as e:
            err.append(e)
        finally:
            done.set()

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    i = 0
    while not done.is_set():
        box.draw([f"{CYAN}{frames[i % len(frames)]}{RESET} writing note"])
        i += 1
        time.sleep(0.08)
    t.join(timeout=0.2)
    if err:
        raise err[0]


def showheader(box, key):
    rows = [f"{CYAN}✓{RESET} note opened", f"note = {CYAN}{key}{RESET}", ""]
    rows.extend(commandhelp())
    rows.append(f"{GREY}{'-' * 56}{RESET}")
    box.draw(rows)
    box.done(gap=2)


def showmodelchanged(box, key):
    box.draw([f"{CYAN}✓{RESET} note opened", f"note = {CYAN}{key}{RESET}"])
    box.done(gap=2)


def chatonce(messages):
    payload = {
        "model": MODEL,
        "temperature": 0.2,
        "max_tokens": MAXTOKENS,
        "messages": messages,
    }
    start = time.time()
    out = jpost("/v1/chat/completions", payload)
    text = out["choices"][0]["message"]["content"].strip()
    usage = out.get("usage")
    elapsed = time.time() - start
    return text, usage, elapsed


def normpath(path):
    p = os.path.abspath(os.path.expanduser(path))
    if not p.startswith(ALLOWROOT + os.sep) and p != ALLOWROOT:
        raise ValueError(f"path outside allowed root: {ALLOWROOT}")
    return p


def modelpathok(key):
    path = MODELS[key]
    if os.path.isabs(path) and not os.path.isdir(path):
        return False, path
    return True, path


CONVODB = os.path.join(RUNTIMEDIR, "convos.sqlite3")


def convodb():
    os.makedirs(os.path.dirname(CONVODB), exist_ok=True)
    conn = sqlite3.connect(CONVODB)
    conn.execute("create table if not exists convos (id integer primary key autoincrement, title text, model text, created real, updated real, inp integer default 0, out integer default 0)")
    conn.execute("create table if not exists turns (id integer primary key autoincrement, convo_id integer, role text, content text, ts real)")
    conn.commit()
    return conn


def convonew(model):
    conn = convodb()
    now = time.time()
    cur = conn.execute("insert into convos (title, model, created, updated) values (?, ?, ?, ?)", ("new chat", model, now, now))
    cid = cur.lastrowid
    conn.commit()
    conn.close()
    return cid


def convosave(cid, role, content, inp=0, out=0, title=None):
    conn = convodb()
    now = time.time()
    conn.execute("insert into turns (convo_id, role, content, ts) values (?, ?, ?, ?)", (cid, role, content, now))
    if title is not None:
        conn.execute("update convos set title=?, updated=?, inp=inp+?, out=out+? where id=?", (title, now, inp, out, cid))
    else:
        conn.execute("update convos set updated=?, inp=inp+?, out=out+? where id=?", (now, inp, out, cid))
    conn.commit()
    conn.close()


def convolist(limit=50):
    conn = convodb()
    rows = conn.execute("select id, title, model, updated, inp, out from convos order by updated desc limit ?", (limit,)).fetchall()
    conn.close()
    return [{"id": r[0], "title": r[1], "model": r[2], "updated": r[3], "inp": r[4], "out": r[5]} for r in rows]


def convoload(cid):
    conn = convodb()
    meta = conn.execute("select id, title, model, updated, inp, out from convos where id=?", (cid,)).fetchone()
    turns = conn.execute("select role, content from turns where convo_id=? order by id", (cid,)).fetchall()
    conn.close()
    if not meta:
        return None
    return {"id": meta[0], "title": meta[1], "model": meta[2], "updated": meta[3], "inp": meta[4], "out": meta[5], "turns": [{"role": r[0], "content": r[1]} for r in turns]}


def convorename(cid, title):
    conn = convodb()
    conn.execute("update convos set title=? where id=?", (title, cid))
    conn.commit()
    conn.close()


def convodelete(cid):
    conn = convodb()
    conn.execute("delete from turns where convo_id=?", (cid,))
    conn.execute("delete from convos where id=?", (cid,))
    conn.commit()
    conn.close()


def convotitlefromfirst(text):
    t = re.sub(r"\s+", " ", (text or "").strip())
    return (t[:48] + "...") if len(t) > 48 else (t or "new chat")


def streammain():
    import contextlib
    global MODEL, MODELKEY, ALLOWROOT, WEBMODE, CMDMODE
    out = sys.stdout
    with contextlib.redirect_stdout(sys.stderr):
        ok, path = modelpathok(MODELKEY)
        if not ok:
            raise RuntimeError(f"model not found locally: {path}")
        MODEL = MODELS[MODELKEY]
        start_server_if_needed(showstatus=False)
    messages = [{"role": "system", "content": SYSTEM}]
    ctxstate = {"lastin": 0, "compressions": 0, "memory": ""}
    cid = convonew(MODELKEY)
    turncount = 0

    def emitsettings():
        s = {
            "model": MODELKEY,
            "models": MODELORDER,
            "root": ALLOWROOT,
            "webmode": WEBMODE,
            "cmdmode": CMDMODE,
            "convoId": cid,
            "memchunks": 0,
        }
        try:
            s["memchunks"] = memcount()
        except Exception:
            pass
        out.write(f"SETTINGS:{json.dumps(s)}\n")
        out.flush()

    emitsettings()

    for raw in sys.stdin:
        user = raw.strip()
        if not user:
            out.write("DONE\n"); out.flush()
            continue
        if user == "/quit":
            break
        if user == "/settings":
            emitsettings()
            continue
        if user.startswith("/root "):
            p = os.path.abspath(os.path.expanduser(user[6:].strip()))
            if os.path.isdir(p):
                ALLOWROOT = p
            emitsettings()
            continue
        if user.startswith("/set "):
            parts = user[5:].strip().split(maxsplit=1)
            if len(parts) == 2:
                k, v = parts[0], parts[1]
                if k == "webmode" and v in ("auto", "brave", "bing"):
                    WEBMODE = v
                elif k == "cmdmode" and v in ("strict", "open"):
                    CMDMODE = v
                elif k == "model" and v in MODELS:
                    MODELKEY = v
                    MODEL = MODELS[v]
            emitsettings()
            continue
        if user == "/new":
            messages = [{"role": "system", "content": SYSTEM}]
            ctxstate = {"lastin": 0, "compressions": 0, "memory": ""}
            cid = convonew(MODELKEY)
            turncount = 0
            emitsettings()
            continue
        if user == "/convos":
            out.write(f"CONVOS:{json.dumps(convolist())}\n")
            out.flush()
            continue
        if user.startswith("/rename "):
            rest = user[8:].strip()
            parts = rest.split(maxsplit=1)
            if len(parts) == 2:
                try:
                    convorename(int(parts[0]), parts[1])
                except Exception:
                    pass
            out.write(f"CONVOS:{json.dumps(convolist())}\n")
            out.flush()
            continue
        if user.startswith("/delete "):
            try:
                target = int(user[8:].strip())
                convodelete(target)
                if target == cid:
                    messages = [{"role": "system", "content": SYSTEM}]
                    ctxstate = {"lastin": 0, "compressions": 0, "memory": ""}
                    cid = convonew(MODELKEY)
                    turncount = 0
                    emitsettings()
            except Exception:
                pass
            out.write(f"CONVOS:{json.dumps(convolist())}\n")
            out.flush()
            continue
        if user.startswith("/load "):
            try:
                target = int(user[6:].strip())
                data = convoload(target)
                if data:
                    messages = [{"role": "system", "content": SYSTEM}]
                    for t in data["turns"]:
                        messages.append({"role": t["role"], "content": t["content"]})
                    cid = data["id"]
                    turncount = len([t for t in data["turns"] if t["role"] == "user"])
                    out.write(f"LOADED:{json.dumps(data)}\n")
                    out.flush()
                    emitsettings()
            except Exception as e:
                out.write(f"ERR:{e}\n")
                out.flush()
            continue

        usage = None
        elapsed = 0.0
        try:
            with contextlib.redirect_stdout(sys.stderr):
                if (ans := clockreply(user)) is None:
                    messages, _ = compactcontext(messages, ctxstate, force=False)
                    messages.append({"role": "user", "content": user})
                    ans, usage, elapsed = respond(messages)
                    messages.append({"role": "assistant", "content": ans})
                    if usage:
                        ctxstate["lastin"] = int(usage.get("input_tokens", 0) or 0)
                else:
                    messages.append({"role": "user", "content": user})
                    messages.append({"role": "assistant", "content": ans})
        except Exception as e:
            ans = f"chat error: {e}"

        title = convotitlefromfirst(user) if turncount == 0 else None
        inp = int((usage or {}).get("input_tokens", 0) or 0)
        outc = int((usage or {}).get("output_tokens", 0) or 0)
        try:
            convosave(cid, "user", user, title=title)
            convosave(cid, "assistant", ans, inp=inp, out=outc)
        except Exception:
            pass
        turncount += 1

        lines = ans.splitlines() or [ans]
        for line in lines:
            out.write(f"TOKEN:{line}\n")
        if usage:
            stats = {
                "inp": inp,
                "out": outc,
                "tps": round(float(usage.get("generation_tps", 0) or 0), 1),
                "sec": round(float(elapsed or 0), 2),
            }
            out.write(f"STATS:{json.dumps(stats)}\n")
        out.write("DONE\n")
        out.flush()


def memdbpath():
    return MEMDB


def memdb():
    p = memdbpath()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    conn = sqlite3.connect(p)
    conn.execute(
        """
        create table if not exists memchunks (
            id integer primary key autoincrement,
            path text not null,
            chunk integer not null,
            text text not null,
            vec blob not null,
            dim integer not null,
            created_at text not null default (datetime('now'))
        )
        """
    )
    conn.execute("create index if not exists idx_memchunks_path on memchunks(path)")
    return conn


def textchunks(text, size=1000, overlap=150):
    step = max(1, int(size) - int(overlap))
    return [text[i : i + size] for i in range(0, len(text), step)]


def getembedder():
    if EMBEDDER["tok"] is not None and EMBEDDER["mdl"] is not None:
        return EMBEDDER["tok"], EMBEDDER["mdl"]
    try:
        import torch
        from transformers import AutoModel, AutoTokenizer
    except Exception as e:
        raise RuntimeError(f"embedding deps missing (torch/transformers): {e}")
    tok = AutoTokenizer.from_pretrained(EMBEDMODEL, trust_remote_code=True)
    mdl = AutoModel.from_pretrained(EMBEDMODEL, trust_remote_code=True)
    mdl.eval()
    EMBEDDER["tok"], EMBEDDER["mdl"] = tok, mdl
    return tok, mdl


def embedtexts(texts, batch=EMBEDBATCH):
    if not texts:
        return np.empty((0, 0), dtype=np.float32)
    tok, mdl = getembedder()
    try:
        import torch
    except Exception as e:
        raise RuntimeError(f"embedding deps missing (torch): {e}")
    rows = []
    with torch.no_grad():
        for i in range(0, len(texts), max(1, int(batch))):
            b = tok(texts[i : i + batch], padding=True, truncation=True, return_tensors="pt")
            out = mdl(**b)
            if hasattr(out, "last_hidden_state"):
                v = out.last_hidden_state[:, 0]
            else:
                v = out[0][:, 0]
            v = torch.nn.functional.normalize(v, p=2, dim=1)
            v = v.float()
            rows.append(v.cpu().numpy().astype(np.float32))
    return np.concatenate(rows, axis=0)


def vblob(v):
    return np.asarray(v, dtype=np.float32).tobytes()


def vfromblob(b, dim):
    return np.frombuffer(b, dtype=np.float32, count=int(dim))


def memclear():
    conn = memdb()
    try:
        conn.execute("delete from memchunks")
        conn.commit()
    finally:
        conn.close()


def memcount():
    conn = memdb()
    try:
        n = conn.execute("select count(*) from memchunks").fetchone()[0]
    finally:
        conn.close()
    return int(n)


def memindex(pattern, reset=False):
    files = sorted(glob.glob(pattern, recursive=True))
    if not files:
        raise ValueError("no files matched pattern")
    rows = []
    texts = []
    kept = []
    for fp in files:
        p = os.path.abspath(os.path.expanduser(fp))
        try:
            p = normpath(p)
        except Exception:
            continue
        if not os.path.isfile(p):
            continue
        try:
            txt = open(p, "r", encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        chunks = textchunks(txt)
        for i, ck in enumerate(chunks):
            c = ck.strip()
            if not c:
                continue
            kept.append(p)
            rows.append((p, i, c[:2000]))
            texts.append(c)
    if not rows:
        raise ValueError("no readable non-empty text found")

    vecs = embedtexts(texts)
    conn = memdb()
    try:
        if reset:
            conn.execute("delete from memchunks")
        # replace indexed files atomically by path
        for p in sorted(set(kept)):
            conn.execute("delete from memchunks where path = ?", (p,))
        conn.executemany(
            "insert into memchunks(path, chunk, text, vec, dim) values(?,?,?,?,?)",
            [(p, i, t, sqlite3.Binary(vblob(v)), int(v.shape[0])) for (p, i, t), v in zip(rows, vecs)],
        )
        conn.commit()
    finally:
        conn.close()
    return len(rows), len(set(kept))


def memquery(text, topk=MEMTOPK):
    conn = memdb()
    try:
        rows = conn.execute("select path, chunk, text, vec, dim from memchunks").fetchall()
    finally:
        conn.close()
    if not rows:
        return []
    qv = embedtexts([text])[0]
    scored = []
    for p, c, t, vb, d in rows:
        v = vfromblob(vb, d)
        s = float(np.dot(v, qv))
        scored.append((s, p, int(c), t))
    scored.sort(key=lambda x: x[0], reverse=True)
    k = max(1, min(int(topk), len(scored)))
    return scored[:k]


def memcontext(text, topk=MEMTOPK):
    hits = memquery(text, topk=topk)
    if not hits:
        return None
    lines = []
    for s, p, c, t in hits:
        lines.append(f"[{s:.3f}] {p}#{c}: {shortline(t, 180)}")
    return RAGPREFIX + " || ".join(lines)


def rowsfrompairs(pairs, n):
    rows = []
    for href, title in pairs[: max(1, min(int(n), 10))]:
        t = re.sub(r"<.*?>", "", title)
        t = html.unescape(t).strip()
        link = html.unescape(href)
        rows.append(f"- {t}\\n  {link}")
    return rows


def bingsearch(query, n=5):
    q = urllib.parse.quote_plus(query)
    url = f"https://www.bing.com/search?q={q}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        page = r.read().decode("utf-8", errors="ignore")
    pairs = BING_LINK_RE.findall(page)
    rows = rowsfrompairs(pairs, n)
    if rows:
        return rows
    # fallback: bing rss is simpler and more stable to parse
    rss = f"https://www.bing.com/search?format=rss&q={q}"
    req2 = urllib.request.Request(
        rss,
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
    )
    with urllib.request.urlopen(req2, timeout=20) as r:
        xml = r.read().decode("utf-8", errors="ignore")
    items = BING_RSS_ITEM_RE.findall(xml)
    out = []
    for title, link in items[: max(1, int(n))]:
        t = html.unescape(re.sub(r"<.*?>", "", title)).strip()
        lnk = html.unescape(link).strip()
        if t and lnk:
            out.append(f"- {t}\\n  {lnk}")
    return out


def gogglesrules(sites):
    clean = [str(x).strip() for x in (sites or []) if str(x).strip()]
    if not clean:
        return ""
    return "$discard\n" + "\n".join([f"$site={s}" for s in clean])


def gogglesites(goggles):
    out = []
    for ln in str(goggles or "").splitlines():
        s = ln.strip()
        if not s.startswith("$site="):
            continue
        site = s.split("=", 1)[1].strip()
        if site:
            out.append(site)
    return out


def querywithsites(query, sites):
    clean = [str(x).strip() for x in (sites or []) if str(x).strip()]
    if not clean:
        return query
    clause = " OR ".join([f"site:{s}" for s in clean])
    return f"{query} ({clause})"


def bravespellcheck(query):
    data = braveget("/res/v1/spellcheck/search", {"q": query})
    qobj = data.get("query")
    if isinstance(qobj, dict):
        for key in ("altered", "corrected", "correction", "text", "query"):
            val = qobj.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    for item in data.get("results") or data.get("suggestions") or []:
        if not isinstance(item, dict):
            continue
        for key in ("query", "suggestion", "text", "title"):
            val = item.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return ""


def bravesuggest(query, n=3):
    c = max(1, min(int(n), 8))
    data = braveget("/res/v1/suggest/search", {"q": query, "count": c})
    out = []
    seen = set()
    for item in data.get("results") or data.get("suggestions") or []:
        if not isinstance(item, dict):
            continue
        s = ""
        for key in ("query", "suggestion", "text", "title"):
            val = item.get(key)
            if isinstance(val, str) and val.strip():
                s = val.strip()
                break
        if not s:
            continue
        low = s.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(s)
        if len(out) >= c:
            break
    return out


def tunequery(query):
    raw = shortline(query, 500).strip()
    cleaned = raw
    notes = []
    suggestions = []
    if not raw or not BRAVEKEY:
        return raw, cleaned, notes, suggestions
    try:
        corr = bravespellcheck(raw)
        if corr and corr.lower() != raw.lower():
            cleaned = corr
            notes.append(f"spellcheck: {raw} -> {cleaned}")
    except Exception:
        pass
    try:
        suggestions = bravesuggest(cleaned, n=3)
    except Exception:
        suggestions = []
    return raw, cleaned, notes, suggestions


def bravesearch(query, n=5):
    c = max(1, min(int(n), 10))
    data = braveget("/res/v1/web/search", {"q": query, "count": c, "country": "us", "search_lang": "en"})
    rows = []
    for item in (data.get("web") or {}).get("results") or []:
        title = (item.get("title") or "").strip()
        link = (item.get("url") or "").strip()
        desc = (item.get("description") or "").strip()
        if not title or not link:
            continue
        line = f"- {title}\\n  {link}"
        if desc:
            line += f"\\n  {desc[:220]}"
        rows.append(line)
    return rows[:c]


def braveget(path, params):
    if not BRAVEKEY:
        raise ValueError("brave key missing: set BRAVE_SEARCH_API_KEY")
    q = urllib.parse.urlencode(params or {}, doseq=True)
    url = f"https://api.search.brave.com{path}" + (f"?{q}" if q else "")
    req = urllib.request.Request(
        url,
        headers={
            "X-Subscription-Token": BRAVEKEY,
            "Accept": "application/json",
            "User-Agent": "note/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8", errors="ignore"))


def bravenews(query, n=5):
    c = max(1, min(int(n), 10))
    data = braveget("/res/v1/news/search", {"q": query, "count": c, "country": "us", "search_lang": "en"})
    items = data.get("results") or (data.get("news") or {}).get("results") or []
    rows = []
    for item in items[:c]:
        title = (item.get("title") or "").strip()
        link = (item.get("url") or "").strip()
        desc = (item.get("description") or "").strip()
        age = (item.get("age") or "").strip()
        if not title or not link:
            continue
        line = f"- {title}\\n  {link}"
        if age:
            line += f"\\n  age: {age}"
        if desc:
            line += f"\\n  {desc[:220]}"
        rows.append(line)
    return rows


def bravellmcontext(query, n=8, goggles=None, freshness=None):
    c = max(1, min(int(n), 20))
    params = {"q": query, "count": c, "country": "us", "search_lang": "en"}
    if goggles:
        params["goggles"] = goggles
    if freshness:
        params["freshness"] = freshness
    data = braveget("/res/v1/llm/context", params)
    parts = []
    items = data.get("results") or (data.get("web") or {}).get("results") or []
    for it in items:
        title = (it.get("title") or "").strip()
        link = (it.get("url") or "").strip()
        desc = (it.get("description") or "").strip()
        extra = it.get("extra_snippets") or it.get("snippets") or []
        sn = " ".join([shortline(x, 180) for x in extra[:2] if isinstance(x, str)])
        line = " | ".join([x for x in [title, link, desc[:180], sn[:180]] if x])
        if line:
            parts.append(line)
    # Brave LLM context often returns data.grounding.{generic,news,...}
    grounding = data.get("grounding") or {}
    if isinstance(grounding, dict):
        for _, bucket in grounding.items():
            if not isinstance(bucket, list):
                continue
            for it in bucket:
                if not isinstance(it, dict):
                    continue
                title = (it.get("title") or "").strip()
                link = (it.get("url") or "").strip()
                snippets = it.get("snippets") or it.get("extra_snippets") or []
                sn = " ".join([shortline(x, 180) for x in snippets[:2] if isinstance(x, str)])
                desc = (it.get("description") or "").strip()
                line = " | ".join([x for x in [title, link, desc[:180], sn[:180]] if x])
                if line:
                    parts.append(line)
            if len(parts) >= c:
                break
    parts = parts[:c]
    if parts:
        return "\n".join(parts)
    # fallback for schema changes
    raw = json.dumps(data, ensure_ascii=False)
    return raw[:5000]


def researchexprs(query):
    q = shortline(query, 500)
    return [
        {
            "label": "academic",
            "query": q,
            "goggles": gogglesrules(
                [
                    "arxiv.org",
                    "mit.edu",
                    "stanford.edu",
                    "cmu.edu",
                    "berkeley.edu",
                    "nature.com",
                    "science.org",
                ]
            ),
            "n": 10,
        },
        {
            "label": "institutions",
            "query": q,
            "goggles": gogglesrules(
                [
                    "nih.gov",
                    "nasa.gov",
                    "noaa.gov",
                    "who.int",
                    "oecd.org",
                    "worldbank.org",
                ]
            ),
            "n": 10,
        },
        {"label": "broad", "query": q, "goggles": "", "n": 8},
    ]


def mergegroundings(blocks, cap=12000):
    seen = set()
    out = []
    for label, text in blocks:
        if not text:
            continue
        lines = [x.strip() for x in str(text).splitlines() if x.strip()]
        for ln in lines:
            key = ln.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(f"[{label}] {ln}")
            if sum(len(x) + 1 for x in out) >= cap:
                return "\n".join(out)
    return "\n".join(out)


def researchgrounding(query):
    raw, cleaned, notes, suggestions = tunequery(query)
    blocks = []
    if raw:
        blocks.append(("query", f"raw query: {raw}"))
    if cleaned and cleaned != raw:
        blocks.append(("query", f"cleaned query: {cleaned}"))
    if notes:
        blocks.append(("query", "\n".join(notes[:2])))
    if suggestions:
        blocks.append(("query", "suggestions: " + " | ".join(suggestions[:3])))
    if not BRAVEKEY:
        for cfg in researchexprs(cleaned or query):
            label = cfg["label"]
            scopedq = querywithsites(cfg["query"], gogglesites(cfg.get("goggles") or ""))
            try:
                rows = bingsearch(scopedq, n=8 if label != "broad" else 6)
                txt = "\n".join(rows)
            except Exception as e:
                txt = f"(error: {e})"
            blocks.append((label, txt))
        return mergegroundings(blocks, cap=12000)
    for cfg in researchexprs(cleaned or query):
        label = cfg["label"]
        q = cfg["query"]
        gg = cfg.get("goggles") or ""
        n = cfg.get("n") or 8
        try:
            txt = bravellmcontext(q, n=n, goggles=gg)
        except Exception as e:
            txt = f"(error: {e})"
        blocks.append((label, txt))
    try:
        news = bravenews(cleaned or query, n=6)
        if news:
            blocks.append(("news", "\n".join(news)))
    except Exception:
        pass
    return mergegroundings(blocks, cap=12000)


def searchrows(query, n=5, source=None):
    src = (source or WEBMODE or "auto").strip().lower()
    if src not in ("auto", "brave", "bing"):
        raise ValueError("source must be auto, brave, or bing")
    if src == "bing":
        return "bing", bingsearch(query, n)
    if src == "brave":
        return "brave", bravesearch(query, n)
    if BRAVEKEY:
        try:
            rows = bravesearch(query, n)
            if rows:
                return "brave", rows
        except Exception:
            pass
    return "bing", bingsearch(query, n)


def websearch(query, n=5, source=None):
    used, rows = searchrows(query, n, source)
    return f"tool ok: websearch (source={used})\n" + ("\n".join(rows) if rows else "(no results parsed)")


def toolhelp():
    return (
        "tool json examples:\n"
        '{"tool":"read","path":"/Users/you/file.txt"}\n'
        '{"tool":"write","path":"/Users/you/file.txt","content":"hello","mode":"overwrite"}\n'
        '{"tool":"list","path":"/Users/you/project"}\n'
        '{"tool":"search","path":"/Users/you/project","pattern":"todo","glob":"*.py"}\n'
        '{"tool":"edit","path":"/Users/you/file.txt","find":"old","replace":"new","all":false}\n'
        '{"tool":"websearch","query":"latest mlx-vlm release notes","n":5,"source":"auto"}\n'
        '{"tool":"command","cmd":"git status","cwd":"/Users/you/project"}\n'
        f"allowroot: {ALLOWROOT}\n"
        f"webmode: {WEBMODE} (brave key set: {'yes' if BRAVEKEY else 'no'})\n"
        f"cmdmode: {CMDMODE} (strict allows: {', '.join(sorted(CMDALLOW))})"
    )


def parse_toolcall(text):
    s = text.strip()
    if not s:
        return None
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s)
        s = s.strip()
    if not s.startswith("{"):
        return None
    try:
        obj = json.loads(s)
    except Exception:
        return None
    if not isinstance(obj, dict) or "tool" not in obj:
        return None
    return obj


def trim(text, limit):
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


def rendertext(text):
    if not USINGTTY:
        return text
    s = text
    # lightweight markdown-ish rendering for terminal output
    s = re.sub(r"\*\*([^\n*][^*]*?)\*\*", lambda m: f"{BOLD}{m.group(1)}{RESET}", s)
    s = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", lambda m: f"{ITALIC}{m.group(1)}{RESET}", s)
    s = re.sub(r"`([^`\n]+)`", lambda m: f"{DIM}{m.group(1)}{RESET}", s)
    return s


def peelcd(cmd, cwd):
    parts = re.split(r"\s*(?:&&|;)\s*", cmd, maxsplit=1)
    if len(parts) != 2:
        return cmd, cwd
    head, tail = parts[0].strip(), parts[1].strip()
    if not head.startswith("cd ") or not tail:
        return cmd, cwd
    cdparts = shlex.split(head)
    if len(cdparts) < 2 or cdparts[0] != "cd":
        return cmd, cwd
    target = cdparts[1]
    if target.startswith("~"):
        newcwd = normpath(os.path.expanduser(target))
    elif os.path.isabs(target):
        newcwd = normpath(target)
    else:
        newcwd = normpath(os.path.join(cwd, target))
    return tail, newcwd


def toollabel(call):
    tool = (call.get("tool") or "").strip().lower()
    if tool == "command":
        return call.get("cmd", "")
    if tool == "websearch":
        src = (call.get("source") or WEBMODE or "auto").strip().lower()
        return f"{call.get('query', '')} [{src}]"
    return call.get("path", call.get("query", ""))


def runtool(call):
    tool = (call.get("tool") or "").strip().lower()
    if tool == "read":
        p = normpath(call.get("path", ""))
        with open(p, "r", encoding="utf-8") as f:
            txt = f.read()
        txt = trim(txt, READMAX)
        return f"tool ok: read {p}\n{txt}"
    if tool == "write":
        p = normpath(call.get("path", ""))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        mode = (call.get("mode") or "overwrite").strip().lower()
        content = call.get("content", "")
        if not isinstance(content, str):
            raise ValueError("content must be string")
        fmode = "a" if mode == "append" else "w"
        with open(p, fmode, encoding="utf-8") as f:
            f.write(content)
        return f"tool ok: write {p} ({mode}, {len(content)} chars)"
    if tool == "list":
        p = normpath(call.get("path", ALLOWROOT))
        if not os.path.isdir(p):
            raise ValueError("path is not a directory")
        rows = []
        for name in sorted(os.listdir(p))[:300]:
            fp = os.path.join(p, name)
            kind = "dir" if os.path.isdir(fp) else "file"
            rows.append(f"{kind}\t{name}")
        return f"tool ok: list {p}\n" + "\n".join(rows)
    if tool == "search":
        p = normpath(call.get("path", ALLOWROOT))
        pat = call.get("pattern", "")
        if not pat:
            raise ValueError("pattern required")
        globpat = call.get("glob", "")
        cmd = ["rg", "-n", "--hidden", "--max-count", "200", pat, p]
        if globpat:
            cmd.extend(["-g", globpat])
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=CMDTIMEOUT,
        )
        out = trim((proc.stdout or "") + (proc.stderr or ""), OUTMAX)
        return f"tool ok: search {p}\n{out.strip() or '(no matches)'}"
    if tool == "edit":
        p = normpath(call.get("path", ""))
        find = call.get("find", "")
        repl = call.get("replace", "")
        allhits = bool(call.get("all", False))
        if not find:
            raise ValueError("find required")
        with open(p, "r", encoding="utf-8") as f:
            src = f.read()
        count = src.count(find)
        if count == 0:
            return f"tool ok: edit {p} (no matches)"
        newsrc = src.replace(find, repl) if allhits else src.replace(find, repl, 1)
        with open(p, "w", encoding="utf-8") as f:
            f.write(newsrc)
        done = count if allhits else 1
        return f"tool ok: edit {p} (replaced {done} of {count})"
    if tool == "websearch":
        query = (call.get("query") or "").strip()
        if not query:
            raise ValueError("query required")
        n = call.get("n", 5)
        source = (call.get("source") or "").strip().lower() or None
        return websearch(query, n, source)
    if tool == "command":
        cmd = (call.get("cmd") or "").strip()
        if not cmd:
            raise ValueError("cmd required")
        cwd = normpath(call.get("cwd", os.getcwd()))
        cmd, cwd = peelcd(cmd, cwd)
        if CMDMODE == "strict":
            parts = shlex.split(cmd)
            if not parts:
                raise ValueError("empty command")
            base = os.path.basename(parts[0])
            if base not in CMDALLOW:
                raise ValueError(f"command not allowed in strict mode: {base}")
        print(f"\napprove command? {cmd}")
        ans = input("run [y/N]: ").strip().lower()
        if ans not in ("y", "yes"):
            return "tool skipped: command not approved"
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=CMDTIMEOUT,
        )
        out = trim((proc.stdout or "") + (proc.stderr or ""), OUTMAX)
        return (
            f"tool ok: command `{cmd}` (exit {proc.returncode}) in {cwd}\n"
            f"{out.strip() or '(no output)'}"
        )
    raise ValueError("unknown tool")


def respond(messages):
    total = 0.0
    last_usage = None
    seen = {}
    for _ in range(MAXTOOLROUNDS):
        with spinner("thinking", NOTEPREFIX):
            ans, usage, elapsed = chatonce(messages)
        total += elapsed
        last_usage = usage
        call = parse_toolcall(ans)
        if not call:
            return ans, last_usage, total
        key = json.dumps(call, sort_keys=True, ensure_ascii=True)
        seen[key] = seen.get(key, 0) + 1
        if seen[key] >= 3:
            return "tool loop stalled on repeated call; refine your request.", last_usage, total
        try:
            t0 = time.time()
            result = runtool(call)
            dt = time.time() - t0
            print(f"\n{ITALIC}{DIM}{GREY}tool ok · {call.get('tool')} {toollabel(call)} · {dt:.2f}s{RESET}")
        except Exception as e:
            result = f"tool error: {e}"
            print(f"\n{ITALIC}{DIM}{GREY}tool err · {call.get('tool')} {toollabel(call)} · {e}{RESET}")
        messages.append({"role": "assistant", "content": ans})
        messages.append({"role": "user", "content": result})
    return "tool loop limit reached; refine your request.", last_usage, total


def printstats(usage, elapsed):
    if usage:
        itok = usage.get("input_tokens", 0)
        otok = usage.get("output_tokens", 0)
        ttok = usage.get("total_tokens", itok + otok)
        gtps = usage.get("generation_tps")
        if gtps is None and elapsed > 0 and otok:
            gtps = otok / elapsed
        gtpss = f"{gtps:.2f}" if isinstance(gtps, (int, float)) else "n/a"
        print(f"{DIM}{GREY}stats · {ttok} tok ({itok} in, {otok} out) · {elapsed:.2f}s · {gtpss} tok/s{RESET}")
    else:
        print(f"{DIM}{GREY}stats · {elapsed:.2f}s{RESET}")


def datenow():
    now = datetime.now().astimezone()
    daynum = str(int(now.strftime("%d")))
    hour12 = str(int(now.strftime("%I")))
    return (
        now.strftime(f"%A, %B {daynum}, %Y"),
        now.strftime(f"{hour12}:%M %p %Z"),
    )


def clockreply(user):
    text = user.strip().lower()
    if text == "/now":
        d, t = datenow()
        return f"right now: {d} · {t}"
    has_time = (
        "what time" in text
        or "current time" in text
        or "time is it" in text
        or "tell me the time" in text
    )
    has_date = (
        "what date" in text
        or "today's date" in text
        or "todays date" in text
        or "date is it" in text
        or "today is" in text
    )
    has_day = "what day" in text or "day is it" in text
    if not (has_time or has_date or has_day):
        return None
    d, t = datenow()
    if has_time and (has_date or has_day):
        return f"it’s {t} on {d}."
    if has_time:
        return f"it’s {t}."
    if has_day:
        return f"today is {d}."
    return f"today is {d}."


def recentchat(messages, n=12):
    rows = []
    for m in messages:
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        tag = "you" if role == "user" else "note"
        rows.append(f"{tag}: {shortline(m.get('content', ''), 220)}")
    return "\n".join(rows[-max(1, int(n)) :])


def printrows(rows):
    if not rows:
        print(f"{DIM}{GREY}(no results){RESET}\n")
        return
    for r in rows:
        print(rendertext(r))
        print()


def shortline(text, limit=180):
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    return s[:limit]


def compactcontext(messages, ctxstate, force=False):
    if not messages:
        return messages, False
    if not force and ctxstate.get("lastin", 0) < int(MAXKV * CTXSOFT):
        return messages, False

    system = messages[0]
    turns = messages[1:]
    if turns and turns[0].get("role") == "system" and str(turns[0].get("content", "")).startswith(MEMPREFIX):
        turns = turns[1:]

    if len(turns) <= KEEPRECENT:
        return [system] + ([{"role": "system", "content": MEMPREFIX + ctxstate.get("memory", "")}] if ctxstate.get("memory") else []) + turns, False

    old = turns[:-KEEPRECENT]
    recent = turns[-KEEPRECENT:]

    snaps = []
    for m in old[-48:]:
        role = m.get("role", "?")
        tag = "u" if role == "user" else ("a" if role == "assistant" else role[:1])
        snaps.append(f"{tag}: {shortline(m.get('content', ''), 160)}")

    merged = (ctxstate.get("memory", "") + " || " + " || ".join(snaps)).strip(" |")
    if len(merged) > MEMMAXCHARS:
        merged = merged[-MEMMAXCHARS:]
    ctxstate["memory"] = merged
    ctxstate["compressions"] = int(ctxstate.get("compressions", 0)) + 1

    memmsg = {"role": "system", "content": MEMPREFIX + merged}
    return [system, memmsg, *recent], True


def main():
    global ALLOWROOT, CMDMODE, MODELKEY, MODEL, WEBMODE, MEMAUTO
    messages = [{"role": "system", "content": SYSTEM}]
    ctxstate = {"lastin": 0, "compressions": 0, "memory": ""}
    MODELKEY, box = pickmodel(MODELKEY)
    ok, path = modelpathok(MODELKEY)
    if not ok:
        raise RuntimeError(f"model not found locally: {path}")
    MODEL = MODELS[MODELKEY]
    runwithstatus(box, lambda: start_server_if_needed(showstatus=False))
    box.draw([f"{CYAN}✓{RESET} note opened"])
    time.sleep(0.12)
    showheader(box, MODELKEY)

    while True:
        try:
            user = input(YOUPREFIX).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            break

        if not user:
            continue
        if user == "/quit":
            print("bye")
            break
        if user == "/now":
            ans = clockreply(user)
            messages.append({"role": "user", "content": user})
            messages.append({"role": "assistant", "content": ans})
            print(f"{NOTEPREFIX}{rendertext(ans)}")
            printstats(None, 0.0)
            print()
            continue
        if user == "/reset":
            messages = [{"role": "system", "content": SYSTEM}]
            ctxstate = {"lastin": 0, "compressions": 0, "memory": ""}
            print(f"{DIM}{GREY}chat reset{RESET}")
            continue
        if user == "/system":
            print(f"{DIM}{GREY}system access:{RESET}")
            print(f"{DIM}{GREY}- files are limited to root: {ALLOWROOT}{RESET}")
            print(f"{DIM}{GREY}- web search mode: {WEBMODE} (brave key set: {'yes' if BRAVEKEY else 'no'}){RESET}")
            print(f"{DIM}{GREY}- shell command mode: {CMDMODE} (controls command allowlist only){RESET}")
            print(f"{DIM}{GREY}- strict command allowlist: {', '.join(sorted(CMDALLOW))}{RESET}")
            print(f"{DIM}{GREY}- memory db: {memdbpath()} | chunks: {memcount()} | auto: {'on' if MEMAUTO else 'off'}{RESET}")
            print(f"{DIM}{GREY}- context pressure: {ctxstate.get('lastin',0)}/{MAXKV} tok ({ctxstate.get('lastin',0)/MAXKV:.0%}) | compactions: {ctxstate.get('compressions',0)}{RESET}")
            print()
            continue
        if user == "/project":
            print(f"{DIM}{GREY}project:{RESET}")
            print(f"{DIM}{GREY}- app root: {APPROOT}{RESET}")
            print(f"{DIM}{GREY}- root scope: {ALLOWROOT}{RESET}")
            print(f"{DIM}{GREY}- runtime dir: {RUNTIMEDIR}{RESET}")
            print(f"{DIM}{GREY}- logs: {LOG}{RESET}")
            print(f"{DIM}{GREY}- memory db: {memdbpath()} (chunks: {memcount()}){RESET}")
            print(f"{DIM}{GREY}- model: {MODELKEY} ({MODEL}){RESET}")
            print(f"{DIM}{GREY}- modes: web={WEBMODE}, cmd={CMDMODE}, memauto={'on' if MEMAUTO else 'off'}{RESET}")
            print(f"{DIM}{GREY}- context: {ctxstate.get('lastin',0)}/{MAXKV} ({ctxstate.get('lastin',0)/MAXKV:.0%}), compactions={ctxstate.get('compressions',0)}{RESET}")
            print()
            continue
        if user == "/models":
            MODELKEY, box = pickmodel(MODELKEY, compact=True)
            ok, path = modelpathok(MODELKEY)
            if not ok:
                print(f"error: model not found locally: {path}\n")
                continue
            MODEL = MODELS[MODELKEY]
            runwithstatus(box, lambda: start_server_if_needed(showstatus=False))
            showmodelchanged(box, MODELKEY)
            continue
        if user.startswith("/model "):
            key = user.split(maxsplit=1)[1].strip().lower()
            if key not in MODELS:
                print("error: model must be gemma, qwen, or speed\n")
                continue
            ok, path = modelpathok(key)
            if not ok:
                print(f"error: model not found locally: {path}\n")
                continue
            MODELKEY = key
            MODEL = MODELS[key]
            with spinner("writing note", NOTEPREFIX):
                start_server_if_needed(showstatus=False)
            print(f"{DIM}{GREY}model set: {CYAN}{MODELKEY}{RESET}\n")
            continue
        if user == "/tools":
            print(toolhelp())
            print()
            continue
        if user.startswith("/search "):
            q = user.split(maxsplit=1)[1].strip()
            try:
                with spinner("searching web", NOTEPREFIX):
                    used, rows = searchrows(q, n=8, source=WEBMODE)
            except Exception as e:
                print(f"{DIM}{GREY}search error: {e}{RESET}\n")
                continue
            print(f"{DIM}{GREY}source: {used}{RESET}")
            printrows(rows)
            continue
        if user.startswith("/news "):
            q = user.split(maxsplit=1)[1].strip()
            try:
                with spinner("searching news", NOTEPREFIX):
                    if BRAVEKEY:
                        rows = bravenews(q, n=8)
                    else:
                        rows = bingsearch(f"{q} latest news", n=8)
            except Exception as e:
                print(f"{DIM}{GREY}news error: {e}{RESET}\n")
                continue
            printrows(rows)
            continue
        if user.startswith("/suggest "):
            q = user.split(maxsplit=1)[1].strip()
            if not BRAVEKEY:
                print(f"{DIM}{GREY}suggest error: brave key missing{RESET}\n")
                continue
            try:
                with spinner("getting suggestions", NOTEPREFIX):
                    rows = bravesuggest(q, n=8)
            except Exception as e:
                print(f"{DIM}{GREY}suggest error: {e}{RESET}\n")
                continue
            if not rows:
                print(f"{DIM}{GREY}(no suggestions){RESET}\n")
                continue
            printrows([f"- {x}" for x in rows])
            continue
        if user.startswith("/spellcheck "):
            q = user.split(maxsplit=1)[1].strip()
            if not BRAVEKEY:
                print(f"{DIM}{GREY}spellcheck error: brave key missing{RESET}\n")
                continue
            try:
                with spinner("checking query", NOTEPREFIX):
                    out = bravespellcheck(q)
            except Exception as e:
                print(f"{DIM}{GREY}spellcheck error: {e}{RESET}\n")
                continue
            shown = out or q
            msg = "unchanged" if shown.strip().lower() == q.strip().lower() else "corrected"
            print(f"{DIM}{GREY}{msg}: {shown}{RESET}\n")
            continue
        if user.startswith("/today"):
            arg = user.split(maxsplit=1)[1].strip() if len(user.split(maxsplit=1)) > 1 else ""
            baseq = "current events timeline for the last 12 months, 12 weeks, and 7 days"
            q = f"{baseq} {arg}".strip()
            _, tuned, notes, _ = tunequery(q)
            try:
                with spinner("grounding today", NOTEPREFIX):
                    if BRAVEKEY:
                        live = bravellmcontext(tuned or q, n=12)
                    else:
                        _, rows = searchrows(tuned or q, n=12, source="bing")
                        live = "\n".join(rows)
            except Exception as e:
                print(f"{DIM}{GREY}today grounding error: {e}{RESET}\n")
                continue
            convo = recentchat(messages, n=16)
            prompt = (
                "using live web grounding plus our recent chat context, give a concise timeline with headings: "
                "months, weeks, last 7 days. include major events and mention uncertainty if needed. "
                "end with 3 bullets on what matters now.\n\n"
                f"recent chat:\n{convo}"
            )
            temp = list(messages)
            tunedmsg = ("\nquery tuning:\n" + "\n".join(notes[:2])) if notes else ""
            temp.append({"role": "system", "content": "fresh brave llm-context grounding:\n" + live + tunedmsg})
            temp.append({"role": "user", "content": prompt})
            ans, usage, elapsed = respond(temp)
            messages.append({"role": "user", "content": user})
            messages.append({"role": "assistant", "content": ans})
            if usage:
                ctxstate["lastin"] = int(usage.get("input_tokens", 0) or 0)
            print(f"{NOTEPREFIX}{rendertext(ans)}")
            printstats(usage, elapsed)
            print()
            continue
        if user.startswith("/research "):
            q = user.split(maxsplit=1)[1].strip()
            try:
                with spinner("grounding research", NOTEPREFIX):
                    live = researchgrounding(q)
            except Exception as e:
                print(f"{DIM}{GREY}research grounding error: {e}{RESET}\n")
                continue
            prompt = (
                "synthesize a research-focused answer from the grounded context. prioritize credibility and evidence. "
                "weight academic/lab/institutional sources first, then broader web only for gaps. "
                "include caveats/uncertainty and end with a short source list."
            )
            temp = list(messages)
            temp.append({"role": "system", "content": "fresh brave llm-context grounding:\n" + live})
            temp.append({"role": "user", "content": prompt})
            ans, usage, elapsed = respond(temp)
            messages.append({"role": "user", "content": user})
            messages.append({"role": "assistant", "content": ans})
            if usage:
                ctxstate["lastin"] = int(usage.get("input_tokens", 0) or 0)
            print(f"{NOTEPREFIX}{rendertext(ans)}")
            printstats(usage, elapsed)
            print()
            continue
        if user.startswith("/memstatus"):
            print(f"{DIM}{GREY}memory db: {memdbpath()}{RESET}")
            print(f"{DIM}{GREY}chunks: {memcount()} | auto: {'on' if MEMAUTO else 'off'} | model: {EMBEDMODEL}{RESET}\n")
            continue
        if user.startswith("/memclear"):
            memclear()
            print(f"{DIM}{GREY}memory db cleared{RESET}\n")
            continue
        if user.startswith("/memauto"):
            parts = user.split(maxsplit=1)
            if len(parts) < 2:
                print(f"{DIM}{GREY}memauto: {'on' if MEMAUTO else 'off'}{RESET}\n")
                continue
            mode = parts[1].strip().lower()
            if mode not in ("on", "off"):
                print("error: memauto must be on or off\n")
                continue
            MEMAUTO = mode == "on"
            print(f"{DIM}{GREY}memauto set: {'on' if MEMAUTO else 'off'}{RESET}\n")
            continue
        if user.startswith("/memindex"):
            parts = user.split(maxsplit=1)
            if len(parts) < 2:
                print("usage: /memindex <glob-pattern> (example: /memindex ~/Desktop/**/*.md)\n")
                continue
            pat = parts[1].strip()
            with spinner("indexing memory", NOTEPREFIX):
                chunks, files = memindex(pat, reset=False)
            print(f"{DIM}{GREY}memory indexed: {chunks} chunks from {files} files{RESET}\n")
            continue
        if user.startswith("/memfind"):
            parts = user.split(maxsplit=1)
            if len(parts) < 2:
                print("usage: /memfind <query>\n")
                continue
            q = parts[1].strip()
            with spinner("searching memory", NOTEPREFIX):
                hits = memquery(q, topk=5)
            if not hits:
                print(f"{DIM}{GREY}(no memory hits){RESET}\n")
                continue
            for i, (s, p, c, t) in enumerate(hits, start=1):
                print(f"{DIM}{GREY}[{i}] {s:.3f} {p}#{c}{RESET}")
                print(shortline(t, 280))
                print()
            continue
        if user.startswith("/root") or user.startswith("/allowroot"):
            parts = user.split(maxsplit=1)
            if len(parts) < 2:
                print(f"{DIM}{GREY}root: {ALLOWROOT}{RESET}\n")
                continue
            newroot = os.path.abspath(os.path.expanduser(parts[1].strip()))
            if not os.path.isdir(newroot):
                print("error: root must be an existing directory\n")
                continue
            ALLOWROOT = newroot
            print(f"{DIM}{GREY}root set: {ALLOWROOT}{RESET}\n")
            continue
        if user.startswith("/webmode"):
            parts = user.split(maxsplit=1)
            if len(parts) < 2:
                print(f"{DIM}{GREY}webmode: {WEBMODE} (brave key set: {'yes' if BRAVEKEY else 'no'}){RESET}\n")
                continue
            mode = parts[1].strip().lower()
            if mode not in ("auto", "brave", "bing"):
                print("error: webmode must be auto, brave, or bing\n")
                continue
            if mode == "brave" and not BRAVEKEY:
                print("error: brave key missing. set BRAVE_SEARCH_API_KEY first\n")
                continue
            WEBMODE = mode
            print(f"{DIM}{GREY}webmode set: {WEBMODE}{RESET}\n")
            continue
        if user.startswith("/cmdmode"):
            parts = user.split(maxsplit=1)
            if len(parts) < 2:
                print(f"{DIM}{GREY}cmdmode: {CMDMODE}{RESET}\n")
                continue
            mode = parts[1].strip().lower()
            if mode not in ("strict", "open"):
                print("error: cmdmode must be strict or open\n")
                continue
            CMDMODE = mode
            print(f"{DIM}{GREY}cmdmode set: {CMDMODE}{RESET}\n")
            continue

        if (ans := clockreply(user)) is not None:
            messages.append({"role": "user", "content": user})
            messages.append({"role": "assistant", "content": ans})
            print(f"{NOTEPREFIX}{rendertext(ans)}")
            printstats(None, 0.0)
            print()
            continue

        messages, didcompact = compactcontext(messages, ctxstate, force=False)
        if didcompact:
            print(f"{ITALIC}{DIM}{GREY}context · compacted history for continuity{RESET}")
        if MEMAUTO:
            try:
                mctx = memcontext(user, topk=MEMTOPK)
            except Exception as e:
                mctx = None
                print(f"{ITALIC}{DIM}{GREY}memory · unavailable ({e}){RESET}")
            if mctx:
                messages.append({"role": "system", "content": mctx})
                print(f"{ITALIC}{DIM}{GREY}memory · attached relevant context{RESET}")
        messages.append({"role": "user", "content": user})

        try:
            ans, usage, elapsed = respond(messages)
            messages.append({"role": "assistant", "content": ans})
            if usage:
                ctxstate["lastin"] = int(usage.get("input_tokens", 0) or 0)
            print(f"{NOTEPREFIX}{rendertext(ans)}")
            printstats(usage, elapsed)
            print()
            if ctxstate.get("lastin", 0) >= int(MAXKV * CTXHARD):
                messages, didcompact = compactcontext(messages, ctxstate, force=True)
                if didcompact:
                    print(f"{ITALIC}{DIM}{GREY}context · synced (high pressure){RESET}")
                    print()
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")
            print(f"http error {e.code}: {body}")
        except Exception as e:
            print(f"request failed: {e}")


if __name__ == "__main__":
    if "--stream" in sys.argv[1:]:
        streammain()
    else:
        main()
