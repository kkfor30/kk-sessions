---
name: kk-session-restore
description: 撤销 kk-sessions 对侧栏做过的改动：按首次使用前存下的快照，把会话标题和所在分区恢复原样，删除 kk-sessions 新建的分区。用户说"撤销 kk-sessions 的改动""恢复会话原样""回滚会话整理""kk-session-restore"时使用，通常在运行 `python install.py --uninstall` 之前。支持 Claude Code 桌面端和 Codex 桌面端。不删除会话，不移动或删除磁盘上的文件夹。
---

# kk-session-restore

## 输入

- 快照目录：`~/.agent-rules/kk-sessions/snapshots/`，文件名 `<agent>-<YYYYMMDD-HHMMSS>.json`（`agent` 为 `claude` 或 `codex`）。默认用当前 Agent 最早的一份，那是 kk-sessions 第一次改动侧栏之前的状态；用户指定了某一份就用那份。
- 快照格式和存法见下面「快照」；六个动作的做法见 kk-session-route 的「适配」一节，这里用列出全部会话、改标题、移入分区，外加删除分区。

没有当前 Agent 的快照时，说明无法自动恢复，列出地图里的分区名，建议用户手动删除这些分区，然后结束。

## 流程

1. **读快照和现状**：并行读取快照、列出全部会话（含已归档）、列出分区。
2. **算差异**，只处理快照里有的会话：
   - 标题和快照不同 → 改回快照标题。
   - 所在分区和快照不同 → 移回快照里的分区；那个分区已不存在就移回未分组。
   - 快照里没有、现在存在的分区 → kk-sessions 新建的，列入待删除。
   - 分区 ID 还在、名字和快照不同 → kk-session-setup 对齐时改过名，改回快照里的名字。
   - 快照之后新建的会话不改标题；它们所在的分区被删除后会自动回到未分组。
3. **和用户确认**：给出几项数字（改回标题几个、移回分区几个、改回分区名哪几个、删除分区哪几个），再列出前 10 条标题改动（现在 → 恢复后）。用户明确确认才执行。
4. **先存一份当前快照**，按下面「快照」的方法存，让这次恢复本身也能撤销。
5. **执行**：先改标题，再改回分区名，然后按目标分区批量移动，最后删除待删除的分区。当前 Agent 删除不了分区时，把名字列给用户手动删。
6. **收尾**：全部成功后，把 `snapshots` 目录改名为同级的 `restored-<YYYYMMDD-HHMMSS>`，表示已恢复（安装脚本据此允许卸载；以后再用 kk-sessions 会重新存一份起点快照）。报告改了几处、哪些没成功。提醒用户：要彻底移除，就在 kk-sessions 目录运行 `python install.py --uninstall`；工作区地图 `~/.agent-rules/workspace-map.md` 会保留，不需要可自己删。

## 快照

kk-session-setup、kk-session-tidy、kk-session-route 在**第一次改动侧栏之前**都要检查快照目录：已有当前 Agent 的快照就跳过，没有就存一份。本 Skill 在恢复前也存一份。

存法：列出全部会话（含已归档）和分区，写成 JSON。会话超过 100 个时，只记最近 30 天活动过的会话加上本次要改动的会话；恢复本来就只处理快照里记过的会话：

```json
{
  "agent": "claude",
  "created": "2026-11-11T09:30:00+08:00",
  "sections": [{"id": "cg-…", "name": "🟣 内容制作"}],
  "sessions": [{"id": "local_…", "title": "原标题", "section": "cg-…或 null", "archived": false}]
}
```

只记标题、分区和是否归档，不记聊天内容。

## 边界

- 不删除会话，不归档或取消归档，不改置顶。
- 不移动、不删除磁盘上的文件夹：kk-session-route 建的主题目录里可能已经有产物。需要清理时列出快照之后新建、只有 `README.md` 的目录，让用户自己决定。
