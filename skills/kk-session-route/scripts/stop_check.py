"""Stop 钩子（Claude Code）：新会话第一轮结束前，检查是否已按 kk-session-route 归位。

没归位就拦一次，让模型补做；以下情况直接放行：
- 已经拦过一次（stop_hook_active）
- 还没有工作区地图（未初始化）
- 不是第一轮（用户已发过多条消息，旧会话交给 kk-session-tidy）
- 标题已是 `<类型emoji> <主题>｜…` 格式
"""
import json
import re
import sys
from pathlib import Path

TYPE_EMOJI = ("✍️", "🔍", "🧪", "🎬", "📤", "🛠️", "🐛", "💬")
TITLE_RE = re.compile(r"^(%s) .+[｜|]" % "|".join(map(re.escape, TYPE_EMOJI)))
REASON = ("[kk-session-route] 本会话还没归位。结束前请按 kk-session-route 的「回答后」一节完成："
          "改标题、归入侧栏分区（要产出文件的任务再切目录），最后一句话说明结果。"
          "如果你已在回复里问用户这个会话该归哪里，直接结束即可。")


def prompts_and_title(path):
    prompts, title = 0, None
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") == "custom-title":
            title = d.get("customTitle") or title
        elif d.get("type") == "user" and not d.get("isMeta"):
            c = d.get("message", {}).get("content")
            if isinstance(c, list):
                if any(i.get("type") == "tool_result" for i in c):
                    continue
                c = " ".join(i.get("text", "") for i in c if i.get("type") == "text")
            if isinstance(c, str) and c.strip() and not c.startswith("[Request interrupted"):
                prompts += 1
    return prompts, title


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    if data.get("stop_hook_active"):
        return
    if not (Path.home() / ".agent-rules" / "workspace-map.md").exists():
        return
    path = data.get("transcript_path")
    if not path or not Path(path).exists():
        return
    prompts, title = prompts_and_title(path)
    if prompts > 1 or (title and TITLE_RE.match(title)):
        return
    print(json.dumps({"decision": "block", "reason": REASON}))


if __name__ == "__main__":
    main()
