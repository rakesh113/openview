import type { CandlePage, Meta, Trade } from './types'

async function readError(response: Response): Promise<string> {
  try {
    const body = await response.json()
    if (typeof body?.detail === 'string') return body.detail
    if (body?.detail) return JSON.stringify(body.detail)
  } catch {
    /* response was not JSON */
  }
  return `${response.status} ${response.statusText}`
}

export async function fetchMeta(): Promise<Meta> {
  const response = await fetch('/api/meta')
  if (!response.ok) throw new Error(await readError(response))
  return response.json()
}

export async function fetchSymbols(dataset: string, query?: string, refresh = false): Promise<{
  symbols: string[]
  labels?: Record<string, string>
  truncated: boolean
}> {
  const params = new URLSearchParams({ dataset })
  if (query) params.set('q', query)
  if (refresh) params.set('refresh', 'true')
  const response = await fetch(`/api/symbols?${params}`)
  if (!response.ok) throw new Error(await readError(response))
  return response.json()
}

export async function fetchCandles(args: {
  dataset: string
  symbol: string
  timeframe: string
  before?: number | null
  after?: number | null
  around?: number | null
  limit?: number
}): Promise<CandlePage> {
  const params = new URLSearchParams({
    dataset: args.dataset,
    symbol: args.symbol,
    timeframe: args.timeframe,
  })
  if (args.limit != null) params.set('limit', String(args.limit))
  if (args.before != null) params.set('before', String(args.before))
  if (args.after != null) params.set('after', String(args.after))
  if (args.around != null) params.set('around', String(args.around))
  const response = await fetch(`/api/candles?${params}`)
  if (!response.ok) throw new Error(await readError(response))
  return response.json()
}

export function barsFromPage(page: CandlePage) {
  return page.bars.map(([time, open, high, low, close, volume]) => ({
    time,
    open,
    high,
    low,
    close,
    volume,
  }))
}

export async function parseTrades(file: File, defaultSymbol: string | null): Promise<{
  trades: Trade[]
  errors: string[]
  count: number
}> {
  const body = new FormData()
  body.append('file', file)
  if (defaultSymbol) body.append('default_symbol', defaultSymbol)
  const response = await fetch('/api/trades/parse', { method: 'POST', body })
  if (!response.ok) throw new Error(await readError(response))
  return response.json()
}
