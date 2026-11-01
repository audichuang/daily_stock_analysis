import SwiftUI
import DSACore

private enum WatchlistRoute: Hashable {
    case stock(String)
    case report(Int)
}

private enum WatchlistGroup: String, CaseIterable, Identifiable {
    case all = "全部"
    case held = "持股"
    var id: String { rawValue }
}

struct WatchlistView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @State private var searching = false
    @State private var query = ""
    @State private var filterExpanded = false
    @State private var group = WatchlistGroup.all
    @State private var route: WatchlistRoute?
    @State private var actionError: String?
    @AppStorage("watchlist.sort") private var sortStorage = StockSort.custom.storage
    @AppStorage("watchlist.metric") private var metricStorage = StockRowMetric.changePercent.rawValue

    var body: some View {
        List {
            MarketPicker().plainRow(top: 12)
            indexLine
            content
            PageBottomAnchor().plainRow(horizontal: 0)
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
        .environment(\.defaultMinListRowHeight, 1)
        .dsaPageBottomInset()
        .background(Theme.background)
        .navigationTitle("自選股").navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItemGroup(placement: .topBarTrailing) {
                Button {
                    // 收起時一併清空，隱藏的條件不能繼續篩掉清單。
                    if filterExpanded { query = "" }
                    filterExpanded.toggle()
                } label: {
                    Image(systemName: filterExpanded ? "line.3.horizontal.decrease.circle.fill" : "line.3.horizontal.decrease.circle")
                }
                .accessibilityLabel(filterExpanded ? "收合篩選" : "展開篩選")
                .accessibilityIdentifier("watchlist.filter")
                Button { searching = true } label: { Image(systemName: "plus") }
                    .accessibilityLabel("新增自選股")
            }
        }
        .refreshable { await store.refresh() }
        .sheet(isPresented: $searching) { NavigationStack { StockSearchView() } }
        .navigationDestination(item: $route) { route in
            switch route {
            case let .stock(code): StockDetailView(code: code)
            case let .report(id): ResearchReportView(reportID: id)
            }
        }
    }

    // MARK: - 內容

    /// 骨架、失敗、沒有自選、清單四選一。
    @ViewBuilder private var content: some View {
        switch contentState {
        case .loading:
            ForEach(0..<6, id: \.self) { _ in StockRowSkeleton().plainRow() }
        case let .failed(message):
            ErrorStateView(message: message) { Task { await store.refresh() } }
                .accessibilityIdentifier("watchlist.error")
                .plainRow()
        case .empty:
            EmptyStateView(title: "這個市場還沒有自選股", message: "點右上角加入股票，隨時查看行情與 AI 觀點。")
                .accessibilityIdentifier("watchlist.empty")
                .plainRow()
        case let .ready(banner):
            controls(banner: banner)
            if visible.isEmpty {
                filteredEmpty.plainRow()
            } else {
                ForEach(visible, id: \.self) { code in row(code) }
            }
        }
    }

    @ViewBuilder private func controls(banner: StockListBanner?) -> some View {
        if let banner {
            StockListBannerView(banner: banner) { Task { await store.refresh() } }.plainRow()
        }
        if let actionError {
            Text(actionError)
                .font(.caption).foregroundStyle(Theme.warning)
                .accessibilityIdentifier("watchlist.action-error")
                .plainRow()
        }
        Picker("分組", selection: $group) {
            ForEach(WatchlistGroup.allCases) { Text($0.rawValue).tag($0) }
        }
        .pickerStyle(.segmented)
        .accessibilityIdentifier("watchlist.group")
        .plainRow()
        if filterExpanded {
            TextField("篩選代號或名稱", text: $query)
                .textFieldStyle(.roundedBorder)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .accessibilityIdentifier("watchlist.filter-field")
                .plainRow()
        }
        summaryLine.plainRow()
        columnHeader.plainRow()
    }

    private func row(_ code: String) -> some View {
        // 用 Button 加 navigationDestination：List 裡的 NavigationLink 會多一個箭頭，也不保證是 button 元素。
        Button { route = .stock(code) } label: { StockRow(code: code, metric: metric) }
            .buttonStyle(.plain)
            .accessibilityIdentifier("stock-row.\(code)")
            .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                Button(role: .destructive) { remove(code) } label: {
                    Label("移除", systemImage: "trash")
                }
            }
            .contextMenu {
                Button { route = .stock(code) } label: { Label("查看個股", systemImage: "chart.line.uptrend.xyaxis") }
                if let id = store.latestReport(for: code)?.id {
                    Button { route = .report(id) } label: { Label("查看最新報告", systemImage: "doc.text") }
                }
                Button(role: .destructive) { remove(code) } label: { Label("移除自選", systemImage: "trash") }
            }
            .plainRow()
    }

    @ViewBuilder private var filteredEmpty: some View {
        if group == .held && query.isEmpty && store.portfolioSummary == nil && store.portfolioSummaryFailed {
            // 讀不到帳本時不能說成「沒有持股」。
            VStack(spacing: 8) {
                Text("暫時無法讀取持股").font(.subheadline).foregroundStyle(Theme.secondary)
                Button("重試") { store.retryPortfolioSummary() }.frame(minHeight: 44)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 24)
        } else {
            EmptyStateView(title: query.isEmpty ? "這個市場的自選沒有持股" : "沒有符合的自選股",
                           message: query.isEmpty ? "切回「全部」可查看所有自選。" : "換個代號或名稱再試。")
        }
    }

    // MARK: - 指數與摘要

    /// 單行：一行放不下（美股多於兩檔）才橫捲。
    @ViewBuilder private var indexLine: some View {
        if !store.indices.isEmpty {
            Group {
                if store.indices.count <= 2 {
                    HStack(spacing: 12) {
                        ForEach(store.indices) { indexItem($0).frame(maxWidth: .infinity, alignment: .leading) }
                    }
                } else {
                    ScrollView(.horizontal) {
                        HStack(spacing: 16) { ForEach(store.indices) { indexItem($0) } }
                    }
                    .scrollIndicators(.hidden)
                }
            }
            .accessibilityIdentifier("watchlist.indices")
            .plainRow()
        }
    }

    private func indexItem(_ index: MarketIndex) -> some View {
        HStack(spacing: 5) {
            Text(index.name).foregroundStyle(Theme.secondary).lineLimit(1).minimumScaleFactor(0.8)
            Text(DisplayFormat.number(index.current)).foregroundStyle(Theme.text).lineLimit(1)
                .layoutPriority(1)
            Text(DisplayFormat.percent(index.changePct))
                .foregroundStyle(Theme.changeColor(index.changePct, convention: store.colorConvention))
                .lineLimit(1).layoutPriority(1)
        }
        .font(.caption.monospacedDigit())
        .accessibilityElement(children: .combine)
    }

    private var summaryLine: some View {
        let codes = marketCodes
        let summary = StockListSummary(
            entries: codes.map { store.listEntry(for: $0) },
            actions: codes.map { code in
                let report = store.latestReport(for: code)
                return DecisionAction.resolve(action: report?.action, label: report?.actionLabel)
            },
            quoteTimes: codes.map { store.quote(for: $0)?.asOf }
        )
        return HStack(spacing: 8) {
            Text("漲 \(summary.up)").foregroundStyle(Theme.changeColor(1, convention: store.colorConvention))
            Text("跌 \(summary.down)").foregroundStyle(Theme.changeColor(-1, convention: store.colorConvention))
            Text("平 \(summary.flat)").foregroundStyle(Theme.secondary)
            Text("動作 \(summary.actionCount)").foregroundStyle(Theme.accent)
            Spacer(minLength: 4)
            if let quotedAt = summary.latestQuoteAt {
                Text(DisplayFormat.time(quotedAt))
                    .foregroundStyle(Theme.secondary)
                    .lineLimit(1).minimumScaleFactor(0.7)
            }
        }
        .font(.caption2.monospacedDigit())
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("watchlist.summary")
    }

    private var columnHeader: some View {
        HStack(spacing: 8) {
            sortButton("名稱", key: .name, id: "name")
                .frame(maxWidth: .infinity, alignment: .leading)
            if !dynamicTypeSize.isAccessibilitySize {
                sortButton("現價", key: .price, id: "price").stockRowPriceColumn()
                HStack(spacing: 0) {
                    sortButton(metric.title, key: metric.sortKey, id: "metric")
                    Menu {
                        ForEach(StockRowMetric.allCases) { option in
                            Button(option.title) { select(option) }
                        }
                    } label: {
                        Image(systemName: "chevron.down")
                            .font(.caption2)
                            .frame(width: 18, height: 32)
                    }
                    .accessibilityLabel("切換右欄")
                    .accessibilityIdentifier("watchlist.metric-menu")
                }
                .stockRowMetricColumn()
            }
        }
        .font(.caption2)
        .foregroundStyle(Theme.secondary)
    }

    private func sortButton(_ title: String, key: StockSortKey, id: String) -> some View {
        let active = sort.key == key
        return Button {
            sortStorage = sort.tapped(key).storage
        } label: {
            Text(active ? "\(title) \(sort.ascending ? "↑" : "↓")" : title)
                .fontWeight(active ? .semibold : .regular)
                .foregroundStyle(active ? Theme.text : Theme.secondary)
                .lineLimit(1).minimumScaleFactor(0.8)
                .frame(minHeight: 32)
        }
        .buttonStyle(.plain)
        .accessibilityValue(active ? (sort.ascending ? "遞增" : "遞減") : "未排序")
        .accessibilityIdentifier("watchlist.sort.\(id)")
    }

    // MARK: - 狀態

    private var sort: StockSort { StockSort(storage: sortStorage) ?? .custom }
    private var metric: StockRowMetric { StockRowMetric(rawValue: metricStorage) ?? .changePercent }
    private var marketCodes: [String] { store.watchlist.filter(store.isInMarket) }

    private var contentState: StockListContentState {
        let codes = marketCodes
        return .resolve(codeCount: codes.count, hasLoaded: store.refreshedAt != nil,
                        listError: store.errors["watchlist"], quoteError: store.errors["quotes"],
                        missingQuotes: codes.filter { store.quote(for: $0) == nil }.count)
    }

    private var visible: [String] {
        let entries = marketCodes.map { store.listEntry(for: $0) }.filter { entry in
            (group == .all || store.isHeld(entry.code))
                && (query.isEmpty || entry.code.localizedCaseInsensitiveContains(query)
                    || (entry.name ?? "").localizedCaseInsensitiveContains(query))
        }
        return sort.apply(to: entries).map(\.code)
    }

    private func select(_ option: StockRowMetric) {
        sortStorage = sort.switching(to: option).storage
        metricStorage = option.rawValue
    }

    private func remove(_ code: String) {
        Task {
            do { try await store.removeFromWatchlist(code); actionError = nil }
            catch { actionError = error.localizedDescription }
        }
    }
}

private extension View {
    /// 自選頁的 List 只當捲動容器用：背景與分隔線都自己畫，列距貼齊其他分頁。
    func plainRow(horizontal: CGFloat = 16, top: CGFloat = 0, bottom: CGFloat = 0) -> some View {
        listRowInsets(EdgeInsets(top: top, leading: horizontal, bottom: bottom, trailing: horizontal))
            .listRowSeparator(.hidden)
            .listRowBackground(Color.clear)
    }
}

struct StockSearchView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.dismiss) private var dismiss
    @State private var query = ""
    @State private var market = "all"
    @State private var error: String?
    @State private var loading = false
    @State private var adding: Set<String> = []

    var body: some View {
        PageScroll {
            Picker("搜尋市場", selection: $market) {
                Text("全部").tag("all")
                Text("台股").tag("tw")
                Text("美股").tag("us")
            }.pickerStyle(.segmented)
            if loading { LoadingStateView("載入股票索引…") }
            if let error { ErrorStateView(message: error, retry: { Task { await load() } }) }
            if matches.isEmpty && !loading && error == nil {
                EmptyStateView(title: "沒有符合的股票", message: "可輸入名稱、台股完整代號（2330.TW）或美股代號（AAPL）。")
            }
            ForEach(matches) { stock in
                HStack(spacing: 4) {
                NavigationLink { StockDetailView(code: stock.canonicalCode) } label: {
                    HStack(spacing: 12) {
                        Text(stock.canonicalCode.hasSuffix(".TW") || stock.canonicalCode.hasSuffix(".TWO") ? "TW" : "US")
                            .font(.caption2.bold()).foregroundStyle(Theme.accent)
                            .frame(width: 40, height: 40).background(Theme.accent.opacity(0.08), in: RoundedRectangle(cornerRadius: 12))
                        VStack(alignment: .leading, spacing: 5) {
                            Text(stock.nameZh.isEmpty ? stock.displayCode : stock.nameZh).foregroundStyle(Theme.text).font(.headline)
                            Text(stock.canonicalCode).font(.caption.monospaced()).foregroundStyle(Theme.secondary)
                        }
                        Spacer()
                        Image(systemName: "chevron.right")
                            .foregroundStyle(Theme.secondary)
                    }.padding(.vertical, 8).contentShape(Rectangle())
                }.buttonStyle(.plain)
                addButton(stock)
                }
            }
            if matches.count == 60 { Text("顯示前 60 筆，輸入更多字元可縮小範圍。").font(.caption).foregroundStyle(Theme.secondary) }
        }
        .navigationTitle("搜尋股票").navigationBarTitleDisplayMode(.inline)
        .searchable(text: $query, placement: .navigationBarDrawer(displayMode: .always), prompt: "名稱或代號，例如 台積電、AAPL")
        .accessibilityIdentifier("stock-search")
        .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("完成") { dismiss() }.accessibilityIdentifier("search-dismiss") } }
        .task { await load() }
    }

    /// 不進個股頁就能加入；已在自選的只顯示狀態，移除走自選頁的左滑。
    private func addButton(_ stock: StockIndexItem) -> some View {
        let code = stock.canonicalCode
        let added = store.watchlist.contains(code)
        return Button {
            adding.insert(code)
            Task {
                do { try await store.addToWatchlist(code); error = nil }
                catch { self.error = error.localizedDescription }
                adding.remove(code)
            }
        } label: {
            Image(systemName: added ? "checkmark.circle.fill" : "plus.circle")
                .font(.title3)
                .foregroundStyle(Theme.accent)
                .frame(width: 44, height: 44)
        }
        .buttonStyle(.plain)
        .disabled(added || adding.contains(code))
        // 股名放 value：既有測試用 label 找「股名」進個股頁，不能先命中這顆。
        .accessibilityLabel(added ? "已在自選" : "加入自選股")
        .accessibilityValue(stock.nameZh.isEmpty ? stock.displayCode : stock.nameZh)
        .accessibilityIdentifier("search.add.\(code)")
    }

    private var matches: [StockIndexItem] {
        let term = query.trimmingCharacters(in: .whitespacesAndNewlines)
        return Array(store.stockIndex.filter { item in
            let isTW = item.canonicalCode.hasSuffix(".TW") || item.canonicalCode.hasSuffix(".TWO")
            let isUS = item.market.lowercased() == "us"
            let matchesMarket = market == "tw" ? isTW : market == "us" ? isUS : (isTW || isUS)
            return item.active && matchesMarket && (term.isEmpty
                || item.canonicalCode.localizedCaseInsensitiveContains(term)
                || item.nameZh.localizedCaseInsensitiveContains(term)
                || item.aliases.contains { $0.localizedCaseInsensitiveContains(term) })
        }.prefix(60))
    }

    private func load() async {
        loading = true
        defer { loading = false }
        do { try await store.loadIndex(); error = nil }
        catch { self.error = error.localizedDescription }
    }
}
