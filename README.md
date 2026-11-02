# work-report：日报/周报生成系统

一个 Claude Code skill。说一句「写日报」，它会找出你今天在 Claude Code、Codex 里做过的事和提交过的 Git 记录，整理成两版日报：

- **对外版**：业务语言，给领导看，自动脱敏。
- **留档版**：附仓库、分支、提交、踩坑记录和会话来源，只存本机。

周报汇总本周已保存的日报，缺哪天先补生成哪天。

## 环境要求

- Claude Code
- Python 3.9 及以上（只用标准库，无需安装依赖）
- Git（可选，没有就不采集提交）
- Windows 用户建议 `pip install tzdata`，否则时区按系统当前偏移计算

## 安装

方式一：作为插件安装（推荐）

```
/plugin marketplace add Ranger-ctrl/work-report
/plugin install work-report@work-report
```

方式二：手动复制

把仓库里的 `skills/work-report` 目录复制到 `~/.claude/skills/work-report`。

## 使用

| 说法 | 结果 |
|---|---|
| 写日报 | 今天的日报 |
| 写昨天的日报 / 写 10-30 的日报 | 指定日期的日报 |
| 写周报 | 本周周报 |
| 写上周的周报 | 上周周报 |
| 重新配置日报 | 重新进入首次配置 |

也可以用斜杠命令，例如 `/work-report day yesterday`、`/work-report week last`。插件安装时命令可能带前缀（如 `/work-report:work-report`），以输入 `/` 后的补全列表为准。

第一次使用时会自动探测 Git 作者、代码目录、会话记录和时区，问几个问题后写入配置。

## 配置

配置文件在 `~/.config/work-report/config.json`，可用环境变量 `WORK_REPORT_CONFIG` 指定其他位置。完整示例见 [config.example.json](skills/work-report/config.example.json)。

| 键 | 含义 |
|---|---|
| `timezone` | 时区，如 `Asia/Shanghai` |
| `day_start_hour` | 一天从几点开始算。0 为按日历日；常熬夜的人可设 4，凌晨 4 点前的工作算前一天 |
| `week_start` | 一周从哪天开始，默认 `monday` |
| `authors` | 你的 Git 用户名或邮箱，用来筛出本人提交，多个身份都要列上 |
| `git_roots` / `git_scan_depth` | 在哪些目录下找 Git 仓库，往下找几层 |
| `sources` | 各数据源的开关和路径 |
| `projects` | 仓库或目录到项目显示名的映射，`private: true` 的项目只进留档版 |
| `output_dir` | 报告保存目录 |
| `redact_patterns` | 追加的脱敏正则 |
| `limits` | 对外版条数上限 |

## 手动补充

会议、沟通这类电脑上没留痕的工作，写进 `<output_dir>/notes/YYYY-MM-DD.md`，生成日报时会一起汇总。

## 报告存放

```
<output_dir>/
  daily/2026-11-02.md            对外版
  daily/2026-11-02.archive.md    留档版
  weekly/2026-W45.md
  weekly/2026-W45.archive.md
  notes/2026-11-02.md            手动补充
  templates/                     自定义模板（可选，同名文件覆盖内置模板）
```

同一天重复生成时，会先显示和旧文件的差异，再问你覆盖还是另存。

## 隐私

- 所有采集和生成都在本机完成，脚本不联网。生成报告时，素材会作为对话内容发给你正在使用的 Claude 模型，与平时使用 Claude Code 相同。
- 留档版不脱敏，含会话原文摘录。**不要把 `output_dir` 放进 Git 仓库或网盘同步目录。**
- 脱敏只覆盖常见格式（密钥、连接串、内网 IP、邮箱、手机号），发出前请自己再看一遍对外版。

## 已知限制

- Claude Code 与 Codex 的会话文件格式不是公开接口，版本升级后可能需要适配。解析失败的文件会跳过并提示，不会中断。
- 只统计本机的会话；其他电脑上的工作需要用 notes 补充。

## 许可证

MIT
