# Zhiying 开发姿势

> 记录 Zhiying 项目日常开发的操作规范:分支管理、版本号、部署、多端开发、与对接人协作、agent 操作规矩。
> 用途:给所有开发者(包括 AI agent)一份"该怎么干活"的约定,命令可直接照抄。
> 相关文档:`docs/server.md`(服务器运维,gitignored 含凭证)、`docs/arch.md`(架构)、`CLAUDE.md`(项目说明)。

## 核心一句话

**一条主线(main)+ 每次发布打版本号(tag)+ 服务器只认版本号 + 多端差异用构建档不用分支。**

- 分支用来区分"开发中 / 正式发布",**不是**用来区分"跑在哪个地方"(服务器 / 桌面 / 本地)。
- 一个项目只有一份"真代码"。部署目标之间的差异,用代码里的开关解决,不用分叉。

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
bump 一条龙:改 version.py + frontend/package.json + package-lock.json → `git add .` → commit → 打 tag → push(main + tag)。

**什么时候必须 bump:** 这版代码要上服务器 / 交付时。
**什么时候不用 bump:** 纯文档、注释改动(CLAUDE.md、docs/*、代码注释)。文档提交留在 main 里,下次 bump 时会自动一起带走。

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
bash deploy.sh v0.25.3
```
deploy.sh 干的事:fetch tags → config 迁移(首次)→ checkout 版本 → requirements 变了才 pip → 前端 build → 重启 systemd → 90s 健康检查。

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

## 5. 开发节奏

把注意力分成两条线程:

- **响应线程**(被动):对接人 / 平台侧报 bug → 当天修 → bump → 部署 → 回复。联调期这条线很活跃,优先保证它顺畅,别让它堵住。
- **专注线程**(主动):桌面端、新功能、管道优化,用整块时间做。

发布节奏:
- **联调期(现在)**:一个 bug → 一次 patch bump → 部署验证。快,不攒。
- **稳定期**:攒一批改动 → 一次 bump(patch 修 bug,minor 加功能)→ 有意部署。别为每个小改动发版。

## 6. 多端开发(服务器 / 桌面 / 本地)

同一份代码要跑三处(服务器网页端、桌面端、本地开发)。差异**用构建档,不用分支**:

- 前端加平台开关:`VITE_APP_PLATFORM=server|desktop|web`(或类似 env 变量),组件里用 `usePlatform()` 判断。参考现有 `VITE_YUNZHI_MOCK` 的用法。
- 服务器专属 UI 调整 → 进主线的构建档,服务器 build 时带上,而不是开"服务器修复分支"。
- 桌面端 → 同一仓库的 `desktop/` 包（**pywebview 启动器，非简单壳**）:Windows 桌面机（有 NVIDIA GPU）用它管理本地后端生命周期——检查模型齐全 → 起 uvicorn → 开 WebView2 窗口加载前端 dist → 日志面板 → 优雅关闭。入口 `desktop/desktop.bat`。复用同一前端 dist,**只加不改**共享组件,避免动到对接人正在验证的部分。
- 桌面构建用默认 env 即可:`VITE_YUNZHI_MOCK` 缺省即 mock 本地上传（无云智 Bridge）。`native_video` 已置灰退役（摘要默认 vlm_llm, 前端不再可选, 后端保留兼容历史记录）——桌面与服务器一视同仁。
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

## 9. 命令速查

```bash
# 本地
./bump patch                          # 发版(commit + tag + push 一条龙)
git worktree add ../zhiying-desktop    # 并行开发另一个 checkout

# 服务器(在 /home/services/zhiying 下)
bash deploy.sh v0.25.3                # 部署到指定版本
curl http://127.0.0.1:8011/health     # 验证版本

# 回滚(除非必须,否则向前滚)
bash deploy.sh v0.25.2
```
