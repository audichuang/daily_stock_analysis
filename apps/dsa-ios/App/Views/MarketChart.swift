import Charts
import DSACore
import SwiftUI

struct ChartCandle: Identifiable, Hashable {
    let date: Date
    let open: Double
    let high: Double
    let low: Double
    let close: Double
    let volume: Double?

    var id: Date { date }
}

struct MarketChart: View {
    let candles: [ChartCandle]
    let source: String?
    let asOf: String?
    let convention: MarketColorConvention

    @State private var interval: ChartInterval = .threeMonths
    @State private var style: ChartStyle = .candlestick
    @State private var selectedDate: Date?
    @ScaledMetric(relativeTo: .caption2) private var axisLabelWidth: CGFloat = 46

    init(
        candles: [ChartCandle],
        source: String? = nil,
        asOf: String? = nil,
        convention: MarketColorConvention = .taiwan
    ) {
        self.candles = candles
        self.source = source
        self.asOf = asOf
        self.convention = convention
    }

    private enum ChartInterval: Int, CaseIterable, Identifiable {
        case oneMonth = 1, threeMonths = 3, sixMonths = 6
        var id: Int { rawValue }
        var label: String { "\(rawValue)M" }
        var accessibilityLabel: String { "\(rawValue) 個月" }
    }

    private enum ChartStyle: String, CaseIterable, Identifiable {
        case candlestick = "日 K"
        case line = "收盤線"
        var id: String { rawValue }
    }

    private var visibleCandles: [ChartCandle] {
        let sorted = candles.sorted { $0.date < $1.date }
        guard let latest = sorted.last?.date,
              let cutoff = TradingDay.start(months: interval.rawValue, before: latest) else {
            return sorted
        }
        return sorted.filter { $0.date >= cutoff }
    }

    private var inspectedCandle: ChartCandle? {
        guard let selectedDate else { return visibleCandles.last }
        return visibleCandles.min {
            abs($0.date.timeIntervalSince(selectedDate)) < abs($1.date.timeIntervalSince(selectedDate))
        }
    }

    private var priceDomain: ClosedRange<Double> {
        let data = visibleCandles
        let lower = data.map(\.low).min() ?? 0
        let upper = data.map(\.high).max() ?? 1
        let margin = max((upper - lower) * 0.12, abs(upper) * 0.005, 0.01)
        return (lower - margin)...(upper + margin)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            ViewThatFits(in: .horizontal) {
                HStack {
                    SectionHeading("價格走勢", eyebrow: "MARKET STRUCTURE")
                    Spacer(minLength: 12)
                    stylePicker
                }
                VStack(alignment: .leading, spacing: 12) {
                    SectionHeading("價格走勢", eyebrow: "MARKET STRUCTURE")
                    stylePicker
                }
            }

            if let first = visibleCandles.first, let last = visibleCandles.last {
                let domain = TradingDay.candleBody(around: first.date).lowerBound...TradingDay.candleBody(around: last.date).upperBound
                intervalPicker
                if let candle = inspectedCandle {
                    candleReadout(candle)
                }
                priceChart
                    .chartXScale(domain: domain)
                    .frame(height: 210)
                volumeChart
                    .chartXScale(domain: domain)
                    .frame(height: 66)
                HStack(alignment: .top, spacing: 6) {
                    Image(systemName: "hand.draw")
                    Text("拖曳圖表查看每日價格與成交量")
                }
                .font(.caption2)
                .foregroundStyle(Theme.secondary)
            } else {
                EmptyStateView(title: "尚無日線資料", message: "目前沒有可顯示的行情，取得資料後才會繪製走勢。")
            }

            if source != nil || asOf != nil {
                VStack(alignment: .leading, spacing: 4) {
                    if let source { Text("行情資訊：\(source)") }
                    if let asOf { Text("資料時間：\(asOf)") }
                }
                .font(.caption2)
                .foregroundStyle(Theme.secondary)
                .textSelection(.enabled)
            }
        }
        .onChange(of: interval) { _, _ in selectedDate = nil }
        .environment(\.calendar, TradingDay.calendar)
        .environment(\.timeZone, TradingDay.timeZone)
    }

    private var stylePicker: some View {
        Picker("圖表樣式", selection: $style) {
            ForEach(ChartStyle.allCases) { style in
                Text(style.rawValue).tag(style)
            }
        }
        .pickerStyle(.segmented)
        .frame(minWidth: 130, maxWidth: 180, minHeight: 44)
        .accessibilityIdentifier("chart.style")
    }

    private var intervalPicker: some View {
        HStack(spacing: 8) {
            ForEach(ChartInterval.allCases) { option in
                Button {
                    interval = option
                } label: {
                    Text(option.label)
                        .font(.caption.weight(.bold))
                        .foregroundStyle(interval == option ? Theme.background : Theme.secondary)
                        .frame(maxWidth: .infinity, minHeight: 44)
                        .background(interval == option ? Theme.accent : Theme.elevated, in: RoundedRectangle(cornerRadius: 12))
                }
                .buttonStyle(.plain)
                .accessibilityLabel(option.accessibilityLabel)
                .accessibilityAddTraits(interval == option ? .isSelected : [])
                .accessibilityIdentifier("chart.range.\(option.rawValue)")
            }
        }
    }

    private func candleReadout(_ candle: ChartCandle) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text(candle.date, format: TradingDay.readoutStyle())
                    .font(.caption.weight(.medium))
                    .foregroundStyle(Theme.text)
                Spacer()
                Text(selectedDate == nil ? "最新日線" : "選取日線")
                    .font(.caption2)
                    .foregroundStyle(Theme.secondary)
            }
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], alignment: .leading, spacing: 10) {
                MetricView("開盤", value: price(candle.open))
                MetricView("收盤", value: price(candle.close), tint: Theme.changeColor(candle.close - candle.open, convention: convention))
                MetricView("最高", value: price(candle.high))
                MetricView("最低", value: price(candle.low))
            }
        }
        .padding(14)
        .background(Theme.background.opacity(0.5), in: RoundedRectangle(cornerRadius: 14))
        .accessibilityIdentifier("chart.readout")
    }

    private var priceChart: some View {
        Chart {
            ForEach(visibleCandles) { candle in
                if style == .candlestick {
                    let body = TradingDay.candleBody(around: candle.date)
                    RuleMark(
                        x: .value("日期", candle.date),
                        yStart: .value("最低", candle.low),
                        yEnd: .value("最高", candle.high)
                    )
                    .foregroundStyle(Theme.changeColor(candle.close - candle.open, convention: convention))
                    .lineStyle(StrokeStyle(lineWidth: 1))

                    if candle.open == candle.close {
                        RuleMark(
                            xStart: .value("起點", body.lowerBound),
                            xEnd: .value("終點", body.upperBound),
                            y: .value("開收盤", candle.close)
                        )
                        .foregroundStyle(Theme.secondary)
                    } else {
                        RectangleMark(
                            xStart: .value("起點", body.lowerBound),
                            xEnd: .value("終點", body.upperBound),
                            yStart: .value("開盤", min(candle.open, candle.close)),
                            yEnd: .value("收盤", max(candle.open, candle.close))
                        )
                        .foregroundStyle(Theme.changeColor(candle.close - candle.open, convention: convention))
                    }
                } else {
                    LineMark(x: .value("日期", candle.date), y: .value("收盤", candle.close))
                        .foregroundStyle(Theme.accent)
                        .lineStyle(StrokeStyle(lineWidth: 2))
                }
            }
            if selectedDate != nil, let inspectedCandle {
                RuleMark(x: .value("選取日期", inspectedCandle.date))
                    .foregroundStyle(Theme.text.opacity(0.6))
                    .lineStyle(StrokeStyle(lineWidth: 1, dash: [4, 4]))
                PointMark(x: .value("選取日期", inspectedCandle.date), y: .value("收盤", inspectedCandle.close))
                    .foregroundStyle(Theme.accent)
                    .symbolSize(32)
            }
        }
        .chartYScale(domain: priceDomain)
        .chartXSelection(value: $selectedDate)
        .chartXAxis {
            AxisMarks(values: .automatic(desiredCount: 4)) { _ in
                AxisValueLabel(format: TradingDay.axisStyle()).foregroundStyle(Theme.secondary)
            }
        }
        .chartYAxis {
            AxisMarks(position: .trailing, values: .automatic(desiredCount: 4)) { value in
                AxisGridLine(stroke: StrokeStyle(lineWidth: 0.5, dash: [3, 3])).foregroundStyle(Theme.border)
                AxisValueLabel {
                    if let number = value.as(Double.self) {
                        axisLabel(number.formatted(.number.precision(.fractionLength(0...2))))
                    }
                }
            }
        }
        .accessibilityLabel(style == .candlestick ? "每日 K 線圖" : "每日收盤價走勢圖")
        .accessibilityIdentifier("chart.price")
    }

    private var volumeChart: some View {
        Chart(visibleCandles) { candle in
            if let volume = candle.volume {
                let body = TradingDay.candleBody(around: candle.date)
                RectangleMark(
                    xStart: .value("起點", body.lowerBound),
                    xEnd: .value("終點", body.upperBound),
                    yStart: .value("基準", 0),
                    yEnd: .value("成交量", volume)
                )
                    .foregroundStyle(Theme.changeColor(candle.close - candle.open, convention: convention).opacity(0.5))
            }
        }
        .chartXAxis(.hidden)
        .chartYAxis {
            AxisMarks(position: .trailing, values: .automatic(desiredCount: 2)) { value in
                AxisValueLabel {
                    if let number = value.as(Double.self) {
                        axisLabel(number.formatted(.number.notation(.compactName)))
                    }
                }
            }
        }
        .overlay(alignment: .topLeading) {
            if let candle = inspectedCandle {
                Text("日 K 成交量 \(candle.volume.map { $0.formatted(.number.notation(.compactName)) } ?? "未提供")")
                    .font(.caption2.monospacedDigit())
                    .foregroundStyle(Theme.secondary)
                    .padding(.bottom, 4)
                    .background(Theme.surface.opacity(0.85))
            }
        }
        .accessibilityLabel("每日成交量")
        .accessibilityIdentifier("chart.volume")
    }

    private func price(_ value: Double) -> String {
        value.formatted(.number.precision(.fractionLength(0...2)))
    }

    private func axisLabel(_ text: String) -> some View {
        Text(text).font(.caption2).foregroundStyle(Theme.secondary)
            .lineLimit(1).minimumScaleFactor(0.6)
            .frame(width: axisLabelWidth, alignment: .leading)
    }
}
