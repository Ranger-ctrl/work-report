"""Git 提交：只运行只读命令，按 hash 去重，按 origin 归并 worktree 与多份克隆。"""
import os
import re
import subprocess
from pathlib import Path

from common import expand, parse_ts

NAME = "git"
_SKIP_DIRS = {"node_modules", ".venv", "venv", "target", "build", "dist", ".gradle",
              ".idea", "__pycache__", ".cache", "vendor"}
SEP = "\x1f"


def find_repos(roots, depth):
    """找含 .git（目录或 worktree 的 .git 文件）的目录，不进入仓库内部。"""
    found = []
    for root in roots:
        root = expand(root)
        if not root.is_dir():
            continue
        stack = [(root, 0)]
        while stack:
            d, lv = stack.pop()
            if (d / ".git").exists():
                found.append(d)
                continue
            if lv >= depth:
                continue
            try:
                for c in d.iterdir():
                    if c.is_dir() and not c.name.startswith(".") and c.name not in _SKIP_DIRS:
                        stack.append((c, lv + 1))
            except OSError:
                pass
    return found


def _git(repo, *args, timeout=60):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                       timeout=timeout, encoding="utf-8", errors="replace")
    return r.stdout if r.returncode == 0 else None


def normalize_remote(url):
    """git@host:a/b.git 与 https://host/a/b 归一成 host/a/b。"""
    if not url:
        return None
    u = url.strip()
    u = re.sub(r"^[a-z+]+://", "", u)
    u = re.sub(r"^[^@/]+@", "", u)
    u = u.replace(":", "/", 1) if re.match(r"^[^/]+:[^/\d]", u) else u
    u = re.sub(r"\.git/?$", "", u).rstrip("/")
    return u.lower()


def repo_identity(repo):
    """返回 (项目键, 公共 git 目录)。公共目录用于判断多个 worktree 是否同一仓库。"""
    common = _git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    common = os.path.normcase(os.path.normpath(common.strip())) if common else str(repo)
    remote = normalize_remote(_git(repo, "remote", "get-url", "origin"))
    return remote or common, common


def _author_args(authors):
    # 多个 --author 之间是「或」关系；值按正则匹配 "名字 <邮箱>"，需转义
    return [f"--author={re.escape(a)}" for a in authors if a]


def _parse_log(out):
    commits = []
    for rec in out.split("\x1e"):
        rec = rec.strip("\n")
        if not rec:
            continue
        head, _, rest = rec.partition("\n")
        parts = head.split(SEP)
        if len(parts) < 7:
            continue
        h, ref, cdate, an, ae, parents, subj = parts[:7]
        stat = {"files": 0, "insertions": 0, "deletions": 0}
        m = re.search(r"(\d+) files? changed", rest)
        if m:
            stat["files"] = int(m.group(1))
        m = re.search(r"(\d+) insertions?", rest)
        if m:
            stat["insertions"] = int(m.group(1))
        m = re.search(r"(\d+) deletions?", rest)
        if m:
            stat["deletions"] = int(m.group(1))
        ref = re.sub(r"^refs/(heads|remotes)/", "", ref)
        commits.append({"hash": h, "ref": ref, "time": parse_ts(cdate), "author": an,
                        "email": ae, "merge": len(parents.split()) > 1, "subject": subj, **stat})
    return commits


def collect(cfg, start, end, ctx):
    res = {"source": NAME, "commits": [], "repos": {}, "warnings": [],
           "stats": {"repos_found": 0, "repos_unique": 0}}
    authors = cfg.get("authors") or []
    if not authors:
        res["warnings"].append("配置里没有 authors，无法区分本人提交，已跳过 Git。")
        return res
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        res["warnings"].append("找不到 git 命令，已跳过 Git 提交。")
        return res

    repos = find_repos(cfg.get("git_roots") or [], int(cfg.get("git_scan_depth", 3)))
    res["stats"]["repos_found"] = len(repos)
    by_common = {}  # 同一公共 git 目录的 worktree 只需跑一次 git log --all
    for repo in repos:
        try:
            key, common = repo_identity(repo)
        except Exception:
            continue
        info = by_common.setdefault(common, {"key": key, "paths": [], "branch_paths": {}})
        info["paths"].append(str(repo))
        head = (_git(repo, "rev-parse", "--abbrev-ref", "HEAD") or "").strip()
        if head and head != "HEAD":
            info["branch_paths"].setdefault(head, str(repo))
    res["stats"]["repos_unique"] = len(by_common)

    # 分隔符用 git 占位符生成，不把控制字符直接放进命令行参数
    fmt = "%x1e" + "%x1f".join(["%H", "%S", "%cI", "%an", "%ae", "%P", "%s"])
    seen = set()
    for common, info in by_common.items():
        repo = info["paths"][0]
        out = _git(repo, "log", "--all", "--source", f"--format={fmt}", "--shortstat",
                   f"--since={start.isoformat()}", f"--until={end.isoformat()}",
                   *_author_args(authors), timeout=120)
        if out is None:
            res["warnings"].append(f"git log 失败，已跳过：{repo}")
            continue
        r = res["repos"].setdefault(info["key"], {"key": info["key"], "paths": [], "branch_paths": {}})
        r["paths"].extend(info["paths"])
        r["branch_paths"].update(info["branch_paths"])
        for c in _parse_log(out):
            # --until 含端点，这里按半开区间精确过滤；不同克隆的同一提交只留一份
            if c["time"] is None or not (start <= c["time"] < end) or c["hash"] in seen:
                continue
            seen.add(c["hash"])
            c["repo"] = info["key"]
            # 检出了该分支的 worktree，用于映射项目名
            c["worktree"] = info["branch_paths"].get(c["ref"])
            res["commits"].append(c)
    res["commits"].sort(key=lambda c: c["time"])
    return res
