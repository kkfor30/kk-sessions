# kk-sessions

让每个新会话自动归位：判断这次任务属于哪个分区和目录，建主题目录、切目录、起统一格式的标题、放进对的侧栏分区。支持 Claude Code 桌面端和 Codex 桌面端。

## 三步上手

**1. 安装**：把这句话发给 Claude Code 或 Codex：

> 安装 https://github.com/kkfor30/kk-sessions ：clone 到本地后运行 `python install.py`

或者自己执行：

```bash
git clone https://github.com/kkfor30/kk-sessions.git
cd kk-sessions
python install.py
```

脚本会检测本机的 `~/.claude` 和 `~/.codex`，给每个 Agent 装入三个 Skill、新会话启动钩子和一小段跟进规则。可以重复执行，不会重复添加。用 Codex 的话，装完要在「设置 → Hooks」里信任这个钩子。

**2. 初始化**：新开一个会话，说「初始化会话分区」。`kk-session-setup` 会读你现有会话的标题和目录，拟一套分区和对应目录，你确认后写入 `~/.agent-rules/workspace-map.md`，并在侧栏建好分区。之后可以接着说「整理会话」，把旧会话一次归好。

**3. 日常**：什么都不用做。每个新会话的第一轮会自动归位，并用一句话告诉你归到了哪里。

## 三个 Skill

| Skill | 什么时候用 |
| --- | --- |
| `kk-session-setup` | 第一次使用、重新规划分区时：生成工作区地图、建侧栏分区 |
| `kk-session-route` | 新会话第一轮自动归位：判断分区和目录、建目录和 README、切目录、命名、归区 |
| `kk-session-tidy` | 说「整理会话」时：补标题格式和分区、对长会话提改名建议、列出待推进的会话 |

工作区地图是唯一的规则来源，改分区或目录只改这一个文件。

## 各 Agent 能力

| | 触发 | 改名 | 分区 | 切目录 |
| --- | --- | --- | --- | --- |
| Claude Code 桌面端 | 自动 | 自动 | 自动 | 自动（批准一次） |
| Codex 桌面端 | 自动（需先信任钩子） | 自动 | 自动（首轮可能要下一轮补做） | 手动：产物写到目标目录 |

做不到的动作会在回复里给出建议，由你手动操作。Claude Code 命令行没有侧栏，只给建议。

## 标题

格式 `<类型emoji> <主题>｜<这次做什么>`，例如 `🎬 新品测评｜口播精剪`。侧栏分区表示领域，开头 emoji 表示这次做哪类事，末尾 ` ⏳` 表示在等你处理。

- 主题第一次命名后锁定不变。
- emoji 和｜后半段默认不自动改；只有 `kk-session-tidy` 对很长、阶段明显变化的会话提出改名建议，你确认才改。
- 回复结尾留下只有你能做的事时，Agent 在标题末尾加 ⏳；办完了你自己删掉即可。
- 置顶只由你手动操作。

## 安装选项

```bash
python install.py --agents codex    # 只装某个 Agent
python install.py --dry-run         # 只打印将要做的事
python install.py --uninstall       # 卸载
```

- 自己维护共享 Skill 库时，加 `--skills-dir <目录>` 把 Skill 装到那里，钩子会指向它；Skill 已经另行装好时再加 `--no-skills`。
- 全局规则里已经写了跟进规则时，加 `--no-rules`。
- 首次修改配置前，会把原文件备份为 `<文件名>.kk-sessions.bak`。卸载只移除本项目写入的部分，工作区地图保留。
- 需要 Python 3.8 以上。

## 写入了哪些文件

| | Claude Code | Codex |
| --- | --- | --- |
| Skill | `~/.claude/skills/` | `~/.codex/skills/` |
| 启动钩子 | `~/.claude/settings.json` | `~/.codex/hooks.json` |
| 跟进规则 | `~/.claude/CLAUDE.md` | `~/.codex/AGENTS.md` |
| 工作区地图 | `~/.agent-rules/workspace-map.md`（初始化时生成，两边共用） | |

跟进规则在两段 `<!-- kk-sessions -->` 标记之间，卸载时整段删除。

## 花费

归位只在新会话第一轮执行一次，大约 5 千到 8 千 token，用会话本身的模型。`kk-session-setup` 和 `kk-session-tidy` 只读会话的标题、目录和分区，不读聊天记录。

装完可以按 `docs/验证清单.md` 逐项验收。
