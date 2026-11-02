"""把会话和提交归并为工作项，并按配置映射项目显示名。"""
import fnmatch
import os
from pathlib import Path, PurePath


def _norm(p):
    return os.path.normcase(os.path.normpath(p)).replace("\\", "/") if p else ""


def match_project(rules, *candidates):
    """按顺序匹配规则，返回 (显示名, private)。candidates 是目录名、路径、remote 等。"""
    cands = [c for c in candidates if c]
    for rule in rules or []:
        pat = rule.get("match", "")
        for c in cands:
            c2 = c.replace("\\", "/")
            if fnmatch.fnmatch(c2.lower(), pat.lower()) or \
               fnmatch.fnmatch(PurePath(c2).name.lower(), pat.lower()):
                return rule.get("name") or pat, bool(rule.get("private"))
    return None, False


def _repo_for_dir(workdir, repo_paths):
    """workdir 落在哪个仓库目录下（取最长前缀），返回 (仓库键, 该 worktree 路径)。"""
    w = _norm(workdir)
    best, best_path, best_len = None, None, -1
    for key, paths in repo_paths.items():
        for p in paths:
            n = _norm(p)
            if (w == n or w.startswith(n + "/")) and len(n) > best_len:
                best, best_path, best_len = key, p, len(n)
    return best, best_path


def build_items(sessions, commits, repos, rules):
    """工作项键：能落到某个仓库的用仓库键，否则用会话的工作目录。"""
    repo_paths = {k: v["paths"] for k, v in repos.items()}
    items = {}

    def item(key, label_cands):
        if key not in items:
            name, private = match_project(rules, *label_cands)
            items[key] = {"key": key, "project": name, "private": private,
                          "sessions": [], "commits": [], "branches": set(), "workdirs": set()}
        return items[key]

    for c in commits:
        info = repos.get(c["repo"], {})
        # 先用检出该分支的 worktree 定项目，同仓库不同 worktree 可能属于不同项目
        paths = info.get("paths", [])
        # 仓库只有一份检出时，分支没检出也能确定目录，键与会话保持一致
        wt = c.get("worktree") or (paths[0] if len(paths) == 1 else None)
        if wt:
            it = item(c["repo"] + "#" + _norm(wt), [wt, c["repo"]])
        else:
            it = item(c["repo"], [c["repo"], *info.get("paths", [])])
        it["commits"].append(c)
        if c.get("ref"):
            it["branches"].add(c["ref"])
        it["workdirs"].update(info.get("paths", []))

    home = _norm(str(Path.home()))
    for s in sessions:
        wd = s.get("workdir")
        repo, wt = (_repo_for_dir(wd, repo_paths) if wd else (None, None))
        if repo:
            # 与提交用同一个键，才能把会话和它产生的提交归到一起
            it = item(repo + "#" + _norm(wt), [wt, wd, repo])
        elif not wd or _norm(wd) == home:
            # 在家目录里开的会话彼此无关，各自成项，由模型按内容归类
            it = item("session:" + s["session_id"], [])
            it["project"] = it["project"] or s.get("title") or "未归类会话"
            it["unscoped"] = True
        else:
            it = item(_norm(wd), [wd])
        it["sessions"].append(s)
        if s.get("branch"):
            it["branches"].add(s["branch"])
        if s.get("workdir"):
            it["workdirs"].add(s["workdir"])

    out = []
    for it in items.values():
        if not it["project"]:
            it["project"] = PurePath(it["key"].replace("\\", "/")).name or it["key"]
        it["branches"] = sorted(it["branches"])
        it["workdirs"] = sorted(it["workdirs"])
        times = [m["time"] for s in it["sessions"] for m in s["messages"]] + \
                [c["time"] for c in it["commits"]]
        it["first"], it["last"] = min(times), max(times)
        out.append(it)
    out.sort(key=lambda i: i["first"])
    return out
