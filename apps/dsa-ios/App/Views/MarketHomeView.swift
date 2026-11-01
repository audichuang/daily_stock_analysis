import SwiftUI
import DSACore

struct MarketHomeView: View {
    private static let visibleLimit = 12

    @EnvironmentObject private var store: AppStore
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @State private var searching = false
    @AppStorage("today.sort") private var sortStorage = StockSort.biggestMove.storage

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                MarketPicker()
                indexSection
                marketStatusRow
                reviewCard
                assetCard
                UpcomingEventsCard()
                watchlistSection
                Text("下拉更新 · \(store.refreshedAt.map { $0.formatted(date: .omitted, time: .shortened) } ?? "尚未更新")　AI 評分不是勝率")
                    .font(.caption2).foregroundStyle(Theme.secondary)
            }
            .overlay(alignment: .bottom) { PageBottomAnchor() }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
            .frame(maxWidth: 900, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
        .dsaPageBottomInset()
        .background(Theme.background)
        .navigationTitle("今日").navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button { searching = true } label: { Image(systemName: "magnifyingglass") }
                    .accessibilityLabel("搜尋股票")
            }
        }
        .refreshable { await store.refresh() }
        .sheet(isPresented: $searching) { NavigationStack { StockSearchView() } }
    }

    // MARK: - 指數

    /// 內容、錯誤、載入、空四選一。
    @ViewBuilder private var indexSection: some View {
        if !store.indices.isEmpty {
            indexStrip
        } else if let error = store.errors["indices"] {
            ErrorStateView(message: error) { Task { await store.refresh() } }
        } else if store.indicesLoading || store.refreshing || store.refreshedAt == nil {
            indexSkeleton
        } else {
            Text("暫無此市場的指數行情")
                .font(.subheadline).foregroundStyle(Theme.secondary)
        }
    }

    private var indexColumns: [GridItem] {
        let count = store.indices.count
        let columns = dynamicTypeSize.isAccessibilitySize ? 1 : (count == 4 ? 2 : min(max(count, 1), 3))
        return Array(repeating: GridItem(.flexible(), spacing: 8), count: columns)
    }

    private var indexStrip: some View {
        LazyVGrid(columns: indexColumns, alignment: .leading, spacing: 8) {
            ForEach(store.indices) { IndexCard(index: $0) }
        }
    }

    private var indexSkeleton: some View {
        HStack(spacing: 8) {
            ForEach(0..<2, id: \.self) { _ in
                VStack(alignment: .leading, spacing: 5) {
                    Text("指數名稱").font(.caption)
                    Text("00,000.00").font(.headline)
                    Text("+0.00%").font(.subheadline)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 12).padding(.vertical, 10)
                .background(Theme.surface, in: RoundedRectangle(cornerRadius: DSARadius.card, style: .continuous))
            }
        }
        .redacted(reason: .placeholder)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("正在讀取市場行情")
    }

    /// 開收盤用品牌色與灰，紅綠只留給行情方向。狀態與報價時間併成一行：「休市 · 10/30 13:33」。
    @ViewBuilder private var marketStatusRow: some View {
        let phase = MarketPhaseLabel.text(store.marketPhase)
        let quotedAt = store.indices.compactMap(\.asOf).max().map(Self.shortQuoteTime)
        let line = [phase, quotedAt].compactMap { $0 }.joined(separator: " · ")
        if !line.isEmpty {
            HStack(spacing: 6) {
                if phase != nil {
                    Circle()
                        .fill(store.marketOpen == true ? Theme.accent : Theme.secondary)
                        .frame(width: 6, height: 6)
                        .accessibilityHidden(true)
                }
                Text(line)
                    .font(.caption.monospacedDigit()).foregroundStyle(Theme.secondary)
                    .lineLimit(1).minimumScaleFactor(0.8)
                Spacer(minLength: 0)
            }
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("today.market-status")
        }
    }

    /// ISO 時間轉「10/30 13:33」；解析不了的字串照舊顯示原值。
    private static func shortQuoteTime(_ value: String) -> String {
        let parser = ISO8601DateFormatter()
        parser.formatOptions = [.withInternetDateTime]
        if value.contains(".") { parser.formatOptions.insert(.withFractionalSeconds) }
        guard let date = parser.date(from: value) else { return DisplayFormat.time(value) }
        return DisplayFormatting.shortStamp(date)
    }

    // MARK: - 卡片

    /// 燈號＋立場＋一句話＋關鍵價；詳情還沒讀到或舊報告沒有 payload 時退回列表摘要。
    @ViewBuilder private var reviewCard: some View {
        if let review = matchingReview, let id = review.id {
            let payload = store.marketReviewPayloads[id]?.resolved(for: store.selectedMarket)
            let card = MarketReviewCardText.make(payload: payload, title: review.stockName, summary: review.analysisSummary,
                                                 oneSentence: review.oneSentence, createdAt: review.createdAt)
            NavigationLink { ResearchReportView(reportID: id) } label: {
                DSACard(style: .tinted(Theme.accent)) {
                    VStack(alignment: .leading, spacing: 6) {
                        HStack(spacing: 6) {
                            if let light = card.light {
                                Circle().fill(Self.lightColor(light)).frame(width: 8, height: 8)
                                    .accessibilityHidden(true)
                            }
                            if let lightText = card.lightText {
                                Text(lightText).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.text)
                            }
                            if card.lightText != nil, card.stanceText != nil {
                                Text("·").font(.subheadline).foregroundStyle(Theme.secondary).accessibilityHidden(true)
                            }
                            if let stance = card.stance, let stanceText = card.stanceText {
                                Text(stanceText).font(.subheadline.weight(.semibold)).foregroundStyle(Self.stanceColor(stance))
                            }
                            if card.light == nil, card.stance == nil {
                                Text("AI 盤勢").font(.caption.weight(.bold)).foregroundStyle(Theme.accent)
                            }
                            Spacer(minLength: 8)
                            if let date = card.date {
                                Text(date).font(.caption.monospacedDigit()).foregroundStyle(Theme.secondary)
                            }
                            Image(systemName: "chevron.right")
                                .font(.caption.weight(.semibold)).foregroundStyle(Theme.secondary)
                                .accessibilityHidden(true)
                        }
                        Text(card.line)
                            .font(.subheadline).foregroundStyle(Theme.text)
                            .lineLimit(2)
                            .multilineTextAlignment(.leading)
                            .frame(maxWidth: .infinity, alignment: .leading)
                        if let keyLevels = card.keyLevels {
                            Text(keyLevels)
                                .font(.caption.monospacedDigit()).foregroundStyle(Theme.secondary)
                                .lineLimit(1).minimumScaleFactor(0.8)
                        }
                    }
                }
                .contentShape(Rectangle())
                .accessibilityElement(children: .ignore)
                .accessibilityLabel(Self.reviewAccessibilityLabel(card))
                .accessibilityValue("分析時間 \(DisplayFormat.time(review.createdAt))")
                .accessibilityHint("點開查看完整複盤")
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("today.review")
        }
    }

    /// 燈號點用固定紅黃綠，不跟漲跌配色互換。
    private static func lightColor(_ light: MarketReviewCardText.Light) -> Color {
        switch light {
        case .green: return Theme.down
        case .yellow: return Theme.warning
        case .red: return Theme.danger
        }
    }

    /// 立場用品牌色、灰、琥珀，紅綠只留給行情方向。
    private static func stanceColor(_ stance: MarketReviewCardText.Stance) -> Color {
        switch stance {
        case .offensive: return Theme.accent
        case .balanced: return Theme.secondary
        case .defensive: return Theme.warning
        }
    }

    private static func reviewAccessibilityLabel(_ card: MarketReviewCardText) -> String {
        let heading = [card.lightText, card.stanceText].compactMap { $0 }.joined(separator: " · ")
        return (["AI 盤勢", heading.isEmpty ? nil : heading, card.line, card.keyLevels] as [String?])
            .compactMap { $0 }.joined(separator: "，")
    }

    @ViewBuilder private var assetCard: some View {
        if let summary = store.portfolioSummary?.todayAssetSummary {
            Button { store.selectedTab = 3 } label: {
                HStack(alignment: .firstTextBaseline, spacing: 12) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text(summary.consolidated ? "資產（\(summary.currency)）" : "\(summary.currency) 帳戶資產")
                            .font(.caption).foregroundStyle(Theme.secondary)
                        Text(DisplayFormatting.summaryMoney(summary.equity, currency: summary.currency))
                            .font(.title3.weight(.bold).monospacedDigit()).foregroundStyle(Theme.text)
                            .lineLimit(1).minimumScaleFactor(0.7)
                    }
                    Spacer(minLength: 8)
                    VStack(alignment: .trailing, spacing: 3) {
                        Text("今日損益").font(.caption).foregroundStyle(Theme.secondary)
                        Text(StockListFormat.signedNumber(summary.dayPnl.map { $0.rounded() }))
                            .font(.subheadline.weight(.semibold).monospacedDigit())
                            .foregroundStyle(Theme.changeColor(summary.dayPnl, convention: store.colorConvention))
                            .lineLimit(1).minimumScaleFactor(0.7)
                    }
                }
                .modifier(FlatCardModifier())
                .contentShape(Rectangle())
                .accessibilityElement(children: .combine)
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("today.assets")
        } else if store.portfolioSummaryFailed {
            HStack {
                Text("暫時無法讀取資產").font(.caption).foregroundStyle(Theme.secondary)
                Spacer()
                Button("重試") { store.retryPortfolioSummary() }
                    .font(.caption).frame(minHeight: 44)
                    .accessibilityIdentifier("today.assets.retry")
            }
        }
    }

    // MARK: - 我的關注

    private var sortSelection: Binding<StockSort> {
        Binding(get: { StockSort(storage: sortStorage) ?? .biggestMove }, set: { sortStorage = $0.storage })
    }

    private var contentState: StockListContentState {
        let codes = visibleCodes
        return .resolve(codeCount: codes.count, hasLoaded: store.refreshedAt != nil,
                        listError: store.errors["watchlist"], quoteError: store.errors["quotes"],
                        missingQuotes: codes.filter { store.quote(for: $0) == nil }.count)
    }

    private var sortedCodes: [String] {
        (StockSort(storage: sortStorage) ?? .biggestMove).apply(to: visibleCodes.map { store.listEntry(for: $0) }).map(\.code)
    }

    private var watchlistSection: some View {
        VStack(spacing: 0) {
            HStack(alignment: .center) {
                Text("我的關注").font(.headline).foregroundStyle(Theme.text)
                // Cold start: the list is still empty, so a count here would read "0".
                if !watchlistLoading {
                    Text("\(visibleCodes.count)").font(.caption.monospacedDigit()).foregroundStyle(Theme.secondary)
                }
                Spacer()
                Picker("排序", selection: sortSelection) {
                    Text("異動大").tag(StockSort.biggestMove)
                    Text("自訂").tag(StockSort.custom)
                }
                .pickerStyle(.segmented)
                .frame(maxWidth: 150)
                .disabled(watchlistLoading)
                .accessibilityIdentifier("today.sort")
            }
            .frame(minHeight: 44)
            switch contentState {
            case .loading:
                ForEach(0..<5, id: \.self) { _ in StockRowSkeleton() }
            case let .failed(message):
                ErrorStateView(message: message) { Task { await store.refresh() } }
            case .empty:
                EmptyStateView(title: "建立你的觀察名單", message: "加入\(store.selectedMarket == "tw" ? "台股" : "美股")，一起查看行情與 AI 判斷。", systemImage: "plus.circle")
                Button("搜尋股票") { searching = true }.buttonStyle(PressableButtonStyle())
            case let .ready(banner):
                if let banner {
                    StockListBannerView(banner: banner) { Task { await store.refresh() } }
                        .padding(.bottom, 6)
                }
                marketListHeader
                LazyVStack(spacing: 0) {
                    ForEach(Array(sortedCodes.prefix(Self.visibleLimit)), id: \.self) { code in
                        NavigationLink { StockDetailView(code: code) } label: { StockRow(code: code) }
                            .buttonStyle(.plain)
                            .accessibilityIdentifier("stock-row.\(code)")
                    }
                }
                Button { store.selectedTab = 1 } label: {
                    HStack {
                        Text(remainingCount > 0 ? "查看其餘 \(remainingCount) 檔" : "全部自選股")
                        Spacer()
                        Image(systemName: "arrow.right")
                    }.font(.subheadline.weight(.semibold)).frame(minHeight: 44)
                }
                .buttonStyle(.plain).foregroundStyle(Theme.accent)
                .accessibilityIdentifier("today.show-all")
            }
        }
    }

    private var watchlistLoading: Bool {
        if case .loading = contentState { return true }
        return false
    }

    private var remainingCount: Int { max(visibleCodes.count - Self.visibleLimit, 0) }

    private var marketListHeader: some View {
        HStack(spacing: 8) {
            Text("名稱").frame(maxWidth: .infinity, alignment: .leading)
            if !dynamicTypeSize.isAccessibilitySize {
                Text("現價").stockRowPriceColumn()
                Text("漲跌幅").stockRowMetricColumn()
            }
        }
        .font(.caption2).foregroundStyle(Theme.secondary)
        .padding(.bottom, 4)
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
            Text("台股").tag("tw")
            Text("美股").tag("us")
        }
        .pickerStyle(.segmented).accessibilityIdentifier("market-picker")
    }
}

/// 等寬指數卡：點數＋漲跌幅；來源只有真的有值才顯示。
struct IndexCard: View {
    let index: MarketIndex
    @EnvironmentObject private var store: AppStore

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(index.name)
                .font(.caption.weight(.medium)).foregroundStyle(Theme.secondary)
                .lineLimit(1).minimumScaleFactor(0.8)
            Text(DisplayFormat.number(index.current))
                .font(.headline.monospacedDigit()).foregroundStyle(Theme.text)
                .lineLimit(1).minimumScaleFactor(0.7)
            Text(DisplayFormat.percent(index.changePct))
                .font(.subheadline.weight(.semibold).monospacedDigit())
                .foregroundStyle(Theme.changeColor(index.changePct, convention: store.colorConvention))
                .lineLimit(1).minimumScaleFactor(0.7)
            if delayed {
                Text("延遲報價")
                    .font(.caption2.weight(.semibold)).foregroundStyle(Theme.warning)
                    .lineLimit(1)
            }
        }
        .modifier(FlatCardModifier())
        .accessibilityElement(children: .combine)
    }

    /// 只有備援或延遲來源才提示；正常的即時來源不印名字。
    private var delayed: Bool {
        let value = (index.sourceCode ?? index.source)?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() ?? ""
        return ["fallback", "yfinance"].contains(value)
    }
}

/// DSACard(.flat) as a modifier, for views that already build their own content stack.
private struct FlatCardModifier: ViewModifier {
    func body(content: Content) -> some View {
        DSACard(style: .flat) { content }
    }
}
