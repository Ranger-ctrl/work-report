"""采集入口。不调用模型，只输出素材。

用法：
  python collect.py day [today|yesterday|-N|YYYY-MM-DD|MM-DD] [--out FILE]
  python collect.py week [this|last|-N|2026-W45] [--out FILE]
day 输出一天的工作素材；week 输出本周每天的日报留档状态和整周提交统计。
"""
import argparse
import json
import re
import sys
import tempfile
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (config_path, day_window, expand, get_tz, load_config, logical_today,  # noqa: E402
                    resolve_day, resolve_week, setup_io, week_label)
from collectors import claude_code, codex, git_commits, notes  # noqa: E402
from grouping import build_items  # noqa: E402

ITEM_LIMIT = 8000
TOTAL_LIMIT = 60000
WEEKDAY_CN = "一二三四五六日"
# 生成报告的请求本身不算工作内容
TRIGGER = re.compile(r"^\s*(/?work-report\b.*|.{0,20}(写|生成|出)(一下|一份|个)?.{0,8}(日报|周报).{0,20}|"
                     r"(daily|weekly) report.{0,20})\s*$", re.I | re.S)


def _compact(session):
    """会话太长时，只保留用户输入和每轮最后一段助手回复。"""
    kept, pending = [], None
    for m in session["messages"]:
        if m["role"] == "user":
            if pending:
                kept.append(pending)
                pending = None
            kept.append(m)
        else:
            pending = m
    if pending:
        kept.append(pending)
    return kept


def _size(item):
    return sum(len(m["text"]) for s in item["sessions"] for m in s["messages"])


def shrink(items):
    notes_ = []
    for it in items:
        if _size(it) > ITEM_LIMIT:
            for s in it["sessions"]:
                s["messages"] = _compact(s)
            notes_.append(f"「{it['project']}」会话较长，只保留了用户输入和每轮最后一段回复")
        for s in it["sessions"]:
            for m in s["messages"]:
                if len(m["text"]) > 2000:
                    m["text"] = m["text"][:1000] + "\n……（省略）……\n" + m["text"][-1000:]
    total = 0
    for it in sorted(items, key=_size):  # 小的工作项优先完整保留
        sz = _size(it)
        if total + sz > TOTAL_LIMIT:
            budget = max(TOTAL_LIMIT - total, 2000)
            for s in it["sessions"]:
                s["messages"] = [m for m in s["messages"] if m["role"] == "user"]
            while _size(it) > budget and any(s["messages"] for s in it["sessions"]):
                biggest = max(it["sessions"], key=lambda s: len(s["messages"]))
                biggest["messages"].pop(len(biggest["messages"]) // 2)
            notes_.append(f"总素材超出上限，「{it['project']}」只保留了部分用户输入")
            sz = _size(it)
        total += sz
    return notes_


def drop_report_requests(sessions):
    """去掉「写日报」请求及其后的回复，直到下一条正常的用户输入。"""
    out = []
    for s in sessions:
        kept, skipping = [], False
        for m in s["messages"]:
            if m["role"] == "user":
                skipping = bool(TRIGGER.match(m["text"]))
            if not skipping:
                kept.append(m)
        if any(m["role"] == "user" for m in kept):
            s["messages"] = kept
            out.append(s)
    return out


def _iso(dt, tz):
    return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M")


def serialize(items, tz):
    res = []
    for it in items:
        res.append({
            "project": it["project"],
            "private": it["private"],
            "unscoped": it.get("unscoped", False),
            "key": it["key"],
            "workdirs": it["workdirs"],
            "branches": it["branches"],
            "time_range": [_iso(it["first"], tz), _iso(it["last"], tz)],
            "commits": [{"hash": c["hash"][:10], "time": _iso(c["time"], tz), "ref": c["ref"],
                         "subject": c["subject"], "merge": c["merge"], "files": c["files"],
                         "insertions": c["insertions"], "deletions": c["deletions"]}
                        for c in it["commits"]],
            "sessions": [{"source": s["source"], "session_id": s["session_id"], "title": s["title"],
                          "branch": s["branch"],
                          "messages": [{"time": m["time"].astimezone(tz).strftime("%H:%M"),
                                        "role": m["role"], "text": m["text"]} for m in s["messages"]]}
                         for s in it["sessions"]],
        })
    return res


def collect_day(cfg, d, tz):
    start, end = day_window(d, tz, cfg["day_start_hour"])
    ctx = {"first_day": d, "last_day": d}
    warnings, stats, sessions, commits, repos, note_list = [], {}, [], [], {}, []
    for mod in (claude_code, codex, git_commits, notes):
        src_cfg = cfg["sources"].get(mod.NAME, {"enabled": True})
        if mod.NAME != "notes" and not src_cfg.get("enabled", True):
            continue
        r = mod.collect(cfg, start, end, ctx)
        warnings += r.get("warnings", [])
        stats[mod.NAME] = r.get("stats", {})
        sessions += r.get("sessions", [])
        commits += r.get("commits", [])
        repos.update(r.get("repos", {}))
        note_list += r.get("notes", [])
    sessions = drop_report_requests(sessions)
    for name in ("claude_code", "codex"):
        ss = [s for s in sessions if s["source"] == name]
        if name in stats:
            stats[name].update(sessions=len(ss), messages=sum(len(s["messages"]) for s in ss))
    if "git" in stats:
        stats["git"]["commits"] = len(commits)
    items = build_items(sessions, commits, repos, cfg.get("projects"))
    trunc = shrink(items)
    return {
        "kind": "day",
        "date": d.isoformat(),
        "weekday": "周" + WEEKDAY_CN[d.weekday()],
        "window": [start.isoformat(), end.isoformat()],
        "items": serialize(items, tz),
        "notes": note_list,
        "stats": stats,
        "truncation": trunc,
        "warnings": warnings,
    }


def report_paths(cfg, kind, label):
    base = expand(cfg["output_dir"]) / ("daily" if kind == "day" else "weekly")
    return base / f"{label}.md", base / f"{label}.archive.md"


def collect_week(cfg, ws, tz, today):
    days = [ws + timedelta(days=i) for i in range(7)]
    out_days = []
    for d in days:
        pub, arc = report_paths(cfg, "day", d.isoformat())
        out_days.append({"date": d.isoformat(), "weekday": "周" + WEEKDAY_CN[d.weekday()],
                         "future": d > today, "archive": str(arc) if arc.is_file() else None,
                         "public": str(pub) if pub.is_file() else None})
    start, _ = day_window(days[0], tz, cfg["day_start_hour"])
    _, end = day_window(days[-1], tz, cfg["day_start_hour"])
    g = git_commits.collect(cfg, start, end, {}) if cfg["sources"]["git"].get("enabled", True) \
        else {"commits": [], "warnings": []}
    per = Counter()
    for c in g["commits"]:
        per[build_items([], [c], g["repos"], cfg.get("projects"))[0]["project"]] += 1
    return {"kind": "week", "week": week_label(ws, cfg["week_start"]),
            "range": [days[0].isoformat(), days[-1].isoformat()], "days": out_days,
            "commit_stats": dict(per.most_common()), "warnings": g["warnings"]}


def main(argv=None):
    setup_io()
    ap = argparse.ArgumentParser(description="采集日报/周报素材")
    ap.add_argument("kind", choices=["day", "week"])
    ap.add_argument("when", nargs="?", default=None)
    ap.add_argument("--out", help="素材 JSON 输出路径，默认写到系统临时目录")
    ap.add_argument("--config", help="配置文件路径")
    ap.add_argument("--now", help="测试用：覆盖当前时间（ISO 8601）")
    a = ap.parse_args(argv)

    cfg = load_config(a.config)
    if cfg is None:
        print(json.dumps({"error": "no_config", "config_path": str(a.config or config_path())},
                         ensure_ascii=False))
        return 2
    tz, tz_warn = get_tz(cfg.get("timezone"))
    now = datetime.fromisoformat(a.now).astimezone(tz) if a.now else datetime.now(tz)
    today = logical_today(now, cfg["day_start_hour"])

    if a.kind == "day":
        d = resolve_day(a.when, today)
        data = collect_day(cfg, d, tz)
        label = d.isoformat()
        if d == today and now.date() != today:
            data["warnings"].insert(0, f"现在是 {now:%m-%d %H:%M}，早于每天 {cfg['day_start_hour']} 点的切日时间，"
                                       f"所以生成的是 {d:%m-%d} 的日报。")
    else:
        ws = resolve_week(a.when, today, cfg["week_start"])
        data = collect_week(cfg, ws, tz, today)
        label = data["week"]
    if tz_warn:
        data["warnings"].insert(0, tz_warn)
    pub, arc = report_paths(cfg, a.kind, label)
    data["output"] = {"public": str(pub), "archive": str(arc),
                      "public_exists": pub.is_file(), "archive_exists": arc.is_file()}
    data["limits"] = cfg["limits"]
    data["generated_at"] = now.isoformat(timespec="seconds")

    out = Path(a.out) if a.out else Path(tempfile.gettempdir()) / f"work-report-{a.kind}-{label}.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    summary = {"material": str(out), "label": label, "output": data["output"],
               "warnings": data["warnings"]}
    if a.kind == "day":
        summary["items"] = [f"{i['project']}{'（私人）' if i['private'] else ''}："
                            f"{len(i['sessions'])} 个会话，{len(i['commits'])} 个提交" for i in data["items"]]
        summary["notes"] = len(data["notes"])
        summary["stats"] = data["stats"]
    else:
        summary["days"] = data["days"]
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
