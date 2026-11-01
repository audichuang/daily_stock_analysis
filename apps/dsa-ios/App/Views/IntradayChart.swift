import Charts
import DSACore
import SwiftUI

/// 分時與近一月日線（用來對齊昨收）分開載入：分時一到就出圖，日線慢或失敗只影響昨收與漲跌。
struct IntradayLoaders {
    let day: () async throws -> StockTrend
    let daily: () async throws -> StockTrend
}

/// K 線與分時共用的面板高度。切換分頁時圖表總高不變，下方內容才不會跳動。
enum ChartLayout {
    static let price: CGFloat = 250
    static let volume: CGFloat = 62
    static let oscillator: CGFloat = 92
    static let readoutRow: CGFloat = 18
    static let spacing: CGFloat = 4

    /// K 線三個面板加兩列讀數的總高。
    static let total: CGFloat = price + readoutRow + volume + readoutRow + oscillator + spacing * 4
    /// 分時主圖：總高扣掉成交量與它的讀數列。
    static let intradayPrice: CGFloat = total - readoutRow - volume - spacing * 2
}

/// 分時圖：價格線與均價線、昨收中軸、右側％，下方是成交量。只在切到「分時」時才打 `/trend`。
/// x 軸固定是整個交易時段，時段本身沒有非交易日，所以不用 K 線的序號軸。
struct IntradayChart: View {
    let market: String
    let convention: MarketColorConvention
    let load: IntradayLoaders
    /// 全螢幕時多出來的主圖高度。
    var extraHeight: CGFloat = 0

    @State private var series: IntradaySeries?
    @State private var previousClose: Double?
    @State private var source: String?
    @State private var loading = false
    @State private var failure: String?
    @State private var selected: Date?
    /// 主圖與量圖左右軸欄同寬，兩張圖的 x 才會對齊。
    @ScaledMetric(relativeTo: .caption2) private var axisWidth: CGFloat = 50

    private var zone: TimeZone { IntradaySeries.timeZone(market) ?? .current }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let series, !series.points.isEmpty {
                header(series)
                VStack(alignment: .leading, spacing: ChartLayout.spacing) {
                    chart(series)
                        .frame(height: ChartLayout.intradayPrice + extraHeight)
                    volumeRow(series)
                        .frame(height: ChartLayout.readoutRow)
                    volumeChart(series)
                        .frame(height: ChartLayout.volume)
                }
                footnote(series)
            } else if loading {
                ProgressView("讀取分時…")
                    .frame(maxWidth: .infinity, minHeight: ChartLayout.total + extraHeight)
                    .foregroundStyle(Theme.secondary)
            } else {
                EmptyStateView(title: "沒有分時資料", message: failure ?? "這檔目前取不到當日走勢，可切回日 K 查看。")
                    .frame(minHeight: ChartLayout.total + extraHeight)
            }
        }
        .task { await refresh() }
        // 外層 K 線圖把時區設成 UTC（交易日標籤用）；分時要顯示市場當地時間，這裡蓋回來。
        .environment(\.timeZone, zone)
        .accessibilityIdentifier("chart.intraday")
    }

    private func refresh() async {
        loading = true
        defer { loading = false }
        let parsed: IntradaySeries?
        do {
            let day = try await load.day()
            parsed = IntradaySeries(points: day.points, market: market)
            series = parsed
            source = day.source
            failure = nil
        } catch is CancellationError {
            return
        } catch {
            failure = error.localizedDescription
            return
        }
        loading = false
        // 日線抓不到就不顯示昨收與漲跌，不拿頁面載入時的報價昨收湊（開過夜會錯日）。
        if let parsed, let daily = try? await load.daily() {
            previousClose = parsed.previousClose(from: daily.points)
        }
    }

    private func color(for price: Double) -> Color {
        guard let previousClose else { return Theme.accent }
        return Theme.changeColor(price - previousClose, convention: convention)
    }

    private func inspected(_ series: IntradaySeries) -> IntradaySeries.Point? {
        guard let selected else { return series.points.last }
        return series.points.min { abs($0.time.timeIntervalSince(selected)) < abs($1.time.timeIntervalSince(selected)) }
    }

    /// 與 K 線讀數同樣的兩行：第一行時間與資料截至，第二行價格、漲跌、昨收、均價。
    private func header(_ series: IntradaySeries) -> some View {
        let point = inspected(series)
        return VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                if let point {
                    Text(clock(point.time)).foregroundStyle(Theme.text)
                }
                if let asOf = series.asOf {
                    Text("資料截至 \(clock(asOf))").foregroundStyle(Theme.secondary)
                }
                Spacer(minLength: 0)
                Text(selected == nil ? "最新" : "選取").foregroundStyle(Theme.secondary)
            }
            .font(.caption.weight(.medium))
            HStack(spacing: 8) {
                if let point {
                    Text(price(point.price))
                        .fontWeight(.semibold)
                        .foregroundStyle(color(for: point.price))
                    if let previousClose, previousClose > 0 {
                        let change = (point.price / previousClose - 1) * 100
                        Text(DisplayFormat.percent(change))
                            .foregroundStyle(color(for: point.price))
                        Text("昨收 \(price(previousClose))").foregroundStyle(Theme.secondary)
                    }
                    if let average = point.avgPrice {
                        Text("均價 \(price(average))").foregroundStyle(Theme.warning)
                    }
                }
                Spacer(minLength: 0)
            }
            .font(.caption.monospacedDigit())
        }
        .lineLimit(1)
        .minimumScaleFactor(0.8)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("chart.intraday.readout")
    }

    private func chart(_ series: IntradaySeries) -> some View {
        let scale = series.priceScale(previousClose: previousClose)
        let domain = scale.domain
        let lineColor = color(for: series.points.last?.price ?? 0)
        let point = selected == nil ? nil : inspected(series)
        let averages = series.points.filter { $0.avgPrice != nil }
        return Chart {
            ForEach(series.points) { point in
                AreaMark(x: .value("時間", point.time), yStart: .value("基準", domain.lowerBound), yEnd: .value("價格", point.price), series: .value("區域", "分時"))
                    .foregroundStyle(LinearGradient(colors: [lineColor.opacity(0.28), lineColor.opacity(0)], startPoint: .top, endPoint: .bottom))
                LineMark(x: .value("時間", point.time), y: .value("價格", point.price), series: .value("線", "分時"))
                    .foregroundStyle(lineColor)
                    .lineStyle(StrokeStyle(lineWidth: 1.6))
            }
            ForEach(averages) { point in
                LineMark(x: .value("時間", point.time), y: .value("均價", point.avgPrice ?? point.price), series: .value("線", "均價"))
                    .foregroundStyle(Theme.warning)
                    .lineStyle(StrokeStyle(lineWidth: 1.1))
            }
            if let previousClose, scale.centered {
                RuleMark(y: .value("昨收", previousClose))
                    .foregroundStyle(Theme.secondary.opacity(0.8))
                    .lineStyle(StrokeStyle(lineWidth: 0.8, dash: [4, 3]))
                    .annotation(position: .top, alignment: .leading, spacing: 1) {
                        Text("昨收").font(.caption2).foregroundStyle(Theme.secondary)
                    }
            }
            if let point {
                RuleMark(x: .value("選取", point.time))
                    .foregroundStyle(Theme.text.opacity(0.6))
                    .lineStyle(StrokeStyle(lineWidth: 1))
                PointMark(x: .value("選取", point.time), y: .value("價格", point.price))
                    .foregroundStyle(lineColor)
                    .symbolSize(32)
            }
        }
        .chartLegend(.hidden)
        .chartXScale(domain: series.session)
        .chartYScale(domain: domain)
        .chartPlotStyle { $0.clipped() }
        .chartXSelection(value: $selected)
        .chartXAxis {
            AxisMarks(values: series.axisTicks) { value in
                AxisGridLine(stroke: StrokeStyle(lineWidth: 0.5)).foregroundStyle(Theme.border)
                // 開盤靠左、收盤靠右，標籤才會落在圖內且對齊兩端。
                AxisValueLabel(anchor: tickAnchor(index: value.index, count: value.count), collisionResolution: .disabled) {
                    if let date = value.as(Date.self) {
                        Text(clock(date)).font(.caption2).foregroundStyle(Theme.secondary)
                    }
                }
            }
        }
        .chartYAxis {
            AxisMarks(position: .leading, values: scale.ticks) { value in
                AxisGridLine(stroke: StrokeStyle(lineWidth: 0.5)).foregroundStyle(Theme.border)
                AxisValueLabel {
                    if let number = value.as(Double.self) {
                        axisColumn(price(number), tint: Theme.secondary, alignment: .leading)
                    }
                }
            }
            AxisMarks(position: .trailing, values: scale.ticks) { value in
                AxisValueLabel {
                    if let number = value.as(Double.self), let previousClose, previousClose > 0 {
                        axisColumn(DisplayFormat.percent((number / previousClose - 1) * 100),
                                   tint: Theme.changeColor(number - previousClose, convention: convention),
                                   alignment: .trailing)
                    } else {
                        Color.clear.frame(width: axisWidth, height: 1)
                    }
                }
            }
        }
        .overlay(alignment: edgeMarkerAlignment(series)) {
            if let previousClose, !scale.centered {
                // 大跳空：昨收不在圖上，標在它所在的那一側。
                let above = previousClose > (series.points.last?.price ?? previousClose)
                Text("昨收 \(price(previousClose)) \(above ? "↑" : "↓")")
                    .font(.caption2.monospacedDigit())
                    .foregroundStyle(Theme.secondary)
                    .padding(.horizontal, 4)
                    .background(Theme.surface.opacity(0.85))
                    .padding(.horizontal, axisWidth + 6)
                    .padding(.bottom, above ? 0 : 22)
                    .allowsHitTesting(false)
                    .accessibilityIdentifier("chart.intraday.edgeMarker")
            }
        }
        .accessibilityLabel("分時走勢圖")
    }

    private func edgeMarkerAlignment(_ series: IntradaySeries) -> Alignment {
        guard let previousClose, let last = series.points.last?.price else { return .topTrailing }
        return previousClose > last ? .topTrailing : .bottomTrailing
    }

    private func tickAnchor(index: Int, count: Int) -> UnitPoint {
        index == 0 ? .topLeading : index == count - 1 ? .topTrailing : .top
    }

    private func volumeRow(_ series: IntradaySeries) -> some View {
        let point = inspected(series)
        return Text("成交量 \(point?.volume.map { VolumeDisplay.text($0, market: market) } ?? "未提供")")
            .font(.caption2.monospacedDigit())
            .foregroundStyle(Theme.secondary)
            .lineLimit(1)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func volumeChart(_ series: IntradaySeries) -> some View {
        let bars = series.volumeBars
        let peak = max(bars.map(\.volume).max() ?? 1, 1)
        return Chart(bars) { bar in
            RuleMark(x: .value("時間", bar.time), yStart: .value("基準", 0), yEnd: .value("成交量", bar.volume))
                .foregroundStyle(Theme.changeColor(bar.change, convention: convention).opacity(0.6))
                .lineStyle(StrokeStyle(lineWidth: 1.5))
        }
        .chartLegend(.hidden)
        .chartXScale(domain: series.session)
        .chartYScale(domain: 0...(peak * 1.1))
        .chartXSelection(value: $selected)
        .chartXAxis(.hidden)
        .chartYAxis {
            AxisMarks(position: .leading, values: [peak]) { value in
                AxisValueLabel {
                    if let number = value.as(Double.self) {
                        axisColumn(VolumeDisplay.axisText(number, market: market), tint: Theme.secondary, alignment: .leading)
                    }
                }
            }
            AxisMarks(position: .trailing, values: [peak]) { _ in
                AxisValueLabel {
                    Color.clear.frame(width: axisWidth, height: 1)
                }
            }
        }
        .accessibilityLabel("分時成交量")
        .accessibilityIdentifier("chart.intraday.volume")
    }

    private func axisColumn(_ text: String, tint: Color, alignment: Alignment) -> some View {
        Text(text)
            .font(.caption2.monospacedDigit())
            .foregroundStyle(tint)
            .lineLimit(1)
            .frame(width: axisWidth, alignment: alignment)
    }

    private func footnote(_ series: IntradaySeries) -> some View {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = zone
        let today = calendar.isDate(series.points.last?.time ?? .distantPast, inSameDayAs: Date())
        return VStack(alignment: .leading, spacing: 3) {
            if !today {
                Text("今天不是交易日或尚未開盤，顯示最近一個交易日 \(series.sessionDay) 的走勢。")
                    .foregroundStyle(Theme.warning)
            }
            Text("分時來源：\(source ?? "未標示")　時間為市場當地時間")
                .foregroundStyle(Theme.secondary)
        }
        .font(.caption2)
    }

    /// 24 小時制、市場當地時間。`hour(.twoDigits(amPM: .omitted))` 會變成 12 小時制，15:55 印成 03:55。
    private func clock(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = zone
        formatter.dateFormat = "HH:mm"
        return formatter.string(from: date)
    }

    private func price(_ value: Double) -> String {
        value.formatted(.number.precision(.fractionLength(0...2)))
    }
}
