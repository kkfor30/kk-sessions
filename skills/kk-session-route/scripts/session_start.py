"""SessionStart 钩子（Codex）：新会话开头给会话模型一段说明，代替写进全局指令。

标题和分区由 Stop 钩子 codex_route.py 在后台处理；这里只交代会话本身要做的事：
产物写进地图目录、提议新分区。之后每轮的 ⏳ 由 turn_hint.py 提醒。没有工作区地图时不输出。
JSON 按 ASCII 转义输出，避免 Windows 控制台代码页把中文弄乱。
"""
import json
import sys
from pathlib import Path

HINT = ("[kk-sessions] 本会话由 kk-sessions 管理："
        "1）新会话的标题和侧栏分区由后台钩子在每轮结束后自动处理，不要自己改，也不要调用 move_thread_to_project。"
        "2）要产出文件的任务，动手前先读 ~/.agent-rules/workspace-map.md，按 kk-session-route 的「回答前」一节定分区和产物目录、"
        "没有就建目录和 README.md，产物一律写到该目录的绝对路径；会话所在文件夹不是该目录时，回复最后一句告诉用户产物在哪。"
        "3）这次是长期的新领域或新长期项目、和地图里所有分区都对不上时，回复末尾按 kk-session-route 的「新分区」一节提议新分区，"
        "用户同意后再更新地图、建目录、建分区并移入。"
        "4）之后每轮开头会有 [kk-sessions] 提醒说明怎么维护标题末尾的 ⏳，按提醒做；除此之外不改标题。")

try:
    source = json.loads(sys.stdin.read(1024 * 1024) or "{}").get("source")
except ValueError:
    source = None

# 恢复旧会话时不重复注入：说明只对新会话有用
if source != "resume" and (Path.home() / ".agent-rules" / "workspace-map.md").exists():
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": HINT}}))
