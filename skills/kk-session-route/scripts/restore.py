"""Codex 侧栏回退：按 kk-sessions 第一次改动前的快照，把标题和分区恢复原样，删掉 kk-sessions 建的分区。

不需要模型，也不依赖插件：kk-sessions 会把本脚本复制到 ~/.agent-rules/kk-sessions/restore/，
卸载插件后照样能跑。

  python restore.py            只列出要改什么，不动侧栏
  python restore.py --apply    执行（需要 Codex 桌面端开着）
  python restore.py --snapshot <文件>   指定快照，默认用最早的一份

不覆盖用户自己的改动：标题已经不是 kk-sessions 的格式（用户后来自己改过）就跳过；
会话在用户自己的分区里也跳过。不删除会话，不动磁盘上的文件夹。
"""
import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from codex_route import (BASE, MAP, SNAPSHOTS, TITLE_RE, AppServer, DesktopTools,  # noqa: E402
                         find_codex, map_sections)


PINNED = "Pinned"


def list_threads(srv):
    threads = []
    for archived in (False, True):
        threads += srv.paged("thread/list", {"archived": archived, "limit": 100,
                                             "sourceKinds": ["cli", "vscode", "appServer", "exec"],
                                             "modelProviders": []})
    return {t["id"]: t for t in threads}


def plan(snap, threads, sections_now, map_names):
    """返回 {titles, renames, moves, deletes, skipped}。分区按 app-server 的 ID 比对，快照也是用它存的。"""
    snap_secs = {x["id"]: x["name"] for x in snap["sections"]}
    now_secs = {x["id"]: x["name"] for x in sections_now}
    # Pinned 是置顶列表，只由用户操作：不算 kk-sessions 建的分区，里面的会话也不动
    created = {i for i, n in now_secs.items() if i not in snap_secs and n != PINNED}
    renames = [{"now": now_secs[i], "to": n} for i, n in snap_secs.items() if i in now_secs and now_secs[i] != n]
    titles, moves, skipped = [], [], []
    for s in snap["sessions"]:
        t = threads.get(s["id"])
        if not t:
            continue  # 已删除
        now_title = t.get("name") or ""
        if now_title != s["title"]:
            if TITLE_RE.match(now_title):
                titles.append({"id": s["id"], "now": now_title, "to": s["title"]})
            else:
                skipped.append({"title": now_title, "why": "标题是你后来自己改的"})
        sec = t.get("section") or {}
        now_id, now_name = sec.get("id"), sec.get("name")
        if now_id == s["section"] or now_name == PINNED:
            continue
        if now_id is None or now_id in created or now_name in map_names:
            moves.append({"id": s["id"], "to": snap_secs.get(s["section"])})
        else:
            skipped.append({"title": now_title, "why": f"在你自己的分区「{now_name}」里"})
    return {"titles": titles, "renames": renames, "moves": moves,
            "deletes": [now_secs[i] for i in created], "skipped": skipped}


def report(p):
    print(f"改回标题 {len(p['titles'])} 个，改回分区名 {len(p['renames'])} 个，移回分区 {len(p['moves'])} 个，"
          f"删除分区 {len(p['deletes'])} 个，跳过 {len(p['skipped'])} 个。")
    for t in p["titles"][:10]:
        print(f"  标题：{t['now']}  →  {t['to'] or '（无标题）'}")
    if len(p["titles"]) > 10:
        print(f"  ……另有 {len(p['titles']) - 10} 个")
    for r in p["renames"]:
        print(f"  分区名：{r['now']}  →  {r['to']}")
    if p["deletes"]:
        print("  删除分区：" + "、".join(p["deletes"]))
    for s in p["skipped"][:10]:
        print(f"  跳过：{s['title'] or '（无标题）'}（{s['why']}）")


def apply(p, any_thread):
    """先改标题，再改回分区名，然后移分区，最后删分区。走桌面端通道，侧栏立即刷新。"""
    with DesktopTools(any_thread) as desk:
        if desk is None:
            sys.exit("没连上 Codex 桌面端。请先打开 Codex，再运行一次。")
        for t in p["titles"]:
            desk.call("set_thread_title", {"threadId": t["id"], "title": t["to"] or "新会话"})
        by_name = {x["name"]: x["sectionId"] for x in desk.sections()}
        for r in p["renames"]:
            if r["now"] in by_name:
                desk.call("rename_sidebar_section", {"sectionId": by_name[r["now"]], "name": r["to"]})
        by_name = {x["name"]: x["sectionId"] for x in desk.sections()}
        for m in p["moves"]:
            sid = by_name.get(m["to"]) if m["to"] else None
            desk.call("move_thread_to_sidebar_section", {"threadId": m["id"], "hostId": "local", "sectionId": sid})
        for name in p["deletes"]:
            if name in by_name:
                desk.call("delete_sidebar_section", {"sectionId": by_name[name]})


def main():
    for s in (sys.stdout,):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="把 Codex 侧栏恢复到 kk-sessions 第一次改动前")
    ap.add_argument("--apply", action="store_true", help="执行；不加只列出计划")
    ap.add_argument("--snapshot", type=Path, help="指定快照文件，默认用最早的 codex 快照")
    a = ap.parse_args()

    snaps = sorted(SNAPSHOTS.glob("codex-*.json"))
    path = a.snapshot or (snaps[0] if snaps else None)
    if not path or not path.exists():
        sys.exit("没有 Codex 快照：kk-sessions 还没改过 Codex 侧栏，或已经恢复过。")
    snap = json.loads(path.read_text(encoding="utf-8"))
    binary = find_codex()
    if not binary:
        sys.exit("找不到 codex 可执行文件。可在 ~/.agent-rules/kk-sessions/config.json 写 {\"codex_bin\": \"路径\"}。")
    map_names = set(map_sections(MAP.read_text(encoding="utf-8"))) if MAP.exists() else set()

    with AppServer(binary) as srv:
        threads = list_threads(srv)
        sections_now = srv.paged("threadSection/list", {"limit": 100})
    p = plan(snap, threads, sections_now, map_names)
    print(f"快照：{path.name}（{snap.get('created', '')}）")
    report(p)
    if not a.apply:
        print("\n确认无误后加 --apply 执行。")
        return
    done = BASE / f"restored-{datetime.now():%Y%m%d-%H%M%S}"
    done.mkdir(parents=True, exist_ok=True)
    # 先记下恢复前的样子，万一想撤回这次恢复
    (done / "before-restore.json").write_text(json.dumps(
        {"agent": "codex", "created": datetime.now().astimezone().isoformat(timespec="seconds"),
         "sections": [{"id": x["id"], "name": x["name"]} for x in sections_now],
         "sessions": [{"id": t["id"], "title": t.get("name") or "",
                       "section": (t.get("section") or {}).get("id")} for t in threads.values()]},
        ensure_ascii=False, indent=1), encoding="utf-8")
    if any(p[k] for k in ("titles", "renames", "moves", "deletes")):
        apply(p, next(iter(threads)))
    # 用的是默认快照时，把它收进 restored-<时间>，表示已恢复；以后再用 kk-sessions 会重新存一份起点快照
    if not a.snapshot:
        for f in snaps:
            shutil.move(str(f), done / f.name)
    print(f"已恢复。恢复前的状态记在 {done / 'before-restore.json'}。")

if __name__ == "__main__":
    main()
