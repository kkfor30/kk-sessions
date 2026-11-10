---
name: kk-session-route
description: 新会话第一轮做会话归位：按工作区地图判断这次内容属于哪个分区和目录，建主题目录、切目录、按统一格式命名、归入侧栏分区。由各 Agent 的 SessionStart 钩子在新会话启动时触发；用户说"路由一下""这个会话归到哪""重新归类"时也使用。支持 Claude Code、Codex、Z Code、WorkBuddy。不用于中途换话题时自动迁移，批量整理旧会话用 kk-session-tidy。
---

# kk-session-route

## 输入

工作区地图：`~/.agent-rules/workspace-map.md`（分区、目录、判定线索、标题格式）。先读它，再判断。

## 六个动作

流程只用这 6 个动作，每个 Agent 怎么完成见下面「适配」：

| 动作 | 含义 |
| --- | --- |
| 取会话 ID | 拿到当前会话的 ID |
| 改标题 | 把当前会话标题设成指定文本 |
| 列出和新建分区 | 找到地图里的同名侧栏分区，没有就新建 |
| 移入分区 | 把当前会话放进该分区 |
| 切目录 | 把会话的工作目录换到目标目录 |
| 列出全部会话 | 取所有会话的标题、分区、目录、最后活动时间（kk-session-tidy 用） |

某个动作在当前 Agent 做不到时，统一降级：在回复里给出建议值（分区名、标题、目录），由用户手动操作。

## 流程

1. **判断归属**：根据用户第一条消息，对照地图选分区和产物目录。
   - 需要具体主题的分区，先列出该目录下已有子目录，能对上就用已有的；对不上再定一个新主题名。调研转正式选题、`_试用` 转正式项目时，整个文件夹移过去。
   - 拿不准时问用户一句，给出你的首选；不要猜着建顶层目录。
2. **建主题目录和 README**：新主题当场建目录和 `README.md`（是什么、状态：想法、下一步），子目录用到时再建。
3. **切目录**：工作目录不在目标目录内时切过去；已经在里面就跳过。一两句话能答完的问题不切目录。切不了时，本会话的产物一律写到目标目录的绝对路径。
4. **命名**：`<类型emoji> <主题>｜<这次做什么>`，emoji 后 20 字以内；类型 emoji 只从地图「标题」表的 8 个里选。
5. **归区**：移入地图里的同名分区；分区不存在就按地图名称新建。
6. **回到正题**：归位只占一句说明（"已归到 🟣 内容制作，标题 `🔍 新品测评｜竞品拆解`"），做不到的动作在同一句里给出建议，然后直接处理用户的请求。

为了少等几轮：读地图和列目标目录放在同一条消息里并行发出；判断完后，建目录、切目录、命名、列分区也放在同一条消息里，最后再归区。

## 标题锁定

- 主题第一次命名后锁定，之后不改。
- emoji 和｜后半段默认也不自动改。只有 kk-session-tidy 会对很长、阶段明显变化的会话提出改名建议，用户确认才改。
- 末尾 ` ⏳` 按地图「跟进」一节增减，这是唯一允许 Agent 自动改的部分。
- 置顶只由用户手动操作。

## 适配

按环境变量判断自己是谁，从上往下第一个命中的为准（Z Code、WorkBuddy 也会设置 `CLAUDE_SESSION_ID`，不能只看它）：

| 判断 | Agent |
| --- | --- |
| 有 `ZCODE_SESSION_ID` | Z Code |
| 有 `CODEBUDDY_SESSION_ID` 或 `WORKBUDDY_APP_VERSION` | WorkBuddy |
| 有 `CODEX_THREAD_ID` | Codex |
| 有 `mcp__ccd_*` 工具 | Claude Code 桌面端 |

### Claude Code 桌面端

| 动作 | 做法 |
| --- | --- |
| 取会话 ID | 不需要，工具都接受 `"self"` |
| 改标题 | `mcp__ccd_session_mgmt__set_session_title`，`session_id: "self"` |
| 列出和新建分区 | `mcp__ccd_sidebar__list_sections` 找同名，没有就 `create_section` |
| 移入分区 | `mcp__ccd_sidebar__move_sessions`，`session_ids: ["self"]`；当前会话嵌在父会话下时会被拒绝，此时跳过，跟随父会话 |
| 切目录 | `mcp__ccd_directory__change_directory`（用户在卡片上批准一次；本轮结束后生效，本轮写文件用绝对路径） |
| 列出全部会话 | `mcp__ccd_session_mgmt__list_sessions` |

这些工具是延迟加载的，先用 ToolSearch 一次性加载再调用。

### Codex 桌面端

| 动作 | 做法 |
| --- | --- |
| 取会话 ID | 环境变量 `CODEX_THREAD_ID` |
| 改标题 | `mcp__codex_app__set_thread_title`（省略 `threadId` 即作用于当前会话） |
| 列出和新建分区 | `list_threads` 返回的 `sections[]` 找同名，没有就 `create_sidebar_section` |
| 移入分区 | `move_thread_to_sidebar_section({threadId, hostId: "local", sectionId})`，然后用 `list_threads` 回读：正式键 `codex:thread:local:<threadId>` 出现在目标分区的 `itemKeys` 里才算成功。首轮常只移进一个 `client-new-thread` 别名，没成功就在下一轮开头补做一次并再回读 |
| 切目录 | 不支持，降级：产物写到目标目录的绝对路径，回复里建议用户在侧栏把会话移到对应项目 |
| 列出全部会话 | `list_threads`（`mode: "history"` 分页），归档用 `list_archived_threads` |

### Z Code

| 动作 | 做法 |
| --- | --- |
| 取会话 ID | 环境变量 `ZCODE_SESSION_ID` |
| 改标题 | `python ~/.skilldock/skills/kk-session-route/scripts/zcode_session.py rename --session <ID> --title "<标题>"`；写库后读回校验，失败自动恢复原标题。侧栏可能要切换分组或重启后才显示 |
| 列出和新建分区 | 不支持，降级：回复里给出建议分区名，由用户在侧栏手动分组 |
| 移入分区 | 不支持，同上 |
| 切目录 | 不支持，降级：产物写到目标目录的绝对路径 |
| 列出全部会话 | `python ~/.skilldock/skills/kk-session-route/scripts/zcode_session.py list`（只读；不含分区） |

### WorkBuddy

| 动作 | 做法 |
| --- | --- |
| 取会话 ID | 环境变量 `CODEBUDDY_SESSION_ID` |
| 改标题 | 不支持，降级：回复里给出建议标题，由用户在侧栏右键重命名 |
| 列出和新建分区 | 不支持，降级 |
| 移入分区 | 不支持，降级 |
| 切目录 | 不支持会话级切换；Bash 里 `cd` 到目标目录后跨命令保持，文件一律写绝对路径 |
| 列出全部会话 | 不支持 |

## 边界

- 只在会话第一轮归位一次。之后话题变化不自动迁移，用户要求时再重新归位。
- 已由用户手动命名或手动放入分区的会话，不覆盖用户的选择。
- fork 或旁支会话：沿用父会话的主题，只换 emoji 和这次做什么，例如 `🐛 新品测评｜导出变慢排查`。主题已和父会话不同时，提醒用户在侧栏拆成顶层会话后再归区（Agent 只能拆自己启动的会话）。
