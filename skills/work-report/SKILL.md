---
name: work-report
description: 自动汇总当天或本周完成的工作，生成日报、周报（对外版 + 留档版）。数据来自 Claude Code 会话、Codex 会话、Git 提交和手动补充笔记。用户说「写日报」「今天的日报」「写昨天的日报」「写周报」「上周周报」「重新配置日报」，或 daily report / weekly report 时使用。
argument-hint: "[day|week|config] [today|yesterday|-N|YYYY-MM-DD|this|last|2026-W45]"
---

# 日报 / 周报生成

参数：`$ARGUMENTS`。没有参数时，根据用户原话判断是日报、周报还是重新配置，以及目标日期或周。
日期写法：`today`、`yesterday`、`-N`（N 天前）、`YYYY-MM-DD`、`MM-DD`；周的写法：`this`、`last`、`-N`、`2026-W45`。用户说中文（如「上周」「10-30」）时自行换算成以上写法。

脚本目录是 `${CLAUDE_SKILL_DIR}/scripts`。下文用 `PY` 指 Python 命令：依次试 `python3`、`python`、`py -3`，取第一个能输出 3.9 及以上版本号的（`PY --version`）。都没有时告诉用户需要安装 Python 3.9+，然后停止。

## 第 0 步：检查配置

日报运行 `PY "${CLAUDE_SKILL_DIR}/scripts/collect.py" day <日期>`，周报运行 `PY "${CLAUDE_SKILL_DIR}/scripts/collect.py" week <周>`。
如果输出是 `{"error": "no_config", ...}`，或用户要求重新配置，先完成「首次配置」一节，再回到这一步。

## 首次配置

1. 运行 `PY "${CLAUDE_SKILL_DIR}/scripts/init_config.py" detect`，得到候选配置 `candidate` 和探测结果 `found`。
2. 把探测结果用简短列表展示给用户：作者（git 用户名和邮箱）、找到的代码根目录及各自仓库数、常用会话目录、是否有 Claude Code 和 Codex 会话、时区。
3. 用 AskUserQuestion 一次问清以下几项（每项给出推荐选项，用户可选「Other」自填）：
   - 一天从几点开始算：0 点（按日历日，推荐），或凌晨 4 点（常工作到午夜之后的人）。
   - 代码根目录：用探测结果，或补充其他目录。
   - 作者：是否还有其他机器或邮箱上的提交身份。
   - 报告保存目录：默认 `~/work-reports`。提醒不要放在 git 仓库或网盘同步目录里，因为留档版不脱敏。
4. 按回答修改 `candidate`。如果用户提到要给仓库起显示名或标记私人项目，写进 `projects`（格式见 `config.example.json`）。
5. 把最终 JSON 写到临时文件，运行 `PY "${CLAUDE_SKILL_DIR}/scripts/init_config.py" write <临时文件>`，再删除临时文件。告诉用户配置文件位置，之后可直接手改。

## 日报

### 1. 采集
第 0 步的输出是摘要 JSON：`material` 是素材文件路径，`output.public` / `output.archive` 是两版报告的保存路径，`warnings` 是需要转告用户的提示（时区退回、凌晨切日、数据源缺失等），`items` 是各工作项的概况。
用 Read 读取 `material`。素材结构：
- `items[]`：工作项。每项有 `project`（显示名）、`private`（私人项目）、`unscoped`（在主目录等非项目目录里开的会话，项目名只是会话标题）、`workdirs`、`branches`、`commits[]`、`sessions[].messages[]`。
- `notes[]`：用户在 `notes/YYYY-MM-DD.md` 手写的补充，视为可信的已完成工作。
- `stats`、`truncation`、`warnings`：写进留档版末尾的采集统计。

### 2. 归并与判断
- `unscoped` 的工作项按内容判断属于哪个项目：能对上其他工作项的并进去，对不上的按内容起一个简短的业务名称。纯闲聊、查资料、配置本机工具这类与工作无关的会话，不写进对外版，在留档版「采集统计」里一句话带过。
- 同一件事分散在多个工作项（如同一仓库的多个 worktree）时合并成一条。
- 「完成」必须有证据：有提交、会话里有测试通过记录、或会话里明确说完成。只讨论过、做了一半、或报错未解决的写进「进行中」，并写清卡在哪里。
- 不编造素材里没有的内容。
- `private: true` 的项目只写进留档版。

### 3. 写两版报告
模板优先用 `<output_dir>/templates/` 下的同名文件，没有就用 `${CLAUDE_SKILL_DIR}/templates/` 里的 `daily.md`（对外版）和 `daily.archive.md`（留档版）。模板里的条目只示意格式，替换成真实内容；没有内容的小节（如「需协调」「手动补充」）整节删掉。

对外版：
- 写给领导看的业务语言，按项目分组，每条一句话，写做了什么、到什么状态。
- 不出现分支名、提交 hash、文件路径、类名、表名、SQL、命令、内部 IP 和会话 ID。
- 「今日完成」最多 `limits.daily` 条，超出时合并小事。
- 「明日计划（草稿）」根据进行中的事项、未合并的提交、被阻塞的事项推断，每条都是推断，所以标题保留「（草稿）」。
- 素材为空时只写一句「今日无采集到的工作记录」，并提示用户可以在 `<output_dir>/notes/<日期>.md` 手写补充后重新生成。

留档版：
- 条目与对外版一致（另含私人项目和无关会话的简述），每条下附仓库、分支、提交 hash 与标题、关键结论与踩坑、会话来源与 ID。
- 末尾「采集统计」如实填写 `window`、`stats`、`truncation`、`warnings`。

### 4. 保存
1. 若 `output.public_exists` 或 `output.archive_exists` 为真：先把新内容写到同目录的 `<原名>.new.md`，用 `git diff --no-index --stat` 和 `git diff --no-index` 展示与旧文件的差异（没有 git 就概述差异），再用 AskUserQuestion 问「覆盖」还是「另存为 -v2」。按回答改名或覆盖，删除 `.new.md`。不要静默覆盖。
2. 否则直接写入 `output.archive` 和 `output.public`（目录不存在先创建）。
3. 对外版脱敏：运行 `PY "${CLAUDE_SKILL_DIR}/scripts/redact.py" <对外版路径>`。输出里 `replaced` 大于 0 时，告诉用户替换了几处、属于哪些类别，并检查替换后的句子是否还通顺。留档版不脱敏。
4. 删除素材文件 `material`（它含有会话原文）。

### 5. 展示
在终端显示对外版全文，然后一行写出留档版路径。`warnings` 非空时在最后简短列出。

## 周报

### 1. 采集
第 0 步的摘要里，`days[]` 列出本周 7 天，每天有 `archive`（已保存的留档版路径，没有为 null）、`public` 和 `future`（还没到的日期）。用 Read 读 `material`，其中 `commit_stats` 是整周按项目统计的提交数。

### 2. 补生成缺失的日报
对 `archive` 为 null 且 `future` 为 false 的每一天，按「日报」第 1–4 步生成该天的两版日报并保存，但不在终端展示全文。素材为空的日子不保存文件，在周报里记为「无记录」。补生成前告诉用户要补哪几天；超过 3 天时先用 AskUserQuestion 确认，因为每天都要读一遍会话。

### 3. 汇总
- 素材是本周各天的留档版日报，用 Read 逐份读取。
- 跨多天的同一件事合并成一条，状态取最后一天的；早先「进行中」后来完成的，只写进「本周完成」。
- 模板用 `weekly.md`（对外版）和 `weekly.archive.md`（留档版），查找顺序与日报相同。
- 对外版规则同日报，「本周完成」最多 `limits.weekly` 条，「下周计划（草稿）」由仍在进行中和被阻塞的事项推断。
- 留档版附每天日报的相对链接、`commit_stats` 表格，以及本次补生成了哪几天、哪几天无记录。

### 4. 保存与展示
与日报第 4、5 步相同：重复生成时先显示差异再问，对外版跑 `redact.py`，删除素材文件，终端显示对外版全文和留档版路径。

## 注意
- 素材和留档版含会话原文，只在本机读写，不要上传、不要粘贴到其他工具。
- 采集脚本只运行只读的 git 命令；本 skill 不做任何 git 写入。
- 用户只要其中一版（如「只要对外版」）时，仍然保存两版，只展示用户要的那版。
