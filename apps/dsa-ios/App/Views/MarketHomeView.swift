import SwiftUI
import DSACore

struct MarketHomeView: View {
    @EnvironmentObject private var store: AppStore
    @State private var searching = false

    var body: some View {
        PageScroll {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 7) {
                    Text(Date.now.formatted(.dateTime.month().day().weekday(.wide)))
                        .font(.caption.weight(.medium)).foregroundStyle(Theme.secondary)
                    Text("讓判斷，有所依據。")
                        .font(.title2.weight(.bold)).foregroundStyle(Theme.text)
                }
                Spacer()
                BrandMark().frame(width: 40, height: 40)
            }
            MarketPicker()
            if let error = store.errors["indices"] { ErrorStateView(message: error) }
            if store.indices.isEmpty && store.refreshing { LoadingStateView("正在讀取市場行情…") }
            else if store.indices.isEmpty && store.errors["indices"] == nil {
                EmptyStateView(title: "尚無指數行情", message: "資料源尚未回傳此市場的指數。")
            }
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 150), alignment: .leading)], spacing: 12) {
                ForEach(store.indices) { index in IndexCard(index: index) }
            }
            if let review = matchingReview, let id = review.id {
                NavigationLink { ResearchReportView(reportID: id) } label: {
                    DSACard {
                        VStack(alignment: .leading, spacing: 14) {
                            HStack {
                                StatusBadge("AI 大盤觀察", tone: .ai, systemImage: "text.magnifyingglass")
                                Spacer()
                                Image(systemName: "arrow.up.right").foregroundStyle(Theme.accent)
                            }
                            Text(review.analysisSummary ?? "閱讀最新大盤複盤與風險觀察")
                                .font(.headline).foregroundStyle(Theme.text).lineLimit(5).multilineTextAlignment(.leading)
                            Text("分析時間 · \(DisplayFormat.time(review.createdAt))")
                                .font(.caption2).foregroundStyle(Theme.secondary)
                        }
                    }
                }.buttonStyle(.plain)
            }
            HStack {
                SectionHeading("我的關注", subtitle: "價格變化與最新 AI 觀點")
                Spacer()
                Button { searching = true } label: {
                    Image(systemName: "plus").frame(width: 44, height: 44)
                }.accessibilityLabel("新增自選股")
            }
            if let error = store.errors["watchlist"] { ErrorStateView(message: error) }
            if visibleCodes.isEmpty {
                EmptyStateView(title: "建立你的觀察名單", message: "加入\(store.selectedMarket == "tw" ? "台股" : "美股")，把行情與 AI 分析放在一起。", systemImage: "plus.circle")
                Button("搜尋股票") { searching = true }.buttonStyle(PressableButtonStyle())
            } else {
                VStack(spacing: 10) {
                    ForEach(Array(visibleCodes.prefix(8)), id: \.self) { code in
                        NavigationLink { StockDetailView(code: code) } label: { StockRow(code: code) }
                            .buttonStyle(.plain)
                    }
                }
                Button("查看全部自選股") { store.selectedTab = 1 }.buttonStyle(SecondaryButtonStyle())
            }
            Text("下拉更新 · \(store.refreshedAt.map { $0.formatted(date: .omitted, time: .shortened) } ?? "尚未更新")\n各筆資料來源與時間分別標示；AI 評分不是勝率。")
                .font(.caption2).foregroundStyle(Theme.secondary)
        }
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
    @EnvironmentObject private var store: AppStore
    var body: some View {
        DSACard {
            VStack(alignment: .leading, spacing: 10) {
                Text(index.name).font(.caption.weight(.semibold)).foregroundStyle(Theme.secondary)
                Text(DisplayFormat.number(index.current)).font(.title3.bold().monospacedDigit()).foregroundStyle(Theme.text)
                Text(DisplayFormat.percent(index.changePct)).font(.subheadline.bold().monospacedDigit())
                    .foregroundStyle(Theme.changeColor(index.changePct, convention: store.colorConvention))
                Text(DisplayFormat.source(index.source)).font(.system(size: 10)).foregroundStyle(Theme.secondary)
                Text(DisplayFormat.time(index.asOf)).font(.system(size: 10)).foregroundStyle(Theme.secondary)
            }
        }.accessibilityElement(children: .combine)
    }
}

struct StockRow: View {
    let code: String
    @EnvironmentObject private var store: AppStore
    var body: some View {
        let quote = store.quote(for: code)
        let report = store.latestReport(for: code)
        DSACard {
            VStack(alignment: .leading, spacing: 12) {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(quote?.stockName ?? report?.stockName ?? code).font(.headline).foregroundStyle(Theme.text)
                        Text(code).font(.caption.monospaced()).foregroundStyle(Theme.secondary)
                    }
                    Spacer(minLength: 12)
                    VStack(alignment: .trailing, spacing: 4) {
                        Text(DisplayFormat.number(quote?.currentPrice)).font(.headline.monospacedDigit()).foregroundStyle(Theme.text)
                        Text(DisplayFormat.percent(quote?.changePercent)).font(.caption.bold().monospacedDigit())
                            .foregroundStyle(Theme.changeColor(quote?.changePercent, convention: store.colorConvention))
                    }
                }
                if let advice = report?.actionLabel ?? report?.operationAdvice {
                    HStack(alignment: .top, spacing: 8) {
                        Text("AI").font(.caption2.bold()).foregroundStyle(Theme.accent)
                        Text(advice).font(.caption).foregroundStyle(Theme.secondary).lineLimit(2)
                        Spacer(minLength: 0)
                        Image(systemName: "chevron.right").font(.caption2).foregroundStyle(Theme.secondary)
                    }
                    Text("分析 · \(DisplayFormat.time(report?.createdAt))").font(.system(size: 10)).foregroundStyle(Theme.secondary)
                }
                if quote?.isStale == true { StatusBadge("資料已過期", tone: .warning) }
                Text(quote == nil ? "報價暫不可用" : "\(DisplayFormat.source(quote?.source)) · \(DisplayFormat.time(quote?.asOf ?? quote?.updateTime))")
                    .font(.system(size: 10)).foregroundStyle(Theme.secondary).lineLimit(2)
            }
        }.accessibilityElement(children: .combine)
    }
}
