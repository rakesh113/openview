import { formatClock, formatPrice } from '../lib/format'
import type { Trade } from '../types'

type Props = {
  trades: Trade[]
  symbol: string | null
  symbolOnly: boolean
  onSymbolOnly: (value: boolean) => void
  hoverTime: number | null
  onFocus: (trade: Trade) => void
  onClear: () => void
}

function pnlOf(trade: Trade): number | null {
  if (trade.pnl != null) return trade.pnl
  if (trade.exit_price == null) return null
  const qty = trade.quantity ?? 1
  return trade.side === 'long'
    ? (trade.exit_price - trade.entry_price) * qty
    : (trade.entry_price - trade.exit_price) * qty
}

export function Blotter(props: Props) {
  const rows = props.symbolOnly && props.symbol
    ? props.trades.filter((trade) => trade.symbol === props.symbol)
    : props.trades
  return (
    <section className="blotter">
      <div className="blotter-bar">
        <strong>Trades</strong>
        <span>{rows.length}</span>
        <label>
          <input
            type="checkbox"
            checked={props.symbolOnly}
            onChange={(event) => props.onSymbolOnly(event.target.checked)}
          />
          This symbol
        </label>
        <button type="button" onClick={props.onClear} disabled={props.trades.length === 0}>
          Clear
        </button>
      </div>
      {rows.length === 0 ? (
        <p className="blotter-empty">Load a backtest CSV to mark entries and exits on the chart.</p>
      ) : (
        <div className="blotter-scroll">
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Side</th>
                <th>Entry</th>
                <th>Price</th>
                <th>Exit</th>
                <th>Price</th>
                <th>Qty</th>
                <th>PnL</th>
                <th>Tag</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((trade, index) => {
                const pnl = pnlOf(trade)
                const active =
                  props.hoverTime != null &&
                  props.hoverTime >= trade.entry_time &&
                  (trade.exit_time == null || props.hoverTime <= trade.exit_time)
                return (
                  <tr
                    key={`${trade.symbol}-${trade.entry_time}-${index}`}
                    className={active ? 'active' : ''}
                    onClick={() => props.onFocus(trade)}
                  >
                    <td>{trade.symbol}</td>
                    <td className={trade.side === 'long' ? 'up' : 'down'}>{trade.side}</td>
                    <td>{formatClock(trade.entry_time)}</td>
                    <td>{formatPrice(trade.entry_price)}</td>
                    <td>{trade.exit_time ? formatClock(trade.exit_time) : 'open'}</td>
                    <td>{trade.exit_price == null ? '—' : formatPrice(trade.exit_price)}</td>
                    <td>{trade.quantity ?? '—'}</td>
                    <td className={pnl == null ? '' : pnl >= 0 ? 'up' : 'down'}>
                      {pnl == null ? '—' : formatPrice(pnl)}
                    </td>
                    <td>{trade.tag ?? ''}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
