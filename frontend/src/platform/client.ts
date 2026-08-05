import { MockYunzhiClient } from "./mock-yunzhi-client"
import {
  YunzhiBridge,
  type YunzhiAuthTicket,
  type YunzhiClient,
} from "./yunzhi-bridge"

// VITE_YUNZHI_MOCK 缺省为 true（独立开发）；联调时置 false + 配精确宿主 Origin
const mockEnabled = import.meta.env.VITE_YUNZHI_MOCK !== "false"

async function forwardTicket(ticket: YunzhiAuthTicket) {
  const endpoint = import.meta.env.VITE_YUNZHI_SESSION_ENDPOINT
  if (!endpoint) return
  const response = await fetch(endpoint, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(ticket),
  })
  if (!response.ok) throw new Error(`应用会话创建失败：HTTP ${response.status}`)
}

export const yunzhiClient: YunzhiClient = mockEnabled
  ? new MockYunzhiClient()
  : new YunzhiBridge({
      hostOrigin: import.meta.env.VITE_YUNZHI_HOST_ORIGIN ?? "",
      onTicket: forwardTicket,
    })

export const isYunzhiMock = mockEnabled
