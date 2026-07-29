# Cerno 前端重构方案 v2.0

> 基于 mockup-dark.html 全新样式，保留全部现有功能，全面性能优化与架构重构

---

## 一、设计目标

| 维度 | 目标 |
|------|------|
| **视觉** | 按 `mockup-dark.html` 新风格重写全部 UI，深色/浅色融合，去 fluid-blob 改为 clean surface |
| **功能** | 现有所有功能零丢失，mockup 未体现的（侧滑面板、设置页、ExportMenu、人脸标签页切换、hover 预览等）全部保留 |
| **性能** | 修复现有性能问题，优化轮询/渲染/内存 |
| **架构** | 解耦 Dashboard，引入自定义 hooks + Context，拆分大组件，React.memo 优化 |
| **代码质量** | TypeScript 严格模式，组件单一职责，逻辑与视图分离 |

---

## 二、新样式系统

### 2.1 CSS 设计令牌（Tailwind 4 `@theme`）

```css
@import "tailwindcss";
@theme {
  --font-sans: 'Inter', system-ui, -apple-system, sans-serif;
  --font-mono: 'JetBrains Mono', 'SF Mono', monospace;

  /* Backgrounds */
  --color-page-bg: #e6e9ed;
  --color-surface: #eef0f3;
  --color-white: #ffffff;

  /* Sidebar */
  --color-sidebar-start: #1a2740;
  --color-sidebar-end: #141f35;

  /* Header */
  --color-header-bg: rgba(255,255,255,0.88);

  /* Borders */
  --color-border: #dde0e5;
  --color-border-light: #e4e7ec;
  --color-border-dark: #1a2332;
  --color-border-major: #1a2332;

  /* Text */
  --color-text-primary: #0f172a;
  --color-text-secondary: #334155;
  --color-text-muted: #475569;
  --color-text-dim: #64748b;

  /* Accents */
  --color-accent-blue: #2563eb;
  --color-accent-green: #16a34a;
  --color-accent-amber: #d97706;
  --color-accent-purple: #7c3aed;
  --color-accent-teal: #0d9488;

  /* Timeline (dark theme) */
  --color-timeline-bg: #14141e;
  --color-timeline-ruler: rgba(0,0,0,0.2);

  /* Shadows */
  --shadow-card: 0 3px 12px rgba(0,0,0,0.07);
  --shadow-sm: 0 1px 3px rgba(0,0,0,0.04);

  /* Radii */
  --radius-card: 8px;
  --radius-lg: 10px;
  --radius-video: 10px;
}

/* Remove fluid blobs — clean background-only */
```

### 2.2 卡片层次

| 卡片类型 | 样式 | 高度 |
|---------|------|------|
| `minor-card` | `bg-surface` + `border #d0d4db` + `radius` | 默认 220px；右列覆写为 `flex: 2.5`（5:2.5:2.5 比例） |
| `major-card` | `bg-white` + `border-dark` + `shadow-md` | `flex-1` 填充剩余；右列覆写为 `flex: 5` |
| `major-card-hd` | `bg-slate-800` + `text-slate-100` | 固定 |

---

## 三、组件树（重构后）

```
App
 └── Dashboard                     ← 精简化，仅保留核心状态 + 编排
      │
      ├── Sidebar                  ← 52px 深蓝渐变（原 LeftSidebar）
      │    └── 页面导航 + 面板开关
      │
      ├── SlideOutPanel            ← 通用侧滑容器（新抽象）
      │    ├── ParameterPanel      ← 四级联动参数（新样式）
      │    └── HistoryPanelContent ← 历史记录列表（新样式）
      │
      ├── Header                   ← 52px 固定栏（从 Dashboard 抽出）
      │    ├── Logo + 标题
      │    └── 上传按钮
      │
      ├── VideoSection             ← 中栏主体（新抽组件）
      │    ├── VideoPlayer         ← <video> + 格式就绪覆盖层
      │    │    └── DetectionOverlay (Canvas rAF)
      │    ├── DetectionTimeline
      │    └── PipelineBar
      │
      ├── RightPanel               ← 两列 340px 布局
      │    ├── LeftColumn
      │    │    └── DetectionPanel (major-card, 全高)
      │    └── RightColumn (5:2.5:2.5)
      │         ├── VideoSearchCard (major-card, flex: 5)
      │         ├── VideoSummaryCard (minor-card, flex: 2.5)
      │         └── VideoInfoCard (minor-card, flex: 2.5)
      │
      ├── ExportMenu               ← 绝对定位弹窗
      │
      └── SettingsPage             ← 全页设置
```

---

## 四、状态管理方案

### 4.1 分层设计

```
Dashboard (global state)
  ├── currentPage          → "dashboard" | "settings"
  ├── activePanel          → "params" | "history" | null
  ├── currentVideoId       → string | null
  ├── currentVideo         → VideoResponse | null
  ├── hasPendingParams     → boolean
  ├── videos               → VideoListItem[]
  ├── listKey              → number (force refresh)
  ├── isUploading          → boolean
  ├── seekTarget           → { start, end } | null
  ├── showExport           → boolean
  │
  ├── hevcOk               → boolean (useHEVCCapability hook)
  ├── proxyStatus          → ProxyStatus | null (useProxyStatus hook)
  ├── streamReady          → boolean (useMemo)
  │
  └── DetectionContext (Provider)
       ├── detectionData   → DetectionData | null
       ├── faceData        → FaceData | null
       ├── plateData       → PlateData | null
       ├── selectedTrackId → number | null
       ├── tracked         → { class_name, track_id } | null
       ├── classFilter     → string | null
       ├── onTrackSelect   → callback
       └── onClassFilterChange → callback
```

### 4.2 自定义 Hooks

| Hook | 职责 | 提取自 |
|------|------|--------|
| `useHEVCCapability()` | 浏览器 HEVC 检测 (canPlayType) | Dashboard |
| `useVideoPolling(videoId)` | 3s 轮询视频详情，visibility-aware | Dashboard |
| `useProxyStatus(videoId, needsProxy)` | 代理状态轮询，就绪后自动停止 | Dashboard |
| `useDetectionData(videoId, enabled, faceEnabled, plateEnabled)` | 检测+人脸+车牌数据懒加载 | Dashboard |
| `useStreamReady(video, hevcOk)` | 计算 stream 是否就绪 | Dashboard |
| `useSearch()` | 搜索状态 + 人脸搜索 | VideoSearchCard |
| `useParameterForm(initialVideo?)` | 参数表单状态 + custom params localStorage | ParameterPanel |

### 4.3 DetectionContext

```typescript
// context/DetectionContext.tsx
interface DetectionState {
  detectionData: DetectionData | null;
  faceData: FaceData | null;
  plateData: PlateData | null;
  selectedTrackId: number | null;
  tracked: { class_name: string; track_id: number } | null;
  classFilter: string | null;
  setDetectionData: (d: DetectionData | null) => void;
  setFaceData: (d: FaceData | null) => void;
  setPlateData: (d: PlateData | null) => void;
  onTrackSelect: (trackId: number, className: string, seekTo?: number) => void;
  onClassFilterChange: (cls: string | null) => void;
}
```

消除 prop drilling：DetectionOverlay / DetectionTimeline / DetectionPanel 通过 context 消费检测状态，不再经 Dashboard 中转。

---

## 五、性能优化方案

### 5.1 轮询优化（现有问题）

**问题 1**：`setInterval` 轮询在标签页隐藏时继续运行，浪费带宽和渲染。

**优化**：
```typescript
// hooks/useVideoPolling.ts
useEffect(() => {
  if (!videoId) return;
  let cancelled = false;
  let timer: ReturnType<typeof setInterval> | null = null;
  
  const poll = async () => {
    const data = await api.getVideo(videoId);
    if (cancelled) return;
    onUpdate(data);
    if (data.status !== "processing" && data.status !== "pending") {
      if (timer) clearInterval(timer);
    }
  };
  
  poll();
  timer = setInterval(poll, 3000);
  
  // ★ 新增：标签页隐藏时暂停轮询
  const onVisibility = () => {
    if (document.hidden && timer) {
      clearInterval(timer);
      timer = null;
    } else if (!document.hidden && !timer) {
      poll();
      timer = setInterval(poll, 3000);
    }
  };
  document.addEventListener("visibilitychange", onVisibility);
  
  return () => {
    cancelled = true;
    if (timer) clearInterval(timer);
    document.removeEventListener("visibilitychange", onVisibility);
  };
}, [videoId]);
```

**效果**：后台标签页零轮询，回归时立即刷新。

### 5.2 DetectionOverlay rAF 优化（现有问题）

**问题 2**：rAF 循环在视频暂停或无检测数据时持续运行。

**优化**：
```typescript
// 在 draw loop 开头：
if (!enabled || !data?.has_detection || videoRef.current?.paused) {
  // 视频暂停时不渲染，但保留最后一帧
  if (!videoRef.current?.paused) {
    requestAnimationFrame(draw);
  }
  return;
}
```

### 5.3 减少不必要的重渲染

**问题 3**：Dashboard 每次 `setCurrentVideo(data)` 都触发所有子组件重建。

**优化**：
- `React.memo` 包裹纯展示组件（VideoInfoCard, PipelineBar, VideoSummaryCard 等）
- `useMemo` 精细化依赖（不传整个 `currentVideo` 对象，只传需要的字段）
- DetectionContext 让 3 个检测组件共享状态而不经 Dashboard 中转

### 5.4 懒加载 + 虚拟化

- **检测列表**：若 track 数 > 50，使用虚拟列表（`IntersectionObserver` 或简单风控限制渲染数）
- **历史列表**：已有 client-side search，数量多时同样限制 DOM 节点数
- **搜索人脸结果**：`useMemo` 缓存 class-local IDs，不每次重新计算

### 5.5 计算缓存

| 计算 | 优化方式 |
|------|---------|
| `classLocalIds` (DetectionPanel) | useMemo，依赖 `tracks` |
| `computeLanes` (DetectionTimeline) | useMemo，依赖 `tracks + classFilter` |
| `filteredTracks` (DetectionTimeline) | useMemo，依赖 `tracks + classFilter` |
| `plateByTrack` (DetectionPanel) | useMemo，依赖 `plateData` |
| `streamReady` | useMemo，依赖具体字段而非整个 video 对象 |

---

## 六、数据流

### 6.1 上传 → 处理 → 完成

```
Upload 按钮 → hidden input → POST multipart → 返回
  → setCurrentVideoId + setCurrentVideo
  → setListKey (刷新历史列表)
  → setHasPendingParams(true) + setActivePanel("params")
  → ParameterPanel 自动弹出（禁止外部点击关闭）
  → 用户配置参数 → PUT /params → Pipeline 启动
  → useVideoPolling 开始 3s 轮询
  → 完成后 → useDetectionData 加载检测/人脸/车牌数据
  → streamReady → video 自动 load()
  → 检测三个组件通过 context 消费数据
```

### 6.2 搜索 → 定位

```
输入关键词 → POST /search/semantic → 结果列表
  → 点击结果 → setSeekTarget → useEffect 设置 video.currentTime
  → 若为 track 结果 → context.onTrackSelect → 三个组件同步高亮
```

### 6.3 检测交互（三个组件联动）

```
DetectionContext 持有:
  detectionData / faceData / plateData
  selectedTrackId / classFilter
  onTrackSelect() / onClassFilterChange()

DetectionOverlay           DetectionPanel             DetectionTimeline
  ├─ rAF 渲染 bbox           ├─ 分类筛选按钮            ├─ 泳道色条
  ├─ click 选 track ───→    ├─ 列表高亮 selected ──→   ├─ 高亮 selected
  ├─ hover 显示提示          ├─ 人脸/车牌内联            ├─ 人脸标记点
  └─ 运动轨迹                ├─ hover 大图预览           ├─ 播放头
                             └─ 导出按钮                └─ 点击选 track ───→
```

---

## 七、文件变更清单

### 新增文件

| 文件 | 说明 |
|------|------|
| `src/hooks/useHEVCCapability.ts` | 浏览器 HEVC 检测 |
| `src/hooks/useVideoPolling.ts` | 视频详情轮询 + visibility 感知 |
| `src/hooks/useProxyStatus.ts` | 代理转码状态轮询 |
| `src/hooks/useDetectionData.ts` | 检测数据懒加载 |
| `src/hooks/useStreamReady.ts` | stream 就绪度计算 |
| `src/hooks/useSearch.ts` | 搜索状态管理 |
| `src/hooks/useParameterForm.ts` | 参数表单状态管理 |
| `src/context/DetectionContext.tsx` | 检测状态上下文 |
| `src/components/Sidebar.tsx` | 新版侧边栏 (替代 LeftSidebar) |
| `src/components/Header.tsx` | 新版顶栏 |
| `src/components/SlideOutPanel.tsx` | 通用侧滑面板容器 |
| `src/components/VideoSection.tsx` | 中栏编排组件 |
| `src/components/VideoPlayer.tsx` | 视频播放器封装 |
| `src/components/RightPanel.tsx` | 右栏两列编排 |

### 重写文件

| 文件 | 变更 |
|------|------|
| `src/index.css` | 全新设计令牌，去除 fluid-blob，新增卡片/暗色时间轴样式 |
| `src/Dashboard.tsx` | 精简至 ~200 行，核心状态+编排，子组件拆分 |
| `src/types/index.ts` | 保持并扩展 |
| `src/components/ParameterPanel.tsx` | 新样式+保留全部功能+提取 useParameterForm |
| `src/components/HistoryPanelContent.tsx` | 新样式 |
| `src/components/PipelineBar.tsx` | 新样式（简化条形） |
| `src/components/VideoInfoCard.tsx` | 新样式（grid 布局，minor-card） |
| `src/components/DetectionPanel.tsx` | 新样式+保留人脸/车牌/悬停/导出全部功能 |
| `src/components/DetectionTimeline.tsx` | 新样式（深色背景） |
| `src/components/DetectionOverlay.tsx` | rAF 性能优化 |
| `src/components/VideoSummaryCard.tsx` | 新样式（minor-card） |
| `src/components/VideoSearchCard.tsx` | 新样式+保留 track/plate/face/结果 actions |
| `src/components/ExportMenu.tsx` | 新样式 |
| `src/components/SettingsPage.tsx` | 新样式+保留 Pipeline 调优表格 |
| `src/components/icons.tsx` | 按新设计调整图标 |

### 保留不变

| 文件 | 说明 |
|------|------|
| `src/App.tsx` | 纯壳，不动 |
| `src/main.tsx` | 入口，不动 |
| `src/services/api.ts` | API 层已经很干净，不动 |
| `src/utils/helpers.ts` | 工具函数，不动 |
| `src/mockData.ts` | Pipeline 阶段计算，不动 |

---

## 八、迁移步骤

### Phase 1: 基础设施

1. 重写 `index.css` —— 新设计令牌、去除 fluid-blob、新增卡片/时间轴样式
2. 创建 `hooks/` 目录，编写所有自定义 hooks
3. 创建 `context/DetectionContext.tsx`
4. 创建通用组件 `Sidebar.tsx`、`Header.tsx`、`SlideOutPanel.tsx`

### Phase 2: 核心重构

5. 重写 `Dashboard.tsx` —— 精简为编排器，引入 hooks + context
6. 创建 `VideoSection.tsx` + `VideoPlayer.tsx` —— 提取视频区域
7. 创建 `RightPanel.tsx` —— 两列 340px 布局

### Phase 3: 组件逐个重写

8. 重写 `VideoInfoCard.tsx` —— grid 布局 minor-card
9. 重写 `VideoSummaryCard.tsx` —— minor-card 样式
10. 重写 `DetectionPanel.tsx` —— major-card 样式 + 新列表 UI + 进度条
11. 重写 `DetectionTimeline.tsx` —— 深色主题
12. 重写 `DetectionOverlay.tsx` —— rAF 性能优化
13. 重写 `PipelineBar.tsx` —— 新样式
14. 重写 `VideoSearchCard.tsx` —— major-card 样式 + 全部搜索类型
15. 重写 `ParameterPanel.tsx` —— 新样式 + useParameterForm
16. 重写 `HistoryPanelContent.tsx` —— 新样式

### Phase 4: 收尾

17. 重写 `ExportMenu.tsx` —— 新样式
18. 重写 `SettingsPage.tsx` —— 新样式
19. 重写 `icons.tsx` —— 按需调整
20. 全面验证功能一致性

---

## 九、需要特别保留的功能清单（mockup 未体现）

以下功能 mockup 未画出，**全部保留**：

| 功能 | 所在组件 | mockup 对应位置 |
|------|---------|----------------|
| 参数面板侧滑交互 | SlideOutPanel + ParameterPanel | 无，侧滑保持 |
| 历史记录侧滑面板 | SlideOutPanel + HistoryPanelContent | 无，侧滑保持 |
| 设置页 (SettingsPage) | SettingsPage | 无，全页替换 |
| 视频信息 - 来源分析 (SourceAnalysis) | VideoInfoCard | 无，追加在 grid 后 |
| 视频信息 - AI 生成检测 (AIDetect) | VideoInfoCard | 无，追加在 grid 后 |
| 检测面板 - 人脸标签页切换 | DetectionPanel (showFaces toggle) | 无，objects/faces 切换保留 |
| 检测列表 - 人脸紫色图标 | DetectionPanel (dtc-face) | mockup 有 person #3 带 face 图标 ✅ |
| 检测列表 - 车牌内联显示 | DetectionPanel (dtc-plate) | mockup 有 car #01 带车牌 ✅ |
| 检测列表 - hover 240px 大图预览 | DetectionPanel | 无，保留 |
| 检测列表 - 导出按钮 (缩略图/track) | DetectionPanel + 函数 | 无，保留 |
| 搜索 - 人脸图片搜索 (👤按钮) | VideoSearchCard | mockup 有紫色人脸按钮 ✅ |
| 搜索 - track 结果 + 缩略图/轨迹按钮 | VideoSearchCard | mockup 有 car #03 的 actions ✅ |
| 搜索 - plate 结果 + 截图按钮 | VideoSearchCard | mockup 有车牌结果 ✅ |
| 搜索 - face 结果展示 | VideoSearchCard | mockup 有人脸匹配区域 ✅ |
| 搜索 - "下载段落" (clip 定位) | VideoSearchCard (frame 结果) | mockup 有下载按钮 ✅ |
| 搜索 - 搜索索引未开启置灰状态 | VideoSearchCard | 无，保留 |
| 处理中骨架屏 | PipelineBar + VideoSummaryCard + VideoSearchCard + VideoInfoCard | 无，保留 |
| 格式就绪覆盖层 (preparing/proxy progress) | VideoPlayer | 无，保留 |
| 代理失败覆盖层 | VideoPlayer | 无，保留 |
| ExportMenu 导出弹窗 | ExportMenu | 无，保留 |
| PipelineBar subtitle "等待参数配置..." | PipelineBar | 无，保留 |
| DetectionTimeline 泳道 hover 工具提示 | DetectionTimeline | 无，保留 |
| DetectionTimeline 人脸标记点 | DetectionTimeline | mockup 有白色圆点 ✅ |
| VideoInfoCard 骨架屏/错误/空三种状态 | VideoInfoCard | 无，保留 |
| 参数面板 COCO 80 类选择器 | ParameterPanel | 无，保留 |
| 参数面板 custom params localStorage 持久化 | ParameterPanel | 无，保留 |
| 参数面板 summaries_mode 选择 | ParameterPanel | 无，保留 |

---

## 十、技术栈

| 工具 | 版本 |
|------|------|
| React | 19 |
| TypeScript | ~5.x |
| Vite | 6 |
| Tailwind CSS | 4 |
| 状态管理 | 无 Redux — Context + hooks |
| 包管理器 | npm |

---

## 十一、关键设计决策总结

| 决策 | 理由 |
|------|------|
| Context 而非 Redux | 检测联动是 3 个组件，范围小，Context 足够；避免引入额外依赖 |
| 自定义 hooks 抽离副作用 | 可测试、可复用、Dashboard 精简 |
| React.memo 选择性使用 | 只在列表项和纯展示卡片上用，避免过度优化 |
| 不引入虚拟滚动库 | 检测/历史数据量在 demo 级 < 200 条，简单限 DOM 足够 |
| 保留现有 api.ts / helpers.ts / mockData.ts | 已是干净抽象，无需动 |
| CSS 变量 + Tailwind 任意值 | Tailwind 4 `@theme` 桥接设计令牌，同时保留 Tailwind 便利 |
| Visibility-aware 轮询 | 轻量方案，不需要 Web Worker 或 Service Worker |
