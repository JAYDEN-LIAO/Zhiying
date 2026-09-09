import { useEffect, useMemo, useState } from "react";
import { api } from "../../services/api";
import { fmtDuration } from "../../utils/helpers";
import { IconClose, IconFolder, IconVideo } from "../icons";
import type { FileItem, VideoGroup } from "../../types";

/* ════════════════════════════════════════════════════════════
   FilePickerModal — 统一文件库选择器
   mode="single"  解析场景：单选、仅视频文件 → 返回 1 个 File ID
   mode="multi"   搜索场景：多选 + 文件夹树勾选 → 返回 File ID / Folder ID 数组
   ════════════════════════════════════════════════════════════ */

const VIDEO_EXTS = new Set([
  ".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv", ".webm", ".m4v", ".ts", ".mpg", ".mpeg", ".3gp",
]);

function isVideoFile(f: FileItem): boolean {
  const raw = (f.file_ext ?? f.name.slice(f.name.lastIndexOf("."))).toLowerCase();
  const ext = raw.startsWith(".") ? raw : `.${raw}`;
  return VIDEO_EXTS.has(ext);
}

export interface FilePickResult {
  groupIds: string[]; // 勾选的文件夹（multi）
  videoIds: string[]; // 勾选的独立文件（single 时至多 1 个）
}

export function FilePickerModal({
  mode,
  open,
  onClose,
  onConfirm,
}: {
  mode: "single" | "multi";
  open: boolean;
  onClose: () => void;
  onConfirm: (result: FilePickResult) => void;
}) {
  const [files, setFiles] = useState<FileItem[]>([]);
  const [groups, setGroups] = useState<VideoGroup[]>([]);
  const [loading, setLoading] = useState(false);
  const [checkedGroups, setCheckedGroups] = useState<Set<string>>(new Set());
  const [checkedFiles, setCheckedFiles] = useState<Set<string>>(new Set());
  const [selectedId, setSelectedId] = useState<string | null>(null); // single 模式

  /* 打开时加载文件库（树 = 分组 + 未分组文件） */
  useEffect(() => {
    if (!open) return;
    let alive = true;
    setLoading(true);
    Promise.all([api.listFiles().catch(() => [] as FileItem[]), api.listGroups().catch(() => [] as VideoGroup[])])
      .then(([fs, gs]) => {
        if (!alive) return;
        setFiles(fs.filter(isVideoFile));
        setGroups(gs);
      })
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [open]);

  /* 重置选择状态 */
  useEffect(() => {
    if (open) {
      setCheckedGroups(new Set());
      setCheckedFiles(new Set());
      setSelectedId(null);
    }
  }, [open]);

  /* 树结构：分组 → 组内视频；未分组单独一节 */
  const tree = useMemo(() => {
    const grouped = groups.map((g) => ({
      group: g,
      files: files.filter((f) => f.group_id === g.groupId),
    }));
    const knownGroupIds = new Set(groups.map((g) => g.groupId));
    const loose = files.filter((f) => !f.group_id || !knownGroupIds.has(f.group_id));
    return { grouped, loose };
  }, [files, groups]);

  const inCheckedGroup = (f: FileItem) => !!f.group_id && checkedGroups.has(f.group_id);
  const fileChecked = (f: FileItem) => inCheckedGroup(f) || checkedFiles.has(f.id);

  const toggleGroup = (gid: string) => {
    setCheckedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(gid)) next.delete(gid);
      else next.add(gid);
      return next;
    });
  };

  const toggleFile = (f: FileItem) => {
    if (inCheckedGroup(f)) {
      /* 已整组勾选 → 单击文件取消整组勾选 */
      toggleGroup(f.group_id!);
      return;
    }
    if (mode === "single") {
      setSelectedId((cur) => (cur === f.id ? null : f.id));
      return;
    }
    setCheckedFiles((prev) => {
      const next = new Set(prev);
      if (next.has(f.id)) next.delete(f.id);
      else next.add(f.id);
      return next;
    });
  };

  const confirm = () => {
    if (mode === "single") {
      if (!selectedId) return;
      onConfirm({ groupIds: [], videoIds: [selectedId] });
    } else {
      /* 独立文件排除已被整组勾选覆盖的部分 */
      const covered = new Set<string>();
      for (const g of tree.grouped) {
        if (checkedGroups.has(g.group.groupId)) g.files.forEach((f) => covered.add(f.id));
      }
      const videoIds = [...checkedFiles].filter((id) => !covered.has(id));
      onConfirm({ groupIds: [...checkedGroups], videoIds });
    }
    onClose();
  };

  if (!open) return null;

  const hasSelection = mode === "single" ? selectedId != null : checkedGroups.size + checkedFiles.size > 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-6" onClick={onClose}>
      <div
        className="flex max-h-[76vh] w-[560px] max-w-full flex-col overflow-hidden rounded-card bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 头部 */}
        <div className="flex items-center justify-between border-b border-border-light px-5 py-3.5">
          <div>
            <p className="text-sm font-semibold text-gray-800">
              {mode === "single" ? "从文件库选择视频" : "选择检索范围"}
            </p>
            <p className="mt-0.5 text-xs text-gray-400">
              {mode === "single" ? "单选一个视频文件用于解析" : "勾选文件夹或独立文件，留空 = 全部"}
            </p>
          </div>
          <button onClick={onClose} className="rounded-md p-1.5 text-gray-400 transition-colors hover:bg-surface hover:text-gray-600">
            <IconClose />
          </button>
        </div>

        {/* 文件树 */}
        <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2">
          {loading ? (
            <p className="py-10 text-center text-sm text-gray-400">加载文件库…</p>
          ) : files.length === 0 ? (
            <p className="py-10 text-center text-sm text-gray-400">文件库为空，请先通过「任务列表」导入视频</p>
          ) : (
            <>
              {tree.grouped.map(({ group, files: gFiles }) => (
                <div key={group.groupId} className="mb-1">
                  <label className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm text-gray-800 hover:bg-surface">
                    {mode === "multi" && (
                      <input
                        type="checkbox"
                        className="h-3.5 w-3.5 accent-[#4f7cff]"
                        checked={checkedGroups.has(group.groupId)}
                        onChange={() => toggleGroup(group.groupId)}
                      />
                    )}
                    <span className="text-primary"><IconFolder /></span>
                    <span className="flex-1 truncate font-medium">{group.name ?? group.groupId}</span>
                    <span className="text-xs text-gray-400">{gFiles.length} 个视频</span>
                  </label>
                  <div className="ml-7 flex flex-col">
                    {gFiles.map((f) => (
                      <FileRow
                        key={f.id}
                        file={f}
                        mode={mode}
                        checked={mode === "single" ? selectedId === f.id : fileChecked(f)}
                        onToggle={() => toggleFile(f)}
                      />
                    ))}
                  </div>
                </div>
              ))}
              {tree.loose.length > 0 && (
                <div className="mb-1">
                  <p className="px-2 py-1.5 text-xs font-semibold text-gray-400">未分组文件</p>
                  <div className="ml-2 flex flex-col">
                    {tree.loose.map((f) => (
                      <FileRow
                        key={f.id}
                        file={f}
                        mode={mode}
                        checked={mode === "single" ? selectedId === f.id : fileChecked(f)}
                        onToggle={() => toggleFile(f)}
                      />
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        {/* 底部操作 */}
        <div className="flex items-center justify-between border-t border-border-light px-5 py-3">
          <p className="text-xs text-gray-400">
            {mode === "single"
              ? selectedId
                ? "已选择 1 个视频"
                : "未选择"
              : `${checkedGroups.size} 个文件夹, ${checkedFiles.size} 个独立文件`}
          </p>
          <div className="flex gap-2">
            <button onClick={onClose} className="g-btn">
              取消
            </button>
            <button
              onClick={confirm}
              disabled={!hasSelection}
              className="g-btn g-btn-primary disabled:cursor-not-allowed disabled:opacity-50"
            >
              {mode === "single" ? "开始解析" : "确定"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function FileRow({
  file,
  mode,
  checked,
  onToggle,
}: {
  file: FileItem;
  mode: "single" | "multi";
  checked: boolean;
  onToggle: () => void;
}) {
  return (
    <label
      className={`flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-surface ${
        checked ? "bg-primary-soft/60" : ""
      }`}
    >
      <input
        type={mode === "single" ? "radio" : "checkbox"}
        className="h-3.5 w-3.5 accent-[#4f7cff]"
        checked={checked}
        onChange={onToggle}
      />
      <span className="text-gray-400"><IconVideo /></span>
      <span className="min-w-0 flex-1 truncate text-gray-700">{file.name}</span>
      <span className="shrink-0 text-[11px] text-gray-400">{fmtDuration(file.duration ?? 0)}</span>
    </label>
  );
}
