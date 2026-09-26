export type Bar = {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export type ColumnInfo = { name: string; type: string }

export type DatasetMeta = {
  id: string
  label: string
  connect: string
  ok: boolean
  error: string | null
  table: string | null
  columns: {
    symbol: string
    time: string
    open: string
    high: string
    low: string
    close: string
    volume: string | null
    time_stored_as: string
  } | null
  estimated_rows: number | null
  inspection: { schema: string; table: string; columns: ColumnInfo[] }[]
}

export type Meta = {
  timezone: string
  session: { open: string; close: string }
  timeframes: string[]
  datasets: DatasetMeta[]
}

export type CandlePage = {
  dataset: string
  symbol: string
  timeframe: string
  timezone: string
  bars: number[][]
  has_more: boolean
  next_before: number | null
  has_newer: boolean
  next_after: number | null
  found: boolean
}

export type Trade = {
  symbol: string
  side: 'long' | 'short'
  entry_time: number
  entry_price: number
  exit_time: number | null
  exit_price: number | null
  quantity: number | null
  pnl: number | null
  tag: string | null
}

export type IndicatorType = 'sma' | 'ema' | 'bb' | 'vwap' | 'rsi' | 'macd' | 'atr' | 'volume'

export type Indicator = {
  id: string
  type: IndicatorType
  period: number
  fast: number
  slow: number
  signal: number
  mult: number
  color: string
}

export type Tool = 'cursor' | 'hline' | 'text'

export type Drawing =
  | { id: string; kind: 'hline'; price: number; color: string; label: string }
  | { id: string; kind: 'note'; time: number; price: number; text: string; color: string }

export const TIMEFRAMES = ['1m', '3m', '5m', '15m', '30m', '1h', '4h', '1d', '1w'] as const

export const TIMEFRAME_LABEL: Record<string, string> = {
  '1m': '1m',
  '3m': '3m',
  '5m': '5m',
  '15m': '15m',
  '30m': '30m',
  '1h': '1H',
  '4h': '4H',
  '1d': '1D',
  '1w': '1W',
}

export const TIMEFRAME_SECONDS: Record<string, number> = {
  '1m': 60,
  '3m': 180,
  '5m': 300,
  '15m': 900,
  '30m': 1800,
  '1h': 3600,
  '4h': 14400,
  '1d': 86400,
  '1w': 7 * 86400,
}
