#!/usr/bin/env python3
import argparse
import glob
import json
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer


def loadmodel(name: str):
    tok = AutoTokenizer.from_pretrained(name, trust_remote_code=True)
    mdl = AutoModel.from_pretrained(name, trust_remote_code=True)
    mdl.eval()
    return tok, mdl


def embedtexts(tok, mdl, texts, batchsize=32):
    if not texts:
        return np.empty((0, 0), dtype=np.float32)
    vecs = []
    with torch.no_grad():
        for i in range(0, len(texts), max(1, int(batchsize))):
            batch = tok(texts[i : i + batchsize], padding=True, truncation=True, return_tensors="pt")
            out = mdl(**batch)
            if hasattr(out, "last_hidden_state"):
                v = out.last_hidden_state[:, 0]
            else:
                v = out[0][:, 0]
            v = torch.nn.functional.normalize(v, p=2, dim=1)
            vecs.append(v.cpu().numpy())
    return np.concatenate(vecs, axis=0)


def chunks(text, size=1000, overlap=150):
    step = max(1, size - overlap)
    return [text[i : i + size] for i in range(0, len(text), step)]


def buildindex(model, pattern, outpath):
    files = sorted(glob.glob(pattern, recursive=True))
    if not files:
        raise SystemExit("no files matched pattern")

    rows = []
    texts = []
    for fp in files:
        p = Path(fp)
        if not p.is_file():
            continue
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for i, ck in enumerate(chunks(txt)):
            ck = ck.strip()
            if not ck:
                continue
            rows.append({"path": str(p), "chunk": i, "text": ck[:2000]})
            texts.append(ck)

    if not texts:
        raise SystemExit("no non-empty text chunks found")

    tok, mdl = loadmodel(model)
    vecs = embedtexts(tok, mdl, texts).astype(np.float32)
    np.savez_compressed(outpath, vecs=vecs)
    with open(outpath + ".meta.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=True) + "\n")
    print(f"indexed {len(rows)} chunks -> {outpath}")


def queryindex(model, indexpath, query, topk=5):
    data = np.load(indexpath)
    vecs = data["vecs"]
    with open(indexpath + ".meta.jsonl", "r", encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]

    tok, mdl = loadmodel(model)
    qv = embedtexts(tok, mdl, [query])[0]
    scores = vecs @ qv
    k = max(1, min(int(topk), len(scores)))
    idx = np.argpartition(-scores, k - 1)[:k]
    idx = idx[np.argsort(-scores[idx])]
    for rank, i in enumerate(idx, start=1):
        r = rows[int(i)]
        print(f"[{rank}] score={scores[int(i)]:.4f} file={r['path']} chunk={r['chunk']}")
        print(r["text"][:400].replace("\n", " "))
        print()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="Qwen/Qwen3-Embedding-0.6B")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build")
    b.add_argument("--pattern", required=True, help="glob pattern, e.g. '/path/**/*.md'")
    b.add_argument("--out", default="index.npz")

    q = sub.add_parser("query")
    q.add_argument("--index", default="index.npz")
    q.add_argument("--text", required=True)
    q.add_argument("--topk", type=int, default=5)

    a = p.parse_args()
    if a.cmd == "build":
        buildindex(a.model, a.pattern, a.out)
    else:
        queryindex(a.model, a.index, a.text, a.topk)


if __name__ == "__main__":
    main()
