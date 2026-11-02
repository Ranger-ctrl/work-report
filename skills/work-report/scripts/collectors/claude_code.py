"""Claude Code 会话：~/.claude/projects/<项目>/<session>.jsonl"""
import json
import os
import re
from collections import Counter
from pathlib import Path

from common import expand, parse_ts
from collectors.textutil import clean

NAME = "claude_code"
# 粗筛用：容忍冒号两侧的空格，不依赖文件的紧凑写法
_TYPE = re.compile(r'"type"\s*:\s*"(user|assistant|ai-title)"')


def default_path():
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(base).expanduser() / "projects" if base else Path.home() / ".claude" / "projects"


def _texts(content, role):
    if isinstance(content, str):
        return [content]
    out = []
    for item in content or []:
        if isinstance(item, dict) and item.get("type") == "text":
            out.append(item.get("text", ""))
    return out


def parse_file(fp, start, end):
    """流式读一个会话文件，返回窗口内的会话；没有内容返回 None。"""
    msgs, cwds, branches, title, sid = [], Counter(), Counter(), None, fp.stem
    with open(fp, encoding="utf-8", errors="replace") as f:
        for line in f:
            # 先用子串粗筛，绝大多数工具输出行不必解析
            m = _TYPE.search(line)
            if not m:
                continue
            if m.group(1) == "ai-title":
                try:
                    title = json.loads(line).get("aiTitle") or title
                except ValueError:
                    pass
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            role = d.get("type")
            if role not in ("user", "assistant") or d.get("isSidechain") or d.get("isMeta"):
                continue
            ts = parse_ts(d.get("timestamp"))
            if ts is None or not (start <= ts < end):
                continue
            content = (d.get("message") or {}).get("content")
            for raw in _texts(content, role):
                text = clean(raw)
                if text:
                    msgs.append({"time": ts, "role": role, "text": text})
            if d.get("cwd"):
                cwds[d["cwd"]] += 1
            if d.get("gitBranch") and d["gitBranch"] != "HEAD":
                branches[d["gitBranch"]] += 1
            sid = d.get("sessionId") or sid
    if not any(m["role"] == "user" for m in msgs):
        return None
    return {
        "source": NAME,
        "session_id": sid,
        "title": title,
        "workdir": cwds.most_common(1)[0][0] if cwds else None,
        "workdirs": [c for c, _ in cwds.most_common(5)],
        "branch": branches.most_common(1)[0][0] if branches else None,
        "messages": msgs,
    }


def collect(cfg, start, end, ctx):
    src = cfg["sources"].get(NAME) or {}
    root = expand(src["path"]) if src.get("path") else default_path()
    res = {"source": NAME, "sessions": [], "warnings": [], "stats": {"files_scanned": 0}}
    if not root.is_dir():
        res["warnings"].append(f"未找到 Claude Code 会话目录：{root}")
        return res
    start_epoch = start.timestamp()
    for fp in root.glob("*/*.jsonl"):
        try:
            if fp.stat().st_mtime < start_epoch:
                continue  # 最后修改早于窗口起点，不可能有窗口内的消息
        except OSError:
            continue
        res["stats"]["files_scanned"] += 1
        try:
            s = parse_file(fp, start, end)
        except Exception as e:  # 单个文件坏了不影响整体
            res["warnings"].append(f"解析失败已跳过：{fp.name}（{e}）")
            continue
        if s:
            res["sessions"].append(s)
    return res
