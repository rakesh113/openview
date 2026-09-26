import type { UTCTimestamp } from 'lightweight-charts'
import type { Bar, Indicator } from '../types'
import { atr, bollinger, ema, macd, rsi, sma, vwap, type Series } from './indicators'

export type PlotPoint = { time: UTCTimestamp; value: number; color?: string }

export type Plot = {
  key: string
  indicatorId: string
  group: string
  kind: 'line' | 'hist'
  lower: boolean
  color: string
  dashed: boolean
  title: string
  data: PlotPoint[]
  values: Series
  scale?: { min: number; max: number }
  levels?: number[]
  format: 'price' | 'volume'
  precision: number
}

function points(bars: Bar[], values: Series, color?: (value: number) => string): PlotPoint[] {
  const data: PlotPoint[] = []
  for (let i = 0; i < bars.length; i++) {
    const value = values[i]
    if (value == null || !Number.isFinite(value)) continue
    const point: PlotPoint = { time: bars[i].time as UTCTimestamp, value }
    if (color) point.color = color(value)
    data.push(point)
  }
  return data
}

export function buildPlots(bars: Bar[], indicators: Indicator[]): Plot[] {
  const closes = bars.map((bar) => bar.close)
  const plots: Plot[] = []
  for (const indicator of indicators) {
    if (indicator.type === 'volume') {
      plots.push({
        key: indicator.id,
        indicatorId: indicator.id,
        group: 'volume',
        kind: 'hist',
        lower: true,
        color: indicator.color,
        dashed: false,
        title: 'Volume',
        values: bars.map((bar) => bar.volume),
        data: bars.map((bar) => ({
          time: bar.time as UTCTimestamp,
          value: bar.volume,
          color: bar.close >= bar.open ? 'rgba(8,153,129,0.55)' : 'rgba(242,54,69,0.5)',
        })),
        format: 'volume',
        precision: 0,
      })
    } else if (indicator.type === 'sma') {
      const values = sma(closes, indicator.period)
      plots.push(linePlot(indicator, `SMA ${indicator.period}`, values, bars, false))
    } else if (indicator.type === 'ema') {
      const values = ema(closes, indicator.period)
      plots.push(linePlot(indicator, `EMA ${indicator.period}`, values, bars, false))
    } else if (indicator.type === 'vwap') {
      plots.push(linePlot(indicator, 'VWAP', vwap(bars), bars, false))
    } else if (indicator.type === 'bb') {
      const bands = bollinger(closes, indicator.period, indicator.mult)
      plots.push(linePlot(indicator, `BB ${indicator.period}`, bands.mid, bars, false))
      plots.push(linePlot(indicator, '', bands.upper, bars, true, `${indicator.id}:upper`))
      plots.push(linePlot(indicator, '', bands.lower, bars, true, `${indicator.id}:lower`))
    } else if (indicator.type === 'rsi') {
      plots.push({
        ...linePlot(indicator, `RSI ${indicator.period}`, rsi(closes, indicator.period), bars, false),
        lower: true,
        group: indicator.id,
        scale: { min: 0, max: 100 },
        levels: [30, 70],
      })
    } else if (indicator.type === 'atr') {
      plots.push({
        ...linePlot(indicator, `ATR ${indicator.period}`, atr(bars, indicator.period), bars, false),
        lower: true,
        group: indicator.id,
      })
    } else if (indicator.type === 'macd') {
      const osc = macd(closes, indicator.fast, indicator.slow, indicator.signal)
      const up = 'rgba(8,153,129,0.75)'
      const down = 'rgba(242,54,69,0.75)'
      plots.push({
        key: `${indicator.id}:hist`,
        indicatorId: indicator.id,
        group: indicator.id,
        kind: 'hist',
        lower: true,
        color: indicator.color,
        dashed: false,
        title: `MACD ${indicator.fast},${indicator.slow},${indicator.signal}`,
        values: osc.hist,
        data: points(bars, osc.hist, (value) => (value >= 0 ? up : down)),
        format: 'price',
        precision: 2,
        levels: [0],
      })
      plots.push({
        ...linePlot(indicator, '', osc.line, bars, false, `${indicator.id}:line`),
        lower: true,
        group: indicator.id,
        color: '#2962ff',
      })
      plots.push({
        ...linePlot(indicator, '', osc.signal, bars, false, `${indicator.id}:signal`),
        lower: true,
        group: indicator.id,
        color: '#f5c451',
      })
    }
  }
  return plots
}

function linePlot(
  indicator: Indicator,
  title: string,
  values: Series,
  bars: Bar[],
  dashed: boolean,
  key = indicator.id,
): Plot {
  return {
    key,
    indicatorId: indicator.id,
    group: 'overlay',
    kind: 'line',
    lower: false,
    color: indicator.color,
    dashed,
    title,
    values,
    data: points(bars, values),
    format: 'price',
    precision: 2,
  }
}
