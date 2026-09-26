import { useCallback, useEffect, useRef, useState } from 'react'
import { barsFromPage, fetchCandles, fetchMeta, fetchSymbols, parseTrades } from './api'
import { Blotter } from './components/Blotter'
import { ChartView } from './components/ChartView'
import { IndicatorDialog, TradeDialog } from './components/Dialogs'
import { Toolbar } from './components/Toolbar'
import { Watchlist } from './components/Watchlist'
import { formatPrice } from './lib/format'
import type { Bar, CandlePage, DatasetMeta, Drawing, Indicator, Meta, Tool, Trade } from './types'

const MAX_BARS = 4_000

const DEFAULT_INDICATORS: Indicator[] = [
  { id: 'volume', type: 'volume', period: 20, fast: 12, slow: 26, signal: 9, mult: 2, color: '#26a69a' },
]

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : fallback
  } catch {
    return fallback
  }
}

function mergeBars(existing: Bar[], incoming: Bar[]): Bar[] {
  const byTime = new Map<number, Bar>()
  for (const bar of existing) byTime.set(bar.time, bar)
  for (const bar of incoming) byTime.set(bar.time, bar)
  return [...byTime.values()].sort((a, b) => a.time - b.time)
}

function uid(): string {
  return Math.random().toString(36).slice(2, 10)
}

export function App() {
  const [meta, setMeta] = useState<Meta | null>(null)
  const [bootError, setBootError] = useState<string | null>(null)
  const [dataset, setDataset] = useState('')
  const [symbol, setSymbol] = useState<string | null>(null)
  const [timeframe, setTimeframe] = useState('5m')
  const [symbols, setSymbols] = useState<string[]>([])
  const [labels, setLabels] = useState<Record<string, string>>({})
  const [symbolQuery, setSymbolQuery] = useState('')
  const [truncated, setTruncated] = useState(false)
  const [symbolsLoading, setSymbolsLoading] = useState(false)
  const [symbolsError, setSymbolsError] = useState<string | null>(null)
  const [bars, setBars] = useState<Bar[]>([])
  const [hasMore, setHasMore] = useState(false)
  const [nextBefore, setNextBefore] = useState<number | null>(null)
  const [hasNewer, setHasNewer] = useState(false)
  const [nextAfter, setNextAfter] = useState<number | null>(null)
  const [found, setFound] = useState(true)
  const [loading, setLoading] = useState(false)
  const [paging, setPaging] = useState<'older' | 'newer' | null>(null)
  const [candleError, setCandleError] = useState<string | null>(null)
  const [anchor, setAnchor] = useState('latest')
  const [indicators, setIndicators] = useState<Indicator[]>(() => readJson('openview.indicators', DEFAULT_INDICATORS))
  const [trades, setTrades] = useState<Trade[]>(() => readJson('openview.trades', []))
  const [drawings, setDrawings] = useState<Drawing[]>([])
  const [tool, setTool] = useState<Tool>('cursor')
  const [dialog, setDialog] = useState<'indicators' | 'trades' | null>(null)
  const [hoverTime, setHoverTime] = useState<number | null>(null)
  const [symbolOnly, setSymbolOnly] = useState(true)
  const [listWidth, setListWidth] = useState(() => readJson('openview.listWidth', 248))
  const [blotterHeight, setBlotterHeight] = useState(() => readJson('openview.blotterHeight', 176))
  const [blotterMode, setBlotterMode] = useState<'normal' | 'min' | 'max'>(() => {
    const saved = readJson<'normal' | 'min' | 'max'>('openview.blotterMode', 'normal')
    return saved === 'min' || saved === 'max' ? saved : 'normal'
  })
  const [listOpen, setListOpen] = useState(() => window.innerWidth > 900)
  const [focusToken, setFocusToken] = useState(0)
  const [draft, setDraft] = useState<{ x: number; y: number; time: number; price: number } | null>(null)
  const [tradeBusy, setTradeBusy] = useState(false)
  const [tradeError, setTradeError] = useState<string | null>(null)
  const [rowErrors, setRowErrors] = useState<string[]>([])

  const requestId = useRef(0)
  const limitRef = useRef(280)
  const lock = useRef(false)
  const drawingSymbol = useRef<string | null>(null)
  const pendingFocus = useRef<number | null>(null)
  const pageRef = useRef({ hasMore, nextBefore, hasNewer, nextAfter, bars })
  pageRef.current = { hasMore, nextBefore, hasNewer, nextAfter, bars }

  const current: DatasetMeta | undefined = meta?.datasets.find((item) => item.id === dataset)

  useEffect(() => {
    fetchMeta()
      .then((payload) => {
        setMeta(payload)
        const first = payload.datasets.find((item) => item.ok) ?? payload.datasets[0]
        if (first) setDataset(first.id)
      })
      .catch((error: Error) => setBootError(error.message))
  }, [])

  useEffect(() => {
    localStorage.setItem('openview.indicators', JSON.stringify(indicators))
  }, [indicators])
  useEffect(() => {
    localStorage.setItem('openview.trades', JSON.stringify(trades))
  }, [trades])
  useEffect(() => {
    localStorage.setItem('openview.listWidth', JSON.stringify(listWidth))
    localStorage.setItem('openview.blotterHeight', JSON.stringify(blotterHeight))
    localStorage.setItem('openview.blotterMode', JSON.stringify(blotterMode))
  }, [listWidth, blotterHeight, blotterMode])

  useEffect(() => {
    if (!dataset) return
    let cancel = false
    const query = truncated ? symbolQuery.trim() : ''
    const timer = window.setTimeout(() => {
      setSymbolsLoading(true)
      fetchSymbols(dataset, query || undefined)
        .then((result) => {
          if (cancel) return
          setSymbols(result.symbols)
          setLabels(result.labels ?? {})
          if (!query) setTruncated(result.truncated)
          setSymbolsError(null)
        })
        .catch((error: Error) => {
          if (!cancel) setSymbolsError(error.message)
        })
        .finally(() => {
          if (!cancel) setSymbolsLoading(false)
        })
    }, query ? 160 : 0)
    return () => {
      cancel = true
      window.clearTimeout(timer)
    }
  }, [dataset, truncated, truncated ? symbolQuery : ''])

  useEffect(() => {
    if (symbol || truncated || symbols.length === 0) return
    const preferred = ['RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'ICICIBANK'].find((item) => symbols.includes(item))
    setSymbol(preferred ?? symbols[0])
  }, [symbol, symbols, truncated])

  useEffect(() => {
    if (!symbol) {
      setDrawings([])
      drawingSymbol.current = null
      return
    }
    drawingSymbol.current = symbol
    setDrawings(readJson(`openview.drawings.${symbol}`, []))
  }, [symbol])

  const applyPage = useCallback((page: CandlePage, mode: 'replace' | 'older' | 'newer') => {
    const incoming = barsFromPage(page)
    setHasMore(page.has_more)
    setNextBefore(page.next_before)
    setHasNewer(page.has_newer)
    setNextAfter(page.next_after)
    setFound(page.found)
    setBars((prev) => (mode === 'replace' ? incoming : mergeBars(prev, incoming)))
  }, [])

  useEffect(() => {
    if (!dataset || !symbol || (current && !current.ok)) return
    const id = ++requestId.current
    const focus = pendingFocus.current
    pendingFocus.current = null
    setLoading(true)
    setCandleError(null)
    setFound(true)
    if (!focus) setBars([])
    const request = focus
      ? fetchCandles({ dataset, symbol, timeframe, around: focus, limit: limitRef.current })
      : fetchCandles({ dataset, symbol, timeframe, limit: limitRef.current })
    setAnchor(focus ? `focus:${focus}:${id}` : `latest:${dataset}:${symbol}:${timeframe}`)
    request
      .then((page) => {
        if (id !== requestId.current) return
        applyPage(page, 'replace')
      })
      .catch((error: Error) => {
        if (id !== requestId.current) return
        setCandleError(error.message)
        setBars([])
      })
      .finally(() => {
        if (id === requestId.current) setLoading(false)
      })
  }, [applyPage, current, dataset, symbol, timeframe])

  const onViewportBars = useCallback((count: number) => {
    limitRef.current = count
  }, [])

  const loadOlder = useCallback(() => {
    const state = pageRef.current
    if (!dataset || !symbol || lock.current || !state.hasMore || state.nextBefore == null) return
    if (state.bars.length >= MAX_BARS) return
    const id = requestId.current
    lock.current = true
    setPaging('older')
    setAnchor('keep')
    const run = async () => {
      let before: number | null = state.nextBefore
      let incoming: Bar[] = []
      let last: CandlePage | null = null
      for (let hop = 0; hop < 6 && before != null; hop++) {
        const page = await fetchCandles({ dataset, symbol, timeframe, before, limit: limitRef.current })
        if (id !== requestId.current) return
        last = page
        incoming = mergeBars(incoming, barsFromPage(page))
        if (page.bars.length > 0 || !page.has_more) break
        before = page.next_before
      }
      if (!last || id !== requestId.current) return
      setHasMore(last.has_more)
      setNextBefore(last.next_before)
      setHasNewer(last.has_newer)
      setNextAfter(last.next_after)
      setBars((prev) => {
        const merged = mergeBars(incoming, prev)
        if (merged.length <= MAX_BARS) return merged
        const kept = merged.slice(0, MAX_BARS)
        setHasNewer(true)
        setNextAfter(kept[kept.length - 1].time + 1)
        return kept
      })
    }
    run()
      .catch((error: Error) => {
        if (id === requestId.current) setCandleError(error.message)
      })
      .finally(() => {
        lock.current = false
        setPaging(null)
      })
  }, [dataset, symbol, timeframe])

  const loadNewer = useCallback(() => {
    const state = pageRef.current
    if (!dataset || !symbol || lock.current || !state.hasNewer || state.nextAfter == null) return
    if (state.bars.length >= MAX_BARS) return
    const id = requestId.current
    lock.current = true
    setPaging('newer')
    setAnchor('keep')
    fetchCandles({ dataset, symbol, timeframe, after: state.nextAfter, limit: limitRef.current })
      .then((page) => {
        if (id !== requestId.current) return
        const incoming = barsFromPage(page)
        setHasMore(page.has_more)
        setNextBefore(page.next_before)
        setHasNewer(page.has_newer)
        setNextAfter(page.next_after)
        setFound(page.found)
        setBars((prev) => {
          const merged = mergeBars(prev, incoming)
          if (merged.length <= MAX_BARS) return merged
          const kept = merged.slice(merged.length - MAX_BARS)
          setHasMore(true)
          setNextBefore(kept[0].time)
          return kept
        })
      })
      .catch((error: Error) => {
        if (id === requestId.current) setCandleError(error.message)
      })
      .finally(() => {
        lock.current = false
        setPaging(null)
      })
  }, [applyPage, dataset, symbol, timeframe])

  function jumpLatest() {
    if (pageRef.current.hasNewer && dataset && symbol) {
      pendingFocus.current = null
      const id = ++requestId.current
      setLoading(true)
      setAnchor(`latest:${dataset}:${symbol}:${timeframe}:${id}`)
      fetchCandles({ dataset, symbol, timeframe, limit: limitRef.current })
        .then((page) => {
          if (id !== requestId.current) return
          applyPage(page, 'replace')
        })
        .catch((error: Error) => {
          if (id === requestId.current) setCandleError(error.message)
        })
        .finally(() => {
          if (id === requestId.current) setLoading(false)
        })
      return
    }
    setAnchor(`latest:${dataset}:${symbol}:${timeframe}:${Date.now()}`)
  }

  function focusTrade(trade: Trade) {
    const inside =
      trade.symbol === symbol &&
      bars.length > 0 &&
      trade.entry_time >= bars[0].time &&
      trade.entry_time <= bars[bars.length - 1].time + 3600
    if (inside) {
      setAnchor(`focus:${trade.entry_time}:${Date.now()}`)
      return
    }
    if (trade.symbol !== symbol) {
      pendingFocus.current = trade.entry_time
      setSymbol(trade.symbol)
      return
    }
    if (dataset) {
      pendingFocus.current = null
      const id = ++requestId.current
      setLoading(true)
      setAnchor(`focus:${trade.entry_time}:${id}`)
      fetchCandles({ dataset, symbol: trade.symbol, timeframe, around: trade.entry_time, limit: limitRef.current })
        .then((page) => {
          if (id !== requestId.current) return
          pendingFocus.current = null
          applyPage(page, 'replace')
        })
        .catch((error: Error) => {
          if (id === requestId.current) setCandleError(error.message)
        })
        .finally(() => {
          if (id === requestId.current) setLoading(false)
        })
    }
  }

  function updateDrawings(next: Drawing[]) {
    setDrawings(next)
    if (drawingSymbol.current) {
      localStorage.setItem(`openview.drawings.${drawingSymbol.current}`, JSON.stringify(next))
    }
  }

  function onPlace(place: { tool: Tool; price: number; time: number; x: number; y: number }) {
    if (place.tool === 'hline') {
      updateDrawings([
        ...drawings,
        { id: uid(), kind: 'hline', price: place.price, color: '#f5c451', label: formatPrice(place.price) },
      ])
      return
    }
    if (place.tool === 'text') setDraft(place)
  }

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      const typing = target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT')
      if (event.key === 'Escape') {
        setTool('cursor')
        setDraft(null)
        setDialog(null)
      } else if (event.key === '/' && !typing) {
        event.preventDefault()
        setListOpen(true)
        setFocusToken((value) => value + 1)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  function dragList(event: React.PointerEvent) {
    const start = event.clientX
    const origin = listWidth
    const move = (pointer: PointerEvent) => setListWidth(Math.min(420, Math.max(180, origin + pointer.clientX - start)))
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  function dragBlotter(event: React.PointerEvent) {
    const start = event.clientY
    const origin = blotterHeight
    const move = (pointer: PointerEvent) =>
      setBlotterHeight(Math.min(window.innerHeight * 0.55, Math.max(36, origin - (pointer.clientY - start))))
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  async function onTradeFile(file: File, assign: boolean) {
    setTradeBusy(true)
    setTradeError(null)
    try {
      const result = await parseTrades(file, assign ? symbol : null)
      setTrades(result.trades)
      setRowErrors(result.errors)
      if (result.errors.length === 0) setDialog(null)
      const same = symbol ? result.trades.filter((trade) => trade.symbol === symbol) : []
      const pool = same.length ? same : result.trades
      const latest = [...pool].sort((a, b) => b.entry_time - a.entry_time)[0]
      if (latest) focusTrade(latest)
    } catch (error) {
      setTradeError(error instanceof Error ? error.message : 'Could not read that CSV')
    } finally {
      setTradeBusy(false)
    }
  }

  const visibleSymbols =
    truncated || !symbolQuery.trim()
      ? symbols
      : symbols.filter((item) => {
          const query = symbolQuery.trim().toLowerCase()
          return item.toLowerCase().includes(query) || (labels[item] ?? '').toLowerCase().includes(query)
        })
  const chartTrades = trades.filter((trade) => trade.symbol === symbol)
  const showList = listOpen

  return (
    <div className="app">
      <Toolbar
        datasets={meta?.datasets ?? []}
        dataset={dataset}
        onDataset={(id) => {
          setDataset(id)
          setSymbol(null)
          setSymbols([])
          setLabels({})
          setSymbolQuery('')
          setTruncated(false)
          setBars([])
        }}
        symbol={symbol}
        onFocusSearch={() => {
          setListOpen(true)
          setFocusToken((value) => value + 1)
        }}
        timeframe={timeframe}
        onTimeframe={setTimeframe}
        tool={tool}
        onTool={setTool}
        onIndicators={() => setDialog('indicators')}
        onTrades={() => setDialog('trades')}
        tradeCount={chartTrades.length}
        listOpen={listOpen}
        onToggleList={() => setListOpen((open) => !open)}
      />
      <div className="workspace">
        {showList && (
          <>
            <div className="list-slot" style={{ width: listWidth }}>
              <Watchlist
                symbols={visibleSymbols}
                labels={labels}
                active={symbol}
                query={symbolQuery}
                onQuery={setSymbolQuery}
                onSelect={(next) => {
                  setSymbol(next)
                  if (window.innerWidth <= 900) setListOpen(false)
                }}
                loading={symbolsLoading}
                error={symbolsError}
                truncated={truncated}
                focusToken={focusToken}
              />
            </div>
            <div className="splitter vertical" onPointerDown={dragList} role="separator" aria-orientation="vertical" />
          </>
        )}
        <div className="stage">
          <div className={`chart-stage${blotterMode === 'max' ? ' chart-stage-collapsed' : ''}`}>
            {bootError && <div className="db-error"><h2>OpenView is offline</h2><p>{bootError}</p></div>}
            {current && !current.ok && (
              <div className="db-error">
                <h2>{current.label} is unavailable</h2>
                <p>{current.error}</p>
                <p>
                  The chart requests one time window at a time. DuckDB and MotherDuck describe the tables and
                  answer that window. A CSV or Parquet file, or another candles API, uses the same request.
                  MotherDuck reads <code>MOTHERDUCK_TOKEN</code>.
                </p>
                {current.inspection.length > 0 && (
                  <ul>
                    {current.inspection.slice(0, 12).map((table) => (
                      <li key={`${table.schema}.${table.table}`}>
                        {table.schema}.{table.table}
                        <span> {table.columns.map((column) => column.name).join(', ')}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
            {current?.ok && (
              <ChartView
                bars={bars}
                timeframe={timeframe}
                symbol={symbol}
                indicators={indicators}
                trades={chartTrades}
                drawings={drawings}
                tool={tool}
                anchor={anchor}
                loading={loading}
                paging={paging}
                capped={bars.length >= MAX_BARS && hasMore}
                onNeedOlder={loadOlder}
                onNeedNewer={loadNewer}
                onViewportBars={onViewportBars}
                onJumpLatest={jumpLatest}
                onShowTrades={() => {
                  const pool = chartTrades.length ? chartTrades : trades
                  if (!pool.length) return
                  const first = bars[0]?.time
                  const last = bars[bars.length - 1]?.time
                  const inside =
                    first == null || last == null
                      ? []
                      : pool.filter((trade) => trade.entry_time >= first && trade.entry_time <= last)
                  const target = inside.at(-1) ?? [...pool].sort((a, b) => b.entry_time - a.entry_time)[0]
                  if (target) focusTrade(target)
                }}
                onRemoveIndicator={(id) => setIndicators((items) => items.filter((item) => item.id !== id))}
                onPlace={onPlace}
                onHoverTime={setHoverTime}
                draft={draft}
                onDraftCommit={(text) => {
                  if (!draft) return
                  updateDrawings([
                    ...drawings,
                    { id: uid(), kind: 'note', time: draft.time, price: draft.price, text, color: '#d1d4dc' },
                  ])
                  setDraft(null)
                }}
                onDraftCancel={() => setDraft(null)}
              />
            )}
            {candleError && <div className="toast">{candleError}</div>}
            {current?.ok && !loading && !found && symbol && (
              <div className="toast">No candles for {symbol}.</div>
            )}
          </div>
          {blotterMode === 'normal' && (
            <div className="splitter horizontal" onPointerDown={dragBlotter} role="separator" aria-orientation="horizontal" />
          )}
          <div
            className={`blotter-slot${blotterMode === 'max' ? ' max' : ''}`}
            style={blotterMode === 'normal' ? { height: blotterHeight } : undefined}
          >
            <Blotter
              trades={trades}
              symbol={symbol}
              symbolOnly={symbolOnly}
              onSymbolOnly={setSymbolOnly}
              hoverTime={hoverTime}
              onFocus={focusTrade}
              onClear={() => setTrades([])}
              mode={blotterMode}
              onMinimize={() => setBlotterMode((mode) => (mode === 'min' ? 'normal' : 'min'))}
              onMaximize={() => setBlotterMode((mode) => (mode === 'max' ? 'normal' : 'max'))}
            />
          </div>
          <footer className="statusbar">
            <span>{current?.label ?? 'No dataset'}</span>
            <span>{current?.table ?? ''}</span>
            <span>{current?.columns?.time_stored_as ?? ''}</span>
            <span>{bars.length ? `${bars.length.toLocaleString('en-IN')} bars` : ''}</span>
            <span>{paging === 'older' ? 'Loading history…' : paging === 'newer' ? 'Loading newer bars…' : ''}</span>
            <span className="status-right">Asia/Kolkata · session {meta?.session.open}–{meta?.session.close}</span>
          </footer>
        </div>
      </div>
      {dialog === 'indicators' && (
        <IndicatorDialog indicators={indicators} onChange={setIndicators} onClose={() => setDialog(null)} />
      )}
      {dialog === 'trades' && (
        <TradeDialog
          symbol={symbol}
          busy={tradeBusy}
          error={tradeError}
          rowErrors={rowErrors}
          onClose={() => setDialog(null)}
          onFile={onTradeFile}
        />
      )}
    </div>
  )
}
