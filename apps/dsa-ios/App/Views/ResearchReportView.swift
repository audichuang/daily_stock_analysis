import DSACore
import SwiftUI

struct ResearchReportView: View {
    let reportID: Int
    @EnvironmentObject private var store: AppStore
    @State private var report: AnalysisReport?
    @State private var markdown: String?
    @State private var loading = false
    @State private var errorMessage: String?
    @State private var markdownError: String?
    @State private var fullReportExpanded = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                if loading && report == nil {
                    LoadingStateView("正在讀取 AI 研究報告…")
                }
                if let errorMessage {
                    ErrorStateView(message: errorMessage) { Task { await load() } }
                }
                if let report {
                    reportHeader(report)
                    summaryCard(report)
                    if report.meta.reportType != "market_review" {
                        ReportNewsView(reportID: reportID).id(reportID)
                    }
                    if let strategy = report.strategy {
                        strategyCard(strategy)
                    }
                    if let artifact = report.structuredReport {
                        ResearchArtifactView(artifact: artifact)
                    } else {
                        DSACard {
                            VStack(alignment: .leading, spacing: 8) {
                                SectionHeading("研究依據", systemImage: "text.magnifyingglass")
                                Text("這份報告尚未提供結構化證據與失效條件，可展開完整報告閱讀原始內容。")
                                    .font(.subheadline)
                                    .foregroundStyle(Theme.secondary)
                            }
                        }
                    }
                    fullReportCard
                    Text("報告編號 #\(reportID) · 價格與判讀以報告產生時間為準")
                        .font(.caption2)
                        .foregroundStyle(Theme.secondary)
                        .textSelection(.enabled)
                } else if !loading && errorMessage == nil {
                    EmptyStateView(title: "尚無研究報告", message: "完成分析後，這裡會顯示論點、證據與需要留意的變化。", systemImage: "doc.text.magnifyingglass")
                }
            }
            .padding(20)
            .frame(maxWidth: 760)
            .frame(maxWidth: .infinity)
        }
        .dsaPageBottomInset()
        .background(Theme.background)
        .navigationTitle("AI 研究")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if let markdown, !markdown.isEmpty {
                ToolbarItem(placement: .topBarTrailing) {
                    ShareLink(item: markdown) {
                        Image(systemName: "square.and.arrow.up")
                            .frame(minWidth: 44, minHeight: 44)
                    }
                    .accessibilityLabel("分享完整報告")
                    .accessibilityIdentifier("report.share")
                }
            }
        }
        .task(id: reportID) { await load() }
        .refreshable { await load() }
        .accessibilityIdentifier("report.screen")
    }

    private func reportHeader(_ report: AnalysisReport) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            StatusBadge("AI 研究報告", tone: .ai, systemImage: "waveform.path")
            Text(report.meta.reportType == "market_review" ? "大盤複盤" : (report.meta.stockName ?? report.meta.stockCode))
                .font(.largeTitle.weight(.bold))
                .foregroundStyle(Theme.text)
            if !report.meta.stockCode.isEmpty {
                Text(report.meta.stockCode)
                    .font(.subheadline.monospaced())
                    .foregroundStyle(Theme.secondary)
            }
            Label(DisplayFormat.time(report.meta.createdAt), systemImage: "clock")
                .font(.caption)
                .foregroundStyle(Theme.secondary)
            if let model = report.meta.modelUsed, !model.isEmpty {
                Text("分析模型：\(model)")
                    .font(.caption)
                    .foregroundStyle(Theme.secondary)
                    .textSelection(.enabled)
            }
        }
    }

    private func summaryCard(_ report: AnalysisReport) -> some View {
        DSACard {
            VStack(alignment: .leading, spacing: 16) {
                SectionHeading("這份分析怎麼看")
                if let summary = report.summary.analysisSummary, !summary.isEmpty {
                    NativeMarkdownText(text: summary)
                } else {
                    Text("這份報告沒有摘要，可閱讀下方的研究論點或完整報告。")
                        .font(.subheadline).foregroundStyle(Theme.secondary)
                }
                if let advice = PresentationText.action(report.summary.action, label: report.summary.actionLabel, advice: report.summary.operationAdvice) {
                    Divider().overlay(Theme.border)
                    MetricView("模型判讀", value: advice)
                }
                if let trend = report.summary.trendPrediction, !trend.isEmpty {
                    MetricView("趨勢描述", value: trend)
                }
                if let score = report.summary.sentimentScore {
                    HStack(alignment: .firstTextBaseline, spacing: 10) {
                        Text(String(score))
                            .font(.system(.largeTitle, design: .rounded, weight: .bold).monospacedDigit())
                            .foregroundStyle(Theme.accent)
                        VStack(alignment: .leading, spacing: 3) {
                            Text("模型評分").font(.subheadline.weight(.semibold)).foregroundStyle(Theme.text)
                            Text("不是勝率，也不是保證報酬").font(.caption).foregroundStyle(Theme.secondary)
                        }
                    }
                    .accessibilityElement(children: .combine)
                }
                if let price = report.meta.currentPrice {
                    MetricView("報告當時價格", value: DisplayFormat.number(price), detail: "此處為分析時快照")
                }
            }
        }
    }

    private func strategyCard(_ strategy: ReportStrategy) -> some View {
        DSACard {
            VStack(alignment: .leading, spacing: 16) {
                SectionHeading("模型規劃價位", subtitle: "保留報告原始條件與區間", systemImage: "slider.horizontal.3")
                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], alignment: .leading, spacing: 18) {
                    MetricView("理想進場", value: strategy.idealBuy ?? "未提供", tint: Theme.accent)
                    MetricView("次要進場", value: strategy.secondaryBuy ?? "未提供")
                    MetricView("停損條件", value: strategy.stopLoss ?? "未提供", tint: Theme.warning)
                    MetricView("停利條件", value: strategy.takeProfit ?? "未提供")
                }
            }
        }
    }

    private var fullReportCard: some View {
        DSACard {
            DisclosureGroup(isExpanded: $fullReportExpanded) {
                VStack(alignment: .leading, spacing: 12) {
                    if let markdownError {
                        ErrorStateView(message: markdownError) { Task { await loadMarkdown() } }
                    }
                    if let markdown, !markdown.isEmpty {
                        NativeMarkdownText(text: markdown)
                    } else if loading {
                        LoadingStateView("正在讀取完整報告…")
                    } else if markdownError == nil {
                        Text("伺服器尚未提供完整文字。")
                            .font(.subheadline).foregroundStyle(Theme.secondary)
                    }
                }
                .padding(.top, 16)
            } label: {
                Label("完整報告", systemImage: "doc.text")
                    .font(.headline)
                    .foregroundStyle(Theme.text)
                    .frame(minHeight: 44)
            }
            .tint(Theme.accent)
            .accessibilityIdentifier("report.fullText")
        }
    }

    @MainActor
    private func load() async {
        guard !loading else { return }
        guard let client = store.client else {
            errorMessage = "請先連接服務再讀取報告。"
            return
        }
        loading = true
        errorMessage = nil
        defer { loading = false }
        do {
            let result = try await client.report(reportID)
            guard !Task.isCancelled else { return }
            report = result
            await loadMarkdown()
        } catch {
            guard !Task.isCancelled else { return }
            errorMessage = error.localizedDescription
        }
    }

    @MainActor
    private func loadMarkdown() async {
        guard let client = store.client else { return }
        markdownError = nil
        do {
            let result = try await client.reportMarkdown(reportID)
            guard !Task.isCancelled else { return }
            markdown = result
        } catch {
            guard !Task.isCancelled else { return }
            markdownError = error.localizedDescription
        }
    }
}

struct ResearchArtifactView: View {
    let artifact: ResearchArtifact

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            thesisCard
            evidenceCard
            invalidationCard
            nextActionsCard
            qualityCard
        }
    }

    private var thesisCard: some View {
        DSACard {
            VStack(alignment: .leading, spacing: 16) {
                SectionHeading("論點與反面證據", systemImage: "point.3.connected.trianglepath.dotted")
                NativeMarkdownText(text: artifact.thesis.summary)
                if let horizon = artifact.thesis.horizon, !horizon.isEmpty {
                    MetricView("觀察期間", value: horizon)
                }
                if let label = PresentationText.action(artifact.thesis.action, label: artifact.thesis.actionLabel) {
                    MetricView("結構化判讀", value: label)
                }
                if !artifact.thesis.reasons.isEmpty {
                    researchList(title: "支持這個判斷", items: artifact.thesis.reasons, symbol: "plus.circle", color: Theme.accent)
                }
                if !artifact.thesis.risks.isEmpty {
                    researchList(title: "同時需要留意", items: artifact.thesis.risks, symbol: "exclamationmark.circle", color: Theme.warning)
                }
            }
        }
    }

    private var evidenceCard: some View {
        DSACard {
            VStack(alignment: .leading, spacing: 16) {
                SectionHeading("判斷依據", subtitle: "\(artifact.evidence.count) 項證據 · 保留來源與資料日期", systemImage: "text.magnifyingglass")
                if artifact.evidence.isEmpty {
                    Text("這份研究沒有列出可追溯的證據。")
                        .font(.subheadline).foregroundStyle(Theme.secondary)
                }
                ForEach(artifact.evidence) { evidence in
                    VStack(alignment: .leading, spacing: 10) {
                        Text(PresentationText.evidenceTitle(evidence.title)).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.text)
                        if let summary = evidence.summary, !summary.isEmpty {
                            NativeMarkdownText(text: summary)
                        }
                        ViewThatFits(in: .horizontal) {
                            HStack(spacing: 8) {
                                freshnessBadge(evidence.freshness)
                                Text("品質：\(PresentationText.quality(evidence.qualityLevel))").font(.caption).foregroundStyle(Theme.secondary)
                            }
                            VStack(alignment: .leading, spacing: 8) {
                                freshnessBadge(evidence.freshness)
                                Text("品質：\(PresentationText.quality(evidence.qualityLevel))").font(.caption).foregroundStyle(Theme.secondary)
                            }
                        }
                        Text("來源：\(PresentationText.source(evidence.source))")
                            .font(.caption).foregroundStyle(Theme.secondary)
                        Text("資料時間：\(DisplayFormat.time(evidence.asOf))")
                            .font(.caption).foregroundStyle(Theme.secondary)
                        if let rawURL = evidence.url, let url = URL(string: rawURL), ["https", "http"].contains(url.scheme?.lowercased() ?? "") {
                            Link(destination: url) {
                                Label("開啟來源", systemImage: "arrow.up.right")
                                    .font(.caption.weight(.semibold))
                                    .frame(minHeight: 44)
                            }
                            .tint(Theme.accent)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(14)
                    .background(Theme.background.opacity(0.55), in: RoundedRectangle(cornerRadius: 14))
                }
            }
        }
    }

    private var invalidationCard: some View {
        DSACard {
            VStack(alignment: .leading, spacing: 16) {
                SectionHeading("何時需要重新判斷", subtitle: "論點失效條件", systemImage: "arrow.triangle.branch")
                if artifact.invalidationConditions.isEmpty {
                    Text("模型未提供明確失效條件。")
                        .font(.subheadline).foregroundStyle(Theme.secondary)
                }
                ForEach(artifact.invalidationConditions) { condition in
                    VStack(alignment: .leading, spacing: 8) {
                        Text(condition.description)
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(Theme.text)
                        if let trigger = condition.trigger, !trigger.isEmpty {
                            Text("觸發：\(PresentationText.limitation(trigger))")
                                .font(.subheadline).foregroundStyle(Theme.warning)
                        }
                        if let threshold = condition.threshold, !threshold.isEmpty {
                            Text("\(condition.metric ?? "門檻")：\(threshold)")
                                .font(.caption).foregroundStyle(Theme.secondary)
                        }
                        if let dueAt = condition.dueAt {
                            Text("觀察期限：\(DisplayFormat.time(dueAt))")
                                .font(.caption).foregroundStyle(Theme.secondary)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(14)
                    .background(Theme.warning.opacity(0.06), in: RoundedRectangle(cornerRadius: 14))
                    .overlay(alignment: .leading) {
                        RoundedRectangle(cornerRadius: 2).fill(Theme.warning.opacity(0.7)).frame(width: 3).padding(.vertical, 14)
                    }
                }
            }
        }
    }

    private var nextActionsCard: some View {
        DSACard {
            VStack(alignment: .leading, spacing: 16) {
                SectionHeading("接下來觀察什麼", systemImage: "checklist")
                if artifact.nextActions.isEmpty {
                    Text("這份研究沒有列出後續觀察事項。")
                        .font(.subheadline).foregroundStyle(Theme.secondary)
                }
                ForEach(Array(artifact.nextActions.enumerated()), id: \.offset) { index, action in
                    HStack(alignment: .top, spacing: 12) {
                        Text(String(index + 1))
                            .font(.caption.monospacedDigit().weight(.semibold))
                            .foregroundStyle(Theme.accent)
                            .padding(8)
                            .background(Theme.accent.opacity(0.1), in: Circle())
                        VStack(alignment: .leading, spacing: 6) {
                            Text(action.label).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.text)
                            if let reason = action.reason { NativeMarkdownText(text: reason) }
                            if let dueAt = action.dueAt {
                                Text("時間：\(DisplayFormat.time(dueAt))").font(.caption).foregroundStyle(Theme.secondary)
                            }
                        }
                    }
                }
            }
        }
    }

    private var qualityCard: some View {
        DSACard {
            VStack(alignment: .leading, spacing: 16) {
                SectionHeading("資料完整度", systemImage: "checkmark.shield")
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: 10) { qualityBadges }
                    VStack(alignment: .leading, spacing: 8) { qualityBadges }
                }
                if !artifact.dataQuality.missingBlocks.isEmpty {
                    Text("缺少資料：\(artifact.dataQuality.missingBlocks.map(PresentationText.evidenceTitle).joined(separator: "、"))")
                        .font(.subheadline).foregroundStyle(Theme.warning)
                }
                if !artifact.dataQuality.limitations.isEmpty {
                    researchList(title: "解讀限制", items: artifact.dataQuality.limitations.map(PresentationText.limitation), symbol: "info.circle", color: Theme.secondary)
                }
                Text("研究產生時間：\(DisplayFormat.time(artifact.createdAt))")
                    .font(.caption).foregroundStyle(Theme.secondary)
            }
        }
    }

    @ViewBuilder
    private var qualityBadges: some View {
        StatusBadge(PresentationText.quality(artifact.dataQuality.level), tone: .information)
        StatusBadge("\(artifact.dataQuality.sourceCount) 個來源")
        if artifact.dataQuality.staleCount > 0 {
            StatusBadge("\(artifact.dataQuality.staleCount) 項過期", tone: .warning)
        }
    }

    private func researchList(title: String, items: [String], symbol: String, color: Color) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title).font(.subheadline.weight(.semibold)).foregroundStyle(color)
            ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                HStack(alignment: .top, spacing: 9) {
                    Image(systemName: symbol)
                        .font(.caption)
                        .foregroundStyle(color)
                        .padding(.top, 3)
                        .accessibilityHidden(true)
                    NativeMarkdownText(text: item)
                }
            }
        }
    }

    private func freshnessBadge(_ value: String) -> some View {
        let label: String
        let tone: StatusTone
        switch value {
        case "fresh": label = "時效有效"; tone = .positive
        case "stale": label = "資料過期"; tone = .warning
        case "unknown": label = "時效未確認"; tone = .neutral
        default: label = value; tone = .neutral
        }
        return StatusBadge(label, tone: tone, systemImage: "clock")
    }

}

/// 逐行呈現完整文字，保留表格、程式區塊和換行，不把長報告截成摘要。
private struct NativeMarkdownText: View {
    let text: String

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            ForEach(Array(text.components(separatedBy: .newlines).enumerated()), id: \.offset) { _, line in
                if line.isEmpty {
                    Color.clear.frame(height: 5).accessibilityHidden(true)
                } else if let heading = heading(line) {
                    Text(heading)
                        .font(.headline)
                        .foregroundStyle(Theme.text)
                        .padding(.top, 8)
                        .accessibilityAddTraits(.isHeader)
                } else {
                    Text((try? AttributedString(markdown: line, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))) ?? AttributedString(line))
                        .font(.subheadline)
                        .foregroundStyle(Theme.text.opacity(0.9))
                        .fixedSize(horizontal: false, vertical: true)
                        .lineSpacing(4)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .textSelection(.enabled)
        .tint(Theme.accent)
        .environment(\.openURL, OpenURLAction { url in
            ["https", "http"].contains(url.scheme?.lowercased() ?? "") ? .systemAction : .discarded
        })
    }

    private func heading(_ line: String) -> String? {
        let hashes = line.prefix { $0 == "#" }.count
        guard (1...6).contains(hashes), line.dropFirst(hashes).first == " " else { return nil }
        return String(line.dropFirst(hashes + 1))
    }
}
