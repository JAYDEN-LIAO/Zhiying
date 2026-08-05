/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_YUNZHI_HOST_ORIGIN?: string
  readonly VITE_YUNZHI_MOCK?: string
  readonly VITE_YUNZHI_SESSION_ENDPOINT?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
