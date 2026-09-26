import { bollinger, ema, rsi, sma, vwap } from './indicators.ts'
import assert from 'node:assert/strict'

const closes = [1, 2, 3, 4, 5, 6]
assert.deepEqual(sma(closes, 3), [null, null, 2, 3, 4, 5])

const averages = ema([1, 2, 3, 4], 2)
assert.equal(averages[1], 1.5)
assert.ok((averages[3] as number) > (averages[2] as number))

const rising = Array.from({ length: 30 }, (_, i) => 100 + i)
const strength = rsi(rising, 14)
assert.equal(strength[14], 100)

const bands = bollinger([1, 2, 3, 4, 5], 3, 2)
assert.equal(bands.mid[2], 2)
assert.ok((bands.upper[2] as number) > 2)
assert.ok((bands.lower[2] as number) < 2)

const day = 1_704_220_200 // 2024-01-03 00:00 IST-ish anchor; values only need a shared day
const bars = [0, 1].map((i) => ({
  time: day + i * 60,
  open: 10,
  high: 12,
  low: 8,
  close: 10,
  volume: 10,
}))
const session = vwap(bars)
assert.equal(session[0], 10)
assert.equal(session[1], 10)

console.log('indicators ok')
