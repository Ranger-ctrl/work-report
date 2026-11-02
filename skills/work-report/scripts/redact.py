"""对外版脱敏：按正则替换为 ***，原地改写文件，并输出各类命中次数。

用法：python redact.py <报告文件> [--config FILE] [--check]
--check 只统计不改写。留档版不要用本脚本处理。
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import load_config, setup_io  # noqa: E402

MASK = "***"
_IP4 = r"(?<![\d.])(?:10(?:\.\d{1,3}){3}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}|192\.168(?:\.\d{1,3}){2})(?::\d{2,5})?(?![\d.]*\d)"

# (类别, 正则, 只替换的分组号；0 表示整段)。顺序有意义：连接串先于邮箱，密钥格式先于键值对
BUILTIN = [
    ("连接串", r"(?:jdbc:[a-z0-9]+:(?://)?|(?:redis|rediss|mongodb(?:\+srv)?|mysql|postgres(?:ql)?|amqp)://)[^\s`'\"<>，。）)]+", 0),
    ("密钥", r"\b(?:sk-[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}"
           r"|glpat-[A-Za-z0-9_-]{20,}|xox[abprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{35})", 0),
    ("Authorization", r"(?i)(?<=authorization)(\s*[:=：]\s*)((?:bearer|basic|token)\s+)?([^\s`'\"]+)", 3),
    ("密码/token", r"(?i)\b(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|client[_-]?secret)"
                 r"[\"']?\s*[:=：]\s*[\"']?([^\s`'\",，;；]{4,})", 1),
    ("内网 IP", _IP4, 0),
    ("邮箱", r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![\w:-])", 0),  # 后接冒号的是 SSH 地址
    ("手机号", r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)", 0),
]


def compile_rules(user_patterns=None):
    rules, warnings = [], []
    for name, pat, grp in BUILTIN:
        rules.append((name, re.compile(pat), grp))
    for p in user_patterns or []:
        name, pat = ("自定义", p) if isinstance(p, str) else (p.get("name") or "自定义", p.get("pattern"))
        try:
            rules.append((name, re.compile(pat), 0))
        except (re.error, TypeError) as e:
            warnings.append(f"redact_patterns 中的正则无效，已忽略：{pat}（{e}）")
    return rules, warnings


def redact(text, rules):
    """返回 (脱敏后文本, {类别: 次数})。"""
    counts = {}
    for name, rx, grp in rules:
        def sub(m, grp=grp):
            if grp and m.group(grp) is None:
                return m.group(0)
            if grp:
                s, e = m.start(grp) - m.start(), m.end(grp) - m.start()
                val = m.group(0)[:s] + MASK + m.group(0)[e:]
            else:
                val = MASK
            if val != m.group(0):
                counts[name] = counts.get(name, 0) + 1
            return val
        text = rx.sub(sub, text)
    return text, counts


def main(argv=None):
    setup_io()
    ap = argparse.ArgumentParser(description="对外版报告脱敏")
    ap.add_argument("file")
    ap.add_argument("--config")
    ap.add_argument("--check", action="store_true", help="只统计，不改写文件")
    a = ap.parse_args(argv)
    cfg = load_config(a.config) or {}
    rules, warnings = compile_rules(cfg.get("redact_patterns"))
    fp = Path(a.file)
    text = fp.read_text(encoding="utf-8")
    new, counts = redact(text, rules)
    if not a.check and new != text:
        fp.write_text(new, encoding="utf-8")
    print(json.dumps({"file": str(fp), "replaced": sum(counts.values()), "by_category": counts,
                      "written": not a.check and new != text, "warnings": warnings},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
