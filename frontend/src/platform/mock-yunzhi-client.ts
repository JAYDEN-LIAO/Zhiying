import type {
  FileSelectionOptions,
  YunzhiClient,
  YunzhiHostContext,
  YunzhiResource,
} from "./yunzhi-bridge"

/** 独立开发（Mock）模式下的平台文件库模拟数据。 */
const mockFiles: YunzhiResource[] = [
  {
    resourceType: "FILE",
    id: 10001,
    name: "demo.mp4",
    scope: "PRIVATE",
    path: "/Mock/demo.mp4",
    absolutePath: "/data/yunzhi-files/private/mock/demo.mp4",
    category: "video",
    contentType: "video/mp4",
    size: 12_800_000,
  },
  {
    resourceType: "FILE",
    id: 10002,
    name: "监控_20260805.mp4",
    scope: "PRIVATE",
    path: "/Mock/监控_20260805.mp4",
    absolutePath: "/data/yunzhi-files/private/mock/监控_20260805.mp4",
    category: "video",
    contentType: "video/mp4",
    size: 85_000_000,
  },
]

export class MockYunzhiClient implements YunzhiClient {
  private readonly mockContext: YunzhiHostContext = {
    appKey: "zhiying-extension",
    locale: "zh-CN",
    theme: "light",
    entryPoint: "file.folder.action",
    resource: {
      resourceType: "FOLDER",
      id: 20001,
      name: "视频分析",
      category: "video",
      scope: "PRIVATE",
    },
    capabilities: [
      "context.get",
      "navigation.open",
      "ui.notify",
      "tasks.open",
      "files.select",
      "folders.select",
      "folders.selectSaveTarget",
      "files.preview",
      "files.saveToLibrary",
    ],
  }

  connect = async () => this.mockContext
  context = { get: async () => this.mockContext }
  files = {
    select: async (_options: FileSelectionOptions = {}) => ({ items: [...mockFiles] }),
    selectFolders: async (_options: FileSelectionOptions = {}) => ({
      items: mockFiles.filter((item) => item.resourceType === "FOLDER"),
    }),
    selectSaveTarget: async () => ({
      target: {
        folderId: 20001,
        scope: "PRIVATE",
        name: "Zhiying 分析输出",
        path: "/Mock/Zhiying 分析输出",
        absolutePath: "/data/yunzhi-files/private/mock/analysis-output",
      },
    }),
    saveToLibrary: async (payload: {
      target: { folderId: number; scope: string }
      sources: Array<{ path: string }>
    }) => ({
      scope: payload.target.scope,
      folderId: payload.target.folderId,
      importedFiles: payload.sources.length,
      items: payload.sources.map((source, index) => ({
        resourceType: "FILE" as const,
        id: 30_000 + index,
        name: source.path.split(/[\\/]/).pop() || `输出文件-${index + 1}`,
        sourcePath: source.path,
        importedFiles: 1,
      })),
    }),
    preview: async (fileId: number) => ({ opened: true, fileId }),
  }
  navigation = {
    open: async (_target: "task-center" | "files" | "skills" | "extensions") => ({ opened: true }),
  }
  ui = {
    notify: async (_payload: {
      level?: "success" | "warning" | "error"
      title?: string
      message: string
    }) => ({ shown: true }),
  }
  tasks = { open: async () => ({ opened: true }) }
  dispose() {}
}
