import SwiftUI
import DSACore

struct MarketHomeView: View {
    @EnvironmentObject private var store: AppStore
    @State private var searching = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                MarketPicker()
                if let error = store.errors["indices"] { ErrorStateView(message: error) }
                if store.indices.isEmpty && store.refreshing {
                    LoadingStateView("正在讀取市場行情…")
                } else if store.indices.isEmpty && store.errors["indices"] == nil {
                    Text("暫無此市場的指數行情")
                        .font(.subheadline).foregroundStyle(Theme.secondary)
                }
                indexStrip
                if let review = matchingReview, let id = review.id {
                    NavigationLink { ResearchReportView(reportID: id) } label: {
                        HStack(alignment: .center, spacing: 10) {
                            VStack(alignment: .leading, spacing: 3) {
                                Text("AI 盤勢")
                                    .font(.caption.weight(.bold))
                                    .foregroundStyle(Theme.accent)
                                Text(String(DisplayFormat.time(review.createdAt).prefix(10)))
                                    .font(.caption2).foregroundStyle(Theme.secondary)
                                    .fixedSize(horizontal: true, vertical: false)
                            }
                            Text(review.analysisSummary ?? "閱讀最新大盤觀察")
                                .font(.subheadline)
                                .foregroundStyle(Theme.text)
                                .lineLimit(2)
                                .multilineTextAlignment(.leading)
                                .frame(maxWidth: .infinity, alignment: .leading)
                            Image(systemName: "chevron.right")
                                .font(.caption.weight(.semibold)).foregroundStyle(Theme.secondary)
                        }
                        .padding(12)
                        .frame(minHeight: 44)
                        .background(Theme.accent.opacity(0.06), in: RoundedRectangle(cornerRadius: 10))
                        .accessibilityElement(children: .combine)
                        .accessibilityValue("分析時間 \(DisplayFormat.time(review.createdAt))")
                    }.buttonStyle(.plain)
                }
                VStack(spacing: 0) {
                    HStack(alignment: .center) {
                        Text("我的關注").font(.headline).foregroundStyle(Theme.text)
                        Text("\(visibleCodes.count)").font(.caption.monospacedDigit()).foregroundStyle(Theme.secondary)
                        Spacer()
                        Button { searching = true } label: {
                            Image(systemName: "plus").frame(width: 44, height: 44)
                        }.accessibilityLabel("新增自選股")
                    }
                    marketListHeader
                    if let error = store.errors["watchlist"] { ErrorStateView(message: error) }
                    if visibleCodes.isEmpty {
                        EmptyStateView(title: "建立你的觀察名單", message: "加入\(store.selectedMarket == "tw" ? "台股" : "美股")，一起查看行情與 AI 判斷。", systemImage: "plus.circle")
                        Button("搜尋股票") { searching = true }.buttonStyle(PressableButtonStyle())
                    } else {
                        LazyVStack(spacing: 0) {
                            ForEach(Array(visibleCodes.prefix(12)), id: \.self) { code in
                                NavigationLink { StockDetailView(code: code) } label: { StockRow(code: code) }
                                    .buttonStyle(.plain)
                                    .accessibilityIdentifier("stock-row.\(code)")
                            }
                        }
                        Button { store.selectedTab = 1 } label: {
                            HStack {
                                Text("全部自選股")
                                Spacer()
                                Image(systemName: "arrow.right")
                            }.font(.subheadline.weight(.semibold)).frame(minHeight: 44)
                        }.buttonStyle(.plain).foregroundStyle(Theme.accent)
                    }
                }
                Text("下拉更新 · \(store.refreshedAt.map { $0.formatted(date: .omitted, time: .shortened) } ?? "尚未更新")　AI 評分不是勝率")
                    .font(.caption2).foregroundStyle(Theme.secondary)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
            .frame(maxWidth: 900, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
        .background(Theme.background)
        .navigationTitle("Daily Stock AI").navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button { searching = true } label: { Image(systemName: "magnifyingglass") }
                    .accessibilityLabel("搜尋股票")
            }
        }
        .refreshable { await store.refresh() }
        .sheet(isPresented: $searching) { NavigationStack { StockSearchView() } }
    }

    @ViewBuilder private var indexStrip: some View {
        if store.indices.count == 1, let index = store.indices.first {
            IndexCard(index: index, expanded: true)
        } else if !store.indices.isEmpty {
            ScrollView(.horizontal) {
                HStack(spacing: 8) {
                    ForEach(store.indices) { index in
                        IndexCard(index: index).frame(width: 158)
                    }
                }
            }.scrollIndicators(.hidden)
        }
    }

    private var marketListHeader: some View {
        HStack {
            Text("名稱 / AI 判斷")
            Spacer()
            Text("現價 / 漲跌")
        }
        .font(.caption2).foregroundStyle(Theme.secondary)
        .padding(.bottom, 6)
    }

    private var visibleCodes: [String] { store.watchlist.filter(store.isInMarket) }
    private var matchingReview: HistoryItem? {
        store.marketReviews.first { ($0.region ?? "").split(separator: ",").contains(Substring(store.selectedMarket)) }
    }
}

struct MarketPicker: View {
    @EnvironmentObject private var store: AppStore
    var body: some View {
        Picker("市場", selection: Binding(get: { store.selectedMarket }, set: { value in
            Task { await store.changeMarket(value) }
        })) {
            Text("台股 TAIWAN").tag("tw")
            Text("美股 US").tag("us")
        }
        .pickerStyle(.segmented).accessibilityIdentifier("market-picker")
    }
}

struct IndexCard: View {
    let index: MarketIndex
    var expanded = false
    @EnvironmentObject private var store: AppStore
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            if expanded && !dynamicTypeSize.isAccessibilitySize {
                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    Text(index.name).font(.caption.weight(.medium)).foregroundStyle(Theme.secondary)
                    Spacer(minLength: 4)
                    indexValue
                    indexChange
                }
            } else {
                Text(index.name).font(.caption.weight(.medium)).foregroundStyle(Theme.secondary)
                    .lineLimit(dynamicTypeSize.isAccessibilitySize ? nil : 1)
                indexValue
                indexChange
            }
            Text("\(PresentationText.source(index.source)) · \(DisplayFormat.time(index.asOf))")
                .font(.caption2).foregroundStyle(Theme.secondary)
                .lineLimit(dynamicTypeSize.isAccessibilitySize ? nil : 1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 12).padding(.vertical, 10)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: 10))
        .accessibilityElement(children: .combine)
    }

    private var indexValue: some View {
        Text(DisplayFormat.number(index.current))
            .font(.title3.weight(.bold).monospacedDigit())
            .foregroundStyle(Theme.text)
            .fixedSize(horizontal: true, vertical: false)
    }

    private var indexChange: some View {
        Text(DisplayFormat.percent(index.changePct))
            .font(.subheadline.weight(.semibold).monospacedDigit())
            .foregroundStyle(Theme.changeColor(index.changePct, convention: store.colorConvention))
            .fixedSize(horizontal: !dynamicTypeSize.isAccessibilitySize, vertical: false)
    }
}

struct StockRow: View {
    let code: String
    @EnvironmentObject private var store: AppStore
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @ScaledMetric(relativeTo: .title3) private var priceSize = 23.0

    private var quote: StockQuote? { store.quote(for: code) }
    private var report: HistoryItem? { store.latestReport(for: code) }
    private var changeColor: Color {
        Theme.changeColor(quote?.changePercent, convention: store.colorConvention)
    }

    var body: some View {
        Group {
            if dynamicTypeSize.isAccessibilitySize {
                VStack(alignment: .leading, spacing: 10) {
                    identity
                    prices
                }
            } else {
                HStack(alignment: .center, spacing: 14) {
                    identity
                    Spacer(minLength: 8)
                    prices
                }
            }
        }
        .padding(.vertical, 10)
        .frame(maxWidth: .infinity, minHeight: 64, alignment: .leading)
        .contentShape(Rectangle())
        .overlay(alignment: .bottom) { Rectangle().fill(Theme.border).frame(height: 0.5) }
        .accessibilityElement(children: .combine)
        .accessibilityHint("查看報價時間、來源與完整 AI 分析")
    }

    private var identity: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(quote?.stockName ?? report?.stockName ?? code)
                .font(.body.weight(.semibold)).foregroundStyle(Theme.text)
                .lineLimit(dynamicTypeSize.isAccessibilitySize ? nil : 1)
            HStack(spacing: 7) {
                Text(code).font(.caption.monospaced()).foregroundStyle(Theme.secondary)
                    .fixedSize(horizontal: true, vertical: false)
                if let advice = report?.actionLabel ?? report?.operationAdvice {
                    HStack(spacing: 4) {
                        Text("AI \(advice)")
                            .font(.caption2.weight(.medium)).foregroundStyle(Theme.accent)
                            .lineLimit(1)
                        Text(String(DisplayFormat.time(report?.createdAt).prefix(10)))
                            .font(.caption2).foregroundStyle(Theme.secondary)
                            .fixedSize(horizontal: true, vertical: false)
                    }
                }
            }
            if quote == nil {
                Text("報價暫不可用").font(.caption2).foregroundStyle(Theme.warning)
            } else if quote?.isStale == true {
                Label("報價已過期", systemImage: "clock")
                    .font(.caption2).foregroundStyle(Theme.warning)
            } else if ["fallback", "yfinance"].contains(quote?.source?.lowercased() ?? "") {
                Label("可能延遲", systemImage: "clock")
                    .font(.caption2).foregroundStyle(Theme.warning)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var prices: some View {
        VStack(alignment: .trailing, spacing: 4) {
            Text(DisplayFormat.number(quote?.currentPrice))
                .font(.system(size: priceSize, weight: .bold, design: .rounded).monospacedDigit())
                .foregroundStyle(Theme.text)
                .lineLimit(1).minimumScaleFactor(0.65)
                .fixedSize(horizontal: !dynamicTypeSize.isAccessibilitySize, vertical: false)
                .accessibilityIdentifier("stock-price.\(code)")
            Text(DisplayFormat.percent(quote?.changePercent))
                .font(.subheadline.weight(.bold).monospacedDigit())
                .foregroundStyle(quote?.changePercent == nil ? Theme.secondary : Theme.background)
                .padding(.horizontal, 8).padding(.vertical, 3)
                .frame(minWidth: 74, alignment: .center)
                .background(quote?.changePercent == nil ? Theme.elevated : changeColor, in: RoundedRectangle(cornerRadius: 5))
        }
        .fixedSize(horizontal: !dynamicTypeSize.isAccessibilitySize, vertical: false)
    }
}
