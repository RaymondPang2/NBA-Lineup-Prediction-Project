/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** FastAPI base URL including /api/v1 (src/api/config.ts). */
  readonly VITE_API_BASE_URL?: string
  /** Opt-in team logo URL template with {team_id} and optional {variant}; unset = no logo images (src/lib/teamLogo.ts). */
  readonly VITE_TEAM_LOGO_URL?: string
  /** 1 = public synthetic-data demo build (src/lib/demo.ts). */
  readonly VITE_DEMO_MODE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
