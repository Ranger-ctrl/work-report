"""配置加载与时间窗口计算。只用标准库。"""
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

DEFAULTS = {
    "timezone": None,
    "day_start_hour": 0,
    "week_start": "monday",
    "authors": [],
    "git_roots": [],
    "git_scan_depth": 3,
    "sources": {
        "claude_code": {"enabled": True, "path": None},
        "codex": {"enabled": True, "path": None},
        "git": {"enabled": True},
    },
    "projects": [],
    "output_dir": "~/work-reports",
    "redact_patterns": [],
    "limits": {"daily": 10, "weekly": 15},
}

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def config_path():
    env = os.environ.get("WORK_REPORT_CONFIG")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".config" / "work-report" / "config.json"


def expand(p):
    return Path(os.path.expandvars(str(p))).expanduser()


def load_config(path=None):
    """读取配置并与默认值合并。文件不存在时返回 None。"""
    path = Path(path) if path else config_path()
    if not path.is_file():
        return None
    with open(path, encoding="utf-8") as f:
        user = json.load(f)
    cfg = json.loads(json.dumps(DEFAULTS))
    for k, v in user.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            for sk, sv in v.items():
                if isinstance(sv, dict) and isinstance(cfg[k].get(sk), dict):
                    cfg[k][sk].update(sv)
                else:
                    cfg[k][sk] = sv
        else:
            cfg[k] = v
    return cfg


def get_tz(name):
    """返回 (tzinfo, 警告文本)。缺 tzdata 时退回系统当前 UTC 偏移。"""
    if name:
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(name), None
        except Exception:
            pass
    offset = -(time.altzone if time.daylight and time.localtime().tm_isdst else time.timezone)
    tz = timezone(timedelta(seconds=offset))
    warn = None
    if name:
        warn = (f"无法加载时区 {name}（Windows 上通常是缺少 tzdata），"
                f"已退回系统当前偏移 {tz.tzname(None)}；夏令时切换日可能有偏差。"
                f"可执行 `pip install tzdata` 修复。")
    return tz, warn


def parse_ts(s):
    """解析 ISO 8601 时间戳（含 Z 后缀），返回带时区的 datetime。"""
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def logical_today(now, day_start_hour):
    """day_start_hour 点之前算前一天。now 须为本地时区的 aware datetime。"""
    return (now - timedelta(hours=day_start_hour)).date()


def day_window(d, tz, day_start_hour):
    start = datetime(d.year, d.month, d.day, day_start_hour, tzinfo=tz)
    nxt = d + timedelta(days=1)
    end = datetime(nxt.year, nxt.month, nxt.day, day_start_hour, tzinfo=tz)
    return start, end


def week_start_date(d, week_start="monday"):
    ws = WEEKDAYS.index(week_start)
    return d - timedelta(days=(d.weekday() - ws) % 7)


def week_label(start_date, week_start="monday"):
    """周号取这一周里那个周一所在的 ISO 周。"""
    ws = WEEKDAYS.index(week_start)
    monday = start_date + timedelta(days=(0 - ws) % 7)
    y, w, _ = monday.isocalendar()
    return f"{y}-W{w:02d}"


def parse_week_label(label, week_start="monday"):
    m = re.fullmatch(r"(\d{4})-?W(\d{1,2})", label.strip(), re.I)
    if not m:
        raise ValueError(f"无法识别的周号：{label}，应形如 2026-W45")
    monday = date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
    ws = WEEKDAYS.index(week_start)
    return monday - timedelta(days=(0 - ws) % 7)


def resolve_day(arg, today):
    """today / yesterday / -N / YYYY-MM-DD / MM-DD → date。"""
    a = (arg or "today").strip().lower()
    if a in ("today", "今天"):
        return today
    if a in ("yesterday", "昨天"):
        return today - timedelta(days=1)
    if re.fullmatch(r"-\d+", a):
        return today + timedelta(days=int(a))
    if re.fullmatch(r"\d{1,2}-\d{1,2}", a):
        m, d = map(int, a.split("-"))
        cand = date(today.year, m, d)
        return cand if cand <= today else date(today.year - 1, m, d)
    return date.fromisoformat(a)


def resolve_week(arg, today, week_start="monday"):
    """this / last / -N / 2026-W45 → 这一周的起始日期。"""
    a = (arg or "this").strip().lower()
    cur = week_start_date(today, week_start)
    if a in ("this", "本周"):
        return cur
    if a in ("last", "上周"):
        return cur - timedelta(days=7)
    if re.fullmatch(r"-\d+", a):
        return cur + timedelta(days=7 * int(a))
    return parse_week_label(a, week_start)


def stderr(msg):
    print(msg, file=sys.stderr)


def setup_io():
    """Windows 控制台默认 GBK，统一改成 UTF-8，避免中文乱码。"""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
