"""SessionStart 钩子：提醒 Agent 在第一条消息按 kk-session-route 归位（先回答，本轮结束前归位）。

输出 hookSpecificOutput.additionalContext，供 Codex 使用；Claude Code 的钩子直接 echo 同一段提示。
JSON 按 ASCII 转义输出，避免 Windows 控制台代码页把中文弄乱。
"""
import json

HINT = ("[kk-session-route] 这是新会话，第一条消息按 kk-session-route skill 归位，但不"
        "要让归位挡在回答前面：一两句能答完的问题先直接回答，再在本轮末尾调用 kk-session-route 改标题、归区；要产出文件的任务先调用 kk-session-route 读地图、定目录、建目录，然后处理请求，改标题、归区、切目录放在本轮结束前完成。")

print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                         "additionalContext": HINT}}))
