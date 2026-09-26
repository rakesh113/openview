import type { Bar } from '../types'

export type Series = (number | null)[]

export function sma(values: number[], period: number): Series {
  const out: Series = new Array(values.length).fill(null)
  if (period <= 0) return out
  let sum = 0
  for (let i = 0; i < values.length; i++) {
    sum += values[i]
    if (i >= period) sum -= values[i - period]
    if (i >= period - 1) out[i] = sum / period
  }
  return out
}

export function ema(values: number[], period: number): Series {
  const out: Series = new Array(values.length).fill(null)
  if (period <= 0 || values.length < period) return out
  const k = 2 / (period + 1)
  let sum = 0
  for (let i = 0; i < period; i++) sum += values[i]
  let prev = sum / period
  out[period - 1] = prev
  for (let i = period; i < values.length; i++) {
    prev = values[i] * k + prev * (1 - k)
    out[i] = prev
  }
  return out
}

export function rsi(closes: number[], period: number): Series {
  const out: Series = new Array(closes.length).fill(null)
  if (period <= 0 || closes.length <= period) return out
  let gain = 0
  let loss = 0
  for (let i = 1; i <= period; i++) {
    const delta = closes[i] - closes[i - 1]
    if (delta >= 0) gain += delta
    else loss -= delta
  }
  let avgGain = gain / period
  let avgLoss = loss / period
  const value = () => (avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss))
  out[period] = value()
  for (let i = period + 1; i < closes.length; i++) {
    const delta = closes[i] - closes[i - 1]
    const up = delta > 0 ? delta : 0
    const down = delta < 0 ? -delta : 0
    avgGain = (avgGain * (period - 1) + up) / period
    avgLoss = (avgLoss * (period - 1) + down) / period
    out[i] = value()
  }
  return out
}

export function bollinger(closes: number[], period: number, mult: number): {
  mid: Series
  upper: Series
  lower: Series
} {
  const mid = sma(closes, period)
  const upper: Series = new Array(closes.length).fill(null)
  const lower: Series = new Array(closes.length).fill(null)
  if (period <= 0) return { mid, upper, lower }
  let sum = 0
  let sumSq = 0
  for (let i = 0; i < closes.length; i++) {
    sum += closes[i]
    sumSq += closes[i] * closes[i]
    if (i >= period) {
      sum -= closes[i - period]
      sumSq -= closes[i - period] * closes[i - period]
    }
    if (i >= period - 1) {
      const mean = sum / period
      const variance = Math.max(0, sumSq / period - mean * mean)
      const sd = Math.sqrt(variance)
      upper[i] = mean + mult * sd
      lower[i] = mean - mult * sd
    }
  }
  return { mid, upper, lower }
}

export function macd(closes: number[], fast: number, slow: number, signal: number): {
  line: Series
  signal: Series
  hist: Series
} {
  const fastEma = ema(closes, fast)
  const slowEma = ema(closes, slow)
  const line: Series = closes.map((_, i) =>
    fastEma[i] == null || slowEma[i] == null ? null : (fastEma[i] as number) - (slowEma[i] as number),
  )
  const compact: number[] = []
  const indexes: number[] = []
  line.forEach((value, index) => {
    if (value != null) {
      compact.push(value)
      indexes.push(index)
    }
  })
  const signalCompact = ema(compact, signal)
  const signalLine: Series = closes.map(() => null)
  const hist: Series = closes.map(() => null)
  signalCompact.forEach((value, index) => {
    if (value == null) return
    const at = indexes[index]
    signalLine[at] = value
    hist[at] = (line[at] as number) - value
  })
  return { line, signal: signalLine, hist }
}

export function atr(bars: Pick<Bar, 'high' | 'low' | 'close'>[], period: number): Series {
  const out: Series = new Array(bars.length).fill(null)
  if (period <= 0 || bars.length <= period) return out
  const tr: number[] = new Array(bars.length).fill(0)
  tr[0] = bars[0].high - bars[0].low
  for (let i = 1; i < bars.length; i++) {
    const prev = bars[i - 1].close
    tr[i] = Math.max(
      bars[i].high - bars[i].low,
      Math.abs(bars[i].high - prev),
      Math.abs(bars[i].low - prev),
    )
  }
  let sum = 0
  for (let i = 1; i <= period; i++) sum += tr[i]
  let value = sum / period
  out[period] = value
  for (let i = period + 1; i < bars.length; i++) {
    value = (value * (period - 1) + tr[i]) / period
    out[i] = value
  }
  return out
}

const IST_OFFSET = 5.5 * 3600

export function vwap(bars: Bar[]): Series {
  const out: Series = new Array(bars.length).fill(null)
  let day = Number.NaN
  let pv = 0
  let volume = 0
  for (let i = 0; i < bars.length; i++) {
    const nextDay = Math.floor((bars[i].time + IST_OFFSET) / 86400)
    if (nextDay !== day) {
      day = nextDay
      pv = 0
      volume = 0
    }
    const typical = (bars[i].high + bars[i].low + bars[i].close) / 3
    pv += typical * bars[i].volume
    volume += bars[i].volume
    out[i] = volume > 0 ? pv / volume : null
  }
  return out
}
