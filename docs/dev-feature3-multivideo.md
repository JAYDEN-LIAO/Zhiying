# Dev Doc: 多视频处理

> 目标：支持一次上传多个视频、历史记录以「组」展示、组内视频切换、跨视频搜索、检测面板独立视频切换。

## 现状分析

### 当前架构限制

- **上传**：一次只能上传一个文件，`Dashboard.handleUpload()` 创建单个 `<input>` 并处理单个文件
- **视频列表**：`videos: VideoListItem[]` 是平面数组，无分组概念
- **视频状态**：一个 `currentVideoId` + 一个 `currentVideo`，一次只能查看/处理一个视频
- **后端 Video 模型**：无 `group_id` 或任何分组字段
- **搜索**：已支持 `video_ids` 过滤，搜索结果包含 `video_id` 字段
- **检测数据**：`useDetectionData` hook 绑定到 `currentVideoId`，无独立切换

### 涉及文件（前端）

| 文件 | 角色 |
|---|---|
| `Dashboard.tsx` | 状态编排（上传/选择/切换） |
| `HistoryPanelContent.tsx` | 历史记录列表渲染 |
| `Header.tsx` | 顶部栏（视频名称/参数标签） |
| `VideoSection.tsx` | 中间列编排 |
| `VideoPlayer.tsx` | 视频播放器 |
| `RightPanel.tsx` | 右侧面板编排 |
| `DetectionPanel.tsx` | 物体检测面板 |
| `VideoSearchCard.tsx` | 视频搜索卡片 |
| `VideoSummaryCard.tsx` | 视频摘要卡片 |
| `VideoInfoCard.tsx` | 视频信息卡片 |
| `DetectionTimeline.tsx` | 检测时间轴 |
| `api.ts` | API 调用层 |
| `types/index.ts` | TypeScript 类型 |
| `hooks/useVideoPolling.ts` | 视频轮询 |
| `hooks/useDetectionData.ts` | 检测数据获取 |
| `hooks/useProxyStatus.ts` | 代理状态轮询 |

### 已就绪基础设施

- 搜索 API 已支持 `video_ids` 多视频过滤
- 搜索结果已包含 `video_id` 字段
- `GET /videos/` 列表接口返回全部视频
- `PUT /videos/{id}/params` + `BackgroundTasks` 支持异步处理

## 总体设计方案

### 数据模型（后端新增）

新建 `video_groups` 表，用于将多个视频关联到一个组：

```sql
CREATE TABLE video_groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(256) DEFAULT NULL,      -- 组名（可选）
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

`videos` 表增加一列：

```sql
ALTER TABLE videos ADD COLUMN group_id UUID REFERENCES video_groups(id) ON DELETE SET NULL;
```

不强制非空，单视频上传时 `group_id = NULL`。

**后端改动**：

| 文件 | 改动 |
|---|---|
| `core/models.py` | 新增 `VideoGroup` ORM 模型；`Video` 表增加 `group_id` 列 |
| `api/video_routes.py` | 新增 `POST /videos/upload/batch` 批量上传端点；单视频上传不变 |
| `api/schemas.py` | 新增 `VideoGroupResponse` DTO |
| `core/db.py` | `init_db()` 增量迁移：`ALTER TABLE ... ADD COLUMN IF NOT EXISTS group_id` |

### 上传流程

#### 新增：批量上传端点 `POST /api/v1/videos/upload/batch`

```python
@router.post("/videos/upload/batch", status_code=201)
async def upload_videos_batch(
    request: Request,
    files: list[UploadFile] = File(...),    # 多个文件
    # 参数和单视频上传相同，应用到组内所有视频
    content_type: str = Form("general"),
    # ... 其余参数 ...
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[VideoResponse]]:
```

1. 创建 `VideoGroup` 记录
2. 循环每个文件：保存到磁盘、创建 `Video` 记录（`group_id` 指向新组）、同步 probe、异步 remux/proxy、AICheck
3. 返回该组所有 `VideoResponse` 列表

#### 前端上传改动

`Dashboard.tsx` 中 `handleUpload`：

```typescript
const handleUpload = useCallback(() => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".mp4,.mov,.avi,.mkv,.webm";
    input.multiple = true;                    // ★ 允许多选
    input.onchange = async () => {
      const files = input.files;
      if (!files || files.length === 0) return;
      setIsUploading(true);
      try {
        if (files.length === 1) {
          // 单个文件 → 原有单视频逻辑
          const result = await api.upload(files[0]);
          setCurrentVideoId(result.id);
          setCurrentVideo(result);
        } else {
          // 多个文件 → 批量上传
          const results = await api.uploadBatch(Array.from(files));
          // 组内第一个视频自动选中
          setCurrentVideoId(results[0].id);
          setCurrentVideo(results[0]);
          // ★ 存储组信息
          setVideoGroups(prev => [...prev, {
            groupId: results[0].group_id!,  // 所有视频共享同一个 group_id
            videoIds: results.map(r => r.id),
          }]);
        }
        setListKey((k) => k + 1);
        setHasPendingParams(true);
        setActivePanel("params");
      } catch (err) {
        alert(err instanceof Error ? err.message : "上传失败");
      }
      setIsUploading(false);
    };
    input.click();
}, []);
```

### Dashboard.tsx — 新增分组状态

```typescript
interface VideoGroup {
  groupId: string;
  videoIds: string[];
}

const [videoGroups, setVideoGroups] = useState<VideoGroup[]>([]);
const [currentGroupVideos, setCurrentGroupVideos] = useState<string[]>([]); // 当前选中组的所有视频ID
```

当选中某个视频时，根据其 `group_id` 查询组内所有视频：

```typescript
const handleSelect = useCallback((id: string, groupId?: string) => {
    // ... 原有逻辑 ...
    if (groupId) {
      const group = videoGroups.find(g => g.groupId === groupId);
      setCurrentGroupVideos(group?.videoIds ?? [id]);
    } else {
      setCurrentGroupVideos([id]);
    }
}, []);
```

### 前端组件架构

```
Dashboard (分组状态 + 视频切换)
  ├── Header (statsBar: 组选择器 + 视频名称切换下拉)
  ├── SlideOutPanel > HistoryPanelContent (组卡片 + 展开动画)
  └── Main Area
      ├── VideoSection
      │   ├── VideoPlayer (key={videoId} 自动切换)
      │   └── DetectionTimeline (跟随 videoId)
      │   └── PipelineBar (跟随 videoId)
      └── RightPanel
          ├── DetectionPanel (新增独立视频选择器，可独立于 header 切换)
          ├── VideoSearchCard (搜索同组全部 / 下拉选特定视频)
          ├── VideoSummaryCard (跟随 videoId)
          └── VideoInfoCard (跟随 videoId)
```

## 详细设计

### 3a. 历史记录「组」交互

#### 数据结构

`HistoryPanelContent` 接收分组后的列表。在 `Dashboard` 中预处理：

```typescript
// 将 videos 按 group_id 分组
// 无 group 的单独作为一项
interface HistoryGroup {
  type: "group" | "single";
  groupId?: string;
  videoIds: string[];
  videos: VideoListItem[];  // group 内多个 / single 内一个
}
```

#### 重叠卡片效果

```tsx
// 组卡片（重叠样式）
{group.type === "group" && (expandedGroupId !== group.groupId ? (
  // 折叠态：多卡片重叠
  <div className="group-stack" onClick={() => setExpandedGroupId(group.groupId)}>
    {group.videos.slice(0, 3).map((v, i) => (
      <div key={v.id} className="group-card-stacked"
        style={{
          transform: `rotate(${(i - 1) * 2}deg) translateY(${i * -4}px)`,
          zIndex: 3 - i,
        }}
      >
        {/* 卡片内容 */}
      </div>
    ))}
    <div className="group-count-badge">{group.videos.length} 个视频</div>
  </div>
) : (
  // 展开态：丝滑展开（height transition）
  <div className="group-expanded">
    {group.videos.map((v) => (
      <div key={v.id} className="group-item"> {/* 展开后的各个视频项 */} </div>
    ))}
  </div>
))}
```

**CSS 过渡**：折叠到展开用 `max-height` + `opacity` transition，展开后每个子项带 `stagger-delay` 以产生逐个出现效果。

#### 组选中逻辑

点击组卡片 → 展开；点击组内某个视频 → 选中并关闭缩回。
点击外部其他记录 → 组自动缩回（`Dashboard` 中展开状态与 `currentVideoId` 联动）。

### 3b. Header 视频切换

#### Header.tsx — 新增组模式渲染

当前 `statsBar: ReactNode` 改为更灵活接口，当组内有多个视频时：

```tsx
// Header 中
{groupVideos.length > 1 ? (
  <div className="header-group-selector">
    <span className="header-stats-name">{currentVideo.file_name}</span>
    <button className="header-switch-btn" onClick={toggleDropdown}>
      <svg>▼</svg>
    </button>
    {/* 下拉列表切换不同视频 */}
    {dropdownOpen && (
      <div className="header-video-dropdown">
        {groupVideos.map(v => (
          <button key={v.id} onClick={() => onSwitchVideo(v.id)}
            className={v.id === currentVideoId ? "active" : ""}>
            {v.file_name}
          </button>
        ))}
      </div>
    )}
  </div>
) : (
  // 单视频：原样渲染
  <span className="header-stats-name">{currentVideo.file_name}</span>
)}
```

**联动**：切换时调用 `Dashboard.handleGroupVideoSwitch(videoId)` → 同步更新 `currentVideoId`, `currentVideo`, `seekTarget` 等。

#### 联动的组件

| 组件 | 切换行为 |
|---|---|
| `VideoPlayer` | `key={videoId}` → 自动 unmount/remount，加载新流 |
| `DetectionTimeline` | 通过 `DetectionTimeline` 的 `videoId` 重新加载检测数据 |
| `VideoSummaryCard` | 重新加载摘要 |
| `VideoInfoCard` | `useEffect [videoId]` 重新获取元数据 |
| 轮询 hooks | `videoId` 变化 → 清理旧轮询 → 启动新轮询 |

### 3c. 搜索跨组联动

#### 搜索范围控制

已有基础设施：`POST /search/semantic` 支持 `video_ids` 参数。

前端 UI：

```tsx
// 搜索栏顶部新增
<div className="search-scope-selector">
  <button className={searchScope === "current" ? "active" : ""}
    onClick={() => setSearchScope("current")}>
    当前视频
  </button>
  <button className={searchScope === "group" ? "active" : ""}
    onClick={() => setSearchScope("group")}>
    当前组({groupVideos.length})
  </button>
  {groups.length > 0 && (
    <select onChange={e => setSearchScope(e.target.value === "all" ? "all" : "custom")}>
      <option value="all">全部视频</option>
      {groups.map(g => <option key={g.groupId}>组 {g.groupId}</option>)}
    </select>
  )}
</div>
```

映射到 API 调用：

```typescript
const videoIds = searchScope === "current" ? [currentVideoId]
  : searchScope === "group" ? currentGroupVideos
  : undefined;  // 全部
const data = await api.searchSemantic(query, { video_ids: videoIds });
```

#### 搜索结果点击 → 跨视频跳转

搜索结果每个 `item` 已包含 `video_id`。

点击结果时，判断如果 `item.video_id !== currentVideoId`：

```typescript
onClick={() => {
  if (item.video_id !== currentVideoId) {
    // 先切换视频
    onSwitchVideo(item.video_id);
    // 再跳转到时间点
    setTimeout(() => onSeekTo(item.precise_start, item.precise_end), 100);
  } else {
    onSeekTo(item.precise_start, item.precise_end);
  }
}}
```

**效果**：搜索到视频2的结果 → 点击 → Header 切换到视频2、播放器加载视频2 并 seek 到对应时间点。

### 3d. 检测面板独立视频切换

#### DetectionPanel.tsx — 新增视频选择器

在「全部品类」下拉栏**左边**新增视频下拉：

```tsx
<div className="dtc-video-selector">
  <select value={detectionVideoId} onChange={e => onDetectionVideoChange(e.target.value)}>
    {groupVideos.map(v => (
      <option key={v.id} value={v.id}>{shortName(v.file_name)}</option>
    ))}
  </select>
</div>
```

**独立切换**：`detectionVideoId` 是独立于 `currentVideoId` 的状态，由 `Dashboard.tsx` 管理：

```typescript
const [detectionVideoId, setDetectionVideoId] = useState<string | null>(null);
// 默认与 currentVideoId 同步
useEffect(() => {
  if (!detectionVideoId && currentVideoId) setDetectionVideoId(currentVideoId);
}, [currentVideoId]);
```

#### 检测数据获取独立

`useDetectionData` hook 也需要独立调用：

```typescript
const { detectionData, faceData, plateData } = useDetectionData(
  detectionVideoId ?? currentVideoId,   // ★ 用独立 ID
  showDetection,
  currentVideo?.face_enabled ?? false,
  currentVideo?.plate_enabled ?? false,
);
```

#### 联动规则

| 操作 | 行为 |
|---|---|
| 用户在检测面板选择视频2 | 检测数据切换到视频2，但播放器仍播放视频1 |
| 用户点击检测面板中的某个物体（track） | 联动跳转：切换到视频2 + seek 到对应时间点 |

```typescript
const handleDetectionTrackSelect = useCallback((trackId: number, className: string, seekTo?: number) => {
  // 如果检测面板正看着别的视频，先切换当前视频
  if (detectionVideoId && detectionVideoId !== currentVideoId) {
    handleGroupVideoSwitch(detectionVideoId);
  }
  setSelectedTrackId(trackId);
  if (seekTo !== undefined && videoRef.current) {
    videoRef.current.currentTime = seekTo;
  }
}, [detectionVideoId, currentVideoId, handleGroupVideoSwitch]);
```

## 改动清单

### 后端

| 文件 | 改动 |
|---|---|
| `core/models.py` | 新增 `VideoGroup` 模型；`Video` 表加 `group_id` 列 (FK → video_groups.id) |
| `core/db.py` | `init_db()` 增量迁移加列 |
| `api/video_routes.py` | 新增 `POST /videos/upload/batch` 批量上传端点 |
| `api/schemas.py` | 新增 `VideoGroupResponse` DTO；`VideoResponse` 加 `group_id` 字段 |
| `core/repository.py` | 可选：新增 `list_video_groups()` 查询 |

### 前端

| 文件 | 改动 |
|---|---|
| `types/index.ts` | `VideoListItem` / `VideoResponse` 加 `group_id`；新增 `VideoGroup` 类型 |
| `services/api.ts` | 新增 `uploadBatch()` 方法；`listVideos()` 支持返回 `group_id` |
| `Dashboard.tsx` | 新增分组状态 (`videoGroups`, `currentGroupVideos`, `expandedGroupId`, `detectionVideoId`)；修改 `handleUpload` 支持多选；新增 `handleGroupVideoSwitch`；修改 `handleSelect` 传入 groupId |
| `Header.tsx` | 新增组切换下拉 UI；`onSwitchVideo` 回调 |
| `HistoryPanelContent.tsx` | 完全重写为分组展示：重叠样式 + 展开/缩回动画 |
| `DetectionPanel.tsx` | 新增独立视频选择器；`detectionVideoId` prop |
| `VideoSearchCard.tsx` | 新增搜索范围选择器（当前/组内/全部）；结果点击跨视频跳转 |
| `RightPanel.tsx` | 传递 `groupVideos` 和 `onDetectionVideoChange` 到 DetectionPanel |
| `VideoSection.tsx` | 可选改动：传递 group info |

## 新增的联动逻辑总结

以下场景如果文档未明确提及，可按「同组视频切换逻辑」补充：

| 场景 | 预期行为 |
|---|---|
| 搜索到视频A的结果，当前播放视频B | 自动切换当前视频到A + seek |
| 检测面板选视频A，点击A中物体 | 自动切换当前视频到A + seek |
| 播放器正在播放视频A，检测面板选视频B | 播放器继续放A，检测面板显示B的数据（独立） |
| Header下拉切换视频 | 播放器、时间轴、摘要、信息卡片联动切 |
| 搜索结果中只显示同组视频，但搜索栏自定义可选全部 | 搜索范围切换时清空结果重新搜索 |
| 删除组内的一个视频 | 组仍在，count 减少；删除全部后组消失 |
| 新增上传不组组 | `group_id = NULL`，历史记录中作为单视频项展示 |
