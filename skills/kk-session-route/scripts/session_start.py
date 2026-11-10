"""SessionStart 钩子：提醒 Agent 先调用 kk-session-route。

输出 hookSpecificOutput.additionalContext（Codex、Z Code、WorkBuddy 通用）。
JSON 按 ASCII 转义输出，避免 Windows 控制台代码页把中文弄乱。
"""
import json

HINT = ("[kk-session-route] 这是新会话。回复用户第一条消息前，先调用 kk-session-route skill "
        "完成会话归位（判断分区与产物目录、建目录、切目录、命名、归入侧栏分区，做不到的给出建议），"
        "用一句话说明结果后再处理请求。")

print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                         "additionalContext": HINT}}))
