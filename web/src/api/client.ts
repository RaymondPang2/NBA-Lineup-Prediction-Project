/**
 * Typed HTTP client. Paths, parameters and response bodies are checked at compile time against
 * src/api/schema.d.ts, which `npm run gen:api` generates from the FastAPI OpenAPI document.
 */
import createClient from 'openapi-fetch'
import { apiOrigin } from './config'
import type { paths } from './schema'

/** An API failure in the backend's uniform shape {"error": {"code", "message", "details"}}, or a network failure. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: unknown

  constructor(status: number, code: string, message: string, details: unknown = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }

  /** Worth retrying automatically: the server or the network, not the request. */
  get transient(): boolean {
    return this.status === 0 || this.status === 503 || this.status === 504
  }
}

export function createApi(baseUrl = apiOrigin(), fetchImpl?: typeof fetch) {
  // Resolve fetch at call time (not at module load), so test interceptors and polyfills are honoured.
  return createClient<paths>({ baseUrl, fetch: fetchImpl ?? ((input: Request) => globalThis.fetch(input)) })
}

export const api = createApi()

type Result<T> = { data?: T; error?: unknown; response: Response }

/** Unwrap an openapi-fetch result: return the body or throw an ApiError. Network failures become status 0. */
export async function unwrap<T>(request: Promise<Result<T>>): Promise<T> {
  let result: Result<T>
  try {
    result = await request
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e
    throw new ApiError(0, 'network_error', `Cannot reach the API at ${apiOrigin()}. Is the backend running?`)
  }
  const { data, error, response } = result
  if (response.ok && data !== undefined) return data
  const body = (error ?? {}) as { error?: { code?: string; message?: string; details?: unknown } }
  throw new ApiError(
    response.status,
    body.error?.code ?? `http_${response.status}`,
    body.error?.message ?? `Request failed with HTTP ${response.status}`,
    body.error?.details ?? null,
  )
}
