/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_ARGUS_URL?: string
  readonly VITE_SENTINEL_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
