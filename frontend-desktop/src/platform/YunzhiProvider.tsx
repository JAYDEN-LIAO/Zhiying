import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type PropsWithChildren,
} from "react"
import { isYunzhiMock, yunzhiClient } from "./client"
import type { YunzhiClient, YunzhiHostContext, YunzhiResource } from "./yunzhi-bridge"

type YunzhiContextValue = {
  context?: YunzhiHostContext
  resources: YunzhiResource[]
  connecting: boolean
  working: boolean
  error: string
  mock: boolean
  client: YunzhiClient
  connect(): Promise<YunzhiHostContext>
  selectFiles(): Promise<YunzhiResource[]>
  selectFolders(): Promise<YunzhiResource[]>
}

const YunzhiContext = createContext<YunzhiContextValue | undefined>(undefined)

export function YunzhiProvider({ children }: PropsWithChildren) {
  const [context, setContext] = useState<YunzhiHostContext>()
  const [resources, setResources] = useState<YunzhiResource[]>([])
  const [connecting, setConnecting] = useState(false)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState("")

  const connect = useCallback(async () => {
    if (context) return context
    setConnecting(true)
    setError("")
    try {
      const value = await yunzhiClient.connect()
      setContext(value)
      return value
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "无法连接云智宿主"
      setError(message)
      throw cause
    } finally {
      setConnecting(false)
    }
  }, [context])

  const runSelection = useCallback(async (foldersOnly: boolean) => {
    setWorking(true)
    setError("")
    try {
      const result = foldersOnly
        ? await yunzhiClient.files.selectFolders({ multiple: true, maxItems: 20 })
        : await yunzhiClient.files.select({ multiple: true, maxItems: 20 })
      setResources(result.items)
      return result.items
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "资源选择失败"
      setError(message)
      throw cause
    } finally {
      setWorking(false)
    }
  }, [])

  useEffect(() => {
    void connect()
  }, [connect])

  const value = useMemo<YunzhiContextValue>(() => ({
    context,
    resources,
    connecting,
    working,
    error,
    mock: isYunzhiMock,
    client: yunzhiClient,
    connect,
    selectFiles: () => runSelection(false),
    selectFolders: () => runSelection(true),
  }), [connect, connecting, context, error, resources, runSelection, working])

  return <YunzhiContext.Provider value={value}>{children}</YunzhiContext.Provider>
}

export function useYunzhi() {
  const value = useContext(YunzhiContext)
  if (!value) throw new Error("useYunzhi 必须在 YunzhiProvider 内使用")
  return value
}
