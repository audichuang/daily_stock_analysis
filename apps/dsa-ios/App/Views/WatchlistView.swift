import SwiftUI
import DSACore

struct WatchlistView: View {
    @EnvironmentObject private var store: AppStore
    @State private var searching = false
    @State private var query = ""

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                MarketPicker()
                if let error = store.errors["watchlist"] { ErrorStateView(message: error) }
                if visible.isEmpty {
                    EmptyStateView(title: query.isEmpty ? "這個市場還沒有自選股" : "沒有符合的自選股",
                                   message: "點右上角加入股票，隨時查看行情與 AI 觀點。")
                } else {
                    HStack {
                        Text("\(visible.count) 檔自選")
                        Spacer()
                        Text("現價 / 漲跌")
                    }.font(.caption).foregroundStyle(Theme.secondary)
                    LazyVStack(spacing: 0) {
                        ForEach(visible, id: \.self) { code in
                            NavigationLink { StockDetailView(code: code) } label: { StockRow(code: code) }
                                .buttonStyle(.plain)
                                .accessibilityIdentifier("stock-row.\(code)")
                        }
                    }
                }
            }
            .padding(.horizontal, 16).padding(.vertical, 12)
            .frame(maxWidth: 900, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
        .background(Theme.background)
        .navigationTitle("自選股").navigationBarTitleDisplayMode(.inline)
        .searchable(text: $query, prompt: "篩選代碼或名稱")
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button { searching = true } label: { Image(systemName: "plus") }
                    .accessibilityLabel("新增自選股")
            }
        }
        .refreshable { await store.refresh() }
        .sheet(isPresented: $searching) { NavigationStack { StockSearchView() } }
    }

    private var visible: [String] {
        store.watchlist.filter { code in
            store.isInMarket(code) && (query.isEmpty || code.localizedCaseInsensitiveContains(query)
                || (store.quote(for: code)?.stockName ?? "").localizedCaseInsensitiveContains(query))
        }
    }
}

struct StockSearchView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.dismiss) private var dismiss
    @State private var query = ""
    @State private var market = "all"
    @State private var error: String?
    @State private var loading = false

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
                        Image(systemName: store.watchlist.contains(stock.canonicalCode) ? "star.fill" : "chevron.right")
                            .foregroundStyle(Theme.accent)
                    }.padding(.vertical, 8).contentShape(Rectangle())
                }.buttonStyle(.plain)
            }
            if matches.count == 60 { Text("顯示前 60 筆，輸入更多字元可縮小範圍。").font(.caption).foregroundStyle(Theme.secondary) }
        }
        .navigationTitle("搜尋股票").navigationBarTitleDisplayMode(.inline)
        .searchable(text: $query, placement: .navigationBarDrawer(displayMode: .always), prompt: "名稱或代號，例如 台積電、AAPL")
        .accessibilityIdentifier("stock-search")
        .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("完成") { dismiss() }.accessibilityIdentifier("search-dismiss") } }
        .task { await load() }
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
