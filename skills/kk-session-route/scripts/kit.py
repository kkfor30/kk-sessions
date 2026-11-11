"""把回退工具复制到 ~/.agent-rules/kk-sessions/restore/：卸载或停用插件后，用户照样能回退。

只在已有侧栏快照（kk-sessions 改过侧栏）时复制，文件没变就不动。
"""
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = Path.home() / ".agent-rules" / "kk-sessions"
FILES = {
    HERE / "restore.py": "restore.py",
    HERE / "codex_route.py": "codex_route.py",
    HERE.parent.parent / "kk-session-restore" / "SKILL.md": "RESTORE.md",
}


def keep_restore_kit():
    snaps = BASE / "snapshots"
    if not (snaps.is_dir() and any(snaps.glob("*.json"))):
        return
    dst = BASE / "restore"
    for src, name in FILES.items():
        out = dst / name
        try:
            if src.exists() and (not out.exists() or out.read_bytes() != src.read_bytes()):
                dst.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, out)
        except OSError:
            pass
