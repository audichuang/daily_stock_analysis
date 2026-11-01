import DSACore
import SwiftUI

/// 右兩欄的固定寬度；欄頭與列共用，數字才對得齊。
private struct StockRowColumnWidth: ViewModifier {
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @ScaledMetric private var width: CGFloat
    private let alignment: Alignment

    init(width: CGFloat, alignment: Alignment) {
        _width = ScaledMetric(wrappedValue: width, relativeTo: .subheadline)
        self.alignment = alignment
    }

    func body(content: Content) -> some View {
        if dynamicTypeSize.isAccessibilitySize {
            content
        } else {
            content.frame(width: width, alignment: alignment)
        }
    }
}

extension View {
    func stockRowPriceColumn() -> some View {
        modifier(StockRowColumnWidth(width: 78, alignment: .trailing))
    }

    func stockRowMetricColumn() -> some View {
        modifier(StockRowColumnWidth(width: 74, alignment: .trailing))
    }
}

/// 今日與自選共用的股票列：名稱／現價／右欄，每欄主要與次要兩行。標準字級 54pt。
struct StockRow: View {
    let code: String
    var metric: StockRowMetric = .changePercent
    @EnvironmentObject private var store: AppStore
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    private var quote: StockQuote? { store.quote(for: code) }
    private var report: HistoryItem? { store.latestReport(for: code) }
    private var titles: StockRowTitles {
        StockRowTitles(code: code, name: quote?.stockName ?? report?.stockName)
    }
    private var warning: String? {
        StockRowWarning.text(hasQuote: quote != nil, isStale: quote?.isStale, sourceCode: quote?.sourceCode,
                             source: quote?.source, code: code)
    }
    private var limit: LimitProximity? {
        LimitProximity.of(price: quote?.currentPrice, limitUp: quote?.limitUp, limitDown: quote?.limitDown)
    }

    var body: some View {
        Group {
            if dynamicTypeSize.isAccessibilitySize {
                VStack(alignment: .leading, spacing: 8) {
                    identity
                    HStack(spacing: 12) {
                        priceColumn
                        Spacer(minLength: 8)
                        metricColumn
                    }
                }
                .padding(.vertical, 8)
            } else {
                HStack(alignment: .center, spacing: 8) {
                    identity
                    priceColumn.stockRowPriceColumn()
                    metricColumn.stockRowMetricColumn()
                }
            }
        }
        .frame(maxWidth: .infinity, minHeight: 54, alignment: .leading)
        .contentShape(Rectangle())
        .overlay(alignment: .bottom) { Rectangle().fill(Theme.border).frame(height: 0.5) }
        .accessibilityElement(children: .combine)
        .accessibilityHint("查看報價時間、來源與完整 AI 分析")
    }

    private var identity: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 5) {
                Text(titles.primary)
                    .font(.subheadline.weight(.semibold)).foregroundStyle(Theme.text)
                    .lineLimit(dynamicTypeSize.isAccessibilitySize ? nil : 1)
                if store.isHeld(code) {
                    Text("持")
                        .font(.caption2.weight(.bold)).foregroundStyle(Theme.accent)
                        .accessibilityLabel("持股")
                        .fixedSize()
                }
            }
            secondaryLine
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var secondaryLine: some View {
        HStack(spacing: 5) {
            if let secondary = titles.secondary {
                Text(secondary)
                    .font(.caption2.monospacedDigit()).foregroundStyle(Theme.secondary)
                    .lineLimit(1).layoutPriority(-1)
            }
            if let advice = PresentationText.action(report?.action, label: report?.actionLabel, advice: report?.operationAdvice) {
                Text("AI \(advice)")
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(ActionTone.of(action: report?.action, label: report?.actionLabel ?? report?.operationAdvice).color)
                    .lineLimit(1)
            }
            if let warning {
                Label(warning, systemImage: quote == nil ? "exclamationmark.circle" : "clock")
                    .labelStyle(.titleAndIcon)
                    .font(.caption2).foregroundStyle(Theme.warning)
                    .lineLimit(1).fixedSize()
            } else if let age = ReportAge.staleLabel(createdAt: report?.createdAt) {
                Text(age)
                    .font(.caption2).foregroundStyle(Theme.secondary)
                    .lineLimit(1).fixedSize()
            }
        }
    }

    private var priceColumn: some View {
        VStack(alignment: .trailing, spacing: 2) {
            Text(DisplayFormat.number(quote?.currentPrice))
                .font(.subheadline.weight(.semibold).monospacedDigit())
                .foregroundStyle(Theme.text)
                .lineLimit(1).minimumScaleFactor(0.7)
                .accessibilityIdentifier("stock-price.\(code)")
            if let change = quote?.change {
                Text(StockListFormat.signedNumber(change))
                    .font(.caption2.monospacedDigit())
                    .foregroundStyle(changeColor)
                    .lineLimit(1).minimumScaleFactor(0.7)
            }
        }
    }

    @ViewBuilder private var metricColumn: some View {
        switch metric {
        case .changePercent:
            percentBadge
        case .amount:
            metricWithPercent(StockListFormat.amount(quote?.amount))
        case .volumeRatio:
            metricWithPercent(DisplayFormat.number(quote?.volumeRatio))
        }
    }

    private func metricWithPercent(_ value: String) -> some View {
        VStack(alignment: .trailing, spacing: 2) {
            Text(value)
                .font(.subheadline.weight(.semibold).monospacedDigit())
                .foregroundStyle(Theme.text)
                .lineLimit(1).minimumScaleFactor(0.7)
            Text(DisplayFormat.percent(quote?.changePercent))
                .font(.caption2.monospacedDigit())
                .foregroundStyle(changeColor)
                .lineLimit(1).minimumScaleFactor(0.7)
        }
    }

    /// 平常只有文字色；實心色塊留給近漲跌停，才看得出是例外。
    @ViewBuilder private var percentBadge: some View {
        let text = Text(DisplayFormat.percent(quote?.changePercent))
            .font(.subheadline.weight(.semibold).monospacedDigit())
            .lineLimit(1).minimumScaleFactor(0.7)
        if let limit {
            text
                .foregroundStyle(Theme.background)
                .padding(.horizontal, 6).padding(.vertical, 3)
                .background(Theme.changeColor(limit == .nearUp ? 1 : -1, convention: store.colorConvention),
                            in: RoundedRectangle(cornerRadius: 5))
                .accessibilityValue(limit == .nearUp ? "接近漲停" : "接近跌停")
        } else {
            text.foregroundStyle(changeColor)
        }
    }

    private var changeColor: Color {
        Theme.changeColor(quote?.changePercent, convention: store.colorConvention)
    }
}

/// 首次載入的佔位列，高度與 StockRow 相同，資料回來時版面不跳。
struct StockRowSkeleton: View {
    var body: some View {
        HStack(spacing: 8) {
            VStack(alignment: .leading, spacing: 4) {
                Text("股票名稱").font(.subheadline)
                Text("代號").font(.caption2)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            Text("000.00").font(.subheadline).stockRowPriceColumn()
            Text("+0.00%").font(.subheadline).stockRowMetricColumn()
        }
        .frame(minHeight: 54)
        .redacted(reason: .placeholder)
        .accessibilityHidden(true)
    }
}

/// 清單上方的狀態橫條：清單還能看，只提示哪裡不完整。
struct StockListBannerView: View {
    let banner: StockListBanner
    let retry: () -> Void

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "exclamationmark.triangle")
                .foregroundStyle(Theme.warning)
                .accessibilityHidden(true)
            Text(banner.title)
                .font(.caption).foregroundStyle(Theme.secondary)
                .frame(maxWidth: .infinity, alignment: .leading)
            if banner.canRetry {
                Button("重試", action: retry)
                    .font(.caption.weight(.semibold))
                    .buttonStyle(.plain)
                    .foregroundStyle(Theme.accent)
                    .frame(minHeight: 44)
                    .accessibilityIdentifier("stock-list.retry")
            }
        }
        .padding(.horizontal, 10)
        .frame(minHeight: 36)
        .background(Theme.warning.opacity(0.06), in: RoundedRectangle(cornerRadius: DSARadius.control))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("stock-list.banner")
    }
}
