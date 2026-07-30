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

/** 英文 → 颜色的统一映射（Overlay 版为基础，补充常用类） */
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
