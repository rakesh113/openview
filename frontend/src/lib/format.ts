import { TickMarkType } from 'lightweight-charts'

const priceFormat = new Intl.NumberFormat('en-IN', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

const signedPrice = new Intl.NumberFormat('en-IN', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
  signDisplay: 'exceptZero',
})

export function formatPrice(value: number): string {
  return priceFormat.format(value)
}

export function formatChange(value: number): string {
  return signedPrice.format(value)
}

export function formatVolume(value: number): string {
  const abs = Math.abs(value)
  const sign = value < 0 ? '-' : ''
  if (abs >= 1e7) return `${sign}${(abs / 1e7).toFixed(2)} Cr`
  if (abs >= 1e5) return `${sign}${(abs / 1e5).toFixed(2)} L`
  if (abs >= 1e3) return `${sign}${(abs / 1e3).toFixed(1)} K`
  return `${Math.round(value)}`
}

function parts(time: number) {
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Kolkata',
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(new Date(time * 1000))
}

function part(list: Intl.DateTimeFormatPart[], type: string): string {
  return list.find((item) => item.type === type)?.value ?? ''
}

export function formatTick(time: number, type: TickMarkType, timeframe: string): string {
  const daily = timeframe === '1d' || timeframe === '1w'
  const list = parts(time)
  if (type === TickMarkType.Year) return part(list, 'year')
  if (type === TickMarkType.Month) return part(list, 'month')
  if (type === TickMarkType.DayOfMonth || daily) return `${part(list, 'day')} ${part(list, 'month')}`
  return `${part(list, 'hour')}:${part(list, 'minute')}`
}

export function formatWhen(time: number, timeframe: string): string {
  const daily = timeframe === '1d' || timeframe === '1w'
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Kolkata',
    day: '2-digit',
    month: 'short',
    year: '2-digit',
    hour: daily ? undefined : '2-digit',
    minute: daily ? undefined : '2-digit',
    hour12: false,
  }).format(new Date(time * 1000))
}

export function formatClock(time: number): string {
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Kolkata',
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(time * 1000))
}
