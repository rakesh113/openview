import type { DatasetMeta, Tool } from '../types'
import { TIMEFRAME_LABEL, TIMEFRAMES } from '../types'

type Props = {
  datasets: DatasetMeta[]
  dataset: string
  onDataset: (id: string) => void
  symbol: string | null
  onFocusSearch: () => void
  timeframe: string
  onTimeframe: (value: string) => void
  tool: Tool
  onTool: (tool: Tool) => void
  onIndicators: () => void
  onTrades: () => void
  tradeCount: number
  listOpen: boolean
  onToggleList: () => void
}

export function Toolbar(props: Props) {
  return (
    <header className="toolbar">
      <button type="button" className="icon-btn wordmark" onClick={props.onToggleList} title="Watchlist">
        <BarsIcon />
        <span>OpenView</span>
      </button>
      {props.datasets.length > 1 && (
        <select
          className="dataset"
          value={props.dataset}
          onChange={(event) => props.onDataset(event.target.value)}
          aria-label="Dataset"
        >
          {props.datasets.map((item) => (
            <option key={item.id} value={item.id}>
              {item.label}
              {item.ok ? '' : ' (unavailable)'}
            </option>
          ))}
        </select>
      )}
      <button type="button" className="symbol-btn" onClick={props.onFocusSearch}>
        <strong>{props.symbol ?? 'Symbol'}</strong>
        <span>NSE</span>
      </button>
      <div className="timeframes" role="tablist" aria-label="Timeframe">
        {TIMEFRAMES.map((value) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={props.timeframe === value}
            className={props.timeframe === value ? 'active' : ''}
            onClick={() => props.onTimeframe(value)}
          >
            {TIMEFRAME_LABEL[value]}
          </button>
        ))}
      </div>
      <div className="tool-group" role="toolbar" aria-label="Chart tools">
        <button
          type="button"
          className={props.tool === 'cursor' ? 'active' : ''}
          onClick={() => props.onTool('cursor')}
          title="Crosshair"
        >
          <CrosshairIcon />
        </button>
        <button
          type="button"
          className={props.tool === 'hline' ? 'active' : ''}
          onClick={() => props.onTool('hline')}
          title="Horizontal line"
        >
          <LineIcon />
        </button>
        <button
          type="button"
          className={props.tool === 'text' ? 'active' : ''}
          onClick={() => props.onTool('text')}
          title="Text note"
        >
          <TextIcon />
        </button>
      </div>
      <button type="button" className="text-btn" onClick={props.onIndicators}>
        Indicators
      </button>
      <button type="button" className="text-btn" onClick={props.onTrades}>
        Trades
        {props.tradeCount > 0 && <em>{props.tradeCount}</em>}
      </button>
      <span className={`list-toggle ${props.listOpen ? '' : 'off'}`} />
    </header>
  )
}

function BarsIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 7h16M4 12h16M4 17h16" />
    </svg>
  )
}
function CrosshairIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="6" />
      <path d="M12 2v4M12 18v4M2 12h4M18 12h4" />
    </svg>
  )
}
function LineIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 12h16" />
    </svg>
  )
}
function TextIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M6 6h12M12 6v12" />
    </svg>
  )
}
