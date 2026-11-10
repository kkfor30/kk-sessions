"""Z Code 会话适配脚本：精确改标题、只读列出会话。

已验证版本：Z Code 桌面版 3.17.2（内置引擎 zcode 0.17.1）。
只读写 ~/.zcode/cli/db/db.sqlite 的 session 表标题字段；不调用模型、不读写任何 API Key、
不碰侧栏库 tasks-index.sqlite。零第三方依赖。

用法：
  python zcode_session.py rename --session <id> --title <精确文本>
  python zcode_session.py list [--limit 50] [--archived]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.parse
from pathlib import Path


def db_path() -> Path:
    return Path.home() / ".zcode" / "cli" / "db" / "db.sqlite"


def ro_connect(path: Path) -> sqlite3.Connection:
    uri = "file:" + urllib.parse.quote(str(path).replace("\\", "/")) + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10)
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def read_title(path: Path, session_id: str):
    conn = ro_connect(path)
    try:
        return conn.execute("SELECT title FROM session WHERE id = ?", (session_id,)).fetchone()
    finally:
        conn.close()


def rename(path: Path, session_id: str, title: str) -> dict:
    if read_title(path, session_id) is None:
        raise SystemExit(f"会话不存在：{session_id}")
    conn = sqlite3.connect(path, timeout=15)
    try:
        conn.execute("PRAGMA busy_timeout = 10000")
        conn.execute("BEGIN IMMEDIATE")
        old = conn.execute(
            "SELECT title, title_source, time_title_updated FROM session WHERE id = ?",
            (session_id,)).fetchone()
        # title_source = custom：与用户在侧栏手动改名相同，Z Code 不再自动覆盖。
        cursor = conn.execute(
            "UPDATE session SET title = ?, title_source = 'custom', time_title_updated = ? "
            "WHERE id = ?", (title, int(time.time() * 1000), session_id))
        if cursor.rowcount != 1:
            conn.rollback()
            raise SystemExit("标题未写入：" + session_id)
        conn.commit()
    finally:
        conn.close()
    row = read_title(path, session_id)
    if row is None or row[0] != title:
        restore = sqlite3.connect(path, timeout=15)
        try:
            restore.execute(
                "UPDATE session SET title = ?, title_source = ?, time_title_updated = ? WHERE id = ?",
                (*old, session_id))
            restore.commit()
        finally:
            restore.close()
        raise SystemExit("写入后读回不一致，已恢复原标题")
    return {"status": "renamed", "session": session_id, "old": old[0], "title": title}


def list_sessions(path: Path, limit: int, archived: bool) -> list[dict]:
    condition = "time_archived IS NOT NULL" if archived else "time_archived IS NULL"
    conn = ro_connect(path)
    try:
        rows = conn.execute(
            f"SELECT id, title, directory, time_updated, time_archived, parent_id FROM session "
            f"WHERE time_deleted IS NULL AND {condition} ORDER BY time_updated DESC LIMIT ?",
            (limit,)).fetchall()
    finally:
        conn.close()
    return [{"id": r[0], "title": r[1] or "", "directory": r[2] or "",
             "updated": time.strftime("%Y-%m-%d %H:%M", time.localtime((r[3] or 0) / 1000)),
             "archived": r[4] is not None, "parent": r[5] or ""} for r in rows]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Z Code 会话标题与列表")
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("rename")
    r.add_argument("--session", default=os.environ.get("ZCODE_SESSION_ID"))
    r.add_argument("--title", required=True)
    ls = sub.add_parser("list")
    ls.add_argument("--limit", type=int, default=50)
    ls.add_argument("--archived", action="store_true")
    args = parser.parse_args()

    path = db_path()
    if not path.exists():
        raise SystemExit(f"未找到 Z Code 会话库：{path}")
    if args.cmd == "rename":
        if not args.session:
            raise SystemExit("缺少 --session，且环境变量 ZCODE_SESSION_ID 为空")
        result = rename(path, args.session, args.title)
    else:
        result = list_sessions(path, args.limit, args.archived)
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
