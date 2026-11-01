import Charts
import DSACore
import SwiftUI

/// 個股價格圖：可左右捲動、雙指縮放的 K 線，疊主圖指標與重點標記，下方是成交量與副圖指標。
/// X 軸是 K 棒序號，週末與假日不佔位；三張圖共用同一個捲動位置與可見寬度，拖曳選取也共用。
struct MarketChart: View {
    let candles: [ChartCandle]
    let convention: MarketColorConvention
    let market: String
    let loadIntraday: IntradayLoaders?

    let isFullScreen: Bool
    let extraPriceHeight: CGFloat

    @State private var showsIntraday: Bool
    @State private var interval: ChartInterval
    @State private var period: CandlePeriod
    @State private var style: ChartStyle = .candlestick
    @State private var overlay: Overlay = .ma
    @State private var oscillator: Oscillator = .macd
    /// 區間高低與爆量；預設開。
    @State private var showsMarkers = true
    /// 缺口與均線交叉會蓋住 K 棒，預設關，按了才畫。
    @State private var showsEvents = false
    @State private var hiddenLines: Set<Int> = []
    @State private var selectedX: Double?
    @State private var prepared = PreparedSeries.empty
    @State private var guideSection: KLineGuideSection?
    @State private var showingFullScreen = false
    @AppStorage("chart.gestureHintSeen") private var gestureHintSeen = false
    /// 可見區間的左緣與寬度（根）；區間按鈕只是設定這兩個值，之後可自由捲動、縮放。
    @State private var scrollStart: Double = 0
    @State private var visibleLength: Double = 63
    @State private var pinchBase: ChartViewport?
    @ScaledMetric(relativeTo: .caption2) private var axisLabelWidth: CGFloat = 54

    init(
        candles: [ChartCandle],
        convention: MarketColorConvention = .taiwan,
        market: String = "tw",
        loadIntraday: IntradayLoaders? = nil,
        isFullScreen: Bool = false,
        initialPeriod: CandlePeriod = .day,
        initialShowsIntraday: Bool = false,
        extraPriceHeight: CGFloat = 0
    ) {
        self.candles = candles
        self.convention = convention
        self.market = market
        self.loadIntraday = loadIntraday
        self.isFullScreen = isFullScreen
        self.extraPriceHeight = extraPriceHeight
        _showsIntraday = State(initialValue: initialShowsIntraday)
        _period = State(initialValue: initialPeriod)
        _interval = State(initialValue: ChartInterval.preset(for: initialPeriod))
    }

    /// 預設視窗寬度。捲動與縮放之後就不再對應某個區間，選單只是「回到這個寬度並貼齊最新」。
    private enum ChartInterval: Int, CaseIterable, Identifiable {
        case oneMonth = 1, threeMonths = 3, sixMonths = 6, oneYear = 12, threeYears = 36, fiveYears = 60, all = 1_200
        var id: Int { rawValue }
        var label: String { self == .all ? "全部" : rawValue < 12 ? "\(rawValue)月" : "\(rawValue / 12)年" }
        var accessibilityLabel: String { self == .all ? "全部資料" : rawValue < 12 ? "\(rawValue) 個月" : "\(rawValue / 12) 年" }

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
        let x: Double
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
        let x: Double
        let lower: Double
        let upper: Double
    }

    struct OscillatorPoint: Hashable {
        let date: Date
        let x: Double
        /// MACD：DIF／DEA／柱；KD：K／D；RSI：RSI
        let first: Double
        let second: Double?
        let histogram: Double?
    }

    /// K 棒與它在 X 軸上的序號。
    struct IndexedCandle: Identifiable {
        let index: Int
        let candle: ChartCandle
        var id: Int { index }
        var x: Double { Double(index) }
    }

    // 避開漲跌用的紅綠，免得指標線被看成某一根 K 棒的顏色。
    static let lineColors: [Color] = [Theme.warning, Theme.information, Color(red: 0.78, green: 0.56, blue: 1.0)]

    /// 聚合、指標與標記只在資料、週期或指標選擇變動時算一次；捲動與拖曳選取每一格都會重繪 body，
    /// 在 body 裡重算一千多根 K 棒會卡頓。
    private struct PreparedSeries {
        var full: [ChartCandle]
        var indexed: [IndexedCandle]
        var indexByDate: [Date: Int]
        /// 最新一根相對昨收的漲跌，決定最新價標籤的顏色。
        var latestChange: Double?
        var lines: [OverlayLine]
        var band: [BandPoint]
        var oscillator: [OscillatorPoint]
        var yearRange: KeyPoints.YearRange?
        var gaps: [KeyPoints.Gap]
        var crosses: [KeyPoints.Cross]
        var spikes: [ChartCandle]
        var historyMonths: Int

        static let empty = PreparedSeries(full: [], indexed: [], indexByDate: [:], latestChange: nil, lines: [], band: [], oscillator: [], yearRange: nil, gaps: [], crosses: [], spikes: [], historyMonths: 0)
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
            zip(full.indices, values).compactMap { index, value in value.map { LinePoint(date: full[index].date, x: Double(index), value: $0) } }
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
            band = zip(full.indices, values).compactMap { index, value in
                value.map { BandPoint(x: Double(index), lower: $0.lower, upper: $0.upper) }
            }
        case .none:
            break
        }

        var oscillatorPoints: [OscillatorPoint] = []
        switch oscillator {
        case .macd:
            oscillatorPoints = zip(full.indices, Indicators.macd(closes)).compactMap { index, value in
                value.map { OscillatorPoint(date: full[index].date, x: Double(index), first: $0.dif, second: $0.dea, histogram: $0.histogram) }
            }
        case .kd:
            oscillatorPoints = zip(full.indices, Indicators.kd(full)).compactMap { index, value in
                value.map { OscillatorPoint(date: full[index].date, x: Double(index), first: $0.k, second: $0.d, histogram: nil) }
            }
        case .rsi:
            oscillatorPoints = zip(full.indices, Indicators.rsi(closes)).compactMap { index, value in
                value.map { OscillatorPoint(date: full[index].date, x: Double(index), first: $0, second: nil, histogram: nil) }
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
            full: full,
            indexed: full.enumerated().map { IndexedCandle(index: $0.offset, candle: $0.element) },
            indexByDate: Dictionary(full.enumerated().map { ($0.element.date, $0.offset) }, uniquingKeysWith: { first, _ in first }),
            latestChange: CandleSeries.latestChange(candles),
            lines: lines, band: band, oscillator: oscillatorPoints,
            yearRange: KeyPoints.yearRange(candles.sorted { $0.date < $1.date }),
            gaps: KeyPoints.unfilledGaps(full), crosses: crosses,
            spikes: KeyPoints.volumeSpikes(full), historyMonths: months
        )
    }

    // MARK: - 可見區間

    private var viewport: ChartViewport {
        ChartViewport(start: scrollStart, length: visibleLength)
    }

    private var visibleRange: ClosedRange<Double> {
        scrollStart...(scrollStart + visibleLength)
    }

    private var fullDomain: ClosedRange<Double>? {
        prepared.full.isEmpty ? nil : ChartViewport.domain(barCount: prepared.full.count)
    }

    private func resetViewport() {
        guard let domain = fullDomain else { return }
        let bars = ChartViewport.preferredBars(dates: prepared.full.map(\.date), months: interval.rawValue)
        apply(ChartViewport.initial(domain: domain, preferredBars: bars))
        selectedX = nil
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
                let base = pinchBase ?? viewport
                if pinchBase == nil { pinchBase = base }
                apply(ChartViewport.pinched(from: base, magnification: value.magnification, domain: domain))
            }
            .onEnded { _ in pinchBase = nil }
    }

    private var selectedCandle: ChartCandle? {
        ChartViewport.selectedIndex(selectedX, barCount: prepared.full.count).map { prepared.full[$0] }
    }

    private func inspected(in data: ArraySlice<ChartCandle>) -> ChartCandle? {
        selectedCandle ?? data.last ?? prepared.full.last
    }

    /// Y 軸只依可見 K 棒的高低決定，指標線超出的部分裁掉：暴漲後的月 K 布林下軌可以算到負值，
    /// 納入範圍會把 K 棒壓扁（INTC 2026 月 K 實際踩到）。
    private func priceDomain(_ data: ArraySlice<ChartCandle>) -> ClosedRange<Double> {
        let lower = data.map(\.low).min() ?? 0
        let upper = data.map(\.high).max() ?? 1
        let margin = max((upper - lower) * 0.1, abs(upper) * 0.005, 0.01)
        return (lower - margin)...(upper + margin)
    }

    /// 三張圖共用的捲動與縮放設定。
    private func linkedX<Content: View>(_ chart: Content, domain: ClosedRange<Double>) -> some View {
        chart
            .chartXScale(domain: domain)
            .chartScrollableAxes(.horizontal)
            .chartXVisibleDomain(length: visibleLength)
            .chartScrollPosition(x: $scrollStart)
            .simultaneousGesture(pinch)
    }

    // MARK: - Body

    var body: some View {
        let data = prepared.full[viewport.visibleIndices(barCount: prepared.full.count)]
        VStack(alignment: .leading, spacing: 10) {
            tabRow

            if showsIntraday, let loadIntraday {
                IntradayChart(market: market, convention: convention, load: loadIntraday, extraHeight: extraPriceHeight)
            } else if let domain = fullDomain, !prepared.full.isEmpty {
                if let candle = inspected(in: data) {
                    infoHeader(candle)
                }
                VStack(alignment: .leading, spacing: ChartLayout.spacing) {
                    linkedX(priceChart(data), domain: domain)
                        .frame(height: ChartLayout.price + extraPriceHeight)
                    volumeReadout(inspected(in: data))
                        .frame(height: ChartLayout.readoutRow)
                    linkedX(volumeChart(data), domain: domain)
                        .frame(height: ChartLayout.volume)
                    if oscillator != .none {
                        oscillatorReadout(inspected(in: data))
                            .frame(height: ChartLayout.readoutRow)
                        linkedX(oscillatorChart(), domain: domain)
                            .frame(height: ChartLayout.oscillator)
                    }
                }
                if let year = prepared.yearRange {
                    HStack(spacing: 10) {
                        Text("52 週").foregroundStyle(Theme.secondary)
                        Text("高 \(price(year.high))").foregroundStyle(Theme.text)
                        Text("低 \(price(year.low))").foregroundStyle(Theme.text)
                    }
                    .font(.caption.monospacedDigit())
                    .accessibilityElement(children: .combine)
                    .accessibilityIdentifier("chart.yearRange")
                }
                indicatorRows
                if !gestureHintSeen {
                    HStack(alignment: .top, spacing: 6) {
                        Image(systemName: "hand.draw")
                        Text("左右滑動看更早、雙指縮放；按住後拖曳查看每根 K 棒。")
                    }
                    .font(.caption2)
                    .foregroundStyle(Theme.secondary)
                    // 只提示第一次：離開畫面或開始選取後就不再出現。
                    .onDisappear { gestureHintSeen = true }
                }
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
        .onChange(of: selectedX) { _, new in
            if new != nil { gestureHintSeen = true }
        }
        .sheet(item: $guideSection) { section in
            KLineGuideView(convention: convention, initialSection: section)
        }
        .fullScreenCover(isPresented: $showingFullScreen) {
            MarketChartFullScreen(candles: candles, convention: convention, market: market, loadIntraday: loadIntraday,
                                  period: period, showsIntraday: showsIntraday)
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
                    guideSection = .candle
                } label: {
                    Label("看懂 K 線", systemImage: "questionmark.circle")
                }
                if !isFullScreen {
                    Button {
                        showingFullScreen = true
                    } label: {
                        Label("全螢幕", systemImage: "arrow.up.left.and.arrow.down.right")
                    }
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

    /// 指標直接按：不用先開選單再選。每列右邊的問號開到看懂 K 線的對應段落。
    private var indicatorRows: some View {
        VStack(alignment: .leading, spacing: 6) {
            optionRow("主圖", options: Overlay.allCases, selection: $overlay, label: \.rawValue, id: "chart.overlay", guide: .movingAverage)
            optionRow("副圖", options: Oscillator.allCases, selection: $oscillator, label: \.rawValue, id: "chart.oscillator", guide: .oscillator)
            HStack(spacing: 6) {
                rowTitle("標記")
                toggleChip("重點標記", isOn: $showsMarkers, id: "chart.markers")
                toggleChip("缺口交叉", isOn: $showsEvents, id: "chart.events")
                Spacer(minLength: 0)
                guideButton(.markers)
                if !isFullScreen {
                    Button {
                        showingFullScreen = true
                    } label: {
                        Image(systemName: "arrow.up.left.and.arrow.down.right")
                            .font(.caption)
                            .foregroundStyle(Theme.secondary)
                            .frame(width: 32, height: 34)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("全螢幕")
                    .accessibilityIdentifier("chart.fullscreen")
                }
            }
        }
        .onChange(of: overlay) { _, _ in hiddenLines = [] }
    }

    private func rowTitle(_ title: String) -> some View {
        Text(title)
            .font(.caption)
            .foregroundStyle(Theme.secondary)
            .frame(width: 30, alignment: .leading)
    }

    private func optionRow<Option: Identifiable & Hashable>(
        _ title: String,
        options: [Option],
        selection: Binding<Option>,
        label: @escaping (Option) -> String,
        id: String,
        guide: KLineGuideSection
    ) -> some View {
        HStack(spacing: 6) {
            rowTitle(title)
            ForEach(options) { option in
                let selected = option == selection.wrappedValue
                Button {
                    selection.wrappedValue = option
                } label: {
                    chip(label(option), active: selected)
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(selected ? .isSelected : [])
                .accessibilityIdentifier("\(id).\(label(option))")
            }
            Spacer(minLength: 0)
            guideButton(guide)
        }
    }

    private func toggleChip(_ title: String, isOn: Binding<Bool>, id: String) -> some View {
        Button {
            isOn.wrappedValue.toggle()
        } label: {
            chip(title, active: isOn.wrappedValue)
        }
        .buttonStyle(.plain)
        .accessibilityValue(isOn.wrappedValue ? "顯示中" : "已隱藏")
        .accessibilityIdentifier(id)
    }

    private func guideButton(_ section: KLineGuideSection) -> some View {
        Button {
            guideSection = section
        } label: {
            Image(systemName: "questionmark.circle")
                .font(.caption)
                .foregroundStyle(Theme.secondary)
                .frame(width: 32, height: 34)
        }
        .buttonStyle(.plain)
        .accessibilityLabel("看懂\(section.title)")
        .accessibilityIdentifier("chart.guide.\(section.rawValue)")
    }

    private func chip(_ title: String, active: Bool) -> some View {
        Text(title)
            .font(.caption.weight(.semibold))
            .lineLimit(1)
            .foregroundStyle(active ? Theme.text : Theme.secondary)
            .padding(.horizontal, 10)
            .frame(minHeight: 34)
            .background(active ? Theme.elevated : Theme.elevated.opacity(0.4), in: Capsule())
            .overlay {
                if active { Capsule().stroke(Theme.accent.opacity(0.6), lineWidth: 1) }
            }
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
                Text(selectedX != nil ? "選取" : candle.date == prepared.full.last?.date ? "最新" : "畫面最右")
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

    /// 副圖讀數列：顏色與線一致（DIF／K 黃、DEA／D 藍、柱依正負），一眼對得上是哪條線。
    private func oscillatorReadout(_ candle: ChartCandle?) -> some View {
        let point = candle.flatMap { candle in prepared.oscillator.first { $0.date == candle.date } }
        return HStack(spacing: 8) {
            Text(oscillatorTitle).foregroundStyle(Theme.secondary)
            if let point {
                switch oscillator {
                case .macd:
                    Text("DIF \(price(point.first))").foregroundStyle(Theme.warning)
                    Text("DEA \(point.second.map(price) ?? "—")").foregroundStyle(Theme.information)
                    Text("柱 \(point.histogram.map(price) ?? "—")")
                        .foregroundStyle(Theme.changeColor(point.histogram, convention: convention))
                case .kd:
                    Text("K \(price(point.first))").foregroundStyle(Theme.warning)
                    Text("D \(point.second.map(price) ?? "—")").foregroundStyle(Theme.information)
                case .rsi:
                    Text(price(point.first)).foregroundStyle(Theme.warning)
                case .none:
                    EmptyView()
                }
            }
            Spacer(minLength: 0)
        }
        .font(.caption2.monospacedDigit().weight(.semibold))
        .lineLimit(1)
        .minimumScaleFactor(0.85)
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("chart.oscillator.readout")
    }

    private func volumeReadout(_ candle: ChartCandle?) -> some View {
        let spike = candle.map { candle in prepared.spikes.contains { $0.date == candle.date } } == true ? "・爆量" : ""
        let volume = candle?.volume.map { VolumeDisplay.text($0, market: market) } ?? "未提供"
        return Text("\(period.label) 成交量 \(volume)\(spike)")
            .font(.caption2.monospacedDigit())
            .foregroundStyle(Theme.secondary)
            .lineLimit(1)
            .frame(maxWidth: .infinity, alignment: .leading)
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
        let inspectedCandle = selectedCandle
        let inspectedX = ChartViewport.selectedIndex(selectedX, barCount: prepared.full.count).map { Double($0) }
        let yDomain = priceDomain(data)
        let extremes = KeyPoints.extremes(Array(data))
        let latest = prepared.full.last
        let latestColor = Theme.changeColor(prepared.latestChange, convention: convention)
        let ticks = ChartViewport.axisTicks(barCount: prepared.full.count, visibleLength: visibleLength)
        // 跨年的視窗才標年／月，只寫月日會看不出是哪一年。
        let spansYear = (data.first?.date).flatMap { first in data.last.map { $0.date.timeIntervalSince(first) > 300 * 86_400 } } ?? false
        return Chart {
            if !prepared.band.isEmpty, !hiddenLines.contains(0) || !hiddenLines.contains(2) {
                ForEach(prepared.band, id: \.x) { point in
                    AreaMark(x: .value("序號", point.x), yStart: .value("下軌", point.lower), yEnd: .value("上軌", point.upper), series: .value("區域", "布林"))
                        .foregroundStyle(Theme.information.opacity(0.08))
                }
            }
            if showsEvents {
                ForEach(prepared.gaps, id: \.date) { gap in
                    RectangleMark(
                        xStart: .value("缺口起", Double(prepared.indexByDate[gap.date] ?? 0)),
                        xEnd: .value("缺口迄", fullDomain?.upperBound ?? 0),
                        yStart: .value("缺口下緣", gap.lower),
                        yEnd: .value("缺口上緣", gap.upper)
                    )
                    .foregroundStyle((gap.up ? Theme.changeColor(1, convention: convention) : Theme.changeColor(-1, convention: convention)).opacity(0.12))
                    .annotation(position: .topLeading, alignment: .leading, spacing: 2) {
                        if gap.date == prepared.gaps.last?.date {
                            Text("未補缺口").font(.system(size: 11, weight: .semibold)).foregroundStyle(Theme.secondary)
                        }
                    }
                }
            }
            ForEach(prepared.indexed) { item in
                let candle = item.candle
                if style == .candlestick {
                    let color = Theme.changeColor(candle.close - candle.open, convention: convention).opacity(candle.isProvisional ? 0.45 : 1)
                    RuleMark(
                        x: .value("序號", item.x),
                        yStart: .value("最低", candle.low),
                        yEnd: .value("最高", candle.high)
                    )
                    .foregroundStyle(color)
                    .lineStyle(StrokeStyle(lineWidth: 1))
                    RectangleMark(
                        xStart: .value("起點", item.x - ChartViewport.leadingPadding),
                        xEnd: .value("終點", item.x + ChartViewport.leadingPadding),
                        yStart: .value("開盤", min(candle.open, candle.close)),
                        // 開收相同（十字線）時給一條細線的高度，不然實體會消失。
                        yEnd: .value("收盤", max(candle.open, candle.close, min(candle.open, candle.close) + (yDomain.upperBound - yDomain.lowerBound) * 0.003))
                    )
                    .foregroundStyle(candle.open == candle.close ? Theme.secondary : color)
                } else {
                    AreaMark(x: .value("序號", item.x), yStart: .value("基準", yDomain.lowerBound), yEnd: .value("收盤", candle.close), series: .value("區域", "收盤"))
                        .foregroundStyle(LinearGradient(colors: [Theme.accent.opacity(0.25), Theme.accent.opacity(0)], startPoint: .top, endPoint: .bottom))
                    LineMark(x: .value("序號", item.x), y: .value("收盤", candle.close), series: .value("線", "收盤"))
                        .foregroundStyle(Theme.accent)
                        .lineStyle(StrokeStyle(lineWidth: 2))
                }
            }
            ForEach(prepared.lines.filter { !hiddenLines.contains($0.slot) }) { line in
                ForEach(line.points, id: \.date) { point in
                    LineMark(x: .value("序號", point.x), y: .value("指標", point.value), series: .value("線", line.name))
                        .foregroundStyle(line.color)
                        .lineStyle(StrokeStyle(lineWidth: 1.2))
                }
            }
            if showsMarkers {
                extremeMarks(extremes)
            }
            if showsEvents {
                crossMarks()
            }
            if let latest {
                // 實線：標籤在軸欄同一高度，圖內不留無字虛線。
                RuleMark(y: .value("最新價", latest.close))
                    .foregroundStyle(latestColor.opacity(0.5))
                    .lineStyle(StrokeStyle(lineWidth: 0.6))
            }
            if let inspectedCandle, let inspectedX {
                RuleMark(x: .value("選取", inspectedX))
                    .foregroundStyle(Theme.text.opacity(0.6))
                    .lineStyle(StrokeStyle(lineWidth: 1))
                PointMark(x: .value("選取", inspectedX), y: .value("收盤", inspectedCandle.close))
                    .foregroundStyle(Theme.accent)
                    .symbolSize(32)
            }
        }
        .chartLegend(.hidden)
        .chartYScale(domain: yDomain)
        .chartPlotStyle { $0.clipped() }
        .chartXSelection(value: $selectedX)
        .chartXAxis {
            AxisMarks(values: ticks) { value in
                AxisGridLine(stroke: StrokeStyle(lineWidth: 0.5)).foregroundStyle(Theme.border)
                AxisValueLabel(collisionResolution: .disabled) {
                    if let number = value.as(Double.self), let candle = ChartViewport.selectedIndex(number, barCount: prepared.full.count).map({ prepared.full[$0] }) {
                        Text(candle.date, format: spansYear ? TradingDay.yearMonthAxisStyle() : TradingDay.axisStyle())
                            .font(.caption2)
                            .foregroundStyle(Theme.secondary)
                    }
                }
            }
        }
        .chartYAxis {
            AxisMarks(position: .trailing, values: .automatic(desiredCount: 4)) { value in
                AxisGridLine(stroke: StrokeStyle(lineWidth: 0.5)).foregroundStyle(Theme.border)
                AxisValueLabel {
                    if let number = value.as(Double.self) {
                        axisLabel(number.formatted(.number.precision(.fractionLength(0...2))))
                    }
                }
            }
        }
        // 標籤畫在軸欄：放在圖內的 annotation 會被 clipped() 切掉。overlay 不攔手勢，拖曳選取才不受影響。
        .chartOverlay { proxy in
            GeometryReader { geometry in
                if let latest, yDomain.contains(latest.close), let plot = proxy.plotFrame, let y = proxy.position(forY: latest.close) {
                    Text(price(latest.close))
                        .font(.system(size: 11, weight: .bold).monospacedDigit())
                        .foregroundStyle(Theme.background)
                        .padding(.horizontal, 3)
                        .background(latestColor, in: RoundedRectangle(cornerRadius: 3))
                        .fixedSize()
                        .position(x: geometry.size.width - axisLabelWidth / 2, y: geometry[plot].minY + y)
                        .accessibilityIdentifier("chart.latestPrice")
                }
            }
            .allowsHitTesting(false)
        }
        .accessibilityLabel(style == .candlestick ? "\(period.label)線圖" : "收盤價走勢圖")
        .accessibilityIdentifier("chart.price")
    }

    @ChartContentBuilder
    private func extremeMarks(_ extremes: (high: ChartCandle, low: ChartCandle)?) -> some ChartContent {
        if let extremes {
            let highX = Double(prepared.indexByDate[extremes.high.date] ?? 0)
            let lowX = Double(prepared.indexByDate[extremes.low.date] ?? 0)
            PointMark(x: .value("區間高", highX), y: .value("高", extremes.high.high))
                .symbolSize(0)
                .annotation(position: .top, alignment: labelAlignment(highX), spacing: 2) {
                    markerLabel("高 \(price(extremes.high.high))")
                }
            PointMark(x: .value("區間低", lowX), y: .value("低", extremes.low.low))
                .symbolSize(0)
                .annotation(position: .bottom, alignment: labelAlignment(lowX), spacing: 2) {
                    markerLabel("低 \(price(extremes.low.low))")
                }
        }
    }

    /// 只標可見範圍內最近三次交叉、文字只寫最新一次；盤整時均線來回穿越，全標會糊成一片。
    @ChartContentBuilder
    private func crossMarks() -> some ChartContent {
        let range = visibleRange
        let recent = Array(prepared.crosses.filter { range.contains(Double(prepared.indexByDate[$0.date] ?? -1)) }.suffix(3))
        ForEach(recent, id: \.date) { cross in
            PointMark(x: .value("交叉", Double(prepared.indexByDate[cross.date] ?? 0)), y: .value("交叉價", cross.price))
                .symbol(.triangle)
                .symbolSize(36)
                .foregroundStyle(cross.golden ? Theme.warning : Theme.information)
                .annotation(position: cross.golden ? .bottom : .top, spacing: 2,
                            overflowResolution: .init(x: .fit(to: .chart), y: .fit(to: .chart))) {
                    if cross.date == recent.last?.date {
                        Text(cross.golden ? "黃金交叉" : "死亡交叉").font(.system(size: 11, weight: .semibold))
                            .foregroundStyle(cross.golden ? Theme.warning : Theme.information)
                    }
                }
        }
    }

    /// 標籤靠近視窗左右邊緣時往內側對齊，避免被軸線或畫面邊緣切掉。
    private func labelAlignment(_ x: Double) -> Alignment {
        let position = (x - scrollStart) / max(visibleLength, 1)
        return position > 0.8 ? .trailing : position < 0.2 ? .leading : .center
    }

    private func markerLabel(_ text: String) -> some View {
        Text(text)
            .font(.system(size: 11, weight: .semibold).monospacedDigit())
            .foregroundStyle(Theme.text)
            .padding(.horizontal, 4)
            .padding(.vertical, 1)
            .background(Theme.elevated.opacity(0.9), in: RoundedRectangle(cornerRadius: 4))
    }

    private func volumeChart(_ data: ArraySlice<ChartCandle>) -> some View {
        let peak = data.compactMap(\.volume).max() ?? 1
        let spikeDates = Set(prepared.spikes.map(\.date))
        return Chart(prepared.indexed) { item in
            if let volume = item.candle.volume {
                RectangleMark(
                    xStart: .value("起點", item.x - ChartViewport.leadingPadding),
                    xEnd: .value("終點", item.x + ChartViewport.leadingPadding),
                    yStart: .value("基準", 0),
                    yEnd: .value("成交量", volume)
                )
                .foregroundStyle(Theme.changeColor(item.candle.close - item.candle.open, convention: convention).opacity(spikeDates.contains(item.candle.date) && showsMarkers ? 0.95 : 0.45))
            }
        }
        .chartYScale(domain: 0...(peak * 1.1))
        .chartXSelection(value: $selectedX)
        .chartXAxis(.hidden)
        .chartYAxis {
            AxisMarks(position: .trailing, values: .automatic(desiredCount: 2)) { value in
                AxisValueLabel {
                    if let number = value.as(Double.self) {
                        axisLabel(VolumeDisplay.axisText(number, market: market))
                    }
                }
            }
        }
        .accessibilityLabel("\(period.label)成交量")
        .accessibilityIdentifier("chart.volume")
    }

    private func oscillatorChart() -> some View {
        let range = visibleRange
        let visible = prepared.oscillator.filter { range.contains($0.x) }
        let values = visible.flatMap { [$0.first, $0.second, $0.histogram].compactMap { $0 } }
        let domain: ClosedRange<Double> = oscillator == .macd ? ChartViewport.oscillatorDomain(values: values) : 0...100
        return Chart {
            if oscillator == .kd || oscillator == .rsi {
                let guides: [Double] = oscillator == .kd ? [20, 80] : [30, 70]
                ForEach(guides, id: \.self) { level in
                    RuleMark(y: .value("參考", level))
                        .foregroundStyle(Theme.border)
                        .lineStyle(StrokeStyle(lineWidth: 0.6))
                }
            }
            ForEach(prepared.oscillator, id: \.date) { point in
                if let histogram = point.histogram {
                    RectangleMark(xStart: .value("起點", point.x - ChartViewport.leadingPadding), xEnd: .value("終點", point.x + ChartViewport.leadingPadding),
                                  yStart: .value("零", 0), yEnd: .value("柱", histogram))
                        .foregroundStyle(Theme.changeColor(histogram, convention: convention).opacity(0.55))
                }
                LineMark(x: .value("序號", point.x), y: .value("主線", point.first), series: .value("線", "first"))
                    .foregroundStyle(Theme.warning)
                    .lineStyle(StrokeStyle(lineWidth: 1.2))
                if let second = point.second {
                    LineMark(x: .value("序號", point.x), y: .value("訊號線", second), series: .value("線", "second"))
                        .foregroundStyle(Theme.information)
                        .lineStyle(StrokeStyle(lineWidth: 1.2))
                }
            }
        }
        .chartLegend(.hidden)
        .chartYScale(domain: domain)
        .chartXSelection(value: $selectedX)
        .chartXAxis(.hidden)
        .chartYAxis {
            AxisMarks(position: .trailing, values: .automatic(desiredCount: 3)) { value in
                AxisGridLine(stroke: StrokeStyle(lineWidth: 0.5)).foregroundStyle(Theme.border)
                AxisValueLabel {
                    if let number = value.as(Double.self) {
                        axisLabel(price(number))
                    }
                }
            }
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

    /// 負號依詞彙表用 U+2212（MACD 讀數與軸標會是負值）。
    private func price(_ value: Double) -> String {
        value.formatted(.number.precision(.fractionLength(0...2))).replacingOccurrences(of: "-", with: "−")
    }

    private func axisLabel(_ text: String) -> some View {
        Text(text).font(.caption2).foregroundStyle(Theme.secondary)
            .lineLimit(1)
            .frame(width: axisLabelWidth, alignment: .leading)
    }
}

/// 全螢幕看圖：沿用同一批 K 棒與目前週期，不重抓行情。
private struct MarketChartFullScreen: View {
    let candles: [ChartCandle]
    let convention: MarketColorConvention
    let market: String
    let loadIntraday: IntradayLoaders?
    let period: CandlePeriod
    let showsIntraday: Bool
    @Environment(\.dismiss) private var dismiss

    /// 全螢幕下面板、控制列以外的高度都給主圖。
    private static let reservedHeight: CGFloat = 640

    var body: some View {
        NavigationStack {
            GeometryReader { geometry in
                ScrollView {
                    MarketChart(candles: candles, convention: convention, market: market, loadIntraday: loadIntraday,
                                isFullScreen: true, initialPeriod: period, initialShowsIntraday: showsIntraday,
                                extraPriceHeight: max(geometry.size.height - Self.reservedHeight, 0))
                        .padding(.horizontal, 12)
                }
            }
            .background(Theme.background.ignoresSafeArea())
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("完成") { dismiss() }
                        .accessibilityIdentifier("chart.fullscreen.done")
                }
            }
        }
    }
}
