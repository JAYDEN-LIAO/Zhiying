export type YunzhiResource = {
  resourceType: "FILE" | "FOLDER"
  id: number
  name: string
  scope: string
  path: string
  absolutePath?: string
  category?: string
  contentType?: string
  size?: number
}

export type YunzhiHostContext = {
  appKey: string
  locale: string
  theme: "light" | "dark"
  entryPoint: string
  contributionId?: string
  resource?: {
    resourceType: "FILE" | "FOLDER"
    id: number
    name: string
    category?: string
    scope?: string
  }
  capabilities: string[]
}

export type YunzhiAuthTicket = {
  ticket: string
  expiresIn: number
}

export type FileSelectionOptions = {
  multiple?: boolean
  maxItems?: number
  scopes?: string[]
  categories?: string[]
}

export type YunzhiLibraryTarget = {
  folderId: number
  scope: string
  name: string
  path: string
  absolutePath?: string
}

export type YunzhiLibraryImportResult = {
  scope: string
  folderId: number
  importedFiles: number
  items: Array<{
    resourceType: "FILE" | "FOLDER"
    id: number
    name: string
    sourcePath: string
    importedFiles: number
  }>
}

export interface YunzhiClient {
  connect(): Promise<YunzhiHostContext>
  context: {
    get(): Promise<YunzhiHostContext>
  }
  files: {
    select(options?: FileSelectionOptions): Promise<{ items: YunzhiResource[] }>
    selectFolders(options?: FileSelectionOptions): Promise<{ items: YunzhiResource[] }>
    selectSaveTarget(options?: { scopes?: string[] }): Promise<{ target: YunzhiLibraryTarget }>
    saveToLibrary(payload: {
      target: Pick<YunzhiLibraryTarget, "folderId" | "scope">
      sources: Array<{ path: string }>
    }): Promise<YunzhiLibraryImportResult>
    preview(fileId: number, name?: string): Promise<{ opened: boolean; fileId: number }>
  }
  navigation: {
    open(target: "task-center" | "files" | "skills" | "extensions"): Promise<{ opened: boolean }>
  }
  ui: {
    notify(payload: {
      level?: "success" | "warning" | "error"
      title?: string
      message: string
    }): Promise<{ shown: boolean }>
  }
  tasks: {
    open(): Promise<{ opened: boolean }>
  }
  dispose(): void
}

type BridgeEnvelope = {
  protocol: "yunzhi-extension"
  version: "1.0"
  type: string
  sessionId?: string
  requestId?: string
  payload?: unknown
}

type PendingRequest = {
  resolve: (value: unknown) => void
  reject: (reason: Error) => void
  timer: number
}

export type YunzhiBridgeOptions = {
  hostOrigin: string
  timeoutMs?: number
  onTicket?: (ticket: YunzhiAuthTicket) => void | Promise<void>
}

export class YunzhiBridge implements YunzhiClient {
  private readonly pending = new Map<string, PendingRequest>()
  private readonly readyListeners = new Set<(context: YunzhiHostContext) => void>()
  private sessionId = ""
  private contextValue?: YunzhiHostContext
  private connectPromise?: Promise<YunzhiHostContext>
  private disposed = false

  constructor(private readonly options: YunzhiBridgeOptions) {
    if (!options.hostOrigin || options.hostOrigin === "*") {
      throw new Error("VITE_YUNZHI_HOST_ORIGIN 必须是云智宿主的精确 Origin")
    }
    window.addEventListener("message", this.handleMessage)
  }

  async connect() {
    if (this.contextValue) return this.contextValue
    if (this.connectPromise) return this.connectPromise
    this.connectPromise = new Promise<YunzhiHostContext>((resolve) => this.readyListeners.add(resolve))
    this.post({ protocol: "yunzhi-extension", version: "1.0", type: "extension.ready" })
    return this.connectPromise
  }

  context = {
    get: () => this.request<YunzhiHostContext>("context.get"),
  }

  files = {
    select: (options: FileSelectionOptions = {}) =>
      this.request<{ items: YunzhiResource[] }>("files.select", options),
    selectFolders: (options: FileSelectionOptions = {}) =>
      this.request<{ items: YunzhiResource[] }>("folders.select", options),
    selectSaveTarget: (options: { scopes?: string[] } = {}) =>
      this.request<{ target: YunzhiLibraryTarget }>("folders.selectSaveTarget", options),
    saveToLibrary: (payload: {
      target: Pick<YunzhiLibraryTarget, "folderId" | "scope">
      sources: Array<{ path: string }>
    }) => this.request<YunzhiLibraryImportResult>("files.saveToLibrary", payload),
    preview: (fileId: number, name?: string) =>
      this.request<{ opened: boolean; fileId: number }>("files.preview", { fileId, name }),
  }

  navigation = {
    open: (target: "task-center" | "files" | "skills" | "extensions") =>
      this.request<{ opened: boolean }>("navigation.open", { target }),
  }

  ui = {
    notify: (payload: {
      level?: "success" | "warning" | "error"
      title?: string
      message: string
    }) => this.request<{ shown: boolean }>("ui.notify", payload),
  }

  tasks = {
    open: () => this.request<{ opened: boolean }>("tasks.open"),
  }

  dispose() {
    if (this.disposed) return
    this.disposed = true
    window.removeEventListener("message", this.handleMessage)
    for (const request of this.pending.values()) {
      window.clearTimeout(request.timer)
      request.reject(new Error("Bridge 已关闭"))
    }
    this.pending.clear()
    this.readyListeners.clear()
  }

  private request<T>(type: string, payload?: unknown) {
    if (!this.sessionId) return Promise.reject(new Error("请先等待 Bridge connect() 完成"))
    const requestId = randomRequestId()
    return new Promise<T>((resolve, reject) => {
      const timer = window.setTimeout(() => {
        this.pending.delete(requestId)
        reject(new Error(`Bridge 请求超时：${type}`))
      }, this.options.timeoutMs ?? 15_000)
      this.pending.set(requestId, {
        resolve: resolve as (value: unknown) => void,
        reject,
        timer,
      })
      this.post({
        protocol: "yunzhi-extension",
        version: "1.0",
        sessionId: this.sessionId,
        requestId,
        type,
        payload,
      })
    })
  }

  private post(message: BridgeEnvelope) {
    window.parent.postMessage(message, this.options.hostOrigin)
  }

  private readonly handleMessage = (event: MessageEvent<unknown>) => {
    if (this.disposed || event.origin !== this.options.hostOrigin || event.source !== window.parent) return
    if (!isEnvelope(event.data)) return
    const message = event.data
    if (message.type === "host.ready" && isRecord(message.payload)) {
      this.sessionId = message.sessionId || ""
      this.contextValue = message.payload as YunzhiHostContext
      for (const listener of this.readyListeners) listener(this.contextValue)
      this.readyListeners.clear()
      return
    }
    if (message.type === "auth.ticket" && isRecord(message.payload)) {
      const ticket = message.payload
      if (typeof ticket.ticket === "string" && typeof ticket.expiresIn === "number") {
        Promise.resolve(this.options.onTicket?.(ticket as YunzhiAuthTicket)).catch((error) => {
          console.error("Ticket 转交应用后端失败", error)
        })
      }
      return
    }
    if (!message.requestId || message.sessionId !== this.sessionId) return
    const pending = this.pending.get(message.requestId)
    if (!pending) return
    window.clearTimeout(pending.timer)
    this.pending.delete(message.requestId)
    if (message.type === "response.success") {
      pending.resolve(message.payload)
      return
    }
    const payload = isRecord(message.payload) ? message.payload : {}
    pending.reject(new Error(typeof payload.message === "string" ? payload.message : "Bridge 请求失败"))
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function isEnvelope(value: unknown): value is BridgeEnvelope {
  return isRecord(value)
    && value.protocol === "yunzhi-extension"
    && value.version === "1.0"
    && typeof value.type === "string"
}

/**
 * 生成请求 ID。
 * `crypto.randomUUID` 仅安全上下文（HTTPS / localhost）可用；纯 HTTP 内网
 * （如 http://10.0.0.176:3111）下不可用，回退到 `crypto.getRandomValues`
 * 生成 UUIDv4（该 API 任意上下文可用），兜底用时间戳 + 随机串。
 */
function randomRequestId(): string {
  if (typeof crypto !== "undefined") {
    if (typeof crypto.randomUUID === "function") return crypto.randomUUID()
    if (typeof crypto.getRandomValues === "function") {
      const bytes = crypto.getRandomValues(new Uint8Array(16))
      bytes[6] = (bytes[6] & 0x0f) | 0x40 // version 4
      bytes[8] = (bytes[8] & 0x3f) | 0x80 // variant 10
      const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("")
      return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
    }
  }
  return `req-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}
