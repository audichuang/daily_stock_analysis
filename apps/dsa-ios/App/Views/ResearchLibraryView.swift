import DSACore
import SwiftUI

struct ResearchLibraryView: View {
    @EnvironmentObject private var store: AppStore
    @State private var scope: Scope = .all
    @State private var action: DecisionAction?
    @State private var query = ""
    @State private var items: [HistoryItem] = []
    @State private var nextPage = 1
    @State private var hasMore = true
    @State private var loading = false
    @State private var errorMessage: String?
    @State private var requestGeneration = UUID()
    @State private var route: Route?
    @State private var expanded: Set<String> = []

    private enum Scope: String, CaseIterable, Identifiable {
        case all, tw, us, market
        var id: String { rawValue }
        var title: String {
            switch self {
            case .all: return "全部"
            case .tw: return "台股"
            case .us: return "美股"
            case .market: return "大盤複盤"
            }
        }
        var reportType: String? { self == .market ? "market_review" : nil }
        var marketFilter: String? { self == .tw || self == .us ? rawValue : nil }
    }

    private enum Route: Hashable {
        case report(Int)
        case stock(String)
    }

    private struct Filter: Hashable {
        let scope: Scope
        let action: DecisionAction?
        let term: String
    }

    private static let actionFilters: [DecisionAction] = [.buy, .add, .hold, .watch, .reduce, .sell]

    private var filter: Filter {
        Filter(scope: scope, action: scope == .market ? nil : action,
               term: query.trimmingCharacters(in: .whitespacesAndNewlines))
    }

    private var days: [ResearchLibraryDay] { ResearchLibrary.days(items) }

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 0) {
                filterBar.padding(.bottom, 12)

                if let errorMessage {
                    ErrorStateView(title: "報告載入失敗", message: errorMessage) {
                        Task { await load(reset: nextPage == 1) }
                    }
                    .padding(.bottom, 12)
                }

                if items.isEmpty && !loading && errorMessage == nil { emptyState }

                ForEach(days) { day in
                    Text(day.title)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(Theme.secondary)
                        .padding(.top, 14).padding(.bottom, 4)
                        .accessibilityAddTraits(.isHeader)
                    ForEach(day.entries) { entry in
                        entryView(entry)
                        Divider().overlay(Theme.border)
                    }
                }

                if loading {
                    LoadingStateView(items.isEmpty ? "正在讀取研究報告…" : "正在載入報告…")
                }

                // 捲到底自動載下一頁。id 跟著頁碼換，載完還看得到它時才會再觸發一次；有錯誤就停，等使用者重試。
                if hasMore && !items.isEmpty && errorMessage == nil {
                    Color.clear
                        .frame(height: 1)
                        .id(nextPage)
                        .onAppear { Task { await load(reset: false) } }
                        .accessibilityHidden(true)
                }
                PageBottomAnchor()
            }
            .padding(16)
            .frame(maxWidth: 900, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
        .dsaPageBottomInset()
        .background(Theme.background)
        .navigationTitle("AI 研究")
        .searchable(text: $query, placement: .navigationBarDrawer(displayMode: .always), prompt: "搜尋代號或名稱（全部報告）")
        .task(id: filter) {
            // 打字中不連發請求；換篩選也走同一條，差 0.3 秒感覺不到。
            if !filter.term.isEmpty {
                try? await Task.sleep(for: .milliseconds(300))
                if Task.isCancelled { return }
            }
            await load(reset: true)
        }
        .refreshable { await load(reset: true) }
        .navigationDestination(item: $route) { target in
            switch target {
            case let .report(id): ResearchReportView(reportID: id)
            case let .stock(code): StockDetailView(code: code)
            }
        }
        .accessibilityIdentifier("research-library")
    }

    private var filterBar: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(Scope.allCases) { item in
                    capsule(item.title, selected: scope == item, id: "research.scope.\(item.rawValue)") { scope = item }
                }
                if scope != .market {
                    Divider().frame(height: 20).overlay(Theme.border)
                    ForEach(Self.actionFilters, id: \.rawValue) { item in
                        capsule(item.displayLabel, selected: action == item, id: "research.action.\(item.rawValue)") {
                            action = action == item ? nil : item
                        }
                    }
                }
            }
        }
    }

    private func capsule(_ title: String, selected: Bool, id: String, perform: @escaping () -> Void) -> some View {
        Button(action: perform) {
            Text(title)
                .font(.caption.weight(.semibold))
                .foregroundStyle(selected ? Theme.background : Theme.secondary)
                .padding(.horizontal, 12)
                .frame(minHeight: 32)
                .background(selected ? Theme.accent : Theme.surface, in: Capsule())
                .overlay(Capsule().strokeBorder(Theme.border, lineWidth: 1))
                .frame(minHeight: 44)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(selected ? .isSelected : [])
        .accessibilityIdentifier(id)
    }

    private var emptyState: some View {
        let filtered = !filter.term.isEmpty || scope != .all || filter.action != nil
        return EmptyStateView(
            title: filtered ? "沒有符合的報告" : "還沒有研究報告",
            message: filtered ? "換個代號、名稱或篩選條件試試。" : "個股分析與大盤複盤完成後，會依日期收錄在這裡。",
            systemImage: "doc.text.magnifyingglass"
        )
    }

    @ViewBuilder
    private func entryView(_ entry: ResearchLibraryEntry) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            reportLink(entry.primary, change: entry.changeSummary)
            if !entry.earlier.isEmpty { versions(entry) }
        }
    }

    @ViewBuilder
    private func reportLink(_ item: HistoryItem, change: String?) -> some View {
        let row = LibraryReportRow(report: item, change: change, convention: store.colorConvention)
        if let id = item.id {
            NavigationLink { ResearchReportView(reportID: id) } label: { row }
                .buttonStyle(.plain)
                .contextMenu {
                    if !item.isMarketReview, !item.stockCode.isEmpty {
                        Button("查看個股", systemImage: "chart.xyaxis.line") { route = .stock(item.stockCode) }
                    }
                }
                .accessibilityIdentifier("research.report.\(id)")
        } else {
            row
        }
    }

    private func versions(_ entry: ResearchLibraryEntry) -> some View {
        let isExpanded = expanded.contains(entry.id)
        return VStack(alignment: .leading, spacing: 0) {
            Button {
                if isExpanded { expanded.remove(entry.id) } else { expanded.insert(entry.id) }
            } label: {
                HStack(spacing: 6) {
                    Text("同日另 \(entry.earlier.count) 份")
                    Image(systemName: isExpanded ? "chevron.up" : "chevron.down").accessibilityHidden(true)
                }
                .font(.caption.weight(.medium))
                .foregroundStyle(Theme.accent)
                .frame(minHeight: 44)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("research.versions.\(entry.primary.stockCode)")
            if isExpanded {
                ForEach(Array(entry.earlier.enumerated()), id: \.offset) { _, item in
                    reportLink(item, change: nil)
                }
            }
        }
    }

    @MainActor
    private func load(reset: Bool) async {
        guard let client = store.client else {
            errorMessage = "請先連接服務再讀取研究資料庫。"
            return
        }
        if !reset && loading { return }
        let current = filter
        if reset {
            requestGeneration = UUID()
            // 沒有條件時先沿用首頁已取得的資料，接著用分頁端點更新；有條件就不能拿別的結果墊。
            if current.term.isEmpty && current.action == nil && current.scope == .all {
                items = store.reports
            } else if current.term.isEmpty && current.scope == .market {
                items = store.marketReviews
            } else {
                items = []
            }
            nextPage = 1
            hasMore = true
        }
        let generation = requestGeneration
        let requestedPage = nextPage
        loading = true
        errorMessage = nil
        defer {
            if requestGeneration == generation { loading = false }
        }
        do {
            let response = try await client.historyList(
                reportType: current.scope.reportType,
                q: current.term.isEmpty ? nil : current.term,
                market: current.scope.marketFilter,
                action: current.action?.rawValue,
                page: requestedPage,
                limit: 20
            )
            guard !Task.isCancelled, requestGeneration == generation, current == filter else { return }
            if reset {
                items = response.items
            } else {
                var keys = Set(items.map(identity))
                items.append(contentsOf: response.items.filter { keys.insert(identity($0)).inserted })
            }
            nextPage = response.page + 1
            hasMore = response.page * response.limit < response.total
            errorMessage = nil
        } catch {
            guard !Task.isCancelled, requestGeneration == generation else { return }
            errorMessage = error.localizedDescription
        }
    }

    private func identity(_ item: HistoryItem) -> String {
        if let id = item.id { return "id:\(id)" }
        return "query:\(item.queryId):\(item.stockCode):\(item.createdAt ?? "")"
    }
}

/// 緊湊三行：名稱與分析時價、動作與評分、兩行結論。日期在分組標題，列內不再重複。
private struct LibraryReportRow: View {
    let report: HistoryItem
    let change: String?
    let convention: MarketColorConvention

    private var title: String {
        if let name = report.stockName, !name.isEmpty { return name }
        return report.stockCode
    }

    private var actionLabel: String? {
        PresentationText.action(report.action, label: report.actionLabel)
    }

    var body: some View {
        HStack(alignment: .center, spacing: 10) {
            VStack(alignment: .leading, spacing: 5) {
                if report.isMarketReview { marketHeader } else { stockHeader }
                if !report.isMarketReview { actionLine }
                if let conclusion = report.conclusion {
                    Text(conclusion)
                        .font(.subheadline)
                        .foregroundStyle(Theme.secondary)
                        .lineLimit(2)
                }
                if let change {
                    Label(change, systemImage: "arrow.triangle.2.circlepath")
                        .font(.caption)
                        .foregroundStyle(Theme.warning)
                }
                if report.id == nil {
                    Text("缺少報告編號，暫時無法開啟。")
                        .font(.caption)
                        .foregroundStyle(Theme.warning)
                }
            }
            if report.id != nil {
                Image(systemName: "chevron.right")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(Theme.secondary)
                    .accessibilityHidden(true)
            }
        }
        .padding(.vertical, 10)
        .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
    }

    private var marketHeader: some View {
        HStack(spacing: 8) {
            Image(systemName: "globe.asia.australia").foregroundStyle(Theme.accent).accessibilityHidden(true)
            Text("大盤複盤").font(.subheadline.weight(.semibold)).foregroundStyle(Theme.text)
            if let region = regionName {
                Text(region).font(.caption).foregroundStyle(Theme.secondary)
            }
        }
    }

    private var regionName: String? {
        switch report.region?.lowercased() {
        case "tw": return "台股"
        case "us": return "美股"
        case "both": return "台股＋美股"
        case let .some(value): return value.uppercased()
        case nil: return nil
        }
    }

    private var stockHeader: some View {
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            Text(title)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(Theme.text)
                .lineLimit(1)
            Text(report.stockCode)
                .font(.caption2.monospaced())
                .foregroundStyle(Theme.secondary)
                .lineLimit(1)
            Spacer(minLength: 6)
            if report.currentPrice != nil {
                Text(DisplayFormat.price(report.currentPrice))
                    .font(.subheadline.monospacedDigit())
                    .foregroundStyle(Theme.text)
                Text(DisplayFormat.percent(report.changePct))
                    .font(.caption.weight(.semibold).monospacedDigit())
                    .foregroundStyle(Theme.changeColor(report.changePct, convention: convention))
            }
        }
    }

    private var actionLine: some View {
        HStack(spacing: 8) {
            if let actionLabel {
                Text(actionLabel)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(ActionTone.of(action: report.action, label: report.actionLabel).color)
                    .lineLimit(1)
            }
            if let score = report.sentimentScore {
                Text("評分 \(score)/100")
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(Theme.secondary)
            }
        }
    }
}
