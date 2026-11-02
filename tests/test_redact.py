import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "work-report" / "scripts"))

from redact import compile_rules, redact  # noqa: E402

POSITIVE = [
    "jdbc:mysql://10.0.0.5:3306/db?user=a&password=b",
    "redis://:pw@cache.example.com:6379/0",
    "mongodb+srv://u:p@cluster0.example.net/db",
    "密钥 sk-abcdefghijklmnop1234",
    "AKIAABCDEFGHIJKLMNOP",
    "ghp_" + "a" * 36,
    "Authorization: Bearer eyJhbGciOi.payload.sig",
    "password=hunter22",
    'api_key: "abcd1234"',
    "token：abcdEFG123",
    "访问 192.168.1.10:8080 看看",
    "172.20.3.4",
    "10.1.2.3",
    "联系 a.b@example.com",
    "手机 13812345678",
    "+86 13912345678",
]

NEGATIVE = [
    "升级到 1.10.2.3 版本",
    "v10.0.0 发布",
    "订单号 2026110212345678",
    "合计 13812 元",
    "172.32.0.1",
    "8.8.8.8",
    "password 字段改为必填",
    "192.168.1",
    "git@github.com:owner/repo.git",
    "Issue #12345678901",
    "修复 token 过期后不刷新的问题",
    "耗时 10.5 秒",
]


class RedactTest(unittest.TestCase):
    def setUp(self):
        self.rules, _ = compile_rules()

    def test_positive(self):
        for t in POSITIVE:
            out, counts = redact(t, self.rules)
            with self.subTest(t=t):
                self.assertTrue(counts, f"未命中：{t}")
                self.assertIn("***", out)

    def test_negative(self):
        for t in NEGATIVE:
            out, counts = redact(t, self.rules)
            with self.subTest(t=t):
                self.assertEqual(counts, {}, f"误报：{t} -> {out}")
                self.assertEqual(out, t)

    def test_keeps_key_name(self):
        out, _ = redact("password=hunter22", self.rules)
        self.assertEqual(out, "password=***")

    def test_user_patterns(self):
        rules, warns = compile_rules([r"EMP\d{6}", {"name": "工号", "pattern": r"W\d{5}"}, "("])
        self.assertEqual(len(warns), 1)
        out, counts = redact("EMP123456 和 W12345", rules)
        self.assertEqual(out, "*** 和 ***")
        self.assertEqual(counts, {"自定义": 1, "工号": 1})


if __name__ == "__main__":
    unittest.main()
