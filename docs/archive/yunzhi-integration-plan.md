# Zhiying 接入云智平台 — AI 调查结论与实施方案

> 交付说明：应技术主管要求，基于桌面三份材料（`existing-frontend-application-bridge-integration.md`、`react-antd(1)`、`extension-automation-demo (2)`）与 Zhiying 代码库（当前分支 `feature/yunzhi`）调查后形成的决定。代码 A1/A2/A3 已实现并验证，未提交。

## 1. 两个需求 → 平台两种接入形态

| 需求 | 落地方案（材料依据） | 状态 |
|---|---|---|
| ① 本地文件上传改为 SDK | **Yunzhi Bridge SDK**：前端用 `bridge.files.select()` 从平台文件库选文件，拿 `absolutePath`，后端按共享路径**就地引用**注册视频（不再 multipart 上传字节）。依据：bridge 文档能力表 + `yunzhi-bridge.ts` `files.select` | ✅ 已实现 |
| ② 暴露异步非阻塞接口返回开始处理，再调已有接口汇报进度 | **扩展自动化任务模式**：`POST /internal/yunzhi/jobs` 立即回 `202 {accepted, bizTaskId}`，后台跑 Zhiying 管道，进度推平台 `callback.progressUrl`，完成/失败推 `completeUrl`/`failUrl`。依据：`server.py` 契约 + `manifest.json` automations | ✅ 已实现 |

## 2. 关键设计决定（AI 从材料推断，非猜测）

1. **进度汇报走平台回调**（`progressUrl/completeUrl/failUrl`），与 demo 完全一致；Zhiying 现有 `GET /videos/{id}/status` 保留供 iframe 页面内轮询。
2. **共享文件就地引用 + `source_owned` 所有权标志**：`Video.source_owned` 默认 true；平台共享文件置 false，删除视频时 StorageManager **跳过 unlink 平台源文件**（修掉"删除即清盘"误删平台文件的坑）。
3. **代码先行，部署后置**（联调需服务器，但代码可本地先行验证）。
4. Manifest 自动触发按 demo 默认配置（文件上传即触发任务中心任务）。

## 3. 已实现改动（未提交）

**A1 后端 — 注册共享路径视频**
- `POST /api/v1/videos/register-external`：接收平台共享 `absolutePath`，校验存在 → 建记录（`source_owned=false`）→ probe → 异步 remux
- `core/storage_manager.py`：删除跳过外部源文件 unlink；`core/db.py` 增量迁移新增 `source_owned` 列

**A2 后端 — 自动化任务接口**
- `POST /internal/yunzhi/jobs`（根路径，202 立即返回，`eventId`/`Idempotency-Key` 幂等）
- `services/yunzhi_job_service.py`：共享文件 → 管道 → `StatusTracker.on_progress` → 推 `progressUrl`；完成推 `completeUrl`（`resultData` 含 videoId，结果 JSON 写平台 `workDirectory`）；异常推 `failUrl`

**A3 前端 — Bridge SDK 集成**
- `frontend/src/platform/`（yunzhi-bridge.ts + client.ts + YunzhiProvider + mock）
- `Dashboard.tsx`：平台宿主模式走 `bridge.files.select()` → `registerFromPath`；独立开发（`VITE_YUNZHI_MOCK=true` 默认）保持本地上传
- `.env`：`VITE_YUNZHI_HOST_ORIGIN` / `VITE_YUNZHI_MOCK`

**验证**：后端 venv 导入 + 冒烟测试（202/幂等/422 全对）；前端 `tsc` + `vite build` 通过。

## 4. 需要平台方提供的事实（AI 无法调查）

| 事项 | 用途 |
|---|---|
| 10.0.0.176 服务器 root/admin 凭据 | 部署基线 |
| 平台文件库根路径（如 `/data/yunzhi-files`） | 确认与 Zhiying 共享同一绝对路径视角 |
| 平台扩展应用登记（entry URL / 后台服务地址 / Manifest） | 平台后台配置，需平台侧操作 |
| 平台 Web 精确 Origin（`https://yunzhi.<域>`） | 前端 `VITE_YUNZHI_HOST_ORIGIN` 联调值 |
| ffmpeg CUDA 版（或接受 CPU 兜底） | 10.0.0.176 现存 ffmpeg 6.1.1 无 CUDA |

## 5. 下一步

```
B1 服务器基线（10.0.0.176）: venv + pgvector:pg17 + nginx + systemd + GPU1 固定
B2 平台登记: 扩展应用 + Manifest + iframe CSP frame-ancestors
B3 联调: bridge 文档第 11 节清单逐项验证
B4 端到端: 文件库选视频 → Zhiying 处理 → 任务中心看进度 → 结果回文件库
```

## 6. 待主管确认的开放项

- [ ] 是否启用 Manifest 自动触发（文件上传即自动分析），还是仅交互式 iframe 入口
- [ ] 共享文件策略是否接受"就地引用"（不复制、删除不碰平台文件）
- [ ] 服务器凭据与部署时间窗
