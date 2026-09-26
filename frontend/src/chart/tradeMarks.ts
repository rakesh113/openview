import type { Bar, Trade } from '../types'

export type PlacedTrade = {
  side: 'long' | 'short'
  entryTime: number
  entryPrice: number
  exitTime: number | null
  exitPrice: number | null
  spanEnd: number
  entryVisible: boolean
  exitVisible: boolean
  color: string
  entryText: string
  exitText: string
  pnl: number | null
  open: boolean
}

export function barSpan(timeframe: string): number {
  if (timeframe === '1w') return 7 * 86400
  if (timeframe === '1d') return 86400
  const known: Record<string, number> = {
    '1m': 60,
    '3m': 180,
    '5m': 300,
    '15m': 900,
    '30m': 1800,
    '1h': 3600,
    '4h': 14400,
  }
  return known[timeframe] ?? 60
}

export function tradePnl(trade: Trade): number | null {
  if (trade.pnl != null) return trade.pnl
  if (trade.exit_price == null) return null
  const qty = trade.quantity ?? 1
  return trade.side === 'long'
    ? (trade.exit_price - trade.entry_price) * qty
    : (trade.entry_price - trade.exit_price) * qty
}

export function tradeColor(pnl: number | null): string {
  if (pnl == null) return '#2962ff'
  return pnl >= 0 ? '#089981' : '#f23645'
}

export function formatTradePnl(pnl: number): string {
  const abs = Math.abs(pnl)
  const digits = Number.isInteger(abs) ? 0 : 2
  const body = abs.toLocaleString('en-IN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
  if (pnl > 0) return `+${body}`
  if (pnl < 0) return `−${body}`
  return body
}

function nearestBar(bars: Bar[], time: number): Bar | null {
  if (!bars.length) return null
  let low = 0
  let high = bars.length - 1
  while (low < high) {
    const mid = (low + high) >> 1
    if (bars[mid].time < time) low = mid + 1
    else high = mid
  }
  const next = bars[low]
  const prev = bars[low - 1]
  if (!prev) return next
  return Math.abs(prev.time - time) <= Math.abs(next.time - time) ? prev : next
}

function snapBar(bars: Bar[], time: number, span: number): number | null {
  const bar = nearestBar(bars, time)
  if (!bar || Math.abs(bar.time - time) > span) return null
  return bar.time
}

/** Trades that overlap the loaded candles, snapped onto those bars. */
export function placeTrades(trades: Trade[], bars: Bar[], timeframe: string): PlacedTrade[] {
  if (!trades.length || !bars.length) return []
  const span = barSpan(timeframe)
  const first = bars[0].time
  const last = bars[bars.length - 1].time
  const placed: PlacedTrade[] = []
  for (const trade of trades) {
    const open = trade.exit_time == null || trade.exit_price == null
    const ends = trade.exit_time ?? Number.POSITIVE_INFINITY
    if (ends < first - span || trade.entry_time > last + span) continue
    const entryHit = snapBar(bars, trade.entry_time, span)
    const exitHit = trade.exit_time == null ? null : snapBar(bars, trade.exit_time, span)
    const entryVisible = entryHit != null
    const exitVisible = exitHit != null
    const spanStart = entryHit ?? (trade.entry_time < first ? first : null)
    let spanEnd = exitHit
    if (spanEnd == null && (open || (trade.exit_time != null && trade.exit_time > last))) spanEnd = last
    if (spanStart == null || spanEnd == null || spanEnd < spanStart) continue
    const pnl = tradePnl(trade)
    placed.push({
      side: trade.side,
      entryTime: spanStart,
      entryPrice: trade.entry_price,
      exitTime: exitVisible ? exitHit : null,
      exitPrice: trade.exit_price,
      spanEnd,
      entryVisible,
      exitVisible,
      color: tradeColor(pnl),
      entryText: trade.side === 'long' ? 'Long' : 'Short',
      exitText: pnl == null ? (open ? 'Open' : 'Exit') : formatTradePnl(pnl),
      pnl,
      open,
    })
  }
  return placed
}
