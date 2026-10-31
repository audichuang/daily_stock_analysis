import Charts
import DSACore
import SwiftUI

struct MarketChart: View {
    let candles: [ChartCandle]
    let source: String?
    let asOf: String?
    let convention: MarketColorConvention

    @State private var interval: ChartInterval = .threeMonths
    @State private var period: CandlePeriod = .day
    @State private var style: ChartStyle = .candlestick
    @State private var hiddenAverages: Set<Int> = []
    @State private var selectedDate: Date?
    @State private var showingGuide = false
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
        case oneMonth = 1, threeMonths = 3, sixMonths = 6, oneYear = 12, threeYears = 36, fiveYears = 60
        var id: Int { rawValue }
        var label: String { rawValue < 12 ? "\(rawValue)M" : "\(rawValue / 12)Y" }
        var accessibilityLabel: String { rawValue < 12 ? "\(rawValue) 個月" : "\(rawValue / 12) 年" }

        /// 切換區間時順手換成看得清楚的 K 棒週期：一年塞兩百多根日 K 會擠成細線。
        var suggestedPeriod: CandlePeriod {
            switch self {
            case .oneMonth, .threeMonths, .sixMonths: .day
            case .oneYear, .threeYears: .week
            case .fiveYears: .month
            }
        }
    }

    private enum ChartStyle: String, CaseIterable, Identifiable {
        case candlestick = "K 線"
        case line = "收盤線"
        var id: String { rawValue }
    }

    private struct AverageLine: Identifiable {
        let slot: Int
        let window: Int
        let points: [MovingAveragePoint]
        var id: Int { slot }
        var name: String { "MA\(window)" }
        var color: Color { MarketChart.averageColors[slot % MarketChart.averageColors.count] }
    }

    // 避開漲跌用的紅綠，免得均線被看成某一根 K 棒的顏色。
    static let averageColors: [Color] = [Theme.warning, Theme.information, Color(red: 0.78, green: 0.56, blue: 1.0)]

    private var periodCandles: [ChartCandle] {
        CandleSeries.aggregate(candles, period: period)
    }

    private func visible(_ series: [ChartCandle]) -> [ChartCandle] {
        guard let latest = series.last?.date,
              let cutoff = TradingDay.start(months: interval.rawValue, before: latest) else {
            return series
        }
        return series.filter { $0.date >= cutoff }
    }

    /// 均線在完整序列上算，再裁到可見區間，左緣才不會因為少了前段資料而缺線或偏移。
    private func averages(full: [ChartCandle], visible: [ChartCandle]) -> [AverageLine] {
        guard let start = visible.first?.date else { return [] }
        return period.movingAverageWindows.enumerated().map { slot, window in
            AverageLine(slot: slot, window: window,
                        points: CandleSeries.movingAverage(full, window: window).filter { $0.date >= start })
        }
    }

    private func inspected(in data: [ChartCandle]) -> ChartCandle? {
        guard let selectedDate else { return data.last }
        return data.min {
            abs($0.date.timeIntervalSince(selectedDate)) < abs($1.date.timeIntervalSince(selectedDate))
        }
    }

    private func priceDomain(_ data: [ChartCandle], lines: [AverageLine]) -> ClosedRange<Double> {
        let averageValues = lines.filter { !hiddenAverages.contains($0.slot) }.flatMap { $0.points.map(\.value) }
        let lower = (data.map(\.low) + averageValues).min() ?? 0
        let upper = (data.map(\.high) + averageValues).max() ?? 1
        let margin = max((upper - lower) * 0.12, abs(upper) * 0.005, 0.01)
        return (lower - margin)...(upper + margin)
    }

    var body: some View {
        let full = periodCandles
        let data = visible(full)
        let lines = averages(full: full, visible: data)
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

            if let first = data.first, let last = data.last {
                let start = TradingDay.candleBody(around: first.date, spanDays: period.spanDays).lowerBound
                let end = TradingDay.candleBody(around: last.date, spanDays: period.spanDays).upperBound
                let domain = start...end
                intervalPicker
                periodRow
                if let candle = inspected(in: data) {
                    candleReadout(candle, lines: lines)
                }
                priceChart(data, lines: lines)
                    .chartXScale(domain: domain)
                    .frame(height: 230)
                averageLegend(lines)
                volumeChart(data)
                    .chartXScale(domain: domain)
                    .frame(height: 66)
                HStack(alignment: .top, spacing: 6) {
                    Image(systemName: "hand.draw")
                    Text("拖曳圖表查看每根 K 棒的價格、均線與成交量")
                }
                .font(.caption2)
                .foregroundStyle(Theme.secondary)
                let months = historyMonths(full)
                if months < interval.rawValue - 1 {
                    Text("這檔目前只有約 \(months >= 12 ? "\(months / 12) 年 \(months % 12) 個月" : "\(months) 個月")的資料，已顯示全部。")
                        .font(.caption2)
                        .foregroundStyle(Theme.warning)
                }
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
        .onChange(of: interval) { _, newValue in
            selectedDate = nil
            period = newValue.suggestedPeriod
        }
        .onChange(of: period) { _, _ in selectedDate = nil }
        .sheet(isPresented: $showingGuide) {
            KLineGuideView(convention: convention)
        }
        .environment(\.calendar, TradingDay.calendar)
        .environment(\.timeZone, TradingDay.timeZone)
    }

    private func historyMonths(_ series: [ChartCandle]) -> Int {
        guard let first = series.first?.periodStart, let last = series.last?.date else { return 0 }
        return TradingDay.calendar.dateComponents([.month], from: first, to: last).month ?? 0
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
        HStack(spacing: 6) {
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

    private var periodRow: some View {
        HStack(spacing: 10) {
            Picker("K 棒週期", selection: $period) {
                ForEach(CandlePeriod.allCases) { option in
                    Text(option.label).tag(option)
                }
            }
            .pickerStyle(.segmented)
            .frame(minHeight: 44)
            .accessibilityIdentifier("chart.period")
            Button {
                showingGuide = true
            } label: {
                Label("看懂 K 線", systemImage: "questionmark.circle")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(Theme.accent)
                    .frame(minHeight: 44)
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("chart.guide")
        }
    }

    private func candleReadout(_ candle: ChartCandle, lines: [AverageLine]) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Group {
                    if candle.periodStart == candle.date {
                        Text(candle.date, format: TradingDay.readoutStyle())
                    } else {
                        Text("\(candle.periodStart.formatted(TradingDay.readoutStyle())) – \(candle.date.formatted(TradingDay.axisStyle()))")
                    }
                }
                .font(.caption.weight(.medium))
                .foregroundStyle(Theme.text)
                Spacer()
                Text("\(selectedDate == nil ? "最新" : "選取")\(period.label)")
                    .font(.caption2)
                    .foregroundStyle(Theme.secondary)
            }
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], alignment: .leading, spacing: 10) {
                MetricView("開盤", value: price(candle.open))
                MetricView("收盤", value: price(candle.close), tint: Theme.changeColor(candle.close - candle.open, convention: convention))
                MetricView("最高", value: price(candle.high))
                MetricView("最低", value: price(candle.low))
            }
            HStack(spacing: 12) {
                ForEach(lines) { line in
                    let value = line.points.first { $0.date == candle.date }?.value
                    Text("\(line.name) \(value.map(price) ?? "—")")
                        .font(.caption2.monospacedDigit())
                        .foregroundStyle(line.color)
                }
            }
        }
        .padding(14)
        .background(Theme.background.opacity(0.5), in: RoundedRectangle(cornerRadius: 14))
        .accessibilityIdentifier("chart.readout")
    }

    private func averageLegend(_ lines: [AverageLine]) -> some View {
        HStack(spacing: 8) {
            ForEach(lines) { line in
                let hidden = hiddenAverages.contains(line.slot)
                Button {
                    if hidden { hiddenAverages.remove(line.slot) } else { hiddenAverages.insert(line.slot) }
                } label: {
                    HStack(spacing: 5) {
                        Capsule().fill(line.color).frame(width: 14, height: 3)
                        Text(line.name).font(.caption2.weight(.semibold))
                    }
                    .foregroundStyle(hidden ? Theme.secondary.opacity(0.5) : Theme.text)
                    .padding(.horizontal, 10)
                    .frame(minHeight: 32)
                    .background(Theme.elevated.opacity(hidden ? 0.4 : 1), in: Capsule())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("\(line.name) 均線")
                .accessibilityValue(hidden ? "已隱藏" : "顯示中")
                .accessibilityIdentifier("chart.ma.\(line.slot)")
            }
            Spacer(minLength: 0)
        }
    }

    private func priceChart(_ data: [ChartCandle], lines: [AverageLine]) -> some View {
        let inspectedCandle = inspected(in: data)
        return Chart {
            ForEach(data) { candle in
                if style == .candlestick {
                    let body = TradingDay.candleBody(around: candle.date, spanDays: period.spanDays)
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
                    LineMark(x: .value("日期", candle.date), y: .value("收盤", candle.close), series: .value("線", "收盤"))
                        .foregroundStyle(Theme.accent)
                        .lineStyle(StrokeStyle(lineWidth: 2))
                }
            }
            ForEach(lines.filter { !hiddenAverages.contains($0.slot) }) { line in
                ForEach(line.points, id: \.date) { point in
                    LineMark(x: .value("日期", point.date), y: .value("均線", point.value), series: .value("線", line.name))
                        .foregroundStyle(line.color)
                        .lineStyle(StrokeStyle(lineWidth: 1.2))
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
        .chartLegend(.hidden)
        .chartYScale(domain: priceDomain(data, lines: lines))
        .chartXSelection(value: $selectedDate)
        .chartXAxis {
            AxisMarks(values: .automatic(desiredCount: 4)) { _ in
                AxisValueLabel(format: interval.rawValue >= 12 ? TradingDay.yearMonthAxisStyle() : TradingDay.axisStyle())
                    .foregroundStyle(Theme.secondary)
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
        .accessibilityLabel(style == .candlestick ? "\(period.label)線圖" : "收盤價走勢圖")
        .accessibilityIdentifier("chart.price")
    }

    private func volumeChart(_ data: [ChartCandle]) -> some View {
        let inspectedCandle = inspected(in: data)
        return Chart(data) { candle in
            if let volume = candle.volume {
                let body = TradingDay.candleBody(around: candle.date, spanDays: period.spanDays)
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
                Text("\(period.label) 成交量 \(candle.volume.map { $0.formatted(.number.notation(.compactName)) } ?? "未提供")")
                    .font(.caption2.monospacedDigit())
                    .foregroundStyle(Theme.secondary)
                    .padding(.bottom, 4)
                    .background(Theme.surface.opacity(0.85))
            }
        }
        .accessibilityLabel("\(period.label)成交量")
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
