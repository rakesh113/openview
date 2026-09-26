import assert from 'node:assert/strict'
import { placeTrades } from './tradeMarks.ts'
import type { Bar, Trade } from '../types.ts'

function bars(start: number, count: number, step = 300): Bar[] {
  return Array.from({ length: count }, (_, index) => {
    const time = start + index * step
    return { time, open: 100, high: 101, low: 99, close: 100, volume: 1 }
  })
}

function trade(partial: Partial<Trade> & Pick<Trade, 'side' | 'entry_time' | 'entry_price'>): Trade {
  return {
    symbol: 'RELIANCE',
    exit_time: null,
    exit_price: null,
    quantity: 1,
    pnl: null,
    tag: null,
    ...partial,
  }
}

const start = 1_718_688_300 // 2024-06-18 09:15 IST

const loaded = bars(start, 6)
const long = trade({
  side: 'long',
  entry_time: start + 300,
  entry_price: 100,
  exit_time: start + 900,
  exit_price: 102,
  pnl: 200,
})
const placed = placeTrades([long], loaded, '5m')
assert.equal(placed.length, 1)
assert.equal(placed[0].entryText, 'Long')
assert.equal(placed[0].exitText, '+200')
assert.equal(placed[0].entryVisible, true)
assert.equal(placed[0].exitVisible, true)
assert.equal(placed[0].color, '#089981')
assert.equal(placed[0].entryTime, start + 300)

const elsewhere = trade({
  side: 'short',
  entry_time: start + 86400 * 30,
  entry_price: 50,
  exit_time: start + 86400 * 30 + 600,
  exit_price: 40,
  pnl: -10,
})
assert.equal(placeTrades([elsewhere], loaded, '5m').length, 0)

const continuing = trade({
  side: 'short',
  entry_time: start - 86400,
  entry_price: 110,
  exit_time: start + 600,
  exit_price: 108,
  pnl: 100,
})
const held = placeTrades([continuing], loaded, '5m')
assert.equal(held.length, 1)
assert.equal(held[0].entryVisible, false)
assert.equal(held[0].entryTime, start)
assert.equal(held[0].exitVisible, true)
assert.equal(held[0].entryText, 'Short')

const stillOpen = trade({
  side: 'long',
  entry_time: start + 300,
  entry_price: 100,
})
const openMark = placeTrades([stillOpen], loaded, '5m')
assert.equal(openMark.length, 1)
assert.equal(openMark[0].open, true)
assert.equal(openMark[0].exitVisible, false)
assert.equal(openMark[0].spanEnd, loaded[loaded.length - 1].time)
assert.equal(openMark[0].color, '#2962ff')

console.log('trade marks ok')
