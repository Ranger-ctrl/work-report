"""手动补充：<output_dir>/notes/YYYY-MM-DD.md，记录会议、沟通等不在电脑上留痕的工作。"""
from datetime import timedelta

from common import expand

NAME = "notes"


def collect(cfg, start, end, ctx):
    res = {"source": NAME, "notes": [], "warnings": [], "stats": {"files": 0}}
    d, last = ctx["first_day"], ctx["last_day"]
    notes_dir = expand(cfg["output_dir"]) / "notes"
    while d <= last:
        fp = notes_dir / f"{d.isoformat()}.md"
        if fp.is_file():
            text = fp.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                res["notes"].append({"date": d.isoformat(), "path": str(fp), "text": text})
                res["stats"]["files"] += 1
        d += timedelta(days=1)
    return res
