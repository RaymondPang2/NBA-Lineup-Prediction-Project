/**
 * Loads the fixtures recorded from the live API by `npm run fixtures` (git-ignored: they are NBA-derived data).
 * Reading them at runtime, rather than importing, lets a missing fixture produce one clear error.
 */
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

// Vitest runs from web/ (jsdom gives import.meta.url an http: scheme, so resolve from the project root).
const DIR = join(process.cwd(), 'src', 'test', 'fixtures')

export function fixture<T = unknown>(name: string): T {
  const path = join(DIR, `${name}.json`)
  if (!existsSync(path)) {
    throw new Error(`Missing test fixture ${name}.json. Start the API and run \`npm run fixtures\` to record real responses.`)
  }
  return JSON.parse(readFileSync(path, 'utf8')) as T
}

export function manifest(): { recorded_at: string; origin: string; files: Record<string, { method: string; path: string; status: number; body?: unknown }> } {
  return fixture('manifest')
}
