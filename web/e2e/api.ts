import type { APIRequestContext } from '@playwright/test'

export const API = (process.env.API_BASE_URL ?? 'http://127.0.0.1:8000/api/v1').replace(/\/+$/, '')

export async function apiGet<T>(request: APIRequestContext, path: string): Promise<T> {
  const res = await request.get(`${API}${path}`)
  if (!res.ok()) throw new Error(`${path}: HTTP ${res.status()}`)
  return (await res.json()) as T
}

/** Same formatting as the app (src/lib/format.ts fmtSigned). */
export function signed(x: number, digits = 1): string {
  const r = Number(x.toFixed(digits))
  if (r === 0) return (0).toFixed(digits)
  return `${r > 0 ? '+' : '−'}${Math.abs(r).toFixed(digits)}`
}
