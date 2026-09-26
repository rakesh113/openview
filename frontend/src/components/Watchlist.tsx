import { useEffect, useRef } from 'react'

type Props = {
  symbols: string[]
  labels: Record<string, string>
  active: string | null
  query: string
  onQuery: (value: string) => void
  onSelect: (symbol: string) => void
  loading: boolean
  error: string | null
  truncated: boolean
  focusToken: number
}

export function Watchlist({
  symbols,
  labels,
  active,
  query,
  onQuery,
  onSelect,
  loading,
  error,
  truncated,
  focusToken,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  useEffect(() => {
    if (focusToken > 0) inputRef.current?.focus()
  }, [focusToken])

  return (
    <aside className="watchlist">
      <label className="search">
        <input
          ref={inputRef}
          value={query}
          placeholder={truncated ? 'Search symbols' : 'Filter symbols'}
          onChange={(event) => onQuery(event.target.value)}
          aria-label="Search symbols"
        />
      </label>
      {error && <p className="watch-error">{error}</p>}
      {loading && <p className="watch-muted">Loading symbols…</p>}
      {!loading && truncated && !query && (
        <p className="watch-muted">Too many symbols to list. Type a name to search.</p>
      )}
      <ul>
        {symbols.map((symbol) => (
          <li key={symbol}>
            <button
              type="button"
              className={symbol === active ? 'active' : ''}
              onClick={() => onSelect(symbol)}
            >
              <span>{symbol}</span>
              {labels[symbol] ? <small>{labels[symbol]}</small> : null}
            </button>
          </li>
        ))}
      </ul>
      {!loading && symbols.length === 0 && !error && <p className="watch-muted">No symbols</p>}
    </aside>
  )
}
