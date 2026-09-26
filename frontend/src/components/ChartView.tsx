import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  createTextWatermark,
  type Coordinate,
  type TickMarkType,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type ITextWatermarkPluginApi,
  type LogicalRange,
  type MouseEventParams,
  type SeriesType,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts'
import { useEffect, useMemo, useRef, useState } from 'react'
import { ChartOverlay, type NoteMark } from '../chart/overlay'
import { placeTrades } from '../chart/tradeMarks'
import { formatChange, formatPrice, formatTick, formatVolume, formatWhen } from '../lib/format'
import { buildPlots } from '../lib/plots'
import type { Bar, Drawing, Indicator, Tool, Trade } from '../types'

type Props = {
  bars: Bar[]
  timeframe: string
  symbol: string | null
  indicators: Indicator[]
  trades: Trade[]
  drawings: Drawing[]
  tool: Tool
  anchor: string
  loading: boolean
  paging: 'older' | 'newer' | null
  capped: boolean
  onNeedOlder: () => void
  onNeedNewer: () => void
  onViewportBars: (count: number) => void
  onJumpLatest: () => void
  onShowTrades: () => void
  onRemoveIndicator: (id: string) => void
  onPlace: (place: { tool: Tool; price: number; time: number; x: number; y: number }) => void
  onHoverTime: (time: number | null) => void
  draft: { x: number; y: number } | null
  onDraftCommit: (text: string) => void
  onDraftCancel: () => void
}

function tfSeconds(timeframe: string): number {
  if (timeframe === '1w') return 7 * 86400
  if (timeframe === '1d') return 86400
  return ({ '1m': 60, '3m': 180, '5m': 300, '15m': 900, '30m': 1800, '1h': 3600, '4h': 14400 } as Record<string, number>)[timeframe] ?? 60
}

function nearestIndex(bars: Bar[], time: number): number {
  if (!bars.length) return -1
  let low = 0
  let high = bars.length - 1
  while (low < high) {
    const mid = (low + high + 1) >> 1
    if (bars[mid].time <= time) low = mid
    else high = mid - 1
  }
  return low
}

function snapTime(bars: Bar[], time: number, width: number): number | null {
  if (!bars.length) return null
  if (time < bars[0].time - width || time > bars[bars.length - 1].time + width) return null
  return bars[nearestIndex(bars, time)].time
}

export function ChartView({
  bars,
  timeframe,
  symbol,
  indicators,
  trades,
  drawings,
  tool,
  anchor,
  loading,
  paging,
  capped,
  onNeedOlder,
  onNeedNewer,
  onViewportBars,
  onJumpLatest,
  onShowTrades,
  onRemoveIndicator,
  onPlace,
  onHoverTime,
  draft,
  onDraftCommit,
  onDraftCancel,
}: Props) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candleRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null)
  const overlayRef = useRef<ChartOverlay | null>(null)
  const watermarkRef = useRef<ITextWatermarkPluginApi<Time> | null>(null)
  const extraRef = useRef<ISeriesApi<SeriesType>[]>([])
  const linesRef = useRef<IPriceLine[]>([])
  const signatureRef = useRef('')
  const barsRef = useRef(bars)
  const toolRef = useRef(tool)
  const tfRef = useRef(timeframe)
  const olderRef = useRef(onNeedOlder)
  const newerRef = useRef(onNeedNewer)
  const viewportRef = useRef(onViewportBars)
  const placeRef = useRef(onPlace)
  const hoverRef = useRef(onHoverTime)
  const suppressRef = useRef(false)
  const edgeRef = useRef<LogicalRange | null>(null)
  const appliedAnchor = useRef('')
  const prevEdge = useRef<{ first: number | null; length: number }>({ first: null, length: 0 })
  const [hoverIndex, setHoverIndex] = useState<number | null>(null)
  const [away, setAway] = useState(false)
  const [draftText, setDraftText] = useState('')

  barsRef.current = bars
  toolRef.current = tool
  tfRef.current = timeframe
  olderRef.current = onNeedOlder
  newerRef.current = onNeedNewer
  viewportRef.current = onViewportBars
  placeRef.current = onPlace
  hoverRef.current = onHoverTime

  const plots = useMemo(() => buildPlots(bars, indicators), [bars, indicators])

  useEffect(() => {
    const element = canvasRef.current
    if (!element) return
    const chart = createChart(element, {
      autoSize: false,
      layout: {
        background: { type: ColorType.Solid, color: '#131722' },
        textColor: '#787b86',
        fontSize: 12,
        fontFamily: "'Segoe UI', 'Trebuchet MS', Ubuntu, sans-serif",
        panes: {
          enableResize: true,
          separatorColor: '#2a2e39',
          separatorHoverColor: 'rgba(41, 98, 255, 0.45)',
        },
        attributionLogo: true,
      },
      grid: {
        vertLines: { color: '#1e222d' },
        horzLines: { color: '#1e222d' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: '#758696', width: 1, style: LineStyle.Dashed, labelBackgroundColor: '#363a45' },
        horzLine: { color: '#758696', width: 1, style: LineStyle.Dashed, labelBackgroundColor: '#363a45' },
      },
      rightPriceScale: { borderColor: '#2a2e39', minimumWidth: 72 },
      timeScale: {
        borderColor: '#2a2e39',
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 8,
        barSpacing: 8,
        minBarSpacing: 0.4,
        tickMarkFormatter: (time: Time, type: TickMarkType) =>
          typeof time === 'number' ? formatTick(time, type, tfRef.current) : '',
      },
      localization: {
        locale: 'en-IN',
        timeFormatter: (time: Time) => (typeof time === 'number' ? formatWhen(time, tfRef.current) : ''),
      },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: false,
      },
      handleScale: {
        mouseWheel: true,
        pinch: true,
        axisPressedMouseMove: { time: true, price: true },
        axisDoubleClickReset: { time: true, price: true },
      },
      kineticScroll: { mouse: true, touch: true },
    })
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: '#089981',
      downColor: '#f23645',
      borderUpColor: '#089981',
      borderDownColor: '#f23645',
      wickUpColor: '#089981',
      wickDownColor: '#f23645',
      priceLineColor: '#d1d4dc',
    })
    const markers = createSeriesMarkers(candles, [], { zOrder: 'top' })
    const overlay = new ChartOverlay()
    candles.attachPrimitive(overlay)
    const watermark = createTextWatermark(chart.panes()[0], {
      horzAlign: 'center',
      vertAlign: 'center',
      lines: [{ text: '', color: 'rgba(209,212,220,0.045)', fontSize: 84, fontStyle: 'bold' }],
    })

    const reportViewport = () => {
      const spacing = Math.max(chart.timeScale().options().barSpacing, 0.5)
      const width = element.clientWidth
      if (width <= 0) return
      const visible = Math.ceil(width / spacing)
      viewportRef.current(Math.min(900, Math.max(80, visible * 2)))
    }
    const resize = () => {
      const width = element.clientWidth
      const height = element.clientHeight
      if (width > 0 && height > 0) chart.resize(width, height)
      reportViewport()
    }
    const observer = new ResizeObserver(resize)
    observer.observe(element)
    resize()

    const onRange = (range: LogicalRange | null) => {
      if (!range || suppressRef.current) return
      reportViewport()
      const count = barsRef.current.length
      setAway(count > 0 && range.to < count - 3)
      if (range.from < 40) olderRef.current()
      if (count > 0 && range.to > count - 4) newerRef.current()
    }
    chart.timeScale().subscribeVisibleLogicalRangeChange(onRange)

    const onMove = (param: MouseEventParams<Time>) => {
      if (param.point == null || param.time == null || typeof param.time !== 'number') {
        setHoverIndex(null)
        hoverRef.current(null)
        return
      }
      const index = nearestIndex(barsRef.current, param.time)
      const bar = barsRef.current[index]
      if (!bar || bar.time !== param.time) {
        setHoverIndex(null)
        hoverRef.current(null)
        return
      }
      setHoverIndex(index)
      hoverRef.current(bar.time)
    }
    chart.subscribeCrosshairMove(onMove)

    const onClick = (param: MouseEventParams<Time>) => {
      const active = toolRef.current
      if (active === 'cursor' || !param.point || typeof param.time !== 'number') return
      const price = candles.coordinateToPrice(param.point.y as Coordinate)
      if (price == null) return
      placeRef.current({ tool: active, price, time: param.time, x: param.point.x, y: param.point.y })
    }
    chart.subscribeClick(onClick)

    chartRef.current = chart
    candleRef.current = candles
    markersRef.current = markers
    overlayRef.current = overlay
    watermarkRef.current = watermark

    return () => {
      observer.disconnect()
      chart.remove()
      chartRef.current = null
      candleRef.current = null
      extraRef.current = []
      signatureRef.current = ''
    }
  }, [])

  useEffect(() => {
    const chart = chartRef.current
    const series = candleRef.current
    if (!chart || !series) return
    const data = bars.map((bar) => ({
      time: bar.time as UTCTimestamp,
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
    }))
    const range = chart.timeScale().getVisibleLogicalRange()
    suppressRef.current = true
    series.setData(data)
    const previous = prevEdge.current
    if (anchor.startsWith('latest')) {
      if (appliedAnchor.current !== anchor && data.length) {
        appliedAnchor.current = anchor
        const width = canvasRef.current?.clientWidth ?? 960
        const spacing = Math.max(chart.timeScale().options().barSpacing, 1)
        const visible = Math.min(data.length, Math.max(40, Math.round(width / spacing)))
        chart.timeScale().setVisibleLogicalRange({
          from: data.length - visible,
          to: data.length + 6,
        })
      }
    } else if (anchor.startsWith('focus:')) {
      const time = Number(anchor.slice('focus:'.length).split(':')[0])
      const width = tfSeconds(timeframe)
      if (appliedAnchor.current !== anchor && data.length && Number.isFinite(time)) {
        const index = nearestIndex(bars, time)
        if (index >= 0 && Math.abs(bars[index].time - time) <= width) {
          appliedAnchor.current = anchor
          chart.timeScale().setVisibleLogicalRange({ from: index - 80, to: index + 50 })
        }
      }
    } else if (range && previous.first != null && data.length && data[0].time < previous.first) {
      const added = data.length - previous.length
      chart.timeScale().setVisibleLogicalRange({ from: range.from + added, to: range.to + added })
    } else if (range && data.length) {
      chart.timeScale().setVisibleLogicalRange(range)
    }
    prevEdge.current = { first: data[0]?.time ?? null, length: data.length }
    edgeRef.current = chart.timeScale().getVisibleLogicalRange()
    requestAnimationFrame(() => {
      suppressRef.current = false
    })
  }, [anchor, bars])

  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    const signature = plots.map((plot) => `${plot.key}:${plot.color}:${plot.title}:${plot.lower}`).join('|')
    if (signature !== signatureRef.current) {
      for (const series of extraRef.current) chart.removeSeries(series)
      extraRef.current = []
      signatureRef.current = signature
      const panes = new Map<string, number>()
      let nextPane = 1
      for (const plot of plots) {
        if (!plot.lower || panes.has(plot.group)) continue
        panes.set(plot.group, nextPane)
        nextPane += 1
      }
      for (const plot of plots) {
        const paneIndex = plot.lower ? panes.get(plot.group) ?? 1 : 0
        const common = {
          color: plot.color,
          title: plot.title,
          priceLineVisible: false,
          lastValueVisible: plot.kind === 'line' && !plot.dashed && Boolean(plot.title),
          priceFormat:
            plot.format === 'volume'
              ? { type: 'volume' as const }
              : { type: 'price' as const, precision: plot.precision, minMove: 0.01 },
          autoscaleInfoProvider: plot.scale
            ? () => ({ priceRange: { minValue: plot.scale!.min, maxValue: plot.scale!.max } })
            : undefined,
        }
        const series =
          plot.kind === 'hist'
            ? chart.addSeries(HistogramSeries, common, paneIndex)
            : chart.addSeries(
                LineSeries,
                { ...common, lineWidth: 2, lineStyle: plot.dashed ? LineStyle.Dashed : LineStyle.Solid },
                paneIndex,
              )
        for (const level of plot.levels ?? []) {
          series.createPriceLine({
            price: level,
            color: 'rgba(120,123,134,0.55)',
            lineWidth: 1,
            lineStyle: LineStyle.Dotted,
            axisLabelVisible: false,
            title: '',
          })
        }
        extraRef.current.push(series)
        if (paneIndex > 0) chart.panes()[paneIndex]?.setStretchFactor(plot.group === 'volume' ? 0.18 : 0.26)
      }
    }
    plots.forEach((plot, index) => {
      extraRef.current[index]?.setData(plot.data)
    })
  }, [plots])

  const placedTrades = useMemo(() => placeTrades(trades, bars, timeframe), [trades, bars, timeframe])

  useEffect(() => {
    markersRef.current?.setMarkers([])
    overlayRef.current?.setTrades(placedTrades)
  }, [placedTrades])

  useEffect(() => {
    const series = candleRef.current
    if (!series) return
    for (const line of linesRef.current) series.removePriceLine(line)
    linesRef.current = drawings
      .filter((drawing): drawing is Extract<Drawing, { kind: 'hline' }> => drawing.kind === 'hline')
      .map((drawing) =>
        series.createPriceLine({
          price: drawing.price,
          color: drawing.color,
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: drawing.label || 'Level',
        }),
      )
    const width = 86400
    const notes: NoteMark[] = drawings
      .filter((drawing): drawing is Extract<Drawing, { kind: 'note' }> => drawing.kind === 'note')
      .map((drawing) => ({
        time: snapTime(bars, drawing.time, width) ?? drawing.time,
        price: drawing.price,
        text: drawing.text,
        color: drawing.color,
      }))
    overlayRef.current?.setNotes(notes)
  }, [bars, drawings])

  useEffect(() => {
    watermarkRef.current?.applyOptions({
      lines: [{ text: symbol ?? '', color: 'rgba(209,212,220,0.045)', fontSize: 84, fontStyle: 'bold' }],
    })
  }, [symbol])

  useEffect(() => {
    setDraftText('')
  }, [draft])

  const index = hoverIndex ?? (bars.length ? bars.length - 1 : -1)
  const bar = index >= 0 ? bars[index] : null
  const hoverTrade =
    bar == null
      ? null
      : (trades.find(
          (trade) => trade.entry_time <= bar.time && (trade.exit_time == null || trade.exit_time >= bar.time),
        ) ?? null)
  const previous = index > 0 ? bars[index - 1].close : bar?.open
  const change = bar && previous ? bar.close - previous : 0
  const pct = bar && previous ? (change / previous) * 100 : 0
  const up = change >= 0

  const legendItems: { id: string; color: string; label: string }[] = []
  const seen = new Set<string>()
  for (const plot of plots) {
    if (!plot.title || seen.has(plot.indicatorId)) continue
    seen.add(plot.indicatorId)
    const value = index >= 0 ? plot.values[index] : null
    const text = value == null ? '—' : plot.format === 'volume' ? formatVolume(value) : formatPrice(value)
    legendItems.push({ id: plot.indicatorId, color: plot.color, label: `${plot.title} ${text}` })
  }

  return (
    <div className={`chart-wrap tool-${tool}`} ref={wrapRef}>
      <div className="chart-canvas" ref={canvasRef} />
      {(loading || paging) && <div className="chart-progress" />}
      {bar && (
        <div className="legend">
          <div className="legend-main">
            <span className="legend-symbol">{symbol}</span>
            <span className="legend-tf">{timeframe}</span>
            <span>O <b>{formatPrice(bar.open)}</b></span>
            <span>H <b>{formatPrice(bar.high)}</b></span>
            <span>L <b>{formatPrice(bar.low)}</b></span>
            <span>C <b className={up ? 'up' : 'down'}>{formatPrice(bar.close)}</b></span>
            <span className={up ? 'up' : 'down'}>
              {formatChange(change)} ({formatChange(pct)}%)
            </span>
            <span>V <b>{formatVolume(bar.volume)}</b></span>
            {hoverTrade && (
              <span className={hoverTrade.side === 'long' ? 'up' : 'down'}>
                {hoverTrade.side === 'long' ? 'Long' : 'Short'} {formatPrice(hoverTrade.entry_price)}
                {hoverTrade.exit_price != null ? ` → ${formatPrice(hoverTrade.exit_price)}` : ' · open'}
                {hoverTrade.tag ? ` · ${hoverTrade.tag}` : ''}
              </span>
            )}
          </div>
          {legendItems.length > 0 && (
            <div className="legend-inds">
              {legendItems.map((item) => (
                <span key={item.id} style={{ color: item.color }}>
                  {item.label}
                  <button type="button" onClick={() => onRemoveIndicator(item.id)} aria-label={`Remove ${item.label}`}>
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>
      )}
      {trades.length > 0 && (
        <button type="button" className="trades-jump" onClick={onShowTrades}>
          {placedTrades.length === 0
            ? `Show ${trades.length} trade${trades.length === 1 ? '' : 's'}`
            : `${placedTrades.length} trade${placedTrades.length === 1 ? '' : 's'} on chart`}
        </button>
      )}
      {away && (
        <button type="button" className="latest-btn" onClick={onJumpLatest}>
          Latest
        </button>
      )}
      <button
        type="button"
        className="autoscale-btn"
        onClick={() => candleRef.current?.priceScale().applyOptions({ autoScale: true })}
        title="Reset price scale"
      >
        Auto
      </button>
      {capped && <div className="cap-note">History window is full. Switch timeframe for a longer view.</div>}
      {draft && (
        <form
          className="note-form"
          style={{ left: draft.x, top: draft.y }}
          onSubmit={(event) => {
            event.preventDefault()
            if (draftText.trim()) onDraftCommit(draftText.trim())
          }}
        >
          <input
            autoFocus
            value={draftText}
            placeholder="Note"
            onChange={(event) => setDraftText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Escape') onDraftCancel()
            }}
          />
        </form>
      )}
    </div>
  )
}
