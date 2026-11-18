import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '../test/server'
import { api, ApiError, unwrap } from './client'
import { apiOrigin } from './config'

describe('apiOrigin', () => {
  it('accepts VITE_API_BASE_URL with or without the /api/v1 suffix', () => {
    expect(apiOrigin('http://127.0.0.1:8000/api/v1')).toBe('http://127.0.0.1:8000')
    expect(apiOrigin('https://api.example.org/api/v1/')).toBe('https://api.example.org')
    expect(apiOrigin('https://api.example.org')).toBe('https://api.example.org')
    expect(apiOrigin('')).toBe('http://127.0.0.1:8000')
  })
})

describe('unwrap', () => {
  it('returns typed data on success', async () => {
    const seasons = await unwrap(api.GET('/api/v1/seasons'))
    expect(seasons.map((s) => s.season_id)).toContain('2025-26')
  })

  it("turns the backend's error body into an ApiError", async () => {
    const err = await unwrap(api.GET('/api/v1/lineups/{lineup_id}', { params: { path: { lineup_id: 999999999 } } })).catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(404)
    expect(err.code).toBe('not_found')
    expect(err.message).toMatch(/999999999/)
    expect(err.transient).toBe(false)
  })

  it('marks 503 as transient and network failures as status 0', async () => {
    server.use(
      http.get('http://127.0.0.1:8000/api/v1/seasons', () =>
        HttpResponse.json({ error: { code: 'database_unavailable', message: 'database unavailable', details: null } }, { status: 503 }),
      ),
    )
    const e503 = await unwrap(api.GET('/api/v1/seasons')).catch((e) => e)
    expect(e503.code).toBe('database_unavailable')
    expect(e503.transient).toBe(true)

    server.use(http.get('http://127.0.0.1:8000/api/v1/seasons', () => HttpResponse.error()))
    const net = await unwrap(api.GET('/api/v1/seasons')).catch((e) => e)
    expect(net).toBeInstanceOf(ApiError)
    expect(net.status).toBe(0)
    expect(net.transient).toBe(true)
  })
})
