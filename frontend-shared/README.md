# frontend-shared/ — 双前端共享后端对接层

**一份实现，双端复用**：`frontend/`（服务器前端）与 `frontend-desktop/`（桌面前端）各自留 1 行再导出指针，实际代码都在这里。

## 包含（镜像后端 schema/接口的唯一实现）

- `api.ts` — API 客户端（后端接口调用）
- `types.ts` — TS 类型（后端 DTO 镜像）
- `labels.ts` — COCO 类名/颜色映射
- `helpers.ts` — 通用工具函数

## 规则

- **后端接口/字段/类型变更 → 只改这里的对应文件**，双端自动同步，无需改两遍。
- 两个前端各自的 `src/services/api.ts` / `src/types/index.ts` / `src/labels.ts` / `src/utils/helpers.ts` 只是再导出指针（`export * from "../../../frontend-shared/..."`），**不要**在两端本地放实现副本。
- UI 层（Dashboard/components/hooks）不在这里，各前端独立演进。
- 两端 vite.config 的 `server.fs.allow` 已放行 `../frontend-shared`（dev 模式加载用）。
