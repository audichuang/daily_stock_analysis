import SwiftUI
import DSACore

struct StockDetailView: View {
    let code: String
    @EnvironmentObject private var store: AppStore
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @State private var profile: StockProfile?
    @State private var loading = false
    @State private var error: String?
    @State private var actionError: String?
    @State private var changingWatchlist = false
    @State private var starting = false
    @State private var taskID: String?
    @State private var progress: Int?
    @State private var taskMessage: String?
    @State private var polling = false

    var body: some View {
        PageScroll {
            if loading && profile == nil { LoadingStateView("讀取行情與研究…") }
            if let error { ErrorStateView(message: error, retry: { Task { await load() } }) }
            if let profile {
                quoteHeader(profile)
                MarketChart(candles: profile.history.data.compactMap { bar in
                    guard let date = DisplayFormat.date(bar.date) else { return nil }
                    return ChartCandle(date: date, open: bar.open, high: bar.high, low: bar.low, close: bar.close, volume: bar.volume)
                }, source: "日 K · \(profile.history.status == "fresh" ? "資料可用" : "資料不完整")",
                            asOf: profile.history.data.last?.date, convention: store.colorConvention)
                if !profile.history.limitations.isEmpty { limitation(profile.history.limitations) }
                if let quote = profile.quote.data { tradingMetrics(quote) }
                analysisSection(profile)
                if !profile.evidenceQuality.limitations.isEmpty {
                    DSACard {
                        VStack(alignment: .leading, spacing: 12) {
                            SectionHeading("資料狀態", systemImage: "checkmark.shield")
                            limitation(profile.evidenceQuality.limitations)
                        }
                    }
                }
                if profile.market == "tw" {
                    NavigationLink {
                        ToolWebView(path: "/api/v1/stocks/\(code)/dossier?theme=dark", title: "四維度個股檔案")
                    } label: {
                        Label("四維度個股檔案", systemImage: "arrow.up.right.square").frame(maxWidth: .infinity)
                    }.buttonStyle(SecondaryButtonStyle()).accessibilityIdentifier("stock-dossier-link")
                }
            }
        }
        .navigationTitle(profile?.quote.data?.stockName ?? code).navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    changingWatchlist = true
                    Task {
                        defer { changingWatchlist = false }
                        do { try await store.toggleWatchlist(code); actionError = nil }
                        catch { actionError = error.localizedDescription }
                    }
                } label: { Image(systemName: store.watchlist.contains(code) ? "star.fill" : "star") }
                    .disabled(changingWatchlist).accessibilityIdentifier("watchlist-toggle")
                    .accessibilityLabel(store.watchlist.contains(code) ? "移除自選股" : "加入自選股")
            }
        }
        .refreshable { await load() }
        .task {
            taskID = UserDefaults.standard.string(forKey: taskKey)
            await load()
        }
        .task(id: taskID) { if let taskID { await followTask(taskID) } }
    }

    private var taskKey: String { "analysisTask.\(store.baseURL?.absoluteString ?? "").\(code)" }

    private func quoteHeader(_ profile: StockProfile) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text(code).font(.subheadline.monospaced()).foregroundStyle(Theme.secondary)
                Spacer()
                StatusBadge(profile.market.uppercased(), tone: .information)
            }
            HStack(alignment: .firstTextBaseline, spacing: 14) {
                Text(DisplayFormat.number(profile.quote.data?.currentPrice))
                    .font(.system(.largeTitle, design: .rounded, weight: .bold).monospacedDigit()).foregroundStyle(Theme.text)
                Text(DisplayFormat.percent(profile.quote.data?.changePercent))
                    .font(.headline.monospacedDigit()).foregroundStyle(Theme.changeColor(profile.quote.data?.changePercent, convention: store.colorConvention))
                Spacer(minLength: 0)
            }
            HStack {
                Text(DisplayFormat.source(profile.quote.data?.source)).font(.caption)
                if profile.quote.data?.isStale == true { StatusBadge("已過期", tone: .warning) }
            }.foregroundStyle(Theme.secondary)
            Text("資料參考時間 · \(DisplayFormat.time(profile.quote.data?.asOf ?? profile.quote.data?.updateTime))")
                .font(.caption2).foregroundStyle(Theme.secondary)
            Text(MarketDataPresentation.referenceTimeExplanation)
                .font(.caption2).foregroundStyle(Theme.secondary)
                .fixedSize(horizontal: false, vertical: true)
            if !profile.quote.limitations.isEmpty { limitation(profile.quote.limitations) }
            if let actionError { ErrorStateView(message: actionError) }
        }
    }

    private func tradingMetrics(_ quote: StockQuote) -> some View {
        DSACard {
            LazyVGrid(columns: Array(repeating: GridItem(.flexible()), count: dynamicTypeSize.isAccessibilitySize ? 1 : 3), alignment: .leading, spacing: 20) {
                MetricView("開盤", value: DisplayFormat.number(quote.open))
                MetricView("最高", value: DisplayFormat.number(quote.high))
                MetricView("最低", value: DisplayFormat.number(quote.low))
                MetricView("昨收", value: DisplayFormat.number(quote.prevClose))
                MetricView("來源成交量（股）", value: DisplayFormat.number(quote.volume, digits: 0))
                MetricView("量比", value: DisplayFormat.number(quote.volumeRatio))
                if quote.bestBid != nil || quote.bestAsk != nil {
                    MetricView("最佳買價", value: MarketDataPresentation.orderBookPrice(quote.bestBid, volume: quote.bestBidVolume))
                    MetricView("最佳賣價", value: MarketDataPresentation.orderBookPrice(quote.bestAsk, volume: quote.bestAskVolume))
                    MetricView("均價", value: DisplayFormat.number(quote.averagePrice))
                }
            }
        }
    }

    @ViewBuilder private func analysisSection(_ profile: StockProfile) -> some View {
        HStack(alignment: .top) {
            SectionHeading("AI 研究", subtitle: "觀點、依據與失效條件", eyebrow: "RESEARCH, WITH EVIDENCE")
            Spacer()
        }
        if let artifact = profile.research.data.structuredReport {
            DSACard {
                VStack(alignment: .leading, spacing: 12) {
                    StatusBadge(artifact.thesis.actionLabel ?? "AI 觀點", tone: .ai)
                    Text(artifact.thesis.summary).font(.body).foregroundStyle(Theme.text)
                    Text("分析 · \(DisplayFormat.time(artifact.createdAt))").font(.caption).foregroundStyle(Theme.secondary)
                    Text("\(artifact.evidence.count) 項依據 · \(artifact.invalidationConditions.count) 項失效條件")
                        .font(.caption).foregroundStyle(Theme.accent)
                }
            }
            DisclosureGroup("展開依據、風險與失效條件") {
                ResearchArtifactView(artifact: artifact).padding(.top, 12)
            }.foregroundStyle(Theme.accent)
        } else if let latest = profile.research.data.latestReport {
            DSACard {
                VStack(alignment: .leading, spacing: 12) {
                    StatusBadge(latest.actionLabel ?? latest.operationAdvice ?? "研究報告", tone: .ai)
                    Text(latest.analysisSummary ?? "完整分析已保存，點下方閱讀報告。")
                        .font(.body).foregroundStyle(Theme.text)
                    Text("分析 · \(DisplayFormat.time(latest.createdAt))").font(.caption).foregroundStyle(Theme.secondary)
                }
            }
        } else {
            EmptyStateView(title: "這檔股票還沒有 AI 研究", message: "產生分析後，這裡會顯示核心論點、證據與需要持續追蹤的風險。", systemImage: "text.magnifyingglass")
        }
        if let id = profile.research.data.latestReport?.id {
            NavigationLink { ResearchReportView(reportID: id) } label: {
                Label("閱讀完整報告", systemImage: "doc.text").frame(maxWidth: .infinity)
            }.buttonStyle(SecondaryButtonStyle()).accessibilityIdentifier("stock-report-link")
        }
        if let taskMessage {
            DSACard {
                VStack(alignment: .leading, spacing: 10) {
                    Text(taskMessage).font(.subheadline).foregroundStyle(Theme.text)
                    if let progress { ProgressView(value: Double(progress), total: 100).tint(Theme.accent) }
                    if let taskID { Text("任務 \(taskID)").font(.caption2.monospaced()).foregroundStyle(Theme.secondary).textSelection(.enabled) }
                }
            }
        }
        Button {
            Task { if let taskID { await followTask(taskID) } else { await startAnalysis() } }
        } label: {
            HStack {
                if starting || polling { ProgressView().tint(Theme.background) }
                Label(taskID != nil ? "查看分析進度" : "產生最新 AI 分析", systemImage: "waveform.path")
                Spacer()
                Image(systemName: "arrow.right")
            }
        }
        .buttonStyle(PressableButtonStyle()).disabled(starting || polling).accessibilityIdentifier("analysis-start")
        Text("分析在伺服器執行，會保存至研究紀錄。這次操作不發送 Telegram 通知。")
            .font(.caption2).foregroundStyle(Theme.secondary)
        if !profile.research.limitations.isEmpty { limitation(profile.research.limitations) }
    }

    private func limitation(_ values: [String]) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            ForEach(Array(values.enumerated()), id: \.offset) { _, text in
                Label(PresentationText.limitation(text), systemImage: "info.circle").font(.caption).foregroundStyle(Theme.warning)
            }
        }
    }

    private func load() async {
        guard let client = store.client else { return }
        loading = true
        defer { loading = false }
        do { profile = try await client.stockProfile(code, historyDays: 1100); error = nil }
        catch is CancellationError { }
        catch { self.error = error.localizedDescription }
    }

    private func startAnalysis() async {
        guard let client = store.client else { return }
        starting = true
        defer { starting = false }
        do {
            let accepted = try await client.startAnalysis(code)
            taskMessage = "分析已排入佇列，可離開此頁，稍後回來查看。"
            actionError = nil
            UserDefaults.standard.set(accepted.taskId, forKey: taskKey)
            taskID = accepted.taskId
        } catch { actionError = error.localizedDescription }
    }

    private func followTask(_ id: String) async {
        guard let client = store.client, !polling else { return }
        polling = true
        defer { polling = false }
        do {
            while !Task.isCancelled {
                let status = try await client.taskStatus(id)
                progress = status.progress
                switch status.status {
                case "pending", "processing", "cancel_requested":
                    taskMessage = status.status == "pending" ? "等待分析資源…" : "AI 正在整理行情、新聞與研究依據…"
                case "completed":
                    taskMessage = "分析已完成，報告已更新。"
                    UserDefaults.standard.removeObject(forKey: taskKey)
                    await load()
                    await store.refresh()
                    taskID = nil
                    return
                case "failed", "cancelled":
                    taskMessage = status.error ?? "分析未完成，可重新發起。"
                    UserDefaults.standard.removeObject(forKey: taskKey)
                    taskID = nil
                    return
                default: throw LocalError("伺服器回傳未知任務狀態：\(status.status)")
                }
                try await Task.sleep(for: .seconds(3))
            }
        } catch is CancellationError { }
        catch {
            if let apiError = error as? DSAError, apiError.isNotFound {
                UserDefaults.standard.removeObject(forKey: taskKey)
                progress = nil
                taskID = nil
                actionError = nil
                taskMessage = "原分析任務已不存在，請重新產生分析。"
            } else {
                actionError = error.localizedDescription
                taskMessage = "連線中斷；點選查看進度可接續原任務。"
            }
        }
    }
}
