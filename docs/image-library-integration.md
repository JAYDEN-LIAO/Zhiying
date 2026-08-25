# 素材库（ImageLibrary）v0.6 — 前端合并规格（阶段 ①）

> 本文件是**阶段①：桌面前端合并**的施工规格。阶段②（后端实现）独立见 `docs/subjects-backend-spec.md`。
> 定位：**合并既有前端增量**（覆盖式、回归风险为主），给干活 agent 直读清单。代码级细节自读 diff，本文件只记决策、边界、必改点、验收。
> 信息来源：产品交付 `~/Desktop/zy/frontend-desktop/` + `zy/frontend-shared/`（相对本仓库增量）。

## 已拍板决策（A/D/E 与阶段②共享，此处摘要）

- **A 归属**：桌面端专属。只动 `frontend-desktop/` + `frontend-shared/`（仅服务桌面端）。**不碰服务器前端 `frontend/`**。
- **D 版本**：统一 v0.6。
- **E 告警红点**：下一阶段，前端空壳保留不动，后端本期不做。
- **C 检索**（阶段②用，前端据此收敛种类）：目标种类精简为 `person` / `other` 两态。

## 一、交付物与落点

**新增 3 文件** → `frontend-desktop/src/`：`components/ImageLibrary.tsx`、`components/AddSubjectDrawer.tsx`、`mocks/subjectsMock.ts`。

**改动 10 文件** → 各自路径覆盖合并：`App.tsx`、`Sidebar.tsx`、`AppContext.tsx`、`DetectionPanel.tsx`、`Workbench.tsx`、`GlobalSearch.tsx`、`FileLibrary.tsx`、`index.css`、`frontend-shared/types.ts`、`frontend-shared/api.ts`。

**绝不并入**：`frontend-desktop/dist/`、`node_modules/`、`package-lock.json`（无新增依赖）；`vite.config.ts` 的 proxy **`10.0.0.183:8011` → 回退 `localhost:8011`**（合并第一步）。

## 二、强制改动点（合并后必须逐项执行）

1. **P1 历史 bug**：`AddSubjectDrawer.tsx` ~91/96 行 `api.createImageSubject`/`api.uploadSubjectPhoto` **绕过 mock** → 改 `subjectsApi.*`（与 `ImageLibrary` 一致）。否则 dev 沉淀路径打不存在的后端报错。
2. **种类收敛两态**：`frontend-shared/types.ts` `ImageSubjectKind = "person"|"vehicle"|"other"` → `"person"|"other"`。
3. **UI 收敛**：`ImageLibrary.tsx` 新建目标弹窗、`AddSubjectDrawer.tsx` 类型按钮三→二 `[人/其他]`；`ImageLibrary.tsx` `KIND_LABEL`/图标分支并入 `other`。
4. **沉淀 kind 收敛**（漏改会塞进已删的 `vehicle` → 类型错）：
   - `Workbench.tsx` ~359：`..."person" ? "person" : "vehicle"` → `: "other"`
   - `GlobalSearch.tsx` ~543：`isVehicle ? "vehicle" : "person"` → 非人统一 `"other"`（删/改 `VEHICLE_CLASSES` 判断）
5. **mock 收敛**：`mocks/subjectsMock.ts` 全部 `kind:"vehicle"` → `"other"`；`photoSvg`/`makePhotos` 的 vehicle 分支并入 other。
6. **v0.40 → v0.6**：上述文件注释版本号统一。

## 三、验收（阶段①通过标准）

1. `node frontend-desktop/node_modules/typescript/bin/tsc --noEmit` 桌面端 **exit 0**。
2. 服务器前端 `frontend/` **未被改动**、编译不受影响。
3. `npm run dev`：三条沉淀入口（检测「+」/ 图搜「+」/ 素材库页内）全部走 mock 可用；素材库 CRUD/裁剪/拖拽转存正常（P1 修复后）。
4. `vite.config.ts` proxy 为 `localhost:8011`，无 `10.0.0.183` 残留。
5. 回归：原 5 页（文件/工作台/搜索/任务/设置）功能不回归（新增全为可选 prop/条件渲染）。
6. 版本号注释一致 v0.6。

## 四、施工顺序

1. 回退 `vite.config.ts` proxy
2. 覆盖合并 `frontend-shared/types.ts`、`api.ts`（按 C 收敛 kind）
3. 覆盖合并桌面端 10 改动 + 3 新文件
4. 执行【二】全部 6 项
5. 跑【三】全项
6. 统一 v0.6
7. commit/tag/push —— **事前征得用户同意**，作者 `JAYDEN-LIAO`

## 遗留（阶段①别做）

- 后端任何实现 → 见 `docs/subjects-backend-spec.md`（阶段②）
- 服务器前端接入（A，桌面端专属）
- 告警红点后端（E，下一阶段；前端空壳保留）
