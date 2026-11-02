"""会话文本清洗：去掉注入的系统文本，只留人写的和助手说的话。"""
import re

# 整段丢弃：这些标签包着的是系统注入，不是用户本人输入
_DROP_BLOCKS = re.compile(
    r"<(system-reminder|command-message|command-args|local-command-stdout|"
    r"local-command-stderr|user-prompt-submit-hook|environment_context|"
    r"user_instructions|INSTRUCTIONS|app-context|permissions instructions|"
    r"turn_aborted|bash-stdout|bash-stderr)\b[^>]*>.*?</\1\s*>",
    re.S | re.I,
)
_TAG = re.compile(r"</?[a-zA-Z_][\w-]*[^>]*>")
_WS = re.compile(r"\n{3,}")

# 整条消息丢弃的前缀：说明这条是工具或系统生成的
_SKIP_PREFIXES = (
    "# AGENTS.md instructions",
    "Caveat: The messages below were generated",
    "[Request interrupted",
    "This session is being continued from a previous conversation",
    "<command-name>",
    "Base directory for this skill:",
)


def clean(text):
    if not text:
        return ""
    t = text.strip()
    if t.startswith(_SKIP_PREFIXES):
        # 斜杠命令：保留命令名本身，例如 "/work-report week"
        m = re.search(r"<command-name>(.*?)</command-name>", t, re.S)
        if m:
            args = re.search(r"<command-args>(.*?)</command-args>", t, re.S)
            return (m.group(1).strip() + " " + (args.group(1).strip() if args else "")).strip()
        return ""
    t = _DROP_BLOCKS.sub("", t)
    t = _TAG.sub("", t)
    t = _WS.sub("\n\n", t).strip()
    return t


def clip(text, limit):
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + "\n……（中间省略 %d 字）……\n" % (len(text) - limit) + text[-half:]
