/**
 * Backend location. VITE_API_BASE_URL is the API's versioned base, e.g. http://127.0.0.1:8000/api/v1
 * (the form docs/api.md uses). The generated schema's paths already start with /api/v1, and /health
 * lives at the server root, so the client needs the origin: a trailing /api/v1 is stripped.
 */
export const DEFAULT_API_BASE_URL = 'http://127.0.0.1:8000/api/v1'

export function apiOrigin(base: string | undefined = import.meta.env.VITE_API_BASE_URL): string {
  const raw = (base && base.trim()) || DEFAULT_API_BASE_URL
  return raw.replace(/\/+$/, '').replace(/\/api\/v1$/, '')
}
