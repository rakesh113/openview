import type {
  IChartApi,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  SeriesAttachedParameter,
  Time,
} from 'lightweight-charts'

export type TradeSegment = {
  entryTime: number
  entryPrice: number
  exitTime: number
  exitPrice: number
  color: string
}

export type NoteMark = {
  time: number
  price: number
  text: string
  color: string
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
      context.lineWidth = 1.25
      context.font = '12px Segoe UI, Trebuchet MS, sans-serif'
      for (const segment of this.source.segments) {
        const x1 = timeScale.timeToCoordinate(segment.entryTime as Time)
        const x2 = timeScale.timeToCoordinate(segment.exitTime as Time)
        const y1 = series.priceToCoordinate(segment.entryPrice)
        const y2 = series.priceToCoordinate(segment.exitPrice)
        if (x1 == null || x2 == null || y1 == null || y2 == null) continue
        context.strokeStyle = segment.color
        context.globalAlpha = 0.9
        context.beginPath()
        context.moveTo(x1, y1)
        context.lineTo(x2, y2)
        context.stroke()
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
  segments: TradeSegment[] = []
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

  setSegments(segments: TradeSegment[]): void {
    this.segments = segments
    this.requestUpdate()
  }

  setNotes(notes: NoteMark[]): void {
    this.notes = notes
    this.requestUpdate()
  }
}
