"""Codex 会话：~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl

文件格式不是公开稳定接口，任何解析异常都只记警告、不中断。
"""
import json
import os
from datetime import timedelta
from pathlib import Path

from common import expand, parse_ts
from collectors.textutil import clean

NAME = "codex"


def default_path():
    base = os.environ.get("CODEX_HOME")
    return Path(base).expanduser() / "sessions" if base else Path.home() / ".codex" / "sessions"


def _candidate_files(root, start, end):
    """按目录日期预筛。会话可能跨天，所以向前多看 7 天。"""
    d = (start - timedelta(days=7)).date()
    last = end.date()
    while d <= last:
        day_dir = root / f"{d.year:04d}" / f"{d.month:02d}" / f"{d.day:02d}"
        if day_dir.is_dir():
            yield from day_dir.glob("*.jsonl")
        d += timedelta(days=1)


def parse_file(fp, start, end):
    msgs, meta = [], {}
    with open(fp, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            typ, p = d.get("type"), d.get("payload") or {}
            if typ == "session_meta":
                meta = p
                continue
            if typ != "response_item" or p.get("type") != "message":
                continue
            role = p.get("role")
            if role not in ("user", "assistant"):
                continue  # developer/system 是注入的指令
            ts = parse_ts(d.get("timestamp"))
            if ts is None or not (start <= ts < end):
                continue
            for item in p.get("content") or []:
                if item.get("type") in ("input_text", "output_text"):
                    text = clean(item.get("text", ""))
                    if text:
                        msgs.append({"time": ts, "role": role, "text": text})
    if not any(m["role"] == "user" for m in msgs):
        return None
    git = meta.get("git") or {}
    return {
        "source": NAME,
        "session_id": meta.get("id") or meta.get("session_id") or fp.stem,
        "title": None,
        "workdir": meta.get("cwd"),
        "workdirs": [meta["cwd"]] if meta.get("cwd") else [],
        "branch": git.get("branch"),
        "messages": msgs,
    }


def collect(cfg, start, end, ctx):
    src = cfg["sources"].get(NAME) or {}
    root = expand(src["path"]) if src.get("path") else default_path()
    res = {"source": NAME, "sessions": [], "warnings": [], "stats": {"files_scanned": 0}}
    if not root.is_dir():
        return res  # 没装 Codex 是正常情况，不报警告
    for fp in _candidate_files(root, start, end):
        res["stats"]["files_scanned"] += 1
        try:
            s = parse_file(fp, start, end)
        except Exception as e:
            res["warnings"].append(f"Codex 会话未能解析，已跳过：{fp.name}（{e}）")
            continue
        if s:
            res["sessions"].append(s)
    return res
