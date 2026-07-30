# Dev Doc: 前端标签中文化

> 目标：所有前端展示的物体检测标签从英文（`person#75`, `car#1`）改为中文（`人#75`, `汽车#1`），后端完全不动。

## 现状分析

### 标签数据流

```
YOLO 推理 (COCO 英文) → DB class_name → API /detection/data
  → TypeScript Detection.class_name (string)
    → DetectionOverlay (canvas 绘制)
    → DetectionPanel (物体列表)
    → DetectionTimeline (时间轴)
    → VideoSearchCard (搜索结果)
```

`class_name` 来自 YOLO COCO 数据集标准英文名，前后端之间无任何转换层。

### 涉及文件与渲染位置

| 文件 | 行数 | 展示点 | 标签示例 |
|---|---|---|---|
| `DetectionOverlay.tsx` | 163 | Canvas bbox 文字 | `person #75` |
| `DetectionOverlay.tsx` | 116, 135, 148, 158 | Canvas 颜色查找 | keys: person, car... |
| `DetectionOverlay.tsx` | 247 | Click 回调 `onTrackSelect` | `best.class_name` |
| `DetectionPanel.tsx` | 218, 238, 248, 284 | 下拉筛选 + 列表 + 头部 | `person · 12`, `truck #3` |
| `DetectionPanel.tsx` | 261-262 | 功能开关硬编码 | `"person"` (人脸关联), `["car","truck","bus","motorcycle"]` (车牌显示) |
| `DetectionTimeline.tsx` | 144, 179-180 | 时间轴标签 + 悬浮提示 | `person #2`, `car #5` |
| `VideoSearchCard.tsx` | 237 | 搜索结果 track 标签 | `person #2` |

### 三份重复的 CLASS_COLORS 映射

- `DetectionOverlay.tsx:11-26` — 26 项 + default
- `DetectionPanel.tsx:10-18` — 22 项 + default
- `DetectionTimeline.tsx:9-17` — 22 项 + default

**问题**：不一致、重复维护、未中文化。

## 设计方案

### 方案：维护一份 `en→zh` 映射表

新建 `frontend/src/labels.ts` 作为唯一的标签映射中心，导出两个函数供全局使用。

#### labels.ts 内容

```typescript
/* ════════════════════════════════════════════════════════════
   labels.ts — 英文 YOLO COCO 类名 → 中文映射 + 颜色表
   所有组件从此文件导入，不各自维护。
   ════════════════════════════════════════════════════════════ */

/** 英文 → 中文映射（完整 80 类 + 补充） */
export const ZH_LABELS: Record<string, string> = {
  person: "人",
  bicycle: "自行车",
  car: "汽车",
  motorcycle: "摩托车",
  airplane: "飞机",
  bus: "公交车",
  train: "火车",
  truck: "卡车",
  boat: "船",
  "traffic light": "红绿灯",
  "fire hydrant": "消防栓",
  "stop sign": "停止标志",
  parking_meter: "停车计时器",
  bench: "长椅",
  bird: "鸟",
  cat: "猫",
  dog: "狗",
  horse: "马",
  sheep: "羊",
  cow: "牛",
  elephant: "大象",
  bear: "熊",
  zebra: "斑马",
  giraffe: "长颈鹿",
  backpack: "背包",
  umbrella: "雨伞",
  handbag: "手提包",
  tie: "领带",
  suitcase: "行李箱",
  frisbee: "飞盘",
  skis: "滑雪板",
  snowboard: "滑雪板",
  sports_ball: "球",
  kite: "风筝",
  baseball_bat: "棒球棒",
  baseball_glove: "棒球手套",
  skateboard: "滑板",
  surfboard: "冲浪板",
  tennis_racket: "网球拍",
  bottle: "瓶子",
  "wine glass": "酒杯",
  cup: "杯子",
  fork: "叉子",
  knife: "刀",
  spoon: "勺子",
  bowl: "碗",
  banana: "香蕉",
  apple: "苹果",
  sandwich: "三明治",
  orange: "橙子",
  broccoli: "西兰花",
  carrot: "胡萝卜",
  "hot dog": "热狗",
  pizza: "披萨",
  donut: "甜甜圈",
  cake: "蛋糕",
  chair: "椅子",
  couch: "沙发",
  "potted plant": "盆栽",
  bed: "床",
  "dining table": "餐桌",
  toilet: "马桶",
  tv: "电视",
  laptop: "笔记本电脑",
  mouse: "鼠标",
  remote: "遥控器",
  keyboard: "键盘",
  "cell phone": "手机",
  microwave: "微波炉",
  oven: "烤箱",
  toaster: "烤面包机",
  sink: "水槽",
  refrigerator: "冰箱",
  book: "书",
  clock: "钟表",
  vase: "花瓶",
  scissors: "剪刀",
  "teddy bear": "泰迪熊",
  "hair drier": "吹风机",
  toothbrush: "牙刷",
} as const;

/** 传入英文 class_name → 返回中文（无匹配则返回原值） */
export function zh(cls: string): string {
  return ZH_LABELS[cls] ?? cls;
}

/** 构造中文化标签文本，如 "人 #75" */
export function zhLabel(cls: string, id: number | string): string {
  return `${zh(cls)} #${id}`;
}

/** 英文 → 颜色的统一映射（和 ZH_LABELS 共源，不再各自维护） */
export const CLASS_COLORS: Record<string, string> = {
  person: "#FF6B6B", bicycle: "#45B7D1", car: "#4ECDC4", motorcycle: "#F7DC6F",
  airplane: "#A29BFE", bus: "#96CEB4", train: "#DDA0DD", truck: "#FF9F43",
  boat: "#54A0FF", "traffic light": "#FFD700", "fire hydrant": "#FF4757",
  "stop sign": "#FF6348", bench: "#7BED9F", bird: "#70A1FF", cat: "#FFA502",
  dog: "#FF6348", horse: "#E056A0", backpack: "#00B894", umbrella: "#6C5CE7",
  handbag: "#E17055", tie: "#0984E3", suitcase: "#00CEC9",
  skis: "#81ECEC", snowboard: "#74B9FF", skateboard: "#F8A5C2",
  bottle: "#17E8B5", cup: "#FDA7DF", bowl: "#F19066",
  banana: "#FFEAA7", apple: "#FF7675", sandwich: "#FDCB6E",
  chair: "#A29BFE", couch: "#DFE6E9", bed: "#636E72",
  "dining table": "#B2BEC3", tv: "#0984E3", laptop: "#6C5CE7",
  "cell phone": "#54A0FF", remote: "#FDCB6E", keyboard: "#74B9FF",
  book: "#A3CB38", clock: "#F8A5C2", vase: "#D980FA",
  default: "#95A5A6",
};

/** 获取颜色（统一入口） */
export function colorOf(cls: string): string {
  return CLASS_COLORS[cls] ?? CLASS_COLORS.default;
}
```

### 改动清单

| 文件 | 改动 |
|---|---|
| ✅ **新建** `frontend/src/labels.ts` | 唯一映射 + `zh()` / `zhLabel()` / `colorOf()` |
| 📝 `DetectionOverlay.tsx` | 删除本地 `CLASS_COLORS`，改为 import；第 163 行标签用 `zhLabel()`；第 116 行颜色用 `colorOf()`；class_name 保持英文值只在展示时转 |
| 📝 `DetectionPanel.tsx` | 删除本地 `CLASS_COLORS`，改为 import；第 218/238/248/284 行展示用 `zh()`；颜色用 `colorOf()`；第 261-262 行硬编码英文比较不需要改（它们是逻辑判断，不是展示） |
| 📝 `DetectionTimeline.tsx` | 删除本地 `CLASS_COLORS`，改为 import；时间轴标签 144/179 用 `zhLabel()`，颜色用 `colorOf()` |
| 📝 `VideoSearchCard.tsx` | 第 237 行搜索结果用 `zhLabel()` |
| 📝 `ParameterPanel.tsx` | 第 71-84 行的 COCO 英文列表改成中文显示（提交时仍传英文给后端） |

### 不改的地方

- **后端** — 完全不修改
- **`api.ts`** — 不对 API 响应做任何转换
- **`types/index.ts`** — `class_name: string` 保持原样
- **`Dashboard.tsx`** — state 中的 `classFilter` 仍是英文值（用于和 API 数据比对）
- **逻辑判断** — `if (t.class_name === "person")` 这类逻辑仍用英文，只在渲染时转中文

### 关键设计决策

1. **`zh()` 函数无匹配时返回原值** — 新模型或自定义类名不会出 bug
2. **`CLASS_COLORS` 统一管理** — 消除三份重复、不一致的映射表
3. **颜色 key 仍用英文** — 逻辑不变；展示中文但查找颜色时用英文 key
4. **`zhLabel()` 一次搞定 "中文 #ID"** — 几个组件中的 `f"{class_name} #{track_id}"` 模式都统一成一句

### 实施步骤

1. 创建 `frontend/src/labels.ts`
2. DetectionOverlay.tsx：改 import，改 bbox 标签渲染（`zhLabel`），改颜色获取
3. DetectionPanel.tsx：改 import，改 class filter 展示（`zh`），改 track 列表展示
4. DetectionTimeline.tsx：改 import，改时间轴标签和悬浮提示
5. VideoSearchCard.tsx：改搜索结果 track 标签
6. ParameterPanel.tsx：COCO 列表展示中文化（提交值不变）
7. 验证：上传视频 → 物体检测 → 所有标签显示中文
