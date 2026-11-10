# kk-sessions

让每个新会话自动归位：判断这次任务属于哪个分区和目录，建主题目录、切目录、起统一格式的标题、放进对的侧栏分区。支持 Claude Code、Codex、Z Code、WorkBuddy 四个桌面端 Agent，各家做不到的动作降级为在回复里给建议、由你手动操作。

## 四层结构

| 层 | 文件 | 作用 |
| --- | --- | --- |
| 地图 | `templates/workspace-map.md` → `~/.agent-rules/workspace-map.md` | 唯一规则来源：分区、目录、判定线索、标题格式、跟进规则 |
| 通用流程 | `skills/kk-session-route`、`skills/kk-session-tidy` 的流程部分 | 只写做什么：判断归属 → 建目录和 README → 切目录 → 命名 → 归区 → 回到正题 |
| 适配 | 两个 Skill 的「适配」一节、`adapters/<agent>/`、`skills/kk-session-route/scripts/` | 每个 Agent 怎么完成 6 个动作：取会话 ID、改标题、列出和新建分区、移入分区、切目录、列出全部会话 |
| 触发 | `adapters/<agent>/` 里的启动钩子配置 | 新会话启动时提醒 Agent 先调用 `kk-session-route` |

| Skill | 作用 |
| --- | --- |
| `kk-session-route` | 新会话第一轮归位 |
| `kk-session-tidy` | 批量整理已有会话：补标题格式、补分区、阶段改名建议、列出待推进会话（固定用 Sonnet） |

路由在对话内由会话本身的模型完成，不调用后台模型。

## 各 Agent 能力

| | 触发 | 改名 | 分区 | 切目录 | 整理 |
| --- | --- | --- | --- | --- | --- |
| Claude Code | 自动 | 自动 | 自动 | 自动（批准一次） | 自动 |
| Codex | 自动（需先信任钩子） | 自动 | 自动（回读确认，首轮可能要下一轮补做） | 手动 | 自动 |
| Z Code | 自动（重启后生效） | 自动（脚本写库） | 手动 | 手动 | 改名自动，分区手动 |
| WorkBuddy | 自动（重启后生效） | 手动 | 手动 | 手动（产物写到目标目录） | 不支持 |

## 标题

格式 `<类型emoji> <主题>｜<这次做什么>`，例如 `🎬 新品测评｜口播精剪`。分区表示领域，开头 emoji 表示这次做哪类事，末尾 ` ⏳` 表示在等你处理。

- 主题第一次命名后锁定不变。
- emoji 和｜后半段默认不自动改；只有 `kk-session-tidy` 对很长、阶段明显变化的会话提出改名建议，你确认才改。
- 置顶只由你手动操作。

## 安装

先做通用部分：

1. 把 `skills/kk-session-route` 和 `skills/kk-session-tidy` 装进各 Agent 能读到的 Skill 目录（用共享库时装一次即可）。
2. 把 `templates/workspace-map.md` 复制到 `~/.agent-rules/workspace-map.md`，把分区、目录和判定线索改成你自己的。

再按 Agent 装启动钩子（`<HOME>` 换成你的用户目录，路径用正斜杠；示例假设 Skill 装在 `~/.skilldock/skills/`，装在别处就改路径）：

**Claude Code 桌面端**

1. 把 `adapters/claude/settings-snippet.json` 的 `SessionStart` 合并进 `~/.claude/settings.json` 的 `hooks`。
2. 可选（设置 → Claude Code）：分区的分组依据选「状态」；「归档不活跃的会话」设为 30 天。

**Codex 桌面端**

1. 把 `adapters/codex/hooks.json` 放到 `~/.codex/hooks.json`（已有就合并 `hooks`）。
2. 在「设置 → Hooks」里信任这个钩子，否则不会执行。
3. 如果装过其他自动命名插件，先停用，避免抢标题。

**Z Code**

1. 把 `adapters/zcode/hooks-snippet.json` 的 `hooks` 合并进 `~/.zcode/cli/config.json` 顶层，保留原有的 `mcp` 和 `plugins`。必须 `enabled: true`。
2. 重启 Z Code。项目级钩子在 3.17.2 里被禁用，只能放用户级。
3. 改名用 `skills/kk-session-route/scripts/zcode_session.py`，说明见 `adapters/zcode/README.md`。

**WorkBuddy**

1. 把 `adapters/workbuddy/hooks-snippet.json` 的 `hooks` 合并进 `~/.workbuddy/settings.json`，保留其余键。钩子命令在 Git Bash 里执行。
2. 重启 WorkBuddy。

装完按 `docs/验证清单.md` 在每个 Agent 新开一个会话验证。

## 用法

- **新会话**：不用做任何事，第一轮自动归位，做不到的动作会在第一句话里给出建议。
- **整理旧会话**：新开会话说"整理会话"，`kk-session-tidy` 列出建议，确认后执行。
- **待推进**：结尾留下只有你能做的事时，Agent 在标题末尾加 ⏳；办完了自己删掉即可。

## 花费

归位只在新会话第一轮执行一次，大约 5 千到 8 千 token，用会话本身的模型。`kk-session-tidy` 只读会话的标题和分区，不读聊天记录。
