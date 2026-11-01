import Charts
import DSACore
import SwiftUI

/// 個股價格圖：可左右捲動、雙指縮放的 K 線，疊主圖指標與重點標記，下方是成交量與副圖指標。
/// 三張圖共用同一個捲動位置與可見寬度，拖曳選取也共用。
struct MarketChart: View {
    let candles: [ChartCandle]
    let convention: MarketColorConvention
    let market: String
    let loadIntraday: IntradayLoaders?

    @State private var showsIntraday = false
    @State private var interval: ChartInterval = .threeMonths
    @State private var period: CandlePeriod = .day
    @State private var style: ChartStyle = .candlestick
    @State private var overlay: Overlay = .ma
    @State private var oscillator: Oscillator = .macd
    @State private var showsMarkers = true
    @State private var hiddenLines: Set<Int> = []
    @State private var selectedDate: Date?
    @State private var prepared = PreparedSeries.empty
    @State private var showingGuide = false
    /// 可見區間的左緣與寬度（秒）；區間按鈕只是設定這兩個值，之後可自由捲動、縮放。
    @State private var scrollStart = Date()
    @State private var visibleLength: TimeInterval = 90 * 86_400
    @State private var pinchBase: ChartViewport?
    @ScaledMetric(relativeTo: .caption2) private var axisLabelWidth: CGFloat = 46

    init(
        candles: [ChartCandle],
        convention: MarketColorConvention = .taiwan,
        market: String = "tw",
        loadIntraday: IntradayLoaders? = nil
    ) {
        self.candles = candles
        self.convention = convention
        self.market = market
        self.loadIntraday = loadIntraday
    }

    /// 預設視窗寬度。捲動與縮放之後就不再對應某個區間，選單只是「回到這個寬度並貼齊最新」。
    private enum ChartInterval: Int, CaseIterable, Identifiable {
        case oneMonth = 1, threeMonths = 3, sixMonths = 6, oneYear = 12, threeYears = 36, fiveYears = 60, all = 1_200
        var id: Int { rawValue }
        var label: String { self == .all ? "全部" : rawValue < 12 ? "\(rawValue)M" : "\(rawValue / 12)Y" }
        var accessibilityLabel: String { self == .all ? "全部資料" : rawValue < 12 ? "\(rawValue) 個月" : "\(rawValue / 12) 年" }
        var seconds: TimeInterval { Double(rawValue) * 30.44 * 86_400 }

        /// 每種 K 棒的預設視窗：一年塞兩百多根日 K 會擠成細線。
        static func preset(for period: CandlePeriod) -> ChartInterval {
            switch period {
            case .day: .threeMonths
            case .week: .oneYear
            case .month: .fiveYears
            }
        }
    }

    private enum ChartStyle: String, CaseIterable, Identifiable {
        case candlestick = "K 線"
        case line = "收盤線"
        var id: String { rawValue }
    }

    enum Overlay: String, CaseIterable, Identifiable {
        case ma = "MA", ema = "EMA", bollinger = "布林", none = "無"
        var id: String { rawValue }
    }

    enum Oscillator: String, CaseIterable, Identifiable {
        case macd = "MACD", kd = "KD", rsi = "RSI", none = "無"
        var id: String { rawValue }
    }

    struct LinePoint: Hashable {
        let date: Date
        let anchor: Date
        let value: Double
    }

    struct OverlayLine: Identifiable {
        let slot: Int
        let name: String
        let points: [LinePoint]
        var id: Int { slot }
        var color: Color { MarketChart.lineColors[slot % MarketChart.lineColors.count] }
    }

    struct BandPoint: Hashable {
        let anchor: Date
        let lower: Double
        let upper: Double
    }

    struct OscillatorPoint: Hashable {
        let date: Date
        let anchor: Date
        /// MACD：DIF／DEA／柱；KD：K／D；RSI：RSI
        let first: Double
        let second: Double?
        let histogram: Double?
    }

    // 避開漲跌用的紅綠，免得指標線被看成某一根 K 棒的顏色。
    static let lineColors: [Color] = [Theme.warning, Theme.information, Color(red: 0.78, green: 0.56, blue: 1.0)]

    /// 聚合、指標與標記只在資料、週期或指標選擇變動時算一次；捲動與拖曳選取每一格都會重繪 body，
    /// 在 body 裡重算一千多根 K 棒會卡頓。
    private struct PreparedSeries {
        var full: [ChartCandle]
        var lines: [OverlayLine]
        var band: [BandPoint]
        var oscillator: [OscillatorPoint]
        var yearRange: KeyPoints.YearRange?
        var gaps: [KeyPoints.Gap]
        var crosses: [KeyPoints.Cross]
        var spikes: [ChartCandle]
        var historyMonths: Int

        static let empty = PreparedSeries(full: [], lines: [], band: [], oscillator: [], yearRange: nil, gaps: [], crosses: [], spikes: [], historyMonths: 0)
    }

    private struct SeriesKey: Equatable {
        let count: Int
        let lastDate: Date?
        let lastClose: Double?
        let period: CandlePeriod
        let overlay: Overlay
        let oscillator: Oscillator
    }

    private var seriesKey: SeriesKey {
        SeriesKey(count: candles.count, lastDate: candles.last?.date, lastClose: candles.last?.close,
                  period: period, overlay: overlay, oscillator: oscillator)
    }

    private func prepare() {
        let full = CandleSeries.aggregate(candles, period: period)
        let closes = full.map(\.close)
        func points(_ values: [Double?]) -> [LinePoint] {
            zip(full, values).compactMap { candle, value in value.map { LinePoint(date: candle.date, anchor: candle.anchor, value: $0) } }
        }
        var lines: [OverlayLine] = []
        var band: [BandPoint] = []
        switch overlay {
        case .ma:
            lines = period.movingAverageWindows.enumerated().map { slot, window in
                OverlayLine(slot: slot, name: "MA\(window)", points: points(Indicators.sma(closes, period: window)))
            }
        case .ema:
            lines = period.movingAverageWindows.enumerated().map { slot, window in
                OverlayLine(slot: slot, name: "EMA\(window)", points: points(Indicators.ema(closes, period: window)))
            }
        case .bollinger:
            let values = Indicators.bollinger(closes)
            lines = [
                OverlayLine(slot: 0, name: "上軌", points: points(values.map { $0?.upper })),
                OverlayLine(slot: 1, name: "中軌", points: points(values.map { $0?.middle })),
                OverlayLine(slot: 2, name: "下軌", points: points(values.map { $0?.lower }))
            ]
            band = zip(full, values).compactMap { candle, value in
                value.map { BandPoint(anchor: candle.anchor, lower: $0.lower, upper: $0.upper) }
            }
        case .none:
            break
        }

        var oscillatorPoints: [OscillatorPoint] = []
        switch oscillator {
        case .macd:
            oscillatorPoints = zip(full, Indicators.macd(closes)).compactMap { candle, value in
                value.map { OscillatorPoint(date: candle.date, anchor: candle.anchor, first: $0.dif, second: $0.dea, histogram: $0.histogram) }
            }
        case .kd:
            oscillatorPoints = zip(full, Indicators.kd(full)).compactMap { candle, value in
                value.map { OscillatorPoint(date: candle.date, anchor: candle.anchor, first: $0.k, second: $0.d, histogram: nil) }
            }
        case .rsi:
            oscillatorPoints = zip(full, Indicators.rsi(closes)).compactMap { candle, value in
                value.map { OscillatorPoint(date: candle.date, anchor: candle.anchor, first: $0, second: nil, histogram: nil) }
            }
        case .none:
            break
        }

        // 均線交叉固定用短、中兩條均線算，與主圖選哪種指標無關。
        let windows = period.movingAverageWindows
        let crosses = KeyPoints.crosses(fast: CandleSeries.movingAverage(full, window: windows[0]),
                                        slow: CandleSeries.movingAverage(full, window: windows[1]))
        var months = 0
        if let first = full.first?.periodStart, let last = full.last?.date {
            months = TradingDay.calendar.dateComponents([.month], from: first, to: last).month ?? 0
        }
        prepared = PreparedSeries(
            full: full, lines: lines, band: band, oscillator: oscillatorPoints,
            yearRange: KeyPoints.yearRange(candles.sorted { $0.date < $1.date }),
            gaps: KeyPoints.unfilledGaps(full), crosses: crosses,
            spikes: KeyPoints.volumeSpikes(full), historyMonths: months
        )
    }

    // MARK: - 可見區間

    private var visibleRange: ClosedRange<Date> {
        scrollStart...scrollStart.addingTimeInterval(visibleLength)
    }

    /// 依 anchor 排序的 K 棒中，落在可見區間內的那一段（二分搜尋，捲動時每格都會呼叫）。
    private func visibleSlice(_ series: [ChartCandle]) -> ArraySlice<ChartCandle> {
        let range = visibleRange
        let lower = partition(series) { $0.anchor >= range.lowerBound }
        let upper = partition(series) { $0.anchor > range.upperBound }
        return series[lower..<max(lower, upper)]
    }

    private func partition(_ series: [ChartCandle], _ isAfter: (ChartCandle) -> Bool) -> Int {
        var low = 0
        var high = series.count
        while low < high {
            let middle = (low + high) / 2
            if isAfter(series[middle]) { high = middle } else { low = middle + 1 }
        }
        return low
    }

    private var fullDomain: ClosedRange<Date>? {
        guard let first = prepared.full.first, let last = prepared.full.last else { return nil }
        return ChartViewport.domain(firstAnchor: first.anchor, lastAnchor: last.anchor, spanDays: period.spanDays)
    }

    private func resetViewport() {
        guard let domain = fullDomain else { return }
        apply(ChartViewport.initial(domain: domain, preferred: interval.seconds, spanDays: period.spanDays))
        selectedDate = nil
    }

    private func apply(_ viewport: ChartViewport) {
        visibleLength = viewport.length
        scrollStart = viewport.start
    }

    /// 雙指縮放：右緣固定，規則見 `ChartViewport.pinched`。
    private var pinch: some Gesture {
        MagnifyGesture()
            .onChanged { value in
                guard let domain = fullDomain else { return }
                let base = pinchBase ?? ChartViewport(start: scrollStart, length: visibleLength)
                if pinchBase == nil { pinchBase = base }
                apply(ChartViewport.pinched(from: base, magnification: value.magnification, domain: domain, spanDays: period.spanDays))
            }
            .onEnded { _ in pinchBase = nil }
    }

    private func inspected(in data: ArraySlice<ChartCandle>) -> ChartCandle? {
        guard let selectedDate else { return data.last ?? prepared.full.last }
        return CandleSeries.nearest(to: selectedDate, in: Array(data))
    }

    /// Y 軸只依可見 K 棒的高低決定，指標線超出的部分裁掉：暴漲後的月 K 布林下軌可以算到負值，
    /// 納入範圍會把 K 棒壓扁（INTC 2026 月 K 實際踩到）。
    private func priceDomain(_ data: ArraySlice<ChartCandle>) -> ClosedRange<Double> {
        let lower = data.map(\.low).min() ?? 0
        let upper = data.map(\.high).max() ?? 1
        let margin = max((upper - lower) * 0.1, abs(upper) * 0.005, 0.01)
        return (lower - margin)...(upper + margin)
    }

    // MARK: - Body

    var body: some View {
        let data = visibleSlice(prepared.full)
        VStack(alignment: .leading, spacing: 10) {
            tabRow

            if showsIntraday, let loadIntraday {
                IntradayChart(market: market, convention: convention, load: loadIntraday)
            } else if let domain = fullDomain, !prepared.full.isEmpty {
                if let candle = inspected(in: data) {
                    infoHeader(candle)
                }
                Group {
                    priceChart(data)
                        .frame(height: 250)
                    volumeChart(data)
                        .frame(height: 62)
                    if oscillator != .none {
                        oscillatorChart(selected: inspected(in: data))
                            .frame(height: 92)
                    }
                }
                .chartXScale(domain: domain)
                .chartScrollableAxes(.horizontal)
                .chartXVisibleDomain(length: visibleLength)
                .chartScrollPosition(x: $scrollStart)
                .simultaneousGesture(pinch)
                indicatorRow
                HStack(alignment: .top, spacing: 6) {
                    Image(systemName: "hand.draw")
                    Text("左右滑動看更早、雙指縮放；按住後拖曳查看每根 K 棒。")
                }
                .font(.caption2)
                .foregroundStyle(Theme.secondary)
                if interval != .all, prepared.historyMonths < interval.rawValue - 1 {
                    let months = prepared.historyMonths
                    Text("這檔目前只有約 \(months >= 12 ? "\(months / 12) 年 \(months % 12) 個月" : "\(months) 個月")的資料，已顯示全部。")
                        .font(.caption2)
                        .foregroundStyle(Theme.warning)
                }
            } else {
                EmptyStateView(title: "尚無日線資料", message: "目前沒有可顯示的行情，取得資料後才會繪製走勢。")
            }
        }
        .onAppear {
            prepare()
            resetViewport()
        }
        .onChange(of: seriesKey) { old, new in
            prepare()
            // 只換指標時保持目前捲動位置；資料或週期變了才回到最新。
            if old.period != new.period || old.count != new.count || old.lastDate != new.lastDate { resetViewport() }
        }
        .onChange(of: interval) { _, _ in resetViewport() }
        .sheet(isPresented: $showingGuide) {
            KLineGuideView(convention: convention)
        }
        .environment(\.calendar, TradingDay.calendar)
        .environment(\.timeZone, TradingDay.timeZone)
    }

    // MARK: - 控制項

    /// 富途式的週期分頁：分時｜日 K｜週 K｜月 K，右側是區間下拉與「⋯」。
    private var tabRow: some View {
        HStack(spacing: 4) {
            if loadIntraday != nil {
                tab("分時", selected: showsIntraday, id: "chart.tab.intraday") { showsIntraday = true }
            }
            ForEach(CandlePeriod.allCases) { option in
                tab(option.label, selected: !showsIntraday && period == option, id: "chart.tab.\(option.rawValue)") {
                    showsIntraday = false
                    guard period != option else { return }
                    interval = ChartInterval.preset(for: option)
                    period = option
                }
            }
            Spacer(minLength: 4)
            if !showsIntraday {
                Menu {
                    // 用按鈕而不是 Picker：重選目前的區間也要回到該寬度並貼齊最新，Picker 值沒變不會觸發。
                    ForEach(ChartInterval.allCases) { option in
                        Button {
                            interval = option
                            resetViewport()
                        } label: {
                            if option == interval {
                                Label(option.label, systemImage: "checkmark")
                            } else {
                                Text(option.label)
                            }
                        }
                    }
                } label: {
                    HStack(spacing: 3) {
                        Text(interval.label)
                        Image(systemName: "chevron.down").font(.system(size: 9, weight: .bold))
                    }
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(Theme.text)
                    .padding(.horizontal, 10)
                    .frame(minHeight: 32)
                    .background(Theme.elevated, in: Capsule())
                }
                .accessibilityLabel("顯示區間 \(interval.accessibilityLabel)")
                .accessibilityIdentifier("chart.range")
            }
            Menu {
                if !showsIntraday {
                    Picker("圖表樣式", selection: $style) {
                        ForEach(ChartStyle.allCases) { Text($0.rawValue).tag($0) }
                    }
                }
                Button {
                    showingGuide = true
                } label: {
                    Label("看懂 K 線", systemImage: "questionmark.circle")
                }
            } label: {
                Image(systemName: "ellipsis.circle")
                    .font(.body)
                    .foregroundStyle(Theme.secondary)
                    .frame(width: 36, height: 32)
            }
            .accessibilityLabel("更多圖表設定")
            .accessibilityIdentifier("chart.more")
        }
    }

    private func tab(_ title: String, selected: Bool, id: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(spacing: 4) {
                Text(title)
                    .font(.subheadline.weight(selected ? .bold : .medium))
                    .foregroundStyle(selected ? Theme.text : Theme.secondary)
                Capsule()
                    .fill(selected ? Theme.accent : .clear)
                    .frame(width: 18, height: 3)
            }
            .padding(.horizontal, 6)
            .frame(minHeight: 40)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(selected ? .isSelected : [])
        .accessibilityIdentifier(id)
    }

    private var indicatorRow: some View {
        HStack(spacing: 8) {
            Menu {
                Picker("主圖指標", selection: $overlay) {
                    ForEach(Overlay.allCases) { Text($0.rawValue).tag($0) }
                }
            } label: {
                chip("主圖 \(overlay.rawValue)", systemImage: "chart.xyaxis.line", active: overlay != .none)
            }
            .accessibilityIdentifier("chart.overlay")
            Menu {
                Picker("副圖指標", selection: $oscillator) {
                    ForEach(Oscillator.allCases) { Text($0.rawValue).tag($0) }
                }
            } label: {
                chip("副圖 \(oscillator.rawValue)", systemImage: "waveform.path.ecg", active: oscillator != .none)
            }
            .accessibilityIdentifier("chart.oscillator")
            Button {
                showsMarkers.toggle()
            } label: {
                chip("重點標記", systemImage: showsMarkers ? "mappin.and.ellipse" : "mappin.slash", active: showsMarkers)
            }
            .buttonStyle(.plain)
            .accessibilityValue(showsMarkers ? "顯示中" : "已隱藏")
            .accessibilityIdentifier("chart.markers")
            Spacer(minLength: 0)
        }
        .onChange(of: overlay) { _, _ in hiddenLines = [] }
    }

    private func chip(_ title: String, systemImage: String, active: Bool) -> some View {
        Label(title, systemImage: systemImage)
            .font(.caption.weight(.semibold))
            .lineLimit(1)
            .foregroundStyle(active ? Theme.text : Theme.secondary)
            .padding(.horizontal, 10)
            .frame(minHeight: 34)
            .background(active ? Theme.elevated : Theme.elevated.opacity(0.4), in: Capsule())
    }

    // MARK: - 讀數

    /// 圖上方兩行小字（富途／TradingView 的寫法）：日期與開高低收、漲跌；下一行是可點的指標線數值。
    private func infoHeader(_ candle: ChartCandle) -> some View {
        let previous = prepared.full.last { $0.date < candle.periodStart }?.close
        let change = previous.map { (candle.close / $0 - 1) * 100 }
        let tint = Theme.changeColor(change ?? (candle.close - candle.open), convention: convention)
        return VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Group {
                    if candle.periodStart == candle.date {
                        Text(candle.date, format: TradingDay.readoutStyle())
                    } else {
                        Text("\(candle.periodStart.formatted(TradingDay.readoutStyle()))–\(candle.date.formatted(TradingDay.axisStyle()))")
                    }
                }
                .foregroundStyle(Theme.text)
                if candle.isProvisional {
                    StatusBadge("暫定・即時報價", tone: .warning)
                }
                Spacer(minLength: 0)
                Text(selectedDate != nil ? "選取" : candle.date == prepared.full.last?.date ? "最新" : "畫面最右")
                    .foregroundStyle(Theme.secondary)
            }
            .font(.caption.weight(.medium))
            HStack(spacing: 8) {
                readout("開", candle.open)
                readout("高", candle.high)
                readout("低", candle.low)
                readout("收", candle.close, tint: tint)
                if let change {
                    Text(DisplayFormat.percent(change))
                        .foregroundStyle(tint)
                }
            }
            .font(.caption.monospacedDigit())
            .lineLimit(1)
            .minimumScaleFactor(0.75)
            lineLegend(at: candle)
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("chart.readout")
    }

    private func readout(_ label: String, _ value: Double, tint: Color = Theme.text) -> some View {
        HStack(spacing: 2) {
            Text(label).foregroundStyle(Theme.secondary)
            Text(price(value)).foregroundStyle(tint).fontWeight(.semibold)
        }
    }

    private func oscillatorReadout(_ point: OscillatorPoint) -> String {
        switch oscillator {
        case .macd:
            "DIF \(price(point.first))　DEA \(point.second.map(price) ?? "—")　柱 \(point.histogram.map(price) ?? "—")"
        case .kd:
            "K \(price(point.first))　D \(point.second.map(price) ?? "—")"
        case .rsi:
            price(point.first)
        case .none:
            ""
        }
    }

    /// 指標線名稱與當根數值，點一下隱藏／顯示該線。
    private func lineLegend(at candle: ChartCandle) -> some View {
        HStack(spacing: 10) {
            ForEach(prepared.lines) { line in
                let hidden = hiddenLines.contains(line.slot)
                let value = line.points.first { $0.date == candle.date }?.value
                Button {
                    if hidden { hiddenLines.remove(line.slot) } else { hiddenLines.insert(line.slot) }
                } label: {
                    Text("\(line.name) \(value.map(price) ?? "—")")
                        .font(.caption2.monospacedDigit().weight(.medium))
                        .foregroundStyle(hidden ? Theme.secondary.opacity(0.45) : line.color)
                        .strikethrough(hidden, color: Theme.secondary.opacity(0.45))
                        .frame(minHeight: 28)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("\(line.name) 指標線")
                .accessibilityValue(hidden ? "已隱藏" : "顯示中")
                .accessibilityIdentifier("chart.ma.\(line.slot)")
            }
            Spacer(minLength: 0)
        }
        .lineLimit(1)
        .minimumScaleFactor(0.8)
    }

    // MARK: - 圖表

    private func priceChart(_ data: ArraySlice<ChartCandle>) -> some View {
        let inspectedCandle = selectedDate == nil ? nil : inspected(in: data)
        let yDomain = priceDomain(data)
        let extremes = KeyPoints.extremes(Array(data))
        let latest = prepared.full.last
        return Chart {
            if !prepared.band.isEmpty, !hiddenLines.contains(0) || !hiddenLines.contains(2) {
                ForEach(prepared.band, id: \.anchor) { point in
                    AreaMark(x: .value("日期", point.anchor), yStart: .value("下軌", point.lower), yEnd: .value("上軌", point.upper), series: .value("區域", "布林"))
                        .foregroundStyle(Theme.information.opacity(0.08))
                }
            }
            if showsMarkers {
                ForEach(prepared.gaps, id: \.date) { gap in
                    RectangleMark(
                        xStart: .value("缺口起", gap.anchor),
                        xEnd: .value("缺口迄", fullDomain?.upperBound ?? gap.anchor),
                        yStart: .value("缺口下緣", gap.lower),
                        yEnd: .value("缺口上緣", gap.upper)
                    )
                    .foregroundStyle((gap.up ? Theme.changeColor(1, convention: convention) : Theme.changeColor(-1, convention: convention)).opacity(0.12))
                    .annotation(position: .topLeading, alignment: .leading, spacing: 2) {
                        if gap.date == prepared.gaps.last?.date {
                            Text("未補缺口").font(.system(size: 9, weight: .semibold)).foregroundStyle(Theme.secondary)
                        }
                    }
                }
            }
            ForEach(prepared.full) { candle in
                if style == .candlestick {
                    let body = TradingDay.candleBody(around: candle.anchor, spanDays: period.spanDays)
                    let color = Theme.changeColor(candle.close - candle.open, convention: convention).opacity(candle.isProvisional ? 0.45 : 1)
                    RuleMark(
                        x: .value("日期", candle.anchor),
                        yStart: .value("最低", candle.low),
                        yEnd: .value("最高", candle.high)
                    )
                    .foregroundStyle(color)
                    .lineStyle(StrokeStyle(lineWidth: 1))
                    RectangleMark(
                        xStart: .value("起點", body.lowerBound),
                        xEnd: .value("終點", body.upperBound),
                        yStart: .value("開盤", min(candle.open, candle.close)),
                        // 開收相同（十字線）時給一條細線的高度，不然實體會消失。
                        yEnd: .value("收盤", max(candle.open, candle.close, min(candle.open, candle.close) + (yDomain.upperBound - yDomain.lowerBound) * 0.003))
                    )
                    .foregroundStyle(candle.open == candle.close ? Theme.secondary : color)
                } else {
                    AreaMark(x: .value("日期", candle.anchor), yStart: .value("基準", yDomain.lowerBound), yEnd: .value("收盤", candle.close), series: .value("區域", "收盤"))
                        .foregroundStyle(LinearGradient(colors: [Theme.accent.opacity(0.25), Theme.accent.opacity(0)], startPoint: .top, endPoint: .bottom))
                    LineMark(x: .value("日期", candle.anchor), y: .value("收盤", candle.close), series: .value("線", "收盤"))
                        .foregroundStyle(Theme.accent)
                        .lineStyle(StrokeStyle(lineWidth: 2))
                }
            }
            ForEach(prepared.lines.filter { !hiddenLines.contains($0.slot) }) { line in
                ForEach(line.points, id: \.date) { point in
                    LineMark(x: .value("日期", point.anchor), y: .value("指標", point.value), series: .value("線", line.name))
                        .foregroundStyle(line.color)
                        .lineStyle(StrokeStyle(lineWidth: 1.2))
                }
            }
            if showsMarkers {
                markerContent(extremes: extremes, yDomain: yDomain)
            }
            if let latest {
                RuleMark(y: .value("最新價", latest.close))
                    .foregroundStyle(Theme.changeColor(latest.close - latest.open, convention: convention).opacity(0.7))
                    .lineStyle(StrokeStyle(lineWidth: 0.8, dash: [3, 3]))
                    .annotation(position: .trailing, alignment: .center, spacing: 0) {
                        Text(price(latest.close))
                            .font(.system(size: 10, weight: .bold).monospacedDigit())
                            .foregroundStyle(Theme.background)
                            .padding(.horizontal, 3)
                            .background(Theme.changeColor(latest.close - latest.open, convention: convention), in: RoundedRectangle(cornerRadius: 3))
                    }
            }
            if let inspectedCandle {
                RuleMark(x: .value("選取日期", inspectedCandle.anchor))
                    .foregroundStyle(Theme.text.opacity(0.6))
                    .lineStyle(StrokeStyle(lineWidth: 1, dash: [4, 4]))
                PointMark(x: .value("選取日期", inspectedCandle.anchor), y: .value("收盤", inspectedCandle.close))
                    .foregroundStyle(Theme.accent)
                    .symbolSize(32)
            }
        }
        .chartLegend(.hidden)
        .chartYScale(domain: yDomain)
        .chartPlotStyle { $0.clipped() }
        .chartXSelection(value: $selectedDate)
        .chartXAxis {
            AxisMarks(values: .automatic(desiredCount: 4)) { _ in
                AxisGridLine(stroke: StrokeStyle(lineWidth: 0.5, dash: [3, 3])).foregroundStyle(Theme.border)
                AxisValueLabel(format: visibleLength > 300 * 86_400 ? TradingDay.yearMonthAxisStyle() : TradingDay.axisStyle())
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

    @ChartContentBuilder
    private func markerContent(extremes: (high: ChartCandle, low: ChartCandle)?, yDomain: ClosedRange<Double>) -> some ChartContent {
        if let extremes {
            PointMark(x: .value("區間高", extremes.high.anchor), y: .value("高", extremes.high.high))
                .symbolSize(0)
                .annotation(position: .top, alignment: labelAlignment(extremes.high.anchor), spacing: 2) {
                    markerLabel("高 \(price(extremes.high.high))")
                }
            PointMark(x: .value("區間低", extremes.low.anchor), y: .value("低", extremes.low.low))
                .symbolSize(0)
                .annotation(position: .bottom, alignment: labelAlignment(extremes.low.anchor), spacing: 2) {
                    markerLabel("低 \(price(extremes.low.low))")
                }
        }
        if let year = prepared.yearRange {
            ForEach([(year.high, "52 週高"), (year.low, "52 週低")], id: \.1) { level, title in
                if yDomain.contains(level) {
                    RuleMark(y: .value(title, level))
                        .foregroundStyle(Theme.secondary.opacity(0.55))
                        .lineStyle(StrokeStyle(lineWidth: 0.8, dash: [6, 4]))
                        .annotation(position: .top, alignment: .leading, spacing: 1) {
                            Text("\(title) \(price(level))").font(.system(size: 9)).foregroundStyle(Theme.secondary)
                        }
                }
            }
        }
        // 只標可見範圍內最近三次交叉、文字只寫最新一次；盤整時均線來回穿越，全標會糊成一片。
        let range = visibleRange
        let recent = Array(prepared.crosses.filter { range.contains($0.anchor) }.suffix(3))
        ForEach(recent, id: \.date) { cross in
            PointMark(x: .value("交叉", cross.anchor), y: .value("交叉價", cross.price))
                .symbol(.triangle)
                .symbolSize(36)
                .foregroundStyle(cross.golden ? Theme.warning : Theme.information)
                .annotation(position: cross.golden ? .bottom : .top, spacing: 2,
                            overflowResolution: .init(x: .fit(to: .chart), y: .fit(to: .chart))) {
                    if cross.date == recent.last?.date {
                        Text(cross.golden ? "黃金交叉" : "死亡交叉").font(.system(size: 9, weight: .semibold))
                            .foregroundStyle(cross.golden ? Theme.warning : Theme.information)
                    }
                }
        }
    }

    /// 標籤靠近視窗左右邊緣時往內側對齊，避免被軸線或畫面邊緣切掉。
    private func labelAlignment(_ anchor: Date) -> Alignment {
        let position = anchor.timeIntervalSince(scrollStart) / max(visibleLength, 1)
        return position > 0.8 ? .trailing : position < 0.2 ? .leading : .center
    }

    private func markerLabel(_ text: String) -> some View {
        Text(text)
            .font(.system(size: 10, weight: .semibold).monospacedDigit())
            .foregroundStyle(Theme.text)
            .padding(.horizontal, 4)
            .padding(.vertical, 1)
            .background(Theme.elevated.opacity(0.9), in: RoundedRectangle(cornerRadius: 4))
    }

    private func volumeChart(_ data: ArraySlice<ChartCandle>) -> some View {
        let inspectedCandle = inspected(in: data)
        let peak = data.compactMap(\.volume).max() ?? 1
        let spikeDates = Set(prepared.spikes.map(\.date))
        return Chart(prepared.full) { candle in
            if let volume = candle.volume {
                let body = TradingDay.candleBody(around: candle.anchor, spanDays: period.spanDays)
                RectangleMark(
                    xStart: .value("起點", body.lowerBound),
                    xEnd: .value("終點", body.upperBound),
                    yStart: .value("基準", 0),
                    yEnd: .value("成交量", volume)
                )
                .foregroundStyle(Theme.changeColor(candle.close - candle.open, convention: convention).opacity(spikeDates.contains(candle.date) && showsMarkers ? 0.95 : 0.45))
            }
        }
        .chartYScale(domain: 0...(peak * 1.1))
        .chartXSelection(value: $selectedDate)
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
                let spike = spikeDates.contains(candle.date) ? "・爆量" : ""
                Text("\(period.label) 成交量 \(candle.volume.map { $0.formatted(.number.notation(.compactName)) } ?? "未提供")\(spike)")
                    .font(.caption2.monospacedDigit())
                    .foregroundStyle(Theme.secondary)
                    .padding(.bottom, 4)
                    .background(Theme.surface.opacity(0.85))
            }
        }
        .accessibilityLabel("\(period.label)成交量")
        .accessibilityIdentifier("chart.volume")
    }

    private func oscillatorChart(selected candle: ChartCandle?) -> some View {
        let range = visibleRange
        let visible = prepared.oscillator.filter { range.contains($0.anchor) }
        let values = visible.flatMap { [$0.first, $0.second, $0.histogram].compactMap { $0 } }
        let domain: ClosedRange<Double> = oscillator == .macd
            ? {
                let bound = max(values.map(abs).max() ?? 1, 0.0001) * 1.15
                return -bound...bound
            }()
            : 0...100
        return Chart {
            if oscillator == .kd || oscillator == .rsi {
                let guides: [Double] = oscillator == .kd ? [20, 80] : [30, 70]
                ForEach(guides, id: \.self) { level in
                    RuleMark(y: .value("參考", level))
                        .foregroundStyle(Theme.border)
                        .lineStyle(StrokeStyle(lineWidth: 0.6, dash: [3, 3]))
                }
            }
            ForEach(prepared.oscillator, id: \.date) { point in
                if let histogram = point.histogram {
                    let body = TradingDay.candleBody(around: point.anchor, spanDays: period.spanDays)
                    RectangleMark(xStart: .value("起點", body.lowerBound), xEnd: .value("終點", body.upperBound),
                                  yStart: .value("零", 0), yEnd: .value("柱", histogram))
                        .foregroundStyle(Theme.changeColor(histogram, convention: convention).opacity(0.55))
                }
                LineMark(x: .value("日期", point.anchor), y: .value("主線", point.first), series: .value("線", "first"))
                    .foregroundStyle(Theme.warning)
                    .lineStyle(StrokeStyle(lineWidth: 1.2))
                if let second = point.second {
                    LineMark(x: .value("日期", point.anchor), y: .value("訊號線", second), series: .value("線", "second"))
                        .foregroundStyle(Theme.information)
                        .lineStyle(StrokeStyle(lineWidth: 1.2))
                }
            }
        }
        .chartLegend(.hidden)
        .chartYScale(domain: domain)
        .chartXSelection(value: $selectedDate)
        .chartXAxis(.hidden)
        .chartYAxis {
            AxisMarks(position: .trailing, values: .automatic(desiredCount: 3)) { value in
                AxisGridLine(stroke: StrokeStyle(lineWidth: 0.5, dash: [3, 3])).foregroundStyle(Theme.border)
                AxisValueLabel {
                    if let number = value.as(Double.self) {
                        axisLabel(number.formatted(.number.precision(.fractionLength(0...2))))
                    }
                }
            }
        }
        .overlay(alignment: .topLeading) {
            let point = candle.flatMap { candle in prepared.oscillator.first { $0.date == candle.date } }
            Text([oscillatorTitle, point.map(oscillatorReadout)].compactMap { $0 }.joined(separator: "　"))
                .font(.caption2.monospacedDigit().weight(.semibold))
                .foregroundStyle(Theme.secondary)
                .lineLimit(1)
                .minimumScaleFactor(0.75)
                .background(Theme.surface.opacity(0.85))
        }
        .accessibilityLabel("\(oscillator.rawValue) 指標")
        .accessibilityIdentifier("chart.oscillator.panel")
    }

    private var oscillatorTitle: String {
        switch oscillator {
        case .macd: "MACD(12,26,9)"
        case .kd: "KD(9,3,3)"
        case .rsi: "RSI(14)"
        case .none: ""
        }
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
