"""Stop 钩子（Codex）：新会话前几轮结束后，在后台用独立模型定标题和分区，通过 Codex app-server 写回。

- 钩子进程只做轻量检查，然后起一个脱离的后台进程就返回，不挡对话。
- 后台进程：读会话 → 判断要不要归位 → 调一次独立模型（codex exec --ephemeral，无工具）
  → 改标题、建分区、移入分区。不发消息、不改工作目录、不碰会话数据库。
- 目录由会话本身按跟进规则写到目标目录，这里不处理。
- 记录写在 ~/.agent-rules/kk-sessions/codex/：log.jsonl（每次结果）、done/<会话ID>（已处理）。
- 模型和推理强度可在 ~/.agent-rules/kk-sessions/config.json 的 "codex_model"、"codex_effort" 指定。
"""
import glob
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

HOME = Path.home()
MAP = HOME / ".agent-rules" / "workspace-map.md"
BASE = HOME / ".agent-rules" / "kk-sessions"
STATE = BASE / "codex"
SNAPSHOTS = BASE / "snapshots"
DEFAULT_MODEL = "gpt-6-luna"
DEFAULT_EFFORT = "low"
MAX_USER_TURNS = 3  # 超过这么多轮还没归位的，算旧会话，交给 kk-session-tidy
MAX_TRIES = 5  # 同一会话最多起这么多次后台进程，之后不再尝试（如找不到 codex、地图没有分区）
TYPE_EMOJI = ("✍️", "🔍", "🧪", "🎬", "📤", "🛠️", "🐛", "💬")
# 变体选择符 U+FE0F 可有可无：模型常把 ✍️ 写成 ✍
TITLE_RE = re.compile(r"^(%s)️? .+[｜|]" % "|".join(re.escape(e.rstrip("️")) for e in TYPE_EMOJI))


def canonical_title(title):
    """把开头缺了 U+FE0F 的类型 emoji 补成地图里的写法。"""
    for e in TYPE_EMOJI:
        bare = e.rstrip("️")
        if bare != e and title.startswith(bare) and not title.startswith(e):
            return e + title[len(bare):]
    return title
TRIVIAL = {"", "你好", "您好", "hi", "hello", "嗨", "在吗", "谢谢", "好的", "好", "ok", "收到", "继续", "嗯"}
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

POLICY = """你是会话归位助手。输入是用户的工作区地图和一个新会话的开头内容，你只输出 JSON。

1. section：按地图「分区」表选一个分区，必须原样照抄表里的分区名（含开头的颜色 emoji）。
   - 按这次产出的东西属于用户哪个领域来判断：以「放什么」一列为主，判定线索只是举例，不要求出现同样的词。
   - 判断依据是这次在做什么，不是对话里提到了什么：讨论的对象（某个工具、某个话题）可能属于一个领域，而这次的产出属于另一个领域。
   - 兜底分区（一次性问答、杂事那一行）只在这次没有长期产出、或确实不属于任何领域时才选。
2. title：格式 `<类型emoji> <主题>｜<这次做什么>`。
   - 类型 emoji 只从地图「标题」表里选，按这次做的是哪类事选。
   - 主题是长期的话题名，用用户自己的叫法，项目名、产品名照原样写，2 到 8 个字；这次做什么 2 到 10 个字。emoji 后总共不超过 20 个字。
   - 用对话的语言，不加引号、句号或其他符号。
3. waiting：这一轮结束时，事情能不能继续往下推进，是否取决于用户先做一件只有用户能做的事（做决定、验收、提供材料、在外部操作等）。从用户的要求和助手的回复两边一起判断。问题已经答完、或只是附带了可选建议时为 false。
4. reason：一句话说明为什么这样归。
"""

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["section", "title", "waiting", "reason"],
    "properties": {"section": {"type": "string"}, "title": {"type": "string"},
                   "waiting": {"type": "boolean"}, "reason": {"type": "string"}},
}


def log(record):
    STATE.mkdir(parents=True, exist_ok=True)
    record = {"time": datetime.now().isoformat(timespec="seconds"), **record}
    with open(STATE / "log.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def mark_done(thread_id, status):
    (STATE / "done").mkdir(parents=True, exist_ok=True)
    (STATE / "done" / thread_id).write_text(status, encoding="utf-8")


def valid_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9-]{8,80}", value):
        raise ValueError("会话 ID 格式不对")
    return value


# ---------- 找 codex ----------

def find_codex():
    cfg = read_config()
    if cfg.get("codex_bin"):
        return cfg["codex_bin"]
    if sys.platform == "win32":
        # 桌面端自带的 codex.exe 和桌面端同版本，优先用它
        found = sorted(glob.glob(r"C:\Program Files\WindowsApps\OpenAI.Codex_*\app\resources\codex.exe"))
        if found:
            return found[-1]
        entry = shutil.which("codex.exe") or shutil.which("codex")
        if entry and entry.lower().endswith((".cmd", ".bat", "codex")) and not entry.lower().endswith(".exe"):
            exe = glob.glob(str(Path(entry).parent / "node_modules/@openai/codex/node_modules/@openai/"
                                "codex-win32-*/vendor/*/bin/codex.exe"))
            return exe[0] if exe else None
        return entry
    if sys.platform == "darwin":
        for base in ("/Applications", str(HOME / "Applications")):
            for app in ("ChatGPT.app", "Codex.app"):
                p = Path(base) / app / "Contents/Resources/codex"
                if p.is_file():
                    return str(p)
    return shutil.which("codex")


def read_config():
    try:
        return json.loads((BASE / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def worker_env():
    env = os.environ.copy()
    for key in ("CODEX_THREAD_ID", "CODEX_SESSION_ID", "CODEX_APP_TOOLS_PIPE_PATH"):
        env.pop(key, None)
    env["KK_SESSIONS_WORKER"] = "1"
    return env


# ---------- app-server ----------

class AppServer:
    def __init__(self, binary, timeout=20):
        self.binary, self.timeout, self.n = binary, timeout, 0
        self.msgs = queue.Queue()

    def __enter__(self):
        self.proc = subprocess.Popen([self.binary, "app-server", "--disable", "hooks"],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, encoding="utf-8",
                                     env=worker_env(), creationflags=NO_WINDOW)
        threading.Thread(target=self._read, daemon=True).start()
        self.call("initialize", {"clientInfo": {"name": "kk-sessions", "version": "0.1.0"},
                                 "capabilities": {"experimentalApi": True}})
        self._send({"method": "initialized"})
        return self

    def _read(self):
        try:
            for line in self.proc.stdout:
                try:
                    self.msgs.put(json.loads(line))
                except ValueError:
                    pass
        finally:
            self.msgs.put(None)

    def _send(self, value):
        self.proc.stdin.write(json.dumps(value, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    def call(self, method, params):
        self.n += 1
        rid = self.n
        self._send({"id": rid, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                m = self.msgs.get(timeout=max(0.01, deadline - time.monotonic()))
            except queue.Empty:
                raise RuntimeError("app-server 超时：" + method)
            if m is None:
                raise RuntimeError("app-server 已退出")
            if m.get("id") == rid:
                if "error" in m:
                    raise RuntimeError(f"{method} 失败：{m['error'].get('message', m['error'])}")
                return m["result"]

    def paged(self, method, params, key="data"):
        params, out = dict(params), []
        while True:
            page = self.call(method, params)
            out += page.get(key, [])
            if not page.get("nextCursor"):
                return out
            params["cursor"] = page["nextCursor"]

    def __exit__(self, *_):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.kill()


class DesktopTools:
    """桌面端自己的 codex_app 工具通道（会话里改名用的同一个）。经它改名、移分区，侧栏立即刷新；
    app-server 改的要等桌面端下次重新加载才显示。协议：命名管道，4 字节小端长度 + JSON-RPC。"""

    def __init__(self, thread_id):
        self.thread_id, self.f, self.n, self.ns = thread_id, None, 0, {}

    @staticmethod
    def pipes():
        env = os.environ.get("CODEX_APP_TOOLS_PIPE_PATH", "").strip()
        found = [env] if env else []
        if sys.platform == "win32":
            try:
                found += [r"\\.\pipe" + "\\" + p for p in os.listdir("\\\\.\\pipe\\")
                          if p.startswith("codex-app-tools-")]
            except OSError:
                pass
        return list(dict.fromkeys(found))

    def __enter__(self):
        for path in self.pipes():
            try:
                self.f = open(path, "r+b", buffering=0)
                tools = self._request("tools/list", {"threadStartKind": "all"})["tools"]
                self.ns = {t["name"]: t.get("namespace") for t in tools}
                return self
            except (OSError, RuntimeError, KeyError, ValueError):
                self.close()
        return None

    def _request(self, method, params):
        self.n += 1
        body = json.dumps({"id": self.n, "jsonrpc": "2.0", "method": method, "params": params},
                          ensure_ascii=False).encode("utf-8")
        self.f.write(len(body).to_bytes(4, "little") + body)
        while True:
            size = int.from_bytes(self._read(4), "little")
            msg = json.loads(self._read(size))
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(msg["error"].get("message", "desktop tool error"))
                return msg["result"]

    def _read(self, size):
        data = b""
        while len(data) < size:
            chunk = self.f.read(size - len(data))
            if not chunk:
                raise RuntimeError("desktop pipe closed")
            data += chunk
        return data

    def call(self, tool, arguments):
        res = self._request("tools/call", {
            "arguments": arguments, "callerSource": "codex", "callId": f"kk-sessions-{uuid.uuid4()}",
            "namespace": self.ns.get(tool), "threadId": self.thread_id, "tool": tool,
            "turnId": f"kk-sessions-{uuid.uuid4()}"})
        text = " ".join(i.get("text", "") for i in res.get("contentItems", []))
        if not res.get("success"):
            raise RuntimeError(f"{tool} 失败：{text[:200]}")
        return text

    def sections(self):
        return json.loads(self.call("list_threads", {"limit": 1})).get("sections", [])

    def move_to_section(self, name):
        """移进同名侧栏分区，没有就建；已在里面返回 False。新会话常被桌面端放进当前浏览的分区，
        不代表用户的选择，所以只要和目标不同就移。"""
        key = f"codex:thread:local:{self.thread_id}"
        secs = self.sections()
        target = next((s for s in secs if s.get("name") == name), None)
        if target and key in target.get("itemKeys", []):
            return False
        if not target:
            self.call("create_sidebar_section", {"name": name})
            target = next(s for s in self.sections() if s.get("name") == name)
        self.call("move_thread_to_sidebar_section",
                  {"threadId": self.thread_id, "hostId": "local", "sectionId": target["sectionId"]})
        return True

    def close(self):
        if self.f:
            try:
                self.f.close()
            except OSError:
                pass
        self.f = None

    def __exit__(self, *_):
        self.close()


def read_settled(srv, thread_id, turn_id, wait=8):
    """等 Stop 对应的这一轮落盘完成。"""
    deadline = time.monotonic() + wait
    while True:
        t = srv.call("thread/read", {"threadId": thread_id, "includeTurns": True})["thread"]
        turns = t.get("turns") or []
        last = turns[-1] if turns else {}
        if not turn_id or (last.get("id") == turn_id and last.get("status") == "completed"):
            return t
        if time.monotonic() > deadline:
            return t
        time.sleep(0.3)


def user_texts(thread):
    """每轮的用户文字和助手最终回答。"""
    rounds = []
    for turn in thread.get("turns") or []:
        user, answer = [], ""
        for item in turn.get("items", []):
            if item.get("type") == "userMessage":
                user.append(" ".join(p.get("text", "") for p in item.get("content", [])
                                     if p.get("type") == "text"))
            elif item.get("type") == "agentMessage" and item.get("phase") in (None, "final_answer"):
                answer = item.get("text", "") or answer
        text = "\n".join(u for u in user if u.strip()).strip()
        if text:
            rounds.append({"user": text, "answer": answer.strip()})
    return rounds


# ---------- 地图 ----------

def map_sections(text):
    """地图「分区」表第一列的分区名。"""
    names, in_table, body = [], False, False
    for line in text.splitlines():
        if line.startswith("## "):
            in_table, body = line.strip() == "## 分区", False
            continue
        if not (in_table and line.startswith("|")):
            continue
        if set(line.strip()) <= set("|-: "):
            body = True  # 分隔行之后才是数据行，之前是表头
            continue
        cell = line.strip("|").split("|")[0].strip()
        if body and cell and not cell.startswith("<") and cell not in names:
            names.append(cell)
    return names


# ---------- 独立模型 ----------

def usage_of(stdout):
    """codex exec --json 的 turn.completed 事件里带本次 token 用量。"""
    for line in reversed((stdout or "").splitlines()):
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "turn.completed":
            return ev.get("usage")
    return None


def ask_model(binary, context):
    cfg = read_config()
    model = cfg.get("codex_model", DEFAULT_MODEL)
    effort = cfg.get("codex_effort", DEFAULT_EFFORT)
    with tempfile.TemporaryDirectory(prefix="kk-sessions-") as tmp:
        tmp = Path(tmp)
        (tmp / "policy.md").write_text(POLICY, encoding="utf-8")
        (tmp / "schema.json").write_text(json.dumps(SCHEMA), encoding="utf-8")
        out = tmp / "out.json"
        base = [binary, "exec", "--ephemeral", "--ignore-user-config", "--skip-git-repo-check",
                "--sandbox", "read-only", "-C", str(tmp),
                "--disable", "hooks", "--disable", "shell_tool", "--disable", "plugins",
                "--disable", "apps", "--disable", "multi_agent",
                # 关掉用不到的工具和说明，输入从约 8 千降到约 6.3 千 token（剩下的是 Codex 固定的系统提示）
                *[x for f in ("browser_use", "browser_use_external", "computer_use", "image_generation",
                              "goals", "view_image", "unified_exec", "code_mode_host", "skill_search",
                              "tool_suggest", "sleep_tool", "in_app_browser", "workspace_dependencies",
                              "worktrees") for x in ("--disable", f)],
                *[x for c in ("include_apply_patch_tool=false", "include_plan_tool=false",
                              "include_permissions_instructions=false", "include_environment_context=false",
                              "include_apps_instructions=false") for x in ("-c", c)],
                "-c", f'model_reasoning_effort="{effort}"', "-c", "project_doc_max_bytes=0",
                "-c", "skills.max_context_tokens=1", "-c", "agents.enabled=false",
                "-c", 'web_search="disabled"',
                "-c", "model_instructions_file=" + json.dumps(str(tmp / "policy.md")),
                "--output-schema", str(tmp / "schema.json"), "--output-last-message", str(out), "--json", "-"]
        # 实测正常 10～20 秒，偶尔会卡住不返回：45 秒没结果就重来一次。
        # 指定的模型报错（账号没有这个模型）时，退回 Codex 默认模型。
        attempts = [[*base[:2], "-m", model, *base[2:]]] * 2 + [base] if model else [base, base]
        err, i = "", 0
        while i < len(attempts):
            args = attempts[i]
            try:
                proc = subprocess.run(args, input=json.dumps(context, ensure_ascii=False),
                                      capture_output=True, encoding="utf-8", env=worker_env(),
                                      timeout=45, creationflags=NO_WINDOW)
            except subprocess.TimeoutExpired:
                err, i = "超时", i + 1
                continue
            if proc.returncode == 0 and out.exists():
                return (json.loads(out.read_text(encoding="utf-8")), args[3] if "-m" in args else "default",
                        usage_of(proc.stdout))
            err = (proc.stderr or "")[-300:]
            # 报错（不是超时）时重试同一模型没用，直接换默认模型
            i = len(attempts) - 1 if "-m" in args else len(attempts)
        raise RuntimeError("独立模型失败：" + err)


# ---------- 快照 ----------

def ensure_snapshot(srv, sections):
    if SNAPSHOTS.is_dir() and any(SNAPSHOTS.glob("codex-*.json")):
        return
    threads = []
    for archived in (False, True):
        threads += [dict(t, _archived=archived) for t in srv.paged(
            "thread/list", {"archived": archived, "limit": 100,
                            "sourceKinds": ["cli", "vscode", "appServer", "exec"], "modelProviders": []})]
    if len(threads) > 100:
        cutoff = (datetime.now() - timedelta(days=30)).timestamp()
        threads = [t for t in threads if (t.get("updatedAt") or 0) >= cutoff]
    snap = {"agent": "codex", "created": datetime.now().astimezone().isoformat(timespec="seconds"),
            "sections": [{"id": s["id"], "name": s["name"]} for s in sections],
            "sessions": [{"id": t["id"], "title": t.get("name") or "",
                          "section": (t.get("section") or {}).get("id"), "archived": t["_archived"]}
                         for t in threads]}
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    (SNAPSHOTS / f"codex-{datetime.now():%Y%m%d-%H%M%S}.json").write_text(
        json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------- 主流程 ----------

def route(thread_id, turn_id):
    binary = find_codex()
    if not binary:
        return {"status": "no_codex"}
    map_text = MAP.read_text(encoding="utf-8")
    names = map_sections(map_text)
    if not names:
        return {"status": "map_has_no_sections"}
    with AppServer(binary) as srv:
        thread = read_settled(srv, thread_id, turn_id)
        title = thread.get("name") or ""
        if thread.get("parentThreadId") or thread.get("ephemeral"):
            return {"status": "skip_child", "done": True}
        if TITLE_RE.match(title):
            return {"status": "already_titled", "done": True}
        rounds = user_texts(thread)
        if len(rounds) > MAX_USER_TURNS:
            return {"status": "old_thread", "done": True}
        if all(re.sub(r"[\W_]+", "", r["user"]).casefold() in TRIVIAL for r in rounds):
            return {"status": "wait_for_content"}  # 只是打招呼，等下一轮
        context = {
            "workspace_map": map_text[:6000],
            "section_names": names,
            "cwd": thread.get("cwd"),
            "conversation": [{"user": r["user"][:1200], "assistant": r["answer"][-800:]} for r in rounds],
        }
        result, model, usage = ask_model(binary, context)
        new_title = canonical_title(result["title"].strip().strip("`\"'"))
        if not TITLE_RE.match(new_title):
            return {"status": "bad_title", "title": new_title, "model": model}
        if result.get("waiting") and not new_title.endswith("⏳"):
            new_title += " ⏳"
        section = result["section"].strip()
        if section not in names:
            # 兜底分区：名字带「杂项」的那行；用户改了名就用表里最后一行（模板把兜底放在最后）
            section = next((n for n in names if "杂项" in n), names[-1])

        sections = srv.paged("threadSection/list", {"limit": 100})
        ensure_snapshot(srv, sections)
        # 模型思考期间用户可能已经手动改了标题，以用户为准。
        # 原来没有标题时，新出现的标题是桌面端自动生成的，照常覆盖
        now = srv.call("thread/read", {"threadId": thread_id, "includeTurns": False})["thread"]
        if title and (now.get("name") or "") != title:
            return {"status": "user_renamed", "done": True}
        # 新会话常被桌面端放进当前浏览的分区，不代表用户的选择，所以只要和目标不同就移
        via, moved = "desktop", False
        try:
            with DesktopTools(thread_id) as desk:
                if desk is None:
                    raise RuntimeError("no desktop pipe")
                desk.call("set_thread_title", {"threadId": thread_id, "title": new_title})
                if section:
                    moved = desk.move_to_section(section)
        except Exception as e:  # 桌面端没开或通道不可用：退回 app-server，侧栏要等桌面端重新加载才显示
            via = f"app-server（{str(e)[:80]}）"
            srv.call("thread/name/set", {"threadId": thread_id, "name": new_title})
            if section and (now.get("section") or {}).get("name") != section:
                sid = next((s["id"] for s in sections if s["name"] == section), None)
                if not sid:
                    sid = srv.call("threadSection/create", {"name": section})["section"]["id"]
                srv.call("thread/section/move", {"threadId": thread_id, "sectionId": sid})
                moved = True
        return {"status": "routed", "done": True, "title": new_title, "section": section, "moved": moved,
                "via": via, "model": model, "usage": usage, "reason": result.get("reason")}


def worker(thread_id, turn_id):
    start = time.monotonic()
    try:
        res = route(thread_id, turn_id)
    except Exception as e:  # 后台进程，出错只记日志
        res = {"status": "error", "message": str(e)[:300]}
    if res.pop("done", False):
        mark_done(thread_id, res["status"])
    log({"thread": thread_id, **res, "seconds": round(time.monotonic() - start, 1)})


def hook():
    event = json.loads(sys.stdin.read(1024 * 1024) or "{}")
    if event.get("stop_hook_active") or not MAP.exists():
        return
    thread_id = valid_id(event.get("session_id") or os.environ.get("CODEX_THREAD_ID", ""))
    if (STATE / "done" / thread_id).exists():
        return
    tries_file = STATE / "tries" / thread_id
    tries = int(tries_file.read_text() or 0) if tries_file.exists() else 0
    if tries >= MAX_TRIES:
        mark_done(thread_id, "gave_up")
        log({"thread": thread_id, "status": "gave_up", "tries": tries})
        return
    tries_file.parent.mkdir(parents=True, exist_ok=True)
    tries_file.write_text(str(tries + 1))
    turn_id = event.get("turn_id") or ""
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | NO_WINDOW
    args = [sys.executable, "-X", "utf8", __file__, "worker", thread_id, turn_id]
    log({"thread": thread_id, "status": "spawned"})
    for extra in ((subprocess.CREATE_BREAKAWAY_FROM_JOB,) if sys.platform == "win32" else ()) + (0,):
        try:
            subprocess.Popen(args, creationflags=flags | extra, env=worker_env(),
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, close_fds=True,
                             start_new_session=sys.platform != "win32")
            break
        except OSError:
            continue  # 宿主不允许脱离作业对象时，退回普通后台进程


def main():
    for s in (sys.stdin, sys.stdout):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")
    if len(sys.argv) >= 3 and sys.argv[1] == "worker":
        worker(valid_id(sys.argv[2]), sys.argv[3] if len(sys.argv) > 3 else "")
        return
    try:
        if os.environ.get("KK_SESSIONS_WORKER") != "1":
            hook()
    except Exception as e:
        log({"status": "hook_error", "message": str(e)[:300]})
    finally:
        print("{}")


if __name__ == "__main__":
    main()
