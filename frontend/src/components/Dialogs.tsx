import { useEffect, useState } from 'react'
import type { Indicator, IndicatorType } from '../types'

const CATALOG: { type: IndicatorType; name: string; blurb: string }[] = [
  { type: 'sma', name: 'SMA', blurb: 'Simple moving average on close' },
  { type: 'ema', name: 'EMA', blurb: 'Exponential moving average on close' },
  { type: 'bb', name: 'Bollinger Bands', blurb: 'Moving average and standard deviation bands' },
  { type: 'vwap', name: 'VWAP', blurb: 'Session volume-weighted average, reset each IST day' },
  { type: 'volume', name: 'Volume', blurb: 'Volume pane' },
  { type: 'rsi', name: 'RSI', blurb: 'Relative strength, separate pane' },
  { type: 'macd', name: 'MACD', blurb: 'MACD line, signal, and histogram' },
  { type: 'atr', name: 'ATR', blurb: 'Average true range, separate pane' },
]

const COLORS = ['#f5c451', '#42a5f5', '#b39ddb', '#26a69a', '#ef9a9a', '#80cbc4', '#ffab91', '#ce93d8']

export function IndicatorDialog({
  indicators,
  onChange,
  onClose,
}: {
  indicators: Indicator[]
  onChange: (next: Indicator[]) => void
  onClose: () => void
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  function add(type: IndicatorType) {
    if (type === 'volume' && indicators.some((item) => item.type === 'volume')) return
    if (type === 'vwap' && indicators.some((item) => item.type === 'vwap')) return
    const color = COLORS[indicators.length % COLORS.length]
    onChange([
      ...indicators,
      {
        id: `${type}-${Date.now().toString(36)}`,
        type,
        period: type === 'rsi' || type === 'atr' ? 14 : 20,
        fast: 12,
        slow: 26,
        signal: 9,
        mult: 2,
        color,
      },
    ])
  }

  function patch(id: string, partial: Partial<Indicator>) {
    onChange(indicators.map((item) => (item.id === id ? { ...item, ...partial } : item)))
  }

  return (
    <div className="modal-back" onMouseDown={onClose}>
      <div className="modal" onMouseDown={(event) => event.stopPropagation()} role="dialog" aria-label="Indicators">
        <header>
          <h2>Indicators</h2>
          <button type="button" onClick={onClose} aria-label="Close">
            ×
          </button>
        </header>
        <div className="modal-body indicators">
          <ul className="catalog">
            {CATALOG.map((item) => (
              <li key={item.type}>
                <button type="button" onClick={() => add(item.type)}>
                  <strong>{item.name}</strong>
                  <span>{item.blurb}</span>
                </button>
              </li>
            ))}
          </ul>
          <div className="active-inds">
            {indicators.length === 0 && <p className="watch-muted">Nothing on the chart yet.</p>}
            {indicators.map((item) => (
              <div key={item.id} className="ind-row">
                <span className="swatch" style={{ background: item.color }} />
                <strong>{item.type.toUpperCase()}</strong>
                {item.type !== 'vwap' && item.type !== 'volume' && item.type !== 'macd' && (
                  <label>
                    Length
                    <input
                      type="number"
                      min={1}
                      max={500}
                      value={item.period}
                      onChange={(event) => patch(item.id, { period: clamp(event.target.value, 1, 500) })}
                    />
                  </label>
                )}
                {item.type === 'bb' && (
                  <label>
                    Stdev
                    <input
                      type="number"
                      min={0.1}
                      max={5}
                      step={0.1}
                      value={item.mult}
                      onChange={(event) => patch(item.id, { mult: clamp(event.target.value, 0.1, 5) })}
                    />
                  </label>
                )}
                {item.type === 'macd' && (
                  <>
                    <label>
                      Fast
                      <input
                        type="number"
                        min={2}
                        max={100}
                        value={item.fast}
                        onChange={(event) => patch(item.id, { fast: clamp(event.target.value, 2, 100) })}
                      />
                    </label>
                    <label>
                      Slow
                      <input
                        type="number"
                        min={3}
                        max={200}
                        value={item.slow}
                        onChange={(event) => patch(item.id, { slow: clamp(event.target.value, 3, 200) })}
                      />
                    </label>
                    <label>
                      Signal
                      <input
                        type="number"
                        min={2}
                        max={100}
                        value={item.signal}
                        onChange={(event) => patch(item.id, { signal: clamp(event.target.value, 2, 100) })}
                      />
                    </label>
                  </>
                )}
                <label>
                  Color
                  <input type="color" value={toHex(item.color)} onChange={(event) => patch(item.id, { color: event.target.value })} />
                </label>
                <button type="button" onClick={() => onChange(indicators.filter((other) => other.id !== item.id))}>
                  Remove
                </button>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

function clamp(value: string, min: number, max: number): number {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return min
  return Math.min(max, Math.max(min, parsed))
}

function toHex(color: string): string {
  return /^#[0-9a-fA-F]{6}$/.test(color) ? color : '#f5c451'
}

export function TradeDialog({
  symbol,
  busy,
  error,
  rowErrors,
  onClose,
  onFile,
}: {
  symbol: string | null
  busy: boolean
  error: string | null
  rowErrors: string[]
  onClose: () => void
  onFile: (file: File, assignSymbol: boolean) => void
}) {
  const [assign, setAssign] = useState(true)
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="modal-back" onMouseDown={onClose}>
      <div className="modal" onMouseDown={(event) => event.stopPropagation()} role="dialog" aria-label="Load trades">
        <header>
          <h2>Backtest trades</h2>
          <button type="button" onClick={onClose} aria-label="Close">
            ×
          </button>
        </header>
        <div className="modal-body trades-help">
          <p>
            One row is one round trip. Required columns are <code>symbol</code>, <code>side</code>,{' '}
            <code>entry_time</code>, and <code>entry_price</code>. Optional: <code>exit_time</code>,{' '}
            <code>exit_price</code>, <code>quantity</code>, <code>pnl</code>, <code>tag</code>.
          </p>
          <p>
            Times are ISO-8601. A value without a timezone is read as Asia/Kolkata. Each long is drawn in green and
            each short in red, with the entry and exit on the candles and the result shaded between the two prices.{' '}
            <code>long</code>/<code>short</code> and <code>buy</code>/<code>sell</code> both work. Logs that already use{' '}
            <code>Type</code>,{' '}
            <code>Entry Time</code>, <code>Entry Price</code>, <code>Exit Time</code>, <code>Exit Price</code>,{' '}
            <code>PnL</code>, and <code>Reason</code> load as-is.
          </p>
          <pre>{`symbol,side,entry_time,entry_price,exit_time,exit_price,quantity,pnl,tag
RELIANCE,long,2024-01-15T09:45:00+05:30,2488.50,2024-01-15T11:15:00+05:30,2506.20,100,1770,orb`}</pre>
          <label className="check">
            <input type="checkbox" checked={assign} onChange={(event) => setAssign(event.target.checked)} />
            If a row has no symbol, use {symbol ?? 'the chart symbol'}
          </label>
          <label
            className="drop"
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => {
              event.preventDefault()
              const file = event.dataTransfer.files?.[0]
              if (file) onFile(file, assign)
            }}
          >
            <input
              type="file"
              accept=".csv,text/csv"
              onChange={(event) => {
                const file = event.target.files?.[0]
                if (file) onFile(file, assign)
              }}
            />
            {busy ? 'Reading…' : 'Drop a CSV here or click to browse'}
          </label>
          {error && <p className="watch-error">{error}</p>}
          {rowErrors.length > 0 && (
            <ul className="row-errors">
              {rowErrors.slice(0, 8).map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}
