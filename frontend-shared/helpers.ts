/* ════════════════════════════════════════════════════════════
   Shared helpers — extracted from Dashboard.tsx
   ════════════════════════════════════════════════════════════ */

export function fmtDuration(sec: number | null): string {
  if (sec == null) return "--:--";
  // Round to nearest second — matches common video player behaviour
  // (e.g. 138.9s → 2:19, not 2:18 as Math.floor would give)
  const total = Math.round(sec);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

/* 后端 created_at 存 UTC（datetime.now(timezone.utc)），API 通常带 "Z" 偏移；
   个别路径（新记录默认值）可能不带偏移 → 无偏移时按 UTC 解析（补 Z）。 */
export function parseUtcIso(iso: string): Date {
  const hasTz = /(Z|[+-]\d{2}:?\d{2})$/i.test(iso);
  if (hasTz) return new Date(iso);
  // 无偏移 → 补 Z 当 UTC 解析（兼容 "T" 与空格分隔两种格式）
  const normalized = iso.includes("T") ? iso : iso.replace(" ", "T");
  return new Date(normalized + "Z");
}

/* 应用时区（Asia/Shanghai，中国部署服务器 +0800）：时间显示固定于此，不随浏览器时区漂移。
   浏览器为 UTC（或其它时区）时，`new Date("...Z").getHours()` 会显示成 UTC 时间，差 8 小时。 */
const APP_TIMEZONE = "Asia/Shanghai";

function formatInTz(d: Date, opts: Intl.DateTimeFormatOptions): string {
  return new Intl.DateTimeFormat("zh-CN", { ...opts, timeZone: APP_TIMEZONE }).format(d);
}

/** 短格式：M/D HH:mm（历史记录上传时间） */
export function fmtDate(iso: string): string {
  return formatInTz(parseUtcIso(iso), { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });
}

/** 全格式：YYYY/MM/DD HH:mm（视频信息卡 / 参数预设创建时间） */
export function fmtFullDate(iso: string): string {
  return formatInTz(parseUtcIso(iso), { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
}

export function formatSec(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}
