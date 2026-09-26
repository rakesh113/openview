import type {
  IChartApi,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  SeriesAttachedParameter,
  Time,
} from 'lightweight-charts'

import type { PlacedTrade } from './tradeMarks'

export type NoteMark = {
  time: number
  price: number
  text: string
  color: string
}

function xFor(timeScale: ReturnType<IChartApi['timeScale']>, time: number): number | null {
  const direct = timeScale.timeToCoordinate(time as Time)
  if (direct != null) return direct
  const index = timeScale.timeToIndex(time as Time, true)
  if (index == null) return null
  return timeScale.logicalToCoordinate(index as never)
}

function drawArrow(context: CanvasRenderingContext2D, x: number, y: number, up: boolean, color: string) {
  const height = 16
  const half = 7
  context.save()
  context.fillStyle = color
  context.strokeStyle = '#131722'
  context.lineWidth = 1.5
  context.beginPath()
  if (up) {
    context.moveTo(x, y - 1)
    context.lineTo(x - half, y + height)
    context.lineTo(x + half, y + height)
  } else {
    context.moveTo(x, y + 1)
    context.lineTo(x - half, y - height)
    context.lineTo(x + half, y - height)
  }
  context.closePath()
  context.fill()
  context.stroke()
  context.restore()
}

function drawTag(
  context: CanvasRenderingContext2D,
  x: number,
  y: number,
  text: string,
  color: string,
  below: boolean,
) {
  const padX = 6
  const width = Math.ceil(context.measureText(text).width + padX * 2)
  const height = 18
  const top = below ? y : y - height
  context.save()
  context.fillStyle = 'rgba(19, 23, 34, 0.94)'
  context.strokeStyle = color
  context.lineWidth = 1
  context.beginPath()
  context.roundRect(x, top, width, height, 3)
  context.fill()
  context.stroke()
  context.fillStyle = color
  context.textAlign = 'left'
  context.textBaseline = 'middle'
  context.fillText(text, x + padX, top + height / 2)
  context.restore()
}

class OverlayRenderer implements IPrimitivePaneRenderer {
  constructor(private readonly source: ChartOverlay) {}

  draw(target: { useMediaCoordinateSpace: (fn: (scope: { context: CanvasRenderingContext2D }) => void) => void }): void {
    const chart = this.source.chart
    const series = this.source.series
    if (!chart || !series) return
    const timeScale = chart.timeScale()
    target.useMediaCoordinateSpace(({ context }) => {
      context.save()
      context.lineWidth = 1.5
      context.font = '600 12px Segoe UI, Trebuchet MS, sans-serif'
      for (const trade of this.source.trades) {
        const x1 = xFor(timeScale, trade.entryTime)
        const x2 = xFor(timeScale, trade.spanEnd)
        const yEntry = series.priceToCoordinate(trade.entryPrice)
        const yExit = trade.exitPrice == null ? null : series.priceToCoordinate(trade.exitPrice)
        if (x1 == null || x2 == null || yEntry == null) continue
        const left = Math.min(x1, x2)
        const right = Math.max(x1, x2)
        const width = Math.max(right - left, 2)
        const long = trade.side === 'long'
        context.strokeStyle = trade.color
        context.fillStyle = trade.color
        if (yExit != null) {
          const top = Math.min(yEntry, yExit)
          const height = Math.max(Math.abs(yExit - yEntry), 10)
          const boxTop = Math.abs(yExit - yEntry) < 10 ? yEntry - 5 : top
          context.globalAlpha = 0.22
          context.fillRect(left, boxTop, width, height)
          context.globalAlpha = 1
          context.strokeRect(left + 0.5, boxTop + 0.5, width, height)
        } else {
          context.setLineDash([5, 4])
          context.beginPath()
          context.moveTo(left, yEntry)
          context.lineTo(right, yEntry)
          context.stroke()
          context.setLineDash([])
        }
        if (trade.entryVisible) {
          drawArrow(context, x1, yEntry, long, long ? '#089981' : '#f23645')
          drawTag(context, x1 + 10, yEntry + (long ? 16 : -16), trade.entryText, long ? '#089981' : '#f23645', long)
        } else {
          drawTag(context, left + 8, yEntry, `${trade.entryText} from earlier`, long ? '#089981' : '#f23645', false)
        }
        if (trade.exitVisible && trade.exitTime != null && yExit != null) {
          const exitX = xFor(timeScale, trade.exitTime) ?? x2
          drawArrow(context, exitX, yExit, !long, trade.color)
          drawTag(context, exitX + 10, yExit + (long ? -16 : 16), trade.exitText, trade.color, !long)
        }
      }
      context.globalAlpha = 1
      for (const note of this.source.notes) {
        const x = timeScale.timeToCoordinate(note.time as Time)
        const y = series.priceToCoordinate(note.price)
        if (x == null || y == null) continue
        const padX = 6
        const width = Math.min(220, context.measureText(note.text).width + padX * 2)
        const height = 18
        const left = x + 8
        const top = y - height - 8
        context.fillStyle = 'rgba(19, 23, 34, 0.92)'
        context.strokeStyle = note.color
        context.beginPath()
        context.roundRect(left, top, width, height, 3)
        context.fill()
        context.stroke()
        context.fillStyle = '#d1d4dc'
        context.textBaseline = 'middle'
        context.fillText(note.text, left + padX, top + height / 2, width - padX * 2)
      }
      context.restore()
    })
  }
}

export class ChartOverlay implements ISeriesPrimitive<Time> {
  chart: IChartApi | null = null
  series: ISeriesApi<'Candlestick'> | null = null
  trades: PlacedTrade[] = []
  notes: NoteMark[] = []
  private requestUpdate: () => void = () => {}
  private readonly renderer = new OverlayRenderer(this)
  private readonly views: readonly IPrimitivePaneView[] = [
    {
      zOrder: () => 'top',
      renderer: () => this.renderer,
    },
  ]

  attached(param: SeriesAttachedParameter<Time, 'Candlestick'>): void {
    this.chart = param.chart as IChartApi
    this.series = param.series as ISeriesApi<'Candlestick'>
    this.requestUpdate = param.requestUpdate
  }

  detached(): void {
    this.chart = null
    this.series = null
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return this.views
  }

  setTrades(trades: PlacedTrade[]): void {
    this.trades = trades
    this.requestUpdate()
  }

  setNotes(notes: NoteMark[]): void {
    this.notes = notes
    this.requestUpdate()
  }
}
