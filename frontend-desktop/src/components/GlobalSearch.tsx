/* ════════════════════════════════════════════════════════════
   GlobalSearch — 全局搜索（v0.38）
   跨文件夹语义检索 / 以图搜图。经典左右分栏：
     左 34% 检索配置（文本/图像 Tab + Smart Chips + 范围 + 开始）
     右 66% 结果展示（状态栏 + 自适应卡片网格）
   ════════════════════════════════════════════════════════════ */

import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../services/api";
import { useApp } from "../AppContext";
import type { SearchResultItem, VideoListItem } from "../types";
import { formatSec, fmtFullDate } from "../utils/helpers";
import { zh } from "../labels";
import { IconSearch5, IconImageSearch, IconFolder, IconClock, IconClose, IconVideo, IconRetry, IconSort, IconImage, IconPlus } from "./icons";
import { SubjectPhotoPicker } from "./SubjectPhotoPicker";
import { SplitPane } from "./SplitPane";
import { AddSubjectDrawer, type AddSubjectDrawerData } from "./AddSubjectDrawer";

type TabKey = "text" | "image";
type SortKey = "time" | "confidence" | "name";

interface FeatureChip {
  key: string;
  label: string;
  color?: string;
}

/* ── 4 大目标类型 + 各自专属特征 ──
   选中某类型后专属特征面板才出现；颜色/事件为常驻通用特征。
   文本框拼接按「预设句式」组合 token，不把类型名写入。 */
const TYPE_CHIPS: { key: string; label: string; features: FeatureChip[]; phrase: string }[] = [
  { key: "person", label: "人", phrase: "{color}{服饰}{年龄}{性别}{配饰}{动作}", features: [
    { key: "short_sleeve", label: "短袖" }, { key: "long_sleeve", label: "长袖" },
    { key: "coat", label: "外套" }, { key: "vest", label: "无袖" },
    { key: "long_pants", label: "长裤" }, { key: "short_pants", label: "短裤" },
    { key: "skirt", label: "裙子" },
    { key: "young", label: "青年" }, { key: "middle", label: "中年" }, { key: "elder", label: "老年" },
    { key: "male", label: "男子" }, { key: "female", label: "女子" },
    { key: "hat", label: "帽子" }, { key: "glasses", label: "眼镜" }, { key: "mask", label: "口罩" },
    { key: "backpack", label: "背包" },
    { key: "walking", label: "行走" }, { key: "running", label: "奔跑" },
    { key: "standing", label: "站立" }, { key: "sitting", label: "坐着" },
    { key: "riding", label: "骑行" },
  ]},
  { key: "vehicle", label: "车", phrase: "{color}{车型}{车牌}", features: [
    { key: "sedan", label: "轿车" }, { key: "suv", label: "SUV" },
    { key: "truck", label: "卡车" }, { key: "bus", label: "公交车" },
    { key: "van", label: "面包车" }, { key: "taxi", label: "出租车" },
    { key: "police_car", label: "警车" }, { key: "ambulance", label: "救护车" },
    { key: "motorcycle", label: "摩托车" }, { key: "ebike", label: "电动车" },
    { key: "bicycle", label: "自行车" },
    { key: "blue_plate", label: "蓝牌" }, { key: "green_plate", label: "绿牌" },
    { key: "yellow_plate", label: "黄牌" },
  ]},
  { key: "plate", label: "车牌", phrase: "{省份}", features: [
    { key: "jing", label: "京" }, { key: "jin", label: "津" },
    { key: "ji", label: "冀" }, { key: "jin2", label: "晋" },
    { key: "meng", label: "蒙" }, { key: "liao", label: "辽" },
    { key: "ji2", label: "吉" }, { key: "hei", label: "黑" },
    { key: "hu", label: "沪" }, { key: "su", label: "苏" },
    { key: "zhe", label: "浙" }, { key: "wan", label: "皖" },
    { key: "min", label: "闽" }, { key: "gan", label: "赣" },
    { key: "lu", label: "鲁" }, { key: "yu", label: "豫" },
    { key: "e", label: "鄂" }, { key: "xiang", label: "湘" },
    { key: "yue", label: "粤" }, { key: "gui", label: "桂" },
    { key: "qiong", label: "琼" }, { key: "yu2", label: "渝" },
    { key: "chuan", label: "川" }, { key: "gui2", label: "贵" },
    { key: "yun", label: "云" }, { key: "zang", label: "藏" },
    { key: "shan", label: "陕" }, { key: "gan2", label: "甘" },
    { key: "qing", label: "青" }, { key: "ning", label: "宁" },
    { key: "xin", label: "新" },
  ]},
  { key: "text", label: "文本", phrase: "{关键词}", features: [
    { key: "现金", label: "现金" }, { key: "见面", label: "见面" },
    { key: "交谈", label: "交谈" }, { key: "抽烟", label: "抽烟" },
    { key: "打电话", label: "打电话" }, { key: "拍照", label: "拍照" },
    { key: "握手", label: "握手" }, { key: "拥抱", label: "拥抱" },
    { key: "倒地", label: "倒地" }, { key: "逃跑", label: "逃跑" },
    { key: "翻墙", label: "翻墙" }, { key: "戴帽", label: "戴帽" },
    { key: "口罩", label: "口罩" }, { key: "拎包", label: "拎包" },
    { key: "背包", label: "背包" }, { key: "拉箱", label: "拉箱" },
  ]},
];

/* 颜色（人/车/非机动车通用，常驻显示） */
const COLOR_CHIPS: FeatureChip[] = [
  { key: "黑色", label: "黑色", color: "#3b4252" },
  { key: "白色", label: "白色", color: "#f0f2f5" },
  { key: "红色", label: "红色", color: "#f04444" },
  { key: "蓝色", label: "蓝色", color: "#4f6ef7" },
  { key: "黄色", label: "黄色", color: "#f7c948" },
  { key: "绿色", label: "绿色", color: "#36b37e" },
  { key: "灰色", label: "灰色", color: "#8a94a6" },
  { key: "银色", label: "银色", color: "#c0c8d4" },
];

/* 事件（常驻通用特征） */
const ACTION_CHIPS: FeatureChip[] = [
  { key: "打架", label: "打架" }, { key: "摔倒", label: "摔倒" },
  { key: "追逐", label: "追逐" }, { key: "聚集", label: "聚集" },
  { key: "挥手", label: "挥手" }, { key: "搬运", label: "搬运" },
  { key: "争吵", label: "争吵" }, { key: "偷窃", label: "偷窃" },
  { key: "拥堵", label: "拥堵" }, { key: "碰撞", label: "碰撞" },
  { key: "违停", label: "违停" }, { key: "超速", label: "超速" },
  { key: "逆行", label: "逆行" }, { key: "闯红灯", label: "闯红灯" },
  { key: "火灾", label: "火灾" }, { key: "烟雾", label: "烟雾" },
  { key: "闯入", label: "闯入" }, { key: "徘徊", label: "徘徊" },
];

const PRECISION_LABEL: Record<string, string> = {
  plate: "车牌",
  track: "物体",
  text: "文字",
  label: "标签",
  scene: "画面",
  chunk: "片段",
  frame: "画面",
};

/* 胶囊色调：按目标类型分配不同颜色背景 */
const TAG_TONES: Record<string, string> = {
  行人: "blue",
  车: "indigo",
  车辆: "indigo",
  车牌: "purple",
  文字: "amber",
  物体: "teal",
  画面: "slate",
  片段: "slate",
  标签: "slate",
};

/* 从识别描述中提取颜色特征（如「红衣」→「红色」） */
const COLOR_WORDS: [string, string][] = [
  ["红色", "红色"],
  ["红衣", "红色"],
  ["橙色", "橙色"],
  ["黄色", "黄色"],
  ["绿色", "绿色"],
  ["蓝色", "蓝色"],
  ["紫色", "紫色"],
  ["白色", "白色"],
  ["黑色", "黑色"],
  ["灰色", "灰色"],
  ["粉色", "粉色"],
];

export function GlobalSearch() {
  const { videos, caseGroups, openWorkbench, selectedTree } = useApp();

  const [tab, setTab] = useState<TabKey>("text");
  const [query, setQuery] = useState("");
  const [chips, setChips] = useState<Set<string>>(new Set());
  const [activeTypeKey, setActiveTypeKey] = useState<string | null>(null);
  /* 当前展示特征面板的目标类型定义 */
  const activeTypeDef = useMemo(
    () => TYPE_CHIPS.find((t) => t.key === activeTypeKey) ?? null,
    [activeTypeKey],
  );

  /* ── 句式化搜索字符串：根据当前激活类型，按预设模板组合已选 token ── */
  function buildPhrase(q: string): string {
    if (!activeTypeDef) return q;
    /* 从 q 中分出「类型自有 token」+「常驻 token（颜色/事件）」，并按类型特征 key 过滤 */
    const allTokens = q.split(/\s+/).filter(Boolean);
    const typeFeatKeys = new Set(activeTypeDef.features.map((f) => f.key));
    const colorActionKeys = new Set([
      ...COLOR_CHIPS.map((c) => c.key),
      ...ACTION_CHIPS.map((c) => c.key),
    ]);
    /* 类型自有 token（必须属于当前类型的 features 集合） */
    const typeFeats: string[] = [];
    const others: string[] = [];
    for (const tok of allTokens) {
      if (typeFeatKeys.has(tok)) typeFeats.push(tok);
      else others.push(tok);
    }
    /* 按类型预设句式排序 typeFeats：把颜色放最前、车型放颜色后 */
    const phrase = activeTypeDef.phrase;
    const sortedFeats: string[] = [];
    const placeholders = phrase.match(/\{[^}]+\}/g) ?? [];
    for (const ph of placeholders) {
      const slot = ph.slice(1, -1);
      if (slot === "color") {
        sortedFeats.push(...typeFeats.filter((t) => colorActionKeys.has(t) && COLOR_CHIPS.some((c) => c.key === t)));
      } else if (slot === "动作" || slot === "事件") {
        sortedFeats.push(...typeFeats.filter((t) => colorActionKeys.has(t) && ACTION_CHIPS.some((c) => c.key === t)));
      } else {
        /* 其他槽位：按 token 自身在 features 中出现的顺序追加 */
        for (const f of activeTypeDef.features) {
          if (typeFeats.includes(f.key) && !sortedFeats.includes(f.key)) sortedFeats.push(f.key);
        }
      }
    }
    return [...sortedFeats, ...others].join(" ").trim();
  }

  function applyToken(q: string, value: string): string {
    const parts = q.split(/\s+/).filter(Boolean);
    const i = parts.indexOf(value);
    if (i >= 0) parts.splice(i, 1);
    else parts.push(value);
    return buildPhrase(parts.join(" "));
  }

  function toggleChip(value: string, group: "type" | "feature" | "color" | "action") {
    /* 选中目标类型本身不写入文本框（仅切换面板），其他特征 token 才进入 */
    const wasOn = chips.has(value);
    if (group !== "type") setQuery((q) => applyToken(q, value));
    if (group === "type") {
      const typeDef = TYPE_CHIPS.find((t) => t.label === value);
      /* 取消选中时把专属特征面板一起收回（之前漏写，导致面板残留） */
      if (typeDef) setActiveTypeKey(wasOn ? null : typeDef.key);
    }
    setChips((prev) => {
      const next = new Set(prev);
      if (wasOn) next.delete(value);
      else next.add(value);
      return next;
    });
  }
  const [folderIds, setFolderIds] = useState<Set<string> | null>(null); // null = 使用 selectedTree 默认
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const [scopeSearch, setScopeSearch] = useState(""); // 检索范围搜索框
  /* 图像检索：两张图分别保存（人脸 + 通用图搜），相似度阈值共享 */
  const [faceFile, setFaceFile] = useState<File | null>(null);
  const [facePreviewUrl, setFacePreviewUrl] = useState<string | null>(null);
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [imagePreviewUrl, setImagePreviewUrl] = useState<string | null>(null);
  const [similarity, setSimilarity] = useState(0.5);
  const [dragOverFace, setDragOverFace] = useState(false);
  const [dragOverImage, setDragOverImage] = useState(false);
  /* 图像检索时由用户主动选择：人脸 / 通用图搜 */
  const [imageSource, setImageSource] = useState<"face" | "image">("face");
  /* 从素材库选图弹窗 */
  const [assetPicker, setAssetPicker] = useState<{ kind: "face" | "image" } | null>(null);
  const [addSubjectDrawer, setAddSubjectDrawer] = useState<AddSubjectDrawerData | null>(null);

  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<SearchResultItem[]>([]);
  const [total, setTotal] = useState(0);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [libCount, setLibCount] = useState(0);
  const [hasSearched, setHasSearched] = useState(false);

  const [sortKey, setSortKey] = useState<SortKey>("confidence");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [batchBusy, setBatchBusy] = useState(false);
  /* 搜索结果按视频分组（默认全展开，v0.37+）—— 与作用域列表的 expandedGroups 区分 */
  const [resultGroupsOpen, setResultGroupsOpen] = useState<Set<string>>(new Set());

  const fileRef = useRef<HTMLInputElement>(null);
  const imageRef = useRef<HTMLInputElement>(null);
  const videoMap = useMemo(() => new Map(videos.map((v) => [v.id, v])), [videos]);
  const groupNameMap = useMemo(() => {
    const m = new Map<string, string>();
    for (const g of caseGroups) m.set(g.groupId, g.name ?? g.number ?? "未命名文件夹");
    return m;
  }, [caseGroups]);

  /* ── 检索范围：案例多选 → 视频 id 集合
     v0.37：scopeSearch 命中时按相同规则过滤——案例名匹配的视频全收，仅视频名匹配的只收匹配项 */
  function buildScopeIds(): string[] | undefined {
    const activeIds = folderIds ?? (() => {
      // 默认：与案例库 selectedTree 同步
      if (selectedTree.startsWith("g:")) return new Set([selectedTree.slice(2)]);
      return new Set<string>();
    })();
    if (activeIds.size === 0) return undefined;
    const q = scopeSearch.trim().toLowerCase();
    return videos.filter((v) => {
      if (!v.group_id || !activeIds.has(v.group_id)) return false;
      if (q) {
        const g = caseGroups.find((cg) => cg.groupId === v.group_id);
        const caseMatches = !!g && ((g.name ?? "").toLowerCase().includes(q) || (g.number ?? "").toLowerCase().includes(q));
        if (!caseMatches && !(v.file_name?.toLowerCase().includes(q))) return false;
      }
      return true;
    }).map((v) => v.id);
  }

  async function runSearch() {
    if (tab === "text" && !query.trim()) {
      setError("请输入检索描述，或点击下方快捷标签生成语法");
      return;
    }
    if (tab === "image") {
      const src = imageSource === "face" ? faceFile : imageFile;
      if (!src) {
        setError(imageSource === "face" ? "请先选择一张人脸参考图" : "请先选择一张参考图");
        return;
      }
    }
    const ids = buildScopeIds();
    if (ids && ids.length === 0) {
      setResults([]);
      setTotal(0);
      setLibCount(0);
      setElapsedMs(0);
      setHasSearched(true);
      setSearching(false);
      setError("当前筛选条件下没有可检索的视频，请调整检索范围");
      return;
    }
    const t0 = performance.now();
    setSearching(true);
    setError(null);
    try {
      if (tab === "text") {
        // 与 Workbench VideoSearchCard.handleSearch 完全一致：不传 top_k / min_similarity，
        // 后端默认 0.3 门槛 + top_k 20 + 7 路并行召回。原先写死 top_k=60 / min_similarity=0
        // 导致跨视频场景下 frame 路径低分噪声冲榜（v0.37）。
        const res = await api.searchSemantic(query.trim(), { video_ids: ids });
        const list = res.results ?? [];
        setResults(list);
        setTotal(res.total ?? list.length);
        setElapsedMs(Math.round(res.query_time_ms ?? performance.now() - t0));
        const gs = new Set<string>();
        for (const r of list) gs.add(videoMap.get(r.video_id)?.group_id ?? "__ungrouped__");
        setLibCount(gs.size);
        setHasSearched(true);
      } else if (imageSource === "face") {
        const list = await api.searchFace(faceFile!, ids);
        setResults([]);
        setTotal(list.length);
        setElapsedMs(Math.round(performance.now() - t0));
        setLibCount(new Set(list.map((x: { video_id: string }) => x.video_id)).size);
        setHasSearched(true);
        /* 简化：把 face result 也灌到 results 用于渲染 */
        setResults(list.map((x) => ({
          video_id: x.video_id,
          precision_level: "face" as const,
          precise_start: x.first_seen,
          precise_end: x.last_seen,
          thumbnail_url: x.thumbnail_url ?? undefined,
          similarity: x.similarity,
          class_name: x.identity_label ?? `身份 #${x.identity_id}`,
        })) as unknown as SearchResultItem[]);
      } else {
        const res = await api.searchImage(imageFile!, { video_ids: ids, top_k: 60, min_similarity: similarity });
        const list = res.results ?? [];
        setResults(list);
        setTotal(res.total ?? list.length);
        setElapsedMs(Math.round(res.query_time_ms ?? performance.now() - t0));
        const gs = new Set<string>();
        for (const r of list) gs.add(videoMap.get(r.video_id)?.group_id ?? "__ungrouped__");
        setLibCount(gs.size);
        setHasSearched(true);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "检索失败，请稍后重试");
      setResults([]);
      setTotal(0);
      setHasSearched(true);
    } finally {
      setSearching(false);
    }
  }

  function setFace(f: File | null) {
    setFacePreviewUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return f ? URL.createObjectURL(f) : null;
    });
    setFaceFile(f);
  }
  function setImage(f: File | null) {
    setImagePreviewUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return f ? URL.createObjectURL(f) : null;
    });
    setImageFile(f);
  }

  function onDrop(e: React.DragEvent, target: "face" | "image") {
    e.preventDefault();
    if (target === "face") setDragOverFace(false);
    else setDragOverImage(false);
    const f = e.dataTransfer.files?.[0];
    if (f && f.type.startsWith("image/")) {
      if (target === "face") setFace(f);
      else setImage(f);
    } else if (f) setError("仅支持图片文件");
  }

  function targetTag(item: SearchResultItem): string {
    if (item.precision_level === "track" && item.class_name) return zh(item.class_name);
    if (item.precision_level === "plate" && item.plate_text) return "车牌";
    return PRECISION_LABEL[item.precision_level] ?? "目标";
  }

  function simValue(item: SearchResultItem): number {
    const s = item.confidence ?? item.similarity;
    return s == null ? -1 : Math.round(s * 100);
  }

  /* ── 排序：按置信度 / 时间 / 文件名 ── */
  const sortedResults = useMemo(() => {
    const arr = [...results];
    if (sortKey === "confidence") {
      arr.sort((a, b) => simValue(b) - simValue(a));
    } else if (sortKey === "name") {
      arr.sort((a, b) => {
        const na = videoMap.get(a.video_id)?.file_name ?? "";
        const nb = videoMap.get(b.video_id)?.file_name ?? "";
        return na.localeCompare(nb, "zh-Hans-CN");
      });
    } else {
      arr.sort((a, b) => {
        const ta = videoMap.get(a.video_id)?.created_at ?? "";
        const tb = videoMap.get(b.video_id)?.created_at ?? "";
        return tb.localeCompare(ta);
      });
    }
    return arr;
  }, [results, sortKey, videoMap]);

  /* ── 按 video_id 分组（保留 sortedResults 顺序：组顺序 = 首个命中在排序列表里的位置） ── */
  const groupedResults = useMemo(() => {
    const map = new Map<string, SearchResultItem[]>();
    for (const r of sortedResults) {
      const arr = map.get(r.video_id);
      if (arr) arr.push(r);
      else map.set(r.video_id, [r]);
    }
    return Array.from(map, ([videoId, items]) => ({ videoId, items }));
  }, [sortedResults]);

  /* 默认全展开：仅在新搜索完成时重置，不能跟 groupedResults —— 否则 videos 4s 轮询刷新
     （videos → videoMap → sortedResults → groupedResults 整链重算）会每 4s 自动展开一次 */
  useEffect(() => {
    setResultGroupsOpen(new Set(groupedResults.filter((g) => g.items.length >= 2).map((g) => g.videoId)));
  }, [results]);

  /* 可折叠组（≥2 个结果）+ 工具条状态：单结果组不参与折叠，工具条统计只看可折叠组 */
  const collapsibleGroups = useMemo(() => groupedResults.filter((g) => g.items.length >= 2), [groupedResults]);
  const openCollapsibleCount = useMemo(
    () => collapsibleGroups.filter((g) => resultGroupsOpen.has(g.videoId)).length,
    [collapsibleGroups, resultGroupsOpen],
  );
  const allCollapsibleOpen = collapsibleGroups.length > 0 && openCollapsibleCount === collapsibleGroups.length;

  function toggleGroup(videoId: string) {
    setResultGroupsOpen((prev) => {
      const next = new Set(prev);
      if (next.has(videoId)) next.delete(videoId);
      else next.add(videoId);
      return next;
    });
  }
  function setAllGroups(open: boolean) {
    /* 只对可折叠组生效；单结果组不参与（永远展开） */
    setResultGroupsOpen((prev) => {
      const next = new Set(prev);
      for (const g of collapsibleGroups) {
        if (open) next.add(g.videoId);
        else next.delete(g.videoId);
      }
      return next;
    });
  }

  function tagTone(tag: string): string {
    return TAG_TONES[tag] ?? "blue";
  }

  function extractColor(caption?: string | null): string | null {
    if (!caption) return null;
    for (const [kw, name] of COLOR_WORDS) if (caption.includes(kw)) return name;
    return null;
  }

  /* 每行标签胶囊：[命中素材库?] [目标类型] [颜色特征/车牌] [置信度] */
  function buildPills(item: SearchResultItem): { text: string; tone: string }[] {
    const pills: { text: string; tone: string }[] = [];
    /* v0.6：素材库命中 — 醒目标签 [命中: 目标名] */
    if (item.matched_subject) {
      pills.push({ text: `命中: ${item.matched_subject.subject_name}`, tone: "red" });
    }
    const tag = targetTag(item);
    pills.push({ text: tag, tone: tagTone(tag) });
    if (item.precision_level === "plate" && item.plate_text) {
      pills.push({ text: item.plate_text, tone: "purple" });
    } else {
      const color = extractColor(item.caption);
      if (color) pills.push({ text: color, tone: "rose" });
    }
    const sim = simValue(item);
    if (sim >= 0) {
      pills.push({ text: `${sim}%`, tone: sim >= 80 ? "green" : sim >= 60 ? "amber" : "gray" });
    }
    return pills;
  }

  /* 未命名文件显示「摄像头_时间」 */
  function displayName(v?: VideoListItem): string {
    if (v?.file_name) return v.file_name;
    if (v?.created_at) return `摄像头_${fmtFullDate(v.created_at)}`;
    return "未知视频";
  }

  function downloadOriginal(videoId: string, fileName?: string) {
    const a = document.createElement("a");
    a.href = api.getVideoStreamUrl(videoId);
    a.download = fileName || `${videoId}.mp4`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  /* ── v0.6 沉淀：搜索结果 → 图片素材库（取缩略图为底图，kind 由目标类型推断） ── */
  async function addResultToLibrary(r: SearchResultItem) {
    let blob: Blob | null = null;
    if (r.thumbnail_url) {
      try {
        const res = await fetch(r.thumbnail_url);
        if (res.ok) blob = await res.blob();
      } catch { /* 忽略 */ }
    }
    /* 种类两态（v0.6）：person=人；其余（车/车牌/其他物）统一归 other */
    const kind = r.class_name === "person" ? "person" : "other";
    setAddSubjectDrawer({
      kind,
      presetName: r.plate_text ?? (r.class_name ? zh(r.class_name) : undefined),
      image: blob ? { blob } : null,
      source: "search",
      sourceVideoId: r.video_id,
    });
  }

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function batchAnalyze() {
    if (selected.size === 0 || batchBusy) return;
    setBatchBusy(true);
    try {
      await api.analyzeBatch([...selected]);
      setSelected(new Set());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "批量解析失败");
    } finally {
      setBatchBusy(false);
    }
  }

  const goDisabled = searching || (tab === "text" ? !query.trim() : !(imageSource === "face" ? faceFile : imageFile));

  return (
    <div className="gs-page">
      {/* ── 左侧：检索配置面板 ── */}
      <aside className="gs-left">
        <div className="gs-card gs-tabs">
          <button type="button" className={tab === "text" ? "on" : ""} onClick={() => setTab("text")}>
            <IconSearch5 />
            文本检索
          </button>
          <button type="button" className={tab === "image" ? "on" : ""} onClick={() => setTab("image")}>
            <IconImageSearch />
            图像检索
          </button>
        </div>

        <SplitPane direction="col" initial={55} min={20} max={80} className="gs-split-wrap">
          {/* ── 上半：特征卡片（文本/图像 Tab + Chips） ── */}
          <div className="gs-middle">
            {tab === "text" ? (
              <div className="gs-card gs-text-form">
              <textarea
                className="gs-query"
                rows={2}
                placeholder="输入自然语言描述，如：穿黄衣服骑电动车的人"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    runSearch();
                  }
                }}
              />
              {query.trim() && (
                <button
                  type="button"
                  className="gs-clear"
                  onClick={() => {
                    setQuery("");
                    setChips(new Set());
                    setActiveTypeKey(null);
                  }}
                  title="清空文本与特征选择"
                >
                  <IconClose />
                </button>
              )}
              <div className="gs-chips">
                {/* 目标类型 */}
                <div className="gs-chip-group">
                  <span className="gs-chip-tt">目标类型</span>
                  <div className="gs-chip-row">
                    {TYPE_CHIPS.map((t) => (
                      <button
                        key={t.key}
                        type="button"
                        className={"gs-chip" + (chips.has(t.label) ? " on" : "")}
                        onClick={() => toggleChip(t.label, "type")}
                      >
                        {t.label}
                      </button>
                    ))}
                  </div>
                </div>
                {/* 当前类型专属特征：仅在选中某类型后显示 */}
                {activeTypeDef && activeTypeDef.features.length > 0 && (
                  <div className="gs-chip-group">
                    <span className="gs-chip-tt">{activeTypeDef.label}专属特征</span>
                    <div className="gs-chip-row">
                      {activeTypeDef.features.map((f) => (
                        <button
                          key={f.key}
                          type="button"
                          className={"gs-chip" + (chips.has(f.label) ? " on" : "")}
                          onClick={() => toggleChip(f.label, "feature")}
                        >
                          {f.label}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {/* 颜色：常驻通用特征 */}
                <div className="gs-chip-group">
                  <span className="gs-chip-tt">颜色</span>
                  <div className="gs-chip-row">
                    {COLOR_CHIPS.map((c) => (
                      <button
                        key={c.key}
                        type="button"
                        className={"gs-chip" + (chips.has(c.label) ? " on" : "")}
                        onClick={() => toggleChip(c.label, "color")}
                      >
                        {c.color && <i className="gs-dot" style={{ background: c.color }} />}
                        {c.label}
                      </button>
                    ))}
                  </div>
                </div>
                {/* 事件：常驻通用特征 */}
                <div className="gs-chip-group">
                  <span className="gs-chip-tt">事件</span>
                  <div className="gs-chip-row">
                    {ACTION_CHIPS.map((a) => (
                      <button
                        key={a.key}
                        type="button"
                        className={"gs-chip" + (chips.has(a.label) ? " on" : "")}
                        onClick={() => toggleChip(a.label, "action")}
                      >
                        {a.label}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="gs-card gs-image-form">
              {/* 人脸搜索（ArcFace 512d） */}
              <div
                className={"gs-drop gs-drop-face" + (dragOverFace ? " over" : "")}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragOverFace(true);
                }}
                onDragLeave={() => setDragOverFace(false)}
                onDrop={(e) => onDrop(e, "face")}
                onClick={() => fileRef.current?.click()}
              >
                <input
                  ref={fileRef}
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  hidden
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) { setFace(f); setImageSource("face"); }
                    e.target.value = "";
                  }}
                />
                {faceFile ? (
                  <>
                    <img className="gs-drop-preview" src={facePreviewUrl ?? undefined} alt="face preview" />
                    <p className="gs-drop-name">{faceFile.name}</p>
                    <button
                      type="button"
                      className="gs-drop-remove"
                      onClick={(e) => {
                        e.stopPropagation();
                        setFace(null);
                      }}
                    >
                      移除
                    </button>
                  </>
                ) : (
                  <>
                    <div className="gs-drop-icon gs-drop-icon-face">👤</div>
                    <p className="gs-drop-tt">人脸搜索</p>
                    <span className="gs-drop-sub">拖拽或点击上传人脸照片（ArcFace 512d 检索）</span>
                  </>
                )}
                <button
                  type="button"
                  className="gs-asset-pick"
                  onClick={(e) => { e.stopPropagation(); setAssetPicker({ kind: "face" }); }}
                >
                  从素材库选图
                </button>
              </div>

              {/* 通用图搜（Qwen3-VL-Embedding） */}
              <div
                className={"gs-drop gs-drop-img" + (dragOverImage ? " over" : "")}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragOverImage(true);
                }}
                onDragLeave={() => setDragOverImage(false)}
                onDrop={(e) => onDrop(e, "image")}
                onClick={() => imageRef.current?.click()}
              >
                <input
                  ref={imageRef}
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  hidden
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) { setImage(f); setImageSource("image"); }
                    e.target.value = "";
                  }}
                />
                {imageFile ? (
                  <>
                    <img className="gs-drop-preview" src={imagePreviewUrl ?? undefined} alt="image preview" />
                    <p className="gs-drop-name">{imageFile.name}</p>
                    <button
                      type="button"
                      className="gs-drop-remove"
                      onClick={(e) => {
                        e.stopPropagation();
                        setImage(null);
                      }}
                    >
                      移除
                    </button>
                  </>
                ) : (
                  <>
                    <div className="gs-drop-icon">
                      <IconImageSearch />
                    </div>
                    <p className="gs-drop-tt">通用图搜</p>
                    <span className="gs-drop-sub">拖拽或点击上传参考图（Qwen3-VL 整图检索）</span>
                  </>
                )}
                <button
                  type="button"
                  className="gs-asset-pick"
                  onClick={(e) => { e.stopPropagation(); setAssetPicker({ kind: "image" }); }}
                >
                  从素材库选图
                </button>
              </div>
            </div>
          )}
          </div>

          {/* ── 下半：检索范围卡片（可拖拽调整上下比例） ── */}
          <div className="gs-card gs-scope">
            <div className="gs-scope-head">
              <IconFolder />
              <span>检索范围</span>
              <span className="gs-scope-count">
                {!folderIds
                  ? (selectedTree.startsWith("g:")
                      ? (caseGroups.find((g) => g.groupId === selectedTree.slice(2))?.name ?? "跟随案例库")
                      : scopeSearch.trim()
                        ? (() => {
                            const q = scopeSearch.trim().toLowerCase();
                            const matched = caseGroups.filter((g) =>
                              (g.name ?? "").toLowerCase().includes(q) ||
                              (g.number ?? "").toLowerCase().includes(q) ||
                              videos.some((v) => v.group_id === g.groupId && v.file_name?.toLowerCase().includes(q))
                            ).length;
                            return `${matched} 个匹配`;
                          })()
                        : "全部案例")
                  : folderIds.size === 0 ? "全部案例" : `已选 ${folderIds.size} 个`}
              </span>
            </div>
            {/* 检索范围搜索框 */}
            <input
              className="gs-scope-search"
              type="text"
              placeholder="搜索案例名或视频名…"
              value={scopeSearch}
              onChange={(e) => setScopeSearch(e.target.value)}
            />
            <div className="gs-scope-list">
              {!scopeSearch.trim() && (
                <label className={"gs-scope-item" + (folderIds !== null && folderIds.size === 0 ? " on" : "")}>
                  <input type="checkbox" checked={folderIds !== null && folderIds.size === 0} onChange={() => setFolderIds(new Set())} />
                  <span>全部案例</span>
                  <em>{caseGroups.length}</em>
                </label>
              )}
              {caseGroups
                .filter((g) => {
                  if (!scopeSearch.trim()) return true;
                  const q = scopeSearch.trim().toLowerCase();
                  // 案例名/编号匹配：返回整个案例（保留原逻辑）
                  if ((g.name ?? "").toLowerCase().includes(q) || (g.number ?? "").toLowerCase().includes(q)) return true;
                  // 仅视频名匹配：仍返回该案例，但下方只渲染匹配的视频（不让非匹配视频出现在可选列表里）
                  return videos.some((v) => v.group_id === g.groupId && v.file_name?.toLowerCase().includes(q));
                })
                .map((g) => {
                const active = folderIds !== null
                  ? folderIds.has(g.groupId)
                  : selectedTree === `g:${g.groupId}`;
                const expanded = expandedGroups.has(g.groupId);
                const caseVideos = videos.filter((v) => v.group_id === g.groupId);
                /* scopeSearch 命中规则：
                   - 案例名/编号匹配 → 显示该案例下所有视频（用户搜的就是整个案例）
                   - 只有视频名匹配 → 只显示匹配的视频（不让用户误以为整个案例都入选）
                   - 无搜索 → 显示所有视频 */
                const q = scopeSearch.trim().toLowerCase();
                const caseNameMatches = !!q && ((g.name ?? "").toLowerCase().includes(q) || (g.number ?? "").toLowerCase().includes(q));
                const visibleVideos = q && !caseNameMatches
                  ? caseVideos.filter((v) => v.file_name?.toLowerCase().includes(q))
                  : caseVideos;
                return (
                  <div key={g.groupId} className="gs-scope-group">
                    <label className={"gs-scope-item" + (active ? " on" : "")}>
                      <input
                        type="checkbox"
                        checked={active}
                        onChange={() => {
                          setFolderIds((prev) => {
                            const base = prev ?? (() => {
                              if (selectedTree.startsWith("g:")) return new Set([selectedTree.slice(2)]);
                              return new Set<string>();
                            })();
                            const next = new Set(base);
                            if (next.has(g.groupId)) next.delete(g.groupId);
                            else next.add(g.groupId);
                            return next;
                          });
                        }}
                      />
                      <span
                        className="gs-scope-name"
                        onClick={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                          setExpandedGroups((prev) => {
                            const next = new Set(prev);
                            if (next.has(g.groupId)) next.delete(g.groupId);
                            else next.add(g.groupId);
                            return next;
                          });
                        }}
                      >
                        <span className="gs-scope-arrow" style={{ transform: expanded ? "rotate(90deg)" : "rotate(0deg)" }}>▶</span>
                        {g.name ?? g.number ?? "未命名案例"}
                      </span>
                      <em>{q && !caseNameMatches ? `${visibleVideos.length}/${caseVideos.length}` : (g.file_count ?? caseVideos.length)}</em>
                    </label>
                    {expanded && (
                      <div className="gs-scope-videos">
                        {visibleVideos.length === 0 && <span className="gs-scope-empty">无匹配视频</span>}
                        {visibleVideos.map((v) => (
                          <label key={v.id} className="gs-scope-video-item">
                            <input
                              type="checkbox"
                              checked={active}
                              readOnly
                            />
                            <span className="gs-scope-video-name" title={v.file_name}>{v.file_name}</span>
                          </label>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </SplitPane>

        {error && (
          <div className="gs-error">
            <IconRetry className="w-4 h-4" />
            <span>{error}</span>
          </div>
        )}

        <button type="button" className="gs-go" onClick={runSearch} disabled={goDisabled}>
          {searching ? <i className="gs-spin" /> : <IconSearch5 />}
          {searching ? "搜索中…" : "开始搜索"}
        </button>
      </aside>

      {/* ── 右侧：检索结果展示区 ── */}
      <section className="gs-right">
        <div className="gs-toolbar">
          <div className="gs-stat">
            <span className="gs-stat-main">
              {hasSearched ? (
                <>
                  共检索到 <b>{total}</b> 个相关视频片段
                </>
              ) : (
                "尚未检索"
              )}
            </span>
            {hasSearched && (
              <span className="gs-stat-sub">
                耗时 {elapsedMs} ms · 跨越 {libCount} 个文件夹
              </span>
            )}
            {searching && <span className="gs-searching-tip">检索中，请稍候…</span>}
          </div>
          <label className="gs-sort">
            <IconSort />
            <select value={sortKey} onChange={(e) => setSortKey(e.target.value as SortKey)}>
              <option value="confidence">按置信度</option>
              <option value="time">按时间</option>
              <option value="name">按文件名</option>
            </select>
          </label>
        </div>

        {!hasSearched ? (
          <div className="gs-empty">
            <div className="gs-empty-icon">
              <IconSearch5 />
            </div>
            <p>选择检索方式并点击「开始搜索」</p>
            <span className="gs-empty-sub">支持自然语言描述与以图搜图，跨所有文件夹匹配目标</span>
          </div>
        ) : results.length === 0 ? (
          <div className="gs-empty">
            <div className="gs-empty-icon muted">
              <IconClose />
            </div>
            <p>未找到匹配结果</p>
            <span className="gs-empty-sub">试试调整描述、缩短时间段或扩大检索范围</span>
          </div>
        ) : (
          <div className="gs-list">
            {/* 分组工具条：仅当 ≥1 个可折叠组（≥2 结果）时显示，单结果组不参与 */}
            {collapsibleGroups.length >= 1 && (
              <div className="gs-group-toolbar">
                <button
                  type="button"
                  className="gs-group-tool"
                  onClick={() => setAllGroups(!allCollapsibleOpen)}
                >
                  {allCollapsibleOpen ? "全部收起" : "全部展开"}
                </button>
                <span className="gs-group-tool-stat">
                  共 {groupedResults.length} 个视频 · {sortedResults.length} 个结果
                </span>
              </div>
            )}
            {groupedResults.map(({ videoId, items }) => {
              const v = videoMap.get(videoId);
              const isExpanded = resultGroupsOpen.has(videoId);
              const groupName = v?.group_id ? groupNameMap.get(v.group_id) ?? "未命名文件夹" : "未分组";
              const fileName = displayName(v);
              const topSim = Math.round(((items[0]?.confidence ?? items[0]?.similarity) ?? 0) * 100);

              /* 渲染单条结果行（单结果无外框：行顶自带「来源视频 · 置信度」；组内不重复） */
              const renderRow = (r: SearchResultItem, i: number, showSrc: boolean) => {
                const processing = v != null && (v.status === "processing" || v.status === "pending");
                const pct = v?.progress != null ? Math.round(v.progress * 100) : null;
                const timeSec = r.precise_start ?? r.scene_range_start;
                const isSel = selected.has(r.video_id);
                const isTrack = r.precision_level === "track";
                const openResult = () => {
                  const seekTo = timeSec != null ? { start: timeSec, end: r.precise_end ?? null } : undefined;
                  const syncFiles = tab === "image" ? { faceFile: imageSource === "face" ? faceFile ?? undefined : undefined, imageFile: imageSource === "image" ? imageFile ?? undefined : undefined } : {};
                  if (isTrack && r.track_id != null && timeSec != null) {
                    openWorkbench(r.video_id, {
                      versionId: r.video_id,
                      seekTo,
                      selectTrack: { trackId: r.track_id, className: r.class_name ?? "", start: timeSec },
                      searchQuery: tab === "text" ? query.trim() : undefined,
                      ...syncFiles,
                    });
                  } else {
                    openWorkbench(r.video_id, { versionId: r.video_id, ...(seekTo ? { seekTo } : {}), searchQuery: tab === "text" ? query.trim() : undefined, ...syncFiles });
                  }
                };
                return (
                  <div key={`${r.video_id}-${i}`} className={"gs-row" + (isSel ? " sel" : "")}>
                    <div className="gs-row-media" onClick={openResult} title="点击打开对应视频">
                      {r.thumbnail_url ? (
                        <img src={r.thumbnail_url} alt="" loading="lazy" />
                      ) : (
                        <div className="gs-thumb-fallback">
                          <IconVideo />
                        </div>
                      )}
                      <span className="gs-row-badge">{timeSec != null ? formatSec(timeSec) : <IconImage />}</span>
                      {/* v0.6 沉淀：常驻「+ 加入素材库」 */}
                      <button
                        className="gs-row-add"
                        title="加入图片素材库"
                        onClick={(e) => { e.stopPropagation(); void addResultToLibrary(r); }}
                      >
                        <IconPlus />
                      </button>
                      {processing && (
                        <div className="gs-row-mask">
                          <i className="gs-spin" />
                          <span>{pct != null ? `解析中 ${pct}%` : "解析中…"}</span>
                        </div>
                      )}
                    </div>
                    <div className="gs-row-info" onClick={openResult}>
                      {showSrc && (
                        <div className="gs-row-src">
                          <IconVideo />
                          <span className="gs-row-src-name" title={fileName}>{fileName}</span>
                          {topSim > 0 && <span className="gs-row-src-conf">{topSim}%</span>}
                        </div>
                      )}
                      <div className="gs-row-title" title={r.class_name ? `${fileName} · ${r.class_name}` : fileName}>
                        {isTrack && r.class_name ? (
                          <span className="gs-row-target">{zh(r.class_name)}{r.display_seq != null && r.display_seq > 1 ? ` #${r.display_seq}` : ""}</span>
                        ) : (
                          <span className="gs-row-target muted">{targetTag(r)}</span>
                        )}
                        <span className="gs-row-time">{timeSec != null ? formatSec(timeSec) : ""}{r.precise_end != null && r.precise_end !== timeSec ? ` – ${formatSec(r.precise_end)}` : ""}</span>
                      </div>
                      <div className="gs-row-tags">
                        {buildPills(r).map((p, j) => (
                          <span key={j} className={"gs-pill " + p.tone}>
                            {p.text}
                          </span>
                        ))}
                      </div>
                      <div className="gs-row-meta">
                        <span className="gs-meta-time">
                          <IconClock />
                          {v?.created_at ? fmtFullDate(v.created_at) : "--"}
                        </span>
                      </div>
                    </div>
                  </div>
                );
              };

              /* 单结果：不套 .gs-group 外框，行内自带头部（视频名+置信度） */
              if (items.length === 1) {
                return (
                  <div key={videoId} className="gs-solo">
                    {renderRow(items[0], 0, true)}
                  </div>
                );
              }

              /* 多结果：组 body 高度 = min(items.length, 3) * 行高，超出部分组内独立滚动 */
              const visibleRows = Math.min(items.length, 3);
              return (
                <div key={videoId} className="gs-group">
                  <div className={"gs-group-hd" + (isExpanded ? " open" : "")} onClick={() => toggleGroup(videoId)}>
                    <span className="gs-group-arrow">▶</span>
                    <span className="gs-group-name" title={fileName}>{fileName}</span>
                    <span className="gs-group-count">{items.length} 个结果</span>
                    {topSim > 0 && <span className="gs-group-top">{topSim}%</span>}
                    <span className="gs-group-path" title={`${groupName} / ${fileName}`}>{groupName}</span>
                  </div>
                  {isExpanded && (
                    <div
                      className="gs-group-bd"
                      style={{
                        maxHeight: `calc(150px * ${visibleRows} + 8px * ${visibleRows - 1} + 20px)`,
                      }}
                    >
                      {items.map((r, i) => renderRow(r, i, false))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* 从素材库选图弹窗 */}
      {assetPicker && (
        <SubjectPhotoPicker
          onClose={() => setAssetPicker(null)}
          onSelect={(file) => {
            setAssetPicker(null);
            if (assetPicker.kind === "face") { setFace(file); setImageSource("face"); }
            else { setImage(file); setImageSource("image"); }
          }}
        />
      )}

      {/* v0.6 沉淀：搜索结果 → 加入图片素材库 Drawer */}
      <AddSubjectDrawer data={addSubjectDrawer} onClose={() => setAddSubjectDrawer(null)} />
    </div>
  );
}
