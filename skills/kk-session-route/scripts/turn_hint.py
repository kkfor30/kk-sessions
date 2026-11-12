"""UserPromptSubmit 钩子（Claude Code、Codex）：已归位的会话，每轮开头提醒模型按当前标题维护 ⏳。

- 标题还不是 `<类型emoji> <主题>｜…` 格式时不输出：首次归位（含首次 ⏳）由归位流程负责。
- 标题带 ⏳：本轮结束时按结果决定保留还是去掉。
- 标题不带 ⏳：本轮结束时需要才加。
- Codex 后台归位发现地图外的长期新领域时会留一条待提议记录，这里交给会话模型提议一次。
标题来源：Claude Code 读会话记录里最近一次改名；Codex 只读查询本机会话库。
JSON 按 ASCII 转义输出，避免 Windows 控制台代码页把中文弄乱。
"""
import glob
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

HOME = Path.home()
MAP = HOME / ".agent-rules" / "workspace-map.md"
PENDING = HOME / ".agent-rules" / "kk-sessions" / "codex" / "pending"
TYPE_EMOJI = ("✍️", "🔍", "🧪", "🎬", "📤", "🛠️", "🐛", "💬")
TITLE_RE = re.compile(r"^(%s)️? .+[｜|]" % "|".join(re.escape(e.rstrip("️")) for e in TYPE_EMOJI))

WAITING = "做决定、验收、提供材料、在外部操作等只有用户能做、做完才能继续的事"
HAS = ("[kk-sessions] 当前会话标题末尾带 ⏳（等用户处理）。本轮回复结束时判断：仍留下" + WAITING +
       "，就保留；否则去掉。用户给了选择或材料、事情已完成、只剩可选建议，或用户表示结束、交给自己处理"
       "（如「不用管了」「不做了」「我自己来」）时，都要去掉。")
NONE = "[kk-sessions] 本轮回复结尾如果留下" + WAITING + "，在会话标题末尾加 ` ⏳`；只是附带可选建议时不加。"
UNKNOWN = ("[kk-sessions] 本轮回复结束时维护会话标题末尾的 ⏳：留下" + WAITING + "时加上；"
           "已经带着但用户已回来推进、事情已完成或用户表示结束时去掉。")
TAIL = {"claude": "只改 ⏳，标题其他部分不动；改标题用 mcp__ccd_session_mgmt__set_session_title（session_id: \"self\"）。",
        "codex": "只改 ⏳，标题其他部分不动；改标题用 codex_app 的 set_thread_title。"}
PROPOSE = ("[kk-sessions] 后台归位判断这个会话属于地图外的长期新领域，暂归 📦 杂项。还没向用户提议过的话，"
           "本轮回复末尾按 kk-session-route「新分区」一节问一句：建议新分区「{name}」，产物根目录 {root}，判定线索：{clue}。"
           "用户已经答复过就按答复处理，不再问。")


def claude_title(path):
    title = None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"custom-title"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("type") == "custom-title":
                    title = d.get("customTitle") or title
    except OSError:
        return None
    return title


def codex_title(thread_id):
    """返回 (标题, 是否跳过)。会话库读不到时标题为 None；库里还没有这个会话（新会话第一轮）时跳过。"""
    dbs = sorted(glob.glob(str(HOME / ".codex" / "state_*.sqlite")),
                 key=lambda p: int(re.search(r"state_(\d+)", p).group(1)))
    if not dbs:
        return None, False
    try:
        con = sqlite3.connect(Path(dbs[-1]).as_uri() + "?mode=ro", uri=True, timeout=1)
        try:
            row = con.execute("select name, source, thread_source from threads where id = ?",
                              (thread_id,)).fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return None, False
    if not row:
        return "", True
    name, source, thread_source = row
    return name or "", source == "exec" or thread_source in ("automation", "subagent")


def hint(event):
    if os.environ.get("KK_SESSIONS_WORKER") == "1" or not MAP.exists():
        return None
    thread_id = os.environ.get("CODEX_THREAD_ID") or ""
    agent = "codex" if thread_id else "claude"
    parts = []
    if agent == "claude":
        title = claude_title(event.get("transcript_path") or "")
        if not (title and TITLE_RE.match(title)):
            return None
    else:
        thread_id = event.get("session_id") or thread_id
        if not re.fullmatch(r"[A-Za-z0-9-]{8,80}", thread_id):
            return None
        title, skip = codex_title(thread_id)
        if skip or (title is not None and not TITLE_RE.match(title)):
            return None
        pending = PENDING / (thread_id + ".json")
        if pending.exists():
            try:
                parts.append(PROPOSE.format(**json.loads(pending.read_text(encoding="utf-8"))))
            except (OSError, ValueError, KeyError):
                pass
            pending.unlink(missing_ok=True)
    if title is None:
        parts.append(UNKNOWN)
    else:
        parts.append(HAS if title.rstrip().endswith("⏳") else NONE)
    return "".join(parts) + TAIL[agent]


def main():
    try:
        event = json.loads(sys.stdin.buffer.read(1024 * 1024).decode("utf-8", "replace") or "{}")
        text = hint(event)
    except Exception:  # 提醒失败不挡对话
        text = None
    if text:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                                 "additionalContext": text}}))
    else:
        print("{}")


if __name__ == "__main__":
    main()
