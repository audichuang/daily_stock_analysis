import Charts
import DSACore
import SwiftUI

/// 分時與近一月日線（用來對齊昨收）分開載入：分時一到就出圖，日線慢或失敗只影響昨收與漲跌。
struct IntradayLoaders {
    let day: () async throws -> StockTrend
    let daily: () async throws -> StockTrend
}

/// 分時圖：當日價格線，以昨收為基準線，x 軸固定是整個交易時段。只在切到「分時」時才打 `/trend`。
struct IntradayChart: View {
    let market: String
    let convention: MarketColorConvention
    let load: IntradayLoaders

    @State private var series: IntradaySeries?
    @State private var previousClose: Double?
    @State private var source: String?
    @State private var loading = false
    @State private var failure: String?
    @State private var selected: Date?

    private var zone: TimeZone { IntradaySeries.timeZone(market) ?? .current }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let series, !series.points.isEmpty {
                header(series)
                chart(series)
                    .frame(height: 250)
                footnote(series)
            } else if loading {
                ProgressView("讀取分時…")
                    .frame(maxWidth: .infinity, minHeight: 250)
                    .foregroundStyle(Theme.secondary)
            } else {
                EmptyStateView(title: "沒有分時資料", message: failure ?? "這檔目前取不到當日走勢，可切回日 K 查看。")
                    .frame(minHeight: 250)
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

    private func header(_ series: IntradaySeries) -> some View {
        let point = inspected(series)
        return HStack(spacing: 10) {
            if let point {
                Text(clock(point.time))
                    .foregroundStyle(Theme.secondary)
                Text(price(point.price))
                    .foregroundStyle(color(for: point.price))
                if let previousClose, previousClose > 0 {
                    let change = (point.price / previousClose - 1) * 100
                    Text(DisplayFormat.percent(change))
                        .foregroundStyle(color(for: point.price))
                    Text("昨收 \(price(previousClose))").foregroundStyle(Theme.secondary)
                }
            }
            Spacer(minLength: 0)
            Text(selected == nil ? "最新" : "選取").foregroundStyle(Theme.secondary)
        }
        .font(.caption.monospacedDigit())
        .lineLimit(1)
        .minimumScaleFactor(0.8)
    }

    private func chart(_ series: IntradaySeries) -> some View {
        // 昨收不納入 Y 軸：跳空很大時（INTC 10/30 -28%）會把當日走勢壓成一條線；數值已在上方顯示。
        let prices = series.points.map(\.price)
        let lower = prices.min() ?? 0
        let upper = prices.max() ?? 1
        let margin = max((upper - lower) * 0.12, abs(upper) * 0.002, 0.01)
        let domain = (lower - margin)...(upper + margin)
        let lineColor = color(for: series.points.last?.price ?? 0)
        let point = selected == nil ? nil : inspected(series)
        return Chart {
            ForEach(series.points) { point in
                AreaMark(x: .value("時間", point.time), yStart: .value("基準", domain.lowerBound), yEnd: .value("價格", point.price), series: .value("區域", "分時"))
                    .foregroundStyle(LinearGradient(colors: [lineColor.opacity(0.28), lineColor.opacity(0)], startPoint: .top, endPoint: .bottom))
                LineMark(x: .value("時間", point.time), y: .value("價格", point.price), series: .value("線", "分時"))
                    .foregroundStyle(lineColor)
                    .lineStyle(StrokeStyle(lineWidth: 1.6))
            }
            if let previousClose, domain.contains(previousClose) {
                RuleMark(y: .value("昨收", previousClose))
                    .foregroundStyle(Theme.secondary.opacity(0.7))
                    .lineStyle(StrokeStyle(lineWidth: 0.8, dash: [4, 3]))
                    .annotation(position: .top, alignment: .leading, spacing: 1) {
                        Text("昨收").font(.system(size: 9)).foregroundStyle(Theme.secondary)
                    }
            }
            if let point {
                RuleMark(x: .value("選取", point.time))
                    .foregroundStyle(Theme.text.opacity(0.6))
                    .lineStyle(StrokeStyle(lineWidth: 1, dash: [4, 4]))
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
            AxisMarks(values: .automatic(desiredCount: 4)) { value in
                AxisGridLine(stroke: StrokeStyle(lineWidth: 0.5, dash: [3, 3])).foregroundStyle(Theme.border)
                AxisValueLabel {
                    if let date = value.as(Date.self) {
                        Text(clock(date)).font(.caption2).foregroundStyle(Theme.secondary)
                    }
                }
            }
        }
        .chartYAxis {
            AxisMarks(position: .trailing, values: .automatic(desiredCount: 4)) { value in
                AxisGridLine(stroke: StrokeStyle(lineWidth: 0.5, dash: [3, 3])).foregroundStyle(Theme.border)
                AxisValueLabel {
                    if let number = value.as(Double.self) {
                        Text(number.formatted(.number.precision(.fractionLength(0...2))))
                            .font(.caption2).foregroundStyle(Theme.secondary)
                    }
                }
            }
        }
        .accessibilityLabel("分時走勢圖")
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
