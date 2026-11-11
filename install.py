"""kk-sessions 安装脚本：检测本机的 Claude Code 和 Codex，装入 Skill 和钩子。不改全局指令文件。

用法：
  python install.py                 安装到检测到的全部 Agent
  python install.py --agents codex  只装 Codex
  python install.py --uninstall     卸载（移除本项目写入的 Skill 和钩子）
  python install.py --dry-run       只打印将要做的事

可重复执行：已装过的部分会被替换，不会重复添加。
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent
HOME = Path.home()
SKILLS = ["kk-session-route", "kk-session-tidy", "kk-session-setup", "kk-session-restore"]
MARK = "kk-session-route"  # 钩子命令里含这个字符串即视为本项目写入（启动提示的文字里也有）
RULES_START = "<!-- kk-sessions:start -->"  # 旧版写进全局指令的规则块，现在只用于清理
RULES_END = "<!-- kk-sessions:end -->"
AGENTS = {
    "claude": {
        "name": "Claude Code",
        "root": HOME / ".claude",
        "skills": HOME / ".claude" / "skills",
        "hooks_file": HOME / ".claude" / "settings.json",
        "matcher": "startup",
        "rules_file": HOME / ".claude" / "CLAUDE.md",
    },
    "codex": {
        "name": "Codex",
        "root": HOME / ".codex",
        "skills": HOME / ".codex" / "skills",
        "hooks_file": HOME / ".codex" / "hooks.json",
        "rules_file": HOME / ".codex" / "AGENTS.md",
    },
}

DRY = False


def say(msg):
    print(("[dry-run] " if DRY else "") + msg)


def write(f, text):
    """写入或删除文件：内容为空（卸载后只剩空壳）时删掉。按 UTF-8、LF 原样写，不做换行转换。"""
    if not text.strip() or text.strip() == "{}":
        f.unlink(missing_ok=True)
        return
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(text.encode("utf-8"))


def hook_specs(agent, cfg, skills_dir):
    """本项目要写入的钩子：{事件: 钩子组}。和插件用同一份定义（hooks/hooks.json、hooks/codex.json），
    只把插件目录变量和 Python 换成本机的绝对路径。"""
    src = REPO / "hooks" / ("codex.json" if agent == "codex" else "hooks.json")
    events = json.loads(src.read_text(encoding="utf-8"))["hooks"]
    scripts = skills_dir / "kk-session-route" / "scripts"
    py = f'"{Path(sys.executable).as_posix()}"'
    specs = {}
    for event, groups in events.items():
        group = dict(groups[0])
        hooks = []
        for h in group["hooks"]:
            m = re.search(r"scripts/(\w+\.py)", h["command"])
            if m:  # Python 脚本：改成本机 Python + 绝对路径
                cmd = f'{py} "{(scripts / m.group(1)).as_posix()}"'
                h = {"type": "command", "timeout": h.get("timeout", 10), "command": cmd}
                if agent == "codex" and sys.platform == "win32":
                    h["commandWindows"] = "& " + cmd  # Codex 在 Windows 用 PowerShell 跑钩子
            hooks.append(h)
        group["hooks"] = hooks
        specs[event] = group
    return specs


def strip_ours(groups):
    """去掉本项目写入的钩子，保留用户自己的。"""
    kept = []
    for g in groups:
        hooks = [h for h in g.get("hooks", []) if MARK not in json.dumps(h, ensure_ascii=False)]
        if hooks:
            kept.append({**g, "hooks": hooks})
    return kept


def edit_hooks(agent, cfg, skills_dir, remove):
    f = cfg["hooks_file"]
    if remove and not f.exists():
        return
    data = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    hooks = data.setdefault("hooks", {})
    specs = hook_specs(agent, cfg, skills_dir)
    for event in ("SessionStart", "Stop"):
        groups = strip_ours(hooks.get(event, []))
        if not remove and event in specs:
            groups.append(specs[event])
        if groups:
            hooks[event] = groups
        else:
            hooks.pop(event, None)
    if not hooks:
        data.pop("hooks")
    say(f"{'移除' if remove else '写入'}钩子（{'、'.join(specs)}）：{f}")
    if DRY:
        return
    backup = f.with_name(f.name + ".kk-sessions.bak")
    if not remove and f.exists() and MARK not in f.read_text(encoding="utf-8") and not backup.exists():
        shutil.copy2(f, backup)  # 只备份装之前的原始配置
    write(f, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def strip_old_rules(cfg):
    """清理旧版写进全局指令文件的规则块（现在改由启动钩子注入）。"""
    f = cfg["rules_file"]
    text = f.read_text(encoding="utf-8") if f.exists() else ""
    if RULES_START not in text or RULES_END not in text:
        return
    head, rest = text.split(RULES_START, 1)
    say(f"清理旧版规则块：{f}")
    if not DRY:
        write(f, (head.rstrip("\n") + rest.split(RULES_END, 1)[1]).lstrip("\n"))


def edit_skills(target, remove):
    for name in SKILLS:
        dst = target / name
        if dst.is_symlink():
            say(f"跳过链接（由你自己管理）：{dst}")
            continue
        if dst.exists():
            say(f"删除旧版：{dst}")
            if not DRY:
                shutil.rmtree(dst)
        if not remove:
            say(f"安装 Skill：{dst}")
            if not DRY:
                shutil.copytree(REPO / "skills" / name, dst,
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def main():
    global DRY
    p = argparse.ArgumentParser(description="安装或卸载 kk-sessions")
    p.add_argument("--agents", help="逗号分隔：claude,codex；默认装检测到的全部")
    p.add_argument("--uninstall", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--skills-dir", type=Path,
                   help="Skill 统一装到这个目录（自己维护共享 Skill 库时用），钩子指向这里")
    p.add_argument("--no-skills", action="store_true", help="不复制 Skill，只处理钩子")
    p.add_argument("--force", action="store_true", help="卸载时不检查侧栏快照")
    a = p.parse_args()
    DRY = a.dry_run

    wanted = a.agents.split(",") if a.agents else [k for k, v in AGENTS.items() if v["root"].exists()]
    unknown = [w for w in wanted if w not in AGENTS]
    if unknown or not wanted:
        print(f"没有可安装的 Agent：{unknown or '未检测到 ~/.claude 或 ~/.codex'}")
        sys.exit(1)

    snapshots = HOME / ".agent-rules" / "kk-sessions" / "snapshots"
    if a.uninstall and not a.force and snapshots.is_dir() and any(snapshots.iterdir()):
        print("检测到侧栏快照，说明 kk-sessions 改过会话标题或分区。\n"
              "先在 Claude Code 或 Codex 里说「撤销 kk-sessions 的改动」恢复原样，再运行卸载；\n"
              "不需要恢复侧栏的话，加 --force 直接卸载。")
        sys.exit(1)

    if a.skills_dir and not a.no_skills:
        edit_skills(a.skills_dir, a.uninstall)
    for agent in wanted:
        cfg = AGENTS[agent]
        print(f"\n== {cfg['name']}")
        skills_dir = a.skills_dir or cfg["skills"]
        if not a.skills_dir and not a.no_skills:
            edit_skills(skills_dir, a.uninstall)
        edit_hooks(agent, cfg, skills_dir, a.uninstall)
        strip_old_rules(cfg)

    if a.uninstall:
        print("\n已卸载。工作区地图 ~/.agent-rules/workspace-map.md 保留，不需要可自行删除。")
        return
    print("\n装好了。接下来：")
    if "codex" in wanted:
        print("- Codex：打开「设置 → Hooks」，信任 kk-sessions 的两个钩子（SessionStart、Stop），否则不会触发。")
    if not (HOME / ".agent-rules" / "workspace-map.md").exists():
        print("- 新开一个会话，说「初始化会话分区」，按你现有的会话和目录生成工作区地图。")
    else:
        print("- 已有工作区地图，新开会话即可自动归位；说「整理会话」可整理旧会话。")


if __name__ == "__main__":
    main()
