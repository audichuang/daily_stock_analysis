import DSACore
import SwiftUI

struct ResearchLibraryView: View {
    @EnvironmentObject private var store: AppStore
    @State private var kind: ReportKind = .stock
    @State private var query = ""
    @State private var items: [HistoryItem] = []
    @State private var nextPage = 1
    @State private var hasMore = true
    @State private var loading = false
    @State private var errorMessage: String?
    @State private var requestGeneration = UUID()

    private enum ReportKind: String, CaseIterable, Identifiable {
        case stock = "個股研究"
        case market = "大盤複盤"
        var id: String { rawValue }
        var reportType: String? { self == .market ? "market_review" : nil }
    }

    private var visibleItems: [HistoryItem] {
        let term = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !term.isEmpty else { return items }
        return items.filter {
            $0.stockCode.localizedCaseInsensitiveContains(term)
                || ($0.stockName ?? "").localizedCaseInsensitiveContains(term)
                || ($0.region ?? "").localizedCaseInsensitiveContains(term)
        }
    }

    var body: some View {
        PageScroll {
            SectionHeading("從結論追到證據", subtitle: "論點、資料來源與失效條件，一起讀。")
            Picker("研究類型", selection: $kind) {
                ForEach(ReportKind.allCases) { category in
                    Text(category.rawValue).tag(category)
                }
            }
            .pickerStyle(.segmented)
            .frame(minHeight: 44)
            .accessibilityIdentifier("research.kind")

            VStack(alignment: .leading, spacing: 5) {
                Text(query.isEmpty ? "已載入 \(items.count) 份\(kind.rawValue)" : "已載入報告中，\(visibleItems.count) 份符合搜尋")
                    .font(.caption.weight(.medium))
                    .foregroundStyle(Theme.text)
                Text("依時間由新到舊；搜尋只比對已載入的報告。")
                    .font(.caption2)
                    .foregroundStyle(Theme.secondary)
            }

            if let errorMessage {
                ErrorStateView(message: errorMessage) { Task { await load(reset: nextPage == 1) } }
            }

            if visibleItems.isEmpty && !loading && errorMessage == nil {
                EmptyStateView(
                    title: query.isEmpty ? "還沒有\(kind.rawValue)" : "已載入的報告沒有符合項目",
                    message: query.isEmpty
                        ? "個股分析與大盤複盤完成後，會依產生時間收錄在這裡。"
                        : "可調整名稱或代碼；較早的報告請使用下方的載入更多。",
                    systemImage: "doc.text.magnifyingglass"
                )
            }

            ForEach(Array(visibleItems.enumerated()), id: \.offset) { _, item in
                if let id = item.id {
                    NavigationLink {
                        ResearchReportView(reportID: id)
                    } label: {
                        LibraryReportRow(report: item)
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("research.report.\(id)")
                } else {
                    LibraryReportRow(report: item)
                }
            }

            if loading {
                LoadingStateView(items.isEmpty ? "正在讀取研究報告…" : "正在載入報告…")
            }

            if hasMore && !loading {
                Button {
                    Task { await load(reset: false) }
                } label: {
                    Label("載入更多報告", systemImage: "arrow.down")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(SecondaryButtonStyle())
                .accessibilityIdentifier("research.loadMore")
            } else if !loading && !items.isEmpty && errorMessage == nil {
                Text("已載入所有\(kind.rawValue)")
                    .font(.caption)
                    .foregroundStyle(Theme.secondary)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 8)
            }
        }
        .navigationTitle("AI 研究")
        .searchable(text: $query, prompt: "搜尋已載入的名稱或代碼")
        .task(id: kind) { await load(reset: true) }
        .refreshable { await load(reset: true) }
        .accessibilityIdentifier("research-library")
    }

    @MainActor
    private func load(reset: Bool) async {
        guard let client = store.client else {
            errorMessage = "請先連接服務再讀取研究資料庫。"
            return
        }
        if !reset && loading { return }
        if reset {
            requestGeneration = UUID()
            // 首次顯示沿用首頁已取得的資料，接著用相同分頁端點更新。
            items = kind == .market ? store.marketReviews : store.reports
            nextPage = 1
            hasMore = true
        }
        let generation = requestGeneration
        let category = kind
        let requestedPage = nextPage
        loading = true
        errorMessage = nil
        defer {
            if requestGeneration == generation { loading = false }
        }
        do {
            let response = try await client.historyList(reportType: category.reportType, page: requestedPage, limit: 20)
            guard !Task.isCancelled, requestGeneration == generation, category == kind else { return }
            let accepted = response.items.filter {
                category == .market ? $0.reportType == "market_review" : $0.reportType != "market_review"
            }
            if reset {
                items = accepted
            } else {
                var keys = Set(items.map(identity))
                items.append(contentsOf: accepted.filter { keys.insert(identity($0)).inserted })
            }
            nextPage = response.page + 1
            // 個股端點含所有類型；以原始分頁筆數判斷是否還有下一頁，
            // 避免整頁都是大盤複盤時提早結束個股歷史。
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

private struct LibraryReportRow: View {
    let report: HistoryItem

    private var title: String {
        if report.reportType == "market_review" { return "大盤複盤" }
        if let name = report.stockName, !name.isEmpty { return name }
        return report.stockCode
    }

    var body: some View {
        DSACard {
            VStack(alignment: .leading, spacing: 12) {
                HStack(alignment: .top, spacing: 12) {
                    VStack(alignment: .leading, spacing: 5) {
                        Text(title)
                            .font(.headline)
                            .foregroundStyle(Theme.text)
                            .fixedSize(horizontal: false, vertical: true)
                        if !report.stockCode.isEmpty {
                            Text(report.stockCode)
                                .font(.caption.monospaced())
                                .foregroundStyle(Theme.secondary)
                        } else if let region = report.region {
                            Text(region.uppercased())
                                .font(.caption.monospaced())
                                .foregroundStyle(Theme.secondary)
                        }
                    }
                    Spacer(minLength: 0)
                    if report.id != nil {
                        Image(systemName: "arrow.up.right")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(Theme.accent)
                            .accessibilityHidden(true)
                    }
                }
                if report.action != nil || !(report.actionLabel ?? "").isEmpty,
                   let label = PresentationText.action(report.action, label: report.actionLabel) {
                    StatusBadge(label, tone: ActionTone.of(action: report.action, label: report.actionLabel).statusTone)
                } else if let advice = report.operationAdvice, !advice.isEmpty {
                    Text(advice)
                        .font(.subheadline.weight(.medium))
                        .foregroundStyle(Theme.accent)
                        .lineLimit(2)
                }
                if let summary = report.analysisSummary, !summary.isEmpty {
                    Text(summary)
                        .font(.subheadline)
                        .foregroundStyle(Theme.secondary)
                        .lineSpacing(3)
                        .lineLimit(3)
                }
                if let score = report.sentimentScore {
                    Text("模型評分 \(score) · 非勝率")
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(Theme.secondary)
                }
                Text(DisplayFormat.time(report.createdAt))
                    .font(.caption2)
                    .foregroundStyle(Theme.secondary)
                if report.id == nil {
                    Text("這筆歷史缺少報告編號，暫時無法開啟完整內容。")
                        .font(.caption)
                        .foregroundStyle(Theme.warning)
                }
            }
            .frame(minHeight: 44)
        }
        .accessibilityElement(children: .combine)
    }
}
