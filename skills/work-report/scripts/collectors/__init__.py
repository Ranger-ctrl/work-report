"""数据源采集器。每个模块提供 collect(cfg, start, end, ctx) -> dict。

返回结构：
  {"source": 名称, "sessions": [...], "commits": [...], "notes": [...], "warnings": [...], "stats": {...}}
会话结构：
  {"source", "session_id", "title", "workdir", "branch", "first", "last",
   "messages": [{"time", "role": "user"|"assistant", "text"}]}
"""
