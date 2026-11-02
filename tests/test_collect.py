"""用临时目录构造仓库、worktree 和会话文件，端到端跑 collect_day。"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "work-report" / "scripts"))

import collect  # noqa: E402
from common import DEFAULTS  # noqa: E402

CST = timezone(timedelta(hours=8))
HAS_GIT = shutil.which("git") is not None


def git(repo, *args, when=None):
    env = dict(os.environ, GIT_AUTHOR_NAME="tester", GIT_AUTHOR_EMAIL="t@example.com",
               GIT_COMMITTER_NAME="tester", GIT_COMMITTER_EMAIL="t@example.com")
    if when:
        env.update(GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=env)


def jsonl(fp, rows):
    fp.parent.mkdir(parents=True, exist_ok=True)
    # 故意用带空格的默认格式，确认粗筛不依赖紧凑写法
    fp.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def cc_row(role, text, ts, cwd, sid="s1", **kw):
    return {"type": role, "timestamp": ts, "cwd": cwd, "sessionId": sid, "gitBranch": "main",
            "message": {"role": role, "content": text}, **kw}


class CollectDayTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cfg = json.loads(json.dumps(DEFAULTS))
        self.cfg.update(day_start_hour=4, authors=["tester"], git_roots=[str(self.tmp / "code")],
                        output_dir=str(self.tmp / "out"))
        self.cfg["sources"]["claude_code"]["path"] = str(self.tmp / "cc")
        self.cfg["sources"]["codex"]["path"] = str(self.tmp / "codex")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @unittest.skipUnless(HAS_GIT, "需要 git")
    def test_worktrees_dedup_and_grouping(self):
        repo = self.tmp / "code" / "app"
        repo.mkdir(parents=True)
        git(repo, "init", "-q", "-b", "main")
        git(repo, "remote", "add", "origin", "git@example.com:team/app.git")
        (repo / "a.txt").write_text("1")
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "主线提交", when="2026-11-02T10:00:00+08:00")
        for i in range(5):  # 5 个 worktree 共享同一提交，只应出现一次
            git(repo, "worktree", "add", "-q", "-b", f"wt{i}", str(self.tmp / "code" / f"app-wt{i}"))
        wt0 = self.tmp / "code" / "app-wt0"
        (wt0 / "b.txt").write_text("2")
        git(wt0, "add", ".")
        git(wt0, "commit", "-qm", "分支提交", when="2026-11-03T02:00:00+08:00")  # 凌晨 2 点仍属 11-02
        git(repo, "commit", "-q", "--allow-empty", "-m", "次日提交", when="2026-11-03T05:00:00+08:00")

        jsonl(self.tmp / "cc" / "p1" / "s1.jsonl", [
            cc_row("user", "修一下登录", "2026-11-02T03:00:00Z", str(wt0), branch="wt0"),
            cc_row("assistant", "已修复", "2026-11-02T03:05:00Z", str(wt0)),
            cc_row("user", "写日报", "2026-11-02T09:00:00Z", str(wt0)),
            cc_row("assistant", "日报如下", "2026-11-02T09:01:00Z", str(wt0)),
            cc_row("user", "子代理消息", "2026-11-02T03:00:00Z", str(wt0), isSidechain=True),
        ])
        jsonl(self.tmp / "cc" / "p2" / "s2.jsonl", [
            cc_row("user", "查个资料", "2026-11-02T04:00:00Z", str(Path.home()), sid="s2"),
            {"type": "ai-title", "aiTitle": "查资料"},
        ])
        data = collect.collect_day(self.cfg, date(2026, 11, 2), CST)

        subjects = sorted(c["subject"] for i in data["items"] for c in i["commits"])
        self.assertEqual(subjects, ["主线提交", "分支提交"])
        self.assertEqual(data["stats"]["git"]["repos_unique"], 1)
        self.assertEqual(data["stats"]["git"]["repos_found"], 6)

        wt_item = next(i for i in data["items"] if any(c["subject"] == "分支提交" for c in i["commits"]))
        texts = [m["text"] for s in wt_item["sessions"] for m in s["messages"]]
        self.assertEqual(texts, ["修一下登录", "已修复"])  # 写日报请求和子代理消息被去掉

        home_item = next(i for i in data["items"] if i["unscoped"])
        self.assertEqual(home_item["project"], "查资料")

    def test_empty_sources(self):
        self.cfg["git_roots"] = []
        data = collect.collect_day(self.cfg, date(2026, 11, 2), CST)
        self.assertEqual(data["items"], [])
        self.assertTrue(any("Claude Code" in w for w in data["warnings"]))

    def test_codex(self):
        self.cfg["git_roots"] = []
        jsonl(self.tmp / "codex" / "2026" / "11" / "02" / "rollout-x.jsonl", [
            {"type": "session_meta", "payload": {"id": "cx1", "cwd": str(self.tmp / "proj")}},
            {"type": "response_item", "timestamp": "2026-11-02T02:00:00Z",
             "payload": {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "系统指令"}]}},
            {"type": "response_item", "timestamp": "2026-11-02T02:00:01Z",
             "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "加个导出"}]}},
        ])
        data = collect.collect_day(self.cfg, date(2026, 11, 2), CST)
        msgs = [m["text"] for i in data["items"] for s in i["sessions"] for m in s["messages"]]
        self.assertEqual(msgs, ["加个导出"])


if __name__ == "__main__":
    unittest.main()
