/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** FastAPI base URL including /api/v1 (src/api/config.ts). */
  readonly VITE_API_BASE_URL?: string
  /** Opt-in team logo URL template with {team_id} and optional {variant}; unset = no logo images (src/lib/teamLogo.ts). */
  readonly VITE_TEAM_LOGO_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
