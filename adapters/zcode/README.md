# Z Code 适配

- 启动钩子：`hooks-snippet.json`，合并进 `~/.zcode/cli/config.json` 顶层 `hooks`（必须 `enabled: true`；项目级 `.zcode/config.json` 的钩子在 3.17.2 里被禁用，只能放用户级）。`<HOME>` 换成你的用户目录，路径用正斜杠。配置不热加载，改完重启应用。
- 改标题、列会话：`skills/kk-session-route/scripts/zcode_session.py`，随 Skill 一起安装到共享库，Skill 里按安装后的位置调用。脚本只写 `~/.zcode/cli/db/db.sqlite` 的 `session` 表标题字段，不调用模型、不读 API Key、不碰侧栏库 `tasks-index.sqlite`。
- 分区、切目录：没有接口，由用户在侧栏手动操作。
- 已验证版本：Z Code 3.17.2。

```bash
python zcode_session.py list --limit 20
python zcode_session.py rename --session <会话ID> --title "🛠️ 主题｜这次做什么"
```

`rename` 写入 `title_source = custom`（和侧栏手动改名一样，Z Code 不再自动覆盖），写后读回校验，不一致时恢复原标题。
