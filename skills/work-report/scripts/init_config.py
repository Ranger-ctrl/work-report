"""首次配置。

  python init_config.py detect            探测环境，输出候选配置 JSON（不写文件）
  python init_config.py write FILE        把确认后的配置 JSON（FILE 为 - 时读 stdin）写入配置路径
"""
import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DEFAULTS, config_path, setup_io  # noqa: E402
from collectors import claude_code, codex  # noqa: E402
from collectors.git_commits import find_repos  # noqa: E402

COMMON_DIRS = ["code", "projects", "src", "workspace", "workspaces", "IdeaProjects", "repos",
               "dev", "git", "work", "Developer", "Documents/GitHub", "source/repos"]
# Windows 时区名 → IANA，只收常见的；查不到时 timezone 留空，运行时用系统偏移
WIN_TZ = {
    "China Standard Time": "Asia/Shanghai", "Taipei Standard Time": "Asia/Taipei",
    "Tokyo Standard Time": "Asia/Tokyo", "Korea Standard Time": "Asia/Seoul",
    "Singapore Standard Time": "Asia/Singapore", "India Standard Time": "Asia/Kolkata",
    "GMT Standard Time": "Europe/London", "W. Europe Standard Time": "Europe/Berlin",
    "Romance Standard Time": "Europe/Paris", "Eastern Standard Time": "America/New_York",
    "Central Standard Time": "America/Chicago", "Mountain Standard Time": "America/Denver",
    "Pacific Standard Time": "America/Los_Angeles", "UTC": "UTC",
}


def _run(*cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=15)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def detect_timezone():
    if os.environ.get("TZ") and "/" in os.environ["TZ"]:
        return os.environ["TZ"].lstrip(":")
    if sys.platform == "win32":
        return WIN_TZ.get(_run("tzutil", "/g"))
    lt = Path("/etc/localtime")
    try:
        target = str(lt.resolve())
        if "zoneinfo/" in target:
            return target.split("zoneinfo/", 1)[1]
    except OSError:
        pass
    tzfile = Path("/etc/timezone")
    if tzfile.is_file():
        return tzfile.read_text(encoding="utf-8").strip() or None
    return None


def _first_cwd(fp):
    with open(fp, encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f):
            if '"cwd"' in line:
                try:
                    return json.loads(line).get("cwd")
                except ValueError:
                    pass
            if i > 200:
                return None
    return None


def _repo_root(p):
    p = Path(p)
    for d in [p, *p.parents]:
        if (d / ".git").exists():
            return d
    return None


def recent_workdirs(days=30):
    """近 N 天 Claude Code 与 Codex 会话的工作目录及次数。"""
    since = time.time() - days * 86400
    cnt = Counter()
    roots = [claude_code.default_path().glob("*/*.jsonl"), codex.default_path().glob("*/*/*/*.jsonl")]
    for files in roots:
        for fp in files:
            try:
                if fp.stat().st_mtime < since:
                    continue
                cwd = _first_cwd(fp)
            except OSError:
                continue
            if cwd:
                cnt[os.path.normpath(cwd)] += 1
    return cnt


def suggest_roots(workdirs):
    """候选扫描根目录：主目录下常见代码目录 + 会话目录所在仓库的上一级。"""
    home = Path.home()
    roots = {}
    for name in COMMON_DIRS:
        d = home / name
        if d.is_dir():
            roots[os.path.normpath(str(d))] = "常见代码目录"
    for wd, n in workdirs.most_common(30):
        repo = _repo_root(wd)
        if repo is None or repo == home:
            continue
        parent = os.path.normpath(str(repo.parent))
        if os.path.normcase(parent) == os.path.normcase(str(home)):
            parent = os.path.normpath(str(repo))
        if not any(os.path.normcase(parent).startswith(os.path.normcase(r) + os.sep)
                   or os.path.normcase(parent) == os.path.normcase(r) for r in roots):
            roots[parent] = f"近 30 天会话目录（{n} 次）"
    return roots


def detect():
    authors = [v for v in (_run("git", "config", "--global", "user.name"),
                           _run("git", "config", "--global", "user.email")) if v]
    workdirs = recent_workdirs()
    roots = suggest_roots(workdirs)
    root_info = [{"path": r, "reason": why, "repos": len(find_repos([r], 3))} for r, why in roots.items()]
    cfg = json.loads(json.dumps(DEFAULTS))
    cfg.update(timezone=detect_timezone(), authors=authors,
               git_roots=[r["path"] for r in root_info if r["repos"]])
    return {
        "config_path": str(config_path()),
        "config_exists": config_path().is_file(),
        "candidate": cfg,
        "found": {
            "git_installed": bool(_run("git", "--version")),
            "git_roots": root_info,
            "claude_code_sessions": claude_code.default_path().is_dir(),
            "codex_sessions": codex.default_path().is_dir(),
            "top_workdirs": [{"path": p, "sessions": n} for p, n in workdirs.most_common(10)],
        },
        "ask": ["authors 是否完整（多台机器、多个邮箱都要列上）",
                "git_roots 是否要增删",
                "day_start_hour：0（按日历日）还是 4 等（常工作到午夜之后）",
                "output_dir 放哪里（不要放进 git 仓库或网盘同步目录）",
                "projects：是否要给仓库起显示名、标记私人项目"],
    }


def write(src):
    data = json.loads(sys.stdin.read() if src == "-" else Path(src).read_text(encoding="utf-8"))
    h = data.get("day_start_hour", 0)
    if not isinstance(h, int) or not 0 <= h <= 12:
        raise SystemExit("day_start_hour 必须是 0–12 的整数")
    fp = config_path()
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"written": str(fp)}


def main(argv=None):
    setup_io()
    ap = argparse.ArgumentParser(description="work-report 首次配置")
    ap.add_argument("action", choices=["detect", "write"])
    ap.add_argument("file", nargs="?", default="-")
    a = ap.parse_args(argv)
    out = detect() if a.action == "detect" else write(a.file)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
