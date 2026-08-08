# Zhiying 开发姿势

> 记录 Zhiying 项目日常开发的操作规范:分支管理、版本号、部署、多端开发、与对接人协作、agent 操作规矩。
> 用途:给所有开发者(包括 AI agent)一份"该怎么干活"的约定,命令可直接照抄。
> 相关文档:`docs/server.md`(服务器运维,gitignored 含凭证)、`docs/arch.md`(架构)、`CLAUDE.md`(项目说明)。

## 核心一句话

**一条主线(main)+ 每次发布打版本号(tag)+ 服务器只认版本号 + 多端差异用独立前端/构建产物,不用分支。**

- 分支用来区分"开发中 / 正式发布",**不是**用来区分"跑在哪个地方"(服务器 / 桌面 / 本地)。
- 一个项目一份"真后端"。部署目标之间的差异,用**独立前端**(`frontend/` 服务器 + `frontend-desktop/` 桌面,共用后端 + `frontend-shared/` 对接层)解决,不用分叉。

## 1. 分支管理

**只用 `main` 一条长期分支。** 所有改动最终都进 `main`。

- 新功能 / 大改动:开一条**短命分支**(如 `desktop-shell`、`fix-nvdec`),做完立刻 merge 回 `main`,然后删掉。短命 = 存活几小时到几天,别让两条分支长期并存。
- 小改动 / 修 bug:直接改在 `main` 上。
- 并行开发(如同时做"服务器 UI 调整"和"桌面端"):用 `git worktree add` 开两个 checkout,不用反复 `git stash` / 切分支。
- **禁忌**:不要像以前那样长期维护 `feature/yunzhi` 这种"部署专用分支"——那是混乱的根源。部署走 tag,不走分支。

## 2. 版本号与发布

**版本号唯一事实来源:`core/version.py` 的 `__version__`。** git tag 必须写成 `v<version>`(带 v),与 version.py 完全一致。`/health` 返回 `version` 字段,部署后用来核对线上真实版本。

**发版用 `./bump`(仓库根的可执行脚本):**
```bash
./bump patch        # 0.25.2 → 0.25.3(修 bug / 小改动)
./bump minor        # 0.25.2 → 0.26.0(新功能 / 大重构)
./bump 0.26.0       # 直接指定完整版本号
./bump --dry-run patch  # 只预览不改文件
```
bump 一条龙:改 version.py + frontend/package.json + package-lock.json → `git add .` → commit → 打 tag → push(main + tag)。**`frontend-desktop/`（桌面前端）独立版本、不参与 bump/tag**——桌面端版本随后端 `/health` 版本走，无需单独发版。

**什么时候必须 bump:** 任何**后端改动**（bug 修复 / 性能优化 / 管线重构 / 新功能上线）**以及服务器前端改动**（`frontend/` + 共享对接层 `frontend-shared/`——它们会上服务器）都必须 `./bump` 发版动版号（patch 修 bug/小改动，minor 新功能/大重构），**即使不立刻部署**。原因：tag 是冻结快照、服务器只认 tag，不 bump 会让「最新 tag」落后于线上实际状态，部署时对不上。保持"最新 tag = 当前可部署状态"。

**什么时候不用 bump:** 纯文档、注释改动（CLAUDE.md、docs/*、代码注释），以及**桌面前端改动**（`frontend-desktop/`——桌面端相对独立自由，前端改动不发版，随后端版本走）。

> 版本号不是提交计数器,是"可部署状态"的盖章。别为每个提交 bump。

## 3. 部署(git+tag)

完整链路(2026-08-07 跑通,v0.25.1 起):

```
本地:   改代码 → ./bump → commit + tag + push(GitHub)
服务器: bash deploy.sh v<tag>          # 一条命令
验证:   curl http://127.0.0.1:8011/health   # version 与 tag 对上
```

**服务器操作(在 `/home/services/zhiying` 下):**
```bash
bash deploy.sh v0.28.0
```
deploy.sh 干的事:fetch tags → config 迁移(首次)→ checkout 版本 → requirements 变了才 pip → 前端 build → 重启 systemd → 90s 健康检查。

**tag 是冻结快照**: 一旦打 tag,该版本内容固定。**已 tag 的版本随时可部署,与其它并行分支的开发完全无关**——如 v0.27 已 tag 时,desktop 分支在并行开发,照样能独立部署 v0.27.0(服务器拉的是 tag 快照,不掺分支代码)。

**服务器只读铁律:**
- 服务器是**部署目标,不是开发环境**。绝不直接改服务器上的文件(代码 / dist / 配置)。
- 所有改动必须走:本地改 → commit → bump → 服务器 deploy.sh 拉取。
- 服务器有自己的机器配置(`config/config.yaml`、`.env`),deploy.sh 不动它们。

**回滚:**
- 常规回滚 = `bash deploy.sh v<更早的tag>`(重新部署旧版本)。
- ⚠️ **config 坑**:config/config.yaml 已不入库(v0.25.1 起)。回退到"config 仍入库"的老 tag(≤v0.25.0)会 checkout 冲突。
- **正解是向前滚**:出 bug → 修 → `./bump patch` → 部署新版本,而不是退版本。必须回退老 tag 时,先备份并手动还原服务器 config(备份 `config/config.yaml.bak.pre-v0251`)。

## 4. 配置管理

| 文件 | 是否入库 | 用途 |
|---|---|---|
| `config/config.yaml` | ❌ gitignored | 机器相关:路径、密钥、端口。新机复制 `config.yaml.example` 自改 |
| `config/config.yaml.example` | ✅ | 模板,所有字段的参考 |
| `config/config_schema.py` | ✅ | 配置校验 |
| `.env` | ❌ gitignored | API 密钥等敏感值 |
| `data/settings.json` | ❌(运行时生成) | 系统设置,运行时生效,不入库 |

- 新机器部署:复制模板 → 按机器改 video_dir / artifact_dir / 模型路径 / API key。
- 服务器 config 和本地 config 可以不同,互不影响。
- **DB 连接解析顺序（v0.27 起）**: `POSTGRES_URI` 环境变量 → config.yaml 的 `database.uri` → 兜底 5432。config.yaml 是权威（各机端口自定）；服务器 2026-08-08 因系统 postgres 抢 5432 迁到 **5433**。新部署机只需在 config.yaml 配好 `database.uri` 即可，无需再记 POSTGRES_URI。

## 5. 开发节奏

把注意力分成两条线程:

- **响应线程**(被动):对接人 / 平台侧报 bug → 当天修 → bump → 部署 → 回复。联调期这条线很活跃,优先保证它顺畅,别让它堵住。
- **专注线程**(主动):桌面端、新功能、管道优化,用整块时间做。

发布节奏:
- **联调期(现在)**:一个 bug → 一次 patch bump → 部署验证。快,不攒。
- **稳定期**:攒一批改动 → 一次 bump(patch 修 bug,minor 加功能)→ 有意部署。别为每个小改动发版。

## 6. 多端开发(服务器 / 桌面 / 本地)

**双前端共存，单分支**：`frontend/`（服务器前端，v0.28 云智嵌入 UI）+ `frontend-desktop/`（桌面独立前端，v0.27 独立工作台）**完全隔离、各自演进**，共用同一后端（`api/core/pipeline/...`）。后端按启动方式切挂载：默认 `frontend/dist`，桌面启动器传 `ZHIYING_FRONTEND=desktop` → `frontend-desktop/dist`。

- 服务器前端 = `frontend/`（改它不影响桌面）；桌面前端 = `frontend-desktop/`（改它不影响服务器）。
- 桌面端 → `desktop/` 包（**pywebview 启动器**）:检查模型 → 起 uvicorn → 开 WebView2 窗口加载桌面前端 dist → 日志面板 → 优雅关闭。入口 `desktop/desktop.bat`。
- **本地开发**：两端都是 `npm run dev` + HMR（Vite 5173，别同时开两个）；桌面前端生产用 `cd frontend-desktop && npm run build` + desktop.bat。
- **native_video 已全局置灰退役**（摘要默认 vlm_llm, 双前端一视同仁）。

### ✅ 共享对接层（后端接口/字段变更时）

后端新增接口 / 字段 / 类型 → **只改 `frontend-shared/` 一处**，双端自动生效，**不存在「改两遍 / 忘第二遍」**：

- **`frontend-shared/`**（项目根）: `api.ts` / `types.ts` / `labels.ts` / `helpers.ts` —— 镜像后端 schema/接口的唯一实现。
- **双端复用**：`frontend/` 与 `frontend-desktop/` 各自的 `src/services/api.ts` / `src/types/index.ts` / `src/labels.ts` / `src/utils/helpers.ts` 只是 1 行再导出指针（`export * from "../../../frontend-shared/api"` 等）。
- **改后端字段/接口 → 直接改 `frontend-shared/` 一处**，两端构建/运行时都拿到新实现。
- 两端 vite.config 的 `server.fs.allow` 已放行 `../frontend-shared`（dev 模式可加载）。
- **UI 层**（Dashboard/components/hooks）不在共享内，各自演进——`frontend/` 改 UI 不影响桌面，反之亦然。

- 不拆仓库、不用 git submodule——单人维护下 monorepo 最省心。

## 7. 与对接人协作(云智平台)

- **tag 就是契约**:你出版本号(v0.25.x),对接人用 deploy.sh 自己拉。不靠手动传文件(服务器无 rsync,曾用 git bundle——已废弃)。
- 对接人报问题 → 你修 → bump → 部署 → 回复。改代码只走仓库/tag,服务器上绝不手改。
- 平台侧的问题(如 extension-host-page 的 crypto.randomUUID)记下来盯,那是平台该修的,别越权改。
- 待办、阻塞项落成清单(GitHub issues 或 TODO.md),别让它们悬在脑子里。

## 8. Agent 操作规矩

> 任何 AI agent 操作本仓库 / 服务器时遵守:

1. 改代码、本地验证:随便做。
2. **commit / tag / push / 服务器部署,必须先征得用户明确同意**,点头才执行。
3. **同一时刻只允许一个 agent 跑部署闭环**(防止两人同时 bump / deploy 打架)。
4. 每次部署后必须验证:`curl /health` 的 version 与 tag 一致,并验证本次修复的具体点。

## 9. 服务器连接（SSH 通道）

目标 10.0.0.176（root）。**密码在 `docs/server.md`（gitignored，含凭证），绝不写进命令/代码。**

⚠️ **Claude Code Bash 沙箱会拦出站网络**：默认沙箱里 ssh/paramiko 连 10.0.0.176 会报 `No route to host` / TCP CLOSED——不是服务器问题。**任何连服务器的命令必须用 `dangerouslyDisableSandbox=true` 跑**（"连接快/慢"的差别就在这）。

快速通道（paramiko，密码从 server.md 读、不落命令行）：
```python
/home/tj/projects/cerno/.venv/bin/python - << 'PYEOF'
import paramiko, re
pw = re.search(r'\*\*root\*\*.*?`([^`]+)`', open('docs/server.md', encoding='utf-8').read()).group(1)
c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('10.0.0.176', username='root', password=pw, timeout=20, banner_timeout=30)
# 之后 c.exec_command("bash /home/services/zhiying/deploy.sh v0.28.0") 或任意服务器命令
PYEOF
```

部署一条命令（服务器上）：
```bash
bash /home/services/zhiying/deploy.sh v0.28.0
```
验证：`curl http://127.0.0.1:8011/health`（version 应与 tag 对上）。

备选（人肉通道）：会话里输入 `! ssh root@10.0.0.176 ...` 由用户自己跑。

## 10. 命令速查

```bash
# 本地
./bump patch                          # 发版(commit + tag + push 一条龙)
git worktree add ../zhiying-desktop    # 并行开发另一个 checkout

# 服务器(在 /home/services/zhiying 下)
bash deploy.sh v0.28.0                # 部署到指定版本
curl http://127.0.0.1:8011/health     # 验证版本

# 回滚(除非必须,否则向前滚)
bash deploy.sh v0.27.0
```
