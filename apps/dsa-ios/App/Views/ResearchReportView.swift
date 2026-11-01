import DSACore
import SwiftUI

struct ResearchReportView: View {
    let reportID: Int
    @EnvironmentObject private var store: AppStore
    @State private var report: AnalysisReport?
    @State private var latestQuote: StockQuote?
    @State private var markdown: String?
    @State private var loading = false
    @State private var markdownLoading = false
    @State private var errorMessage: String?
    @State private var markdownError: String?
    @State private var fullReportExpanded = false
    @State private var summaryExpanded = false
    @State private var guardrailExpanded = false
    @State private var alertRoute: AlertRoute?

    private struct AlertRoute: Hashable, Identifiable {
        let path: String
        var id: String { path }
    }

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
                    if isMarketReview(report) {
                        marketReviewHeader(report)
                        summaryCard(report)
                    } else {
                        conclusionCard(report)
                        summaryCard(report)
                        positionAdviceCard(report)
                        if let strategy = report.strategy { priceCard(strategy, report: report) }
                        eventCard(report)
                        nextStepsCard(report)
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
                        ReportNewsView(reportID: reportID).id(reportID)
                    }
                    fullReportCard(report)
                    reportFooter(report)
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
        .navigationTitle(navigationTitle)
        .navigationBarTitleDisplayMode(.inline)
        .navigationDestination(item: $alertRoute) { route in
            ToolWebView(path: route.path, title: "價格警報")
        }
        .toolbar {
            if let report, !isMarketReview(report) {
                ToolbarItem(placement: .topBarTrailing) {
                    NavigationLink {
                        ToolWebView(
                            path: ToolLinks.chatPath(code: report.meta.stockCode, name: report.meta.stockName, recordID: reportID),
                            title: "AI 問股"
                        )
                    } label: {
                        Image(systemName: "bubble.left.and.text.bubble.right")
                            .frame(minWidth: 44, minHeight: 44)
                    }
                    .accessibilityLabel("問 AI")
                    .accessibilityIdentifier("report.askAI")
                }
            }
            if let report {
                ToolbarItem(placement: .topBarTrailing) {
                    Menu {
                        ShareLink("分享結論", item: shareSummary(report))
                        if let markdown, !markdown.isEmpty {
                            ShareLink("分享完整報告", item: markdown)
                        }
                    } label: {
                        Image(systemName: "square.and.arrow.up")
                            .frame(minWidth: 44, minHeight: 44)
                    }
                    .accessibilityLabel("分享報告")
                    .accessibilityIdentifier("report.share")
                }
            }
        }
        .task(id: reportID) { await load() }
        .refreshable { await load() }
        .accessibilityIdentifier("report.screen")
    }

    /// Stock name once loaded; market reviews get a fixed title.
    private var navigationTitle: String {
        guard let report else { return "AI 研究" }
        if isMarketReview(report) { return "台股大盤複盤" }
        return ReportText.firstNonEmpty(report.meta.stockName) ?? report.meta.stockCode
    }

    private func guardrail(_ report: AnalysisReport) -> ReportGuardrailDisplay? {
        ReportGuardrailDisplay.of(report.summary, actionText: actionText(report))
    }

    private func isMarketReview(_ report: AnalysisReport) -> Bool {
        report.meta.reportType == "market_review" || report.meta.assetType == "index"
    }

    private func oneSentence(_ report: AnalysisReport) -> String? {
        ReportText.firstNonEmpty(report.summary.oneSentence, report.structuredReport?.thesis.oneSentence)
    }

    private func actionText(_ report: AnalysisReport) -> String? {
        PresentationText.action(report.summary.action, label: report.summary.actionLabel, advice: report.summary.operationAdvice)
    }

    private func shareSummary(_ report: AnalysisReport) -> String {
        let name = isMarketReview(report) ? "大盤複盤" : (report.meta.stockName ?? report.meta.stockCode)
        let lines: [String?] = [
            "\(name)（\(report.meta.stockCode)）",
            actionText(report).map { "動作：\($0)" },
            ReportText.firstNonEmpty(oneSentence(report), report.summary.analysisSummary),
            "報告編號 #\(reportID) · \(DisplayFormat.time(report.meta.createdAt))"
        ]
        return lines.compactMap { $0 }.joined(separator: "\n")
    }

    // MARK: 結論

    private func marketReviewHeader(_ report: AnalysisReport) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("大盤複盤").font(.largeTitle.weight(.bold)).foregroundStyle(Theme.text)
            Label(DisplayFormat.time(report.meta.createdAt), systemImage: "clock")
                .font(.caption).foregroundStyle(Theme.secondary)
        }
    }

    private func conclusionCard(_ report: AnalysisReport) -> some View {
        let meta = report.meta
        let summary = report.summary
        let tone = ActionTone.of(action: summary.action, label: summary.actionLabel ?? summary.operationAdvice)
        return DSACard {
            VStack(alignment: .leading, spacing: 12) {
                NavigationLink {
                    StockDetailView(code: meta.stockCode)
                } label: {
                    HStack(spacing: 6) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(meta.stockName ?? meta.stockCode).font(.headline).foregroundStyle(Theme.text)
                            Text(verbatim: meta.stockCode).font(.caption.monospaced()).foregroundStyle(Theme.secondary)
                        }
                        Image(systemName: "chevron.right").font(.caption).foregroundStyle(Theme.secondary).accessibilityHidden(true)
                        Spacer(minLength: 0)
                    }
                    .frame(minHeight: 44)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("report.company")

                priceHeadline(report, tone: tone)
                sinceReportLine(report)
                if let sentence = guardrail(report)?.headline ?? oneSentence(report) {
                    Text(sentence).font(.body.weight(.semibold)).foregroundStyle(Theme.text)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityIdentifier("report.oneSentence")
                }
                if let display = guardrail(report) { guardrailRow(display) }
                keyLevelsBar(report)
                HStack(alignment: .top, spacing: 12) {
                    MetricView("模型評分（非勝率）", value: summary.sentimentScore.map { "\($0)/100" } ?? DisplayNumber.noValue)
                    MetricView("信心度", value: summary.confidenceLevel.map(PresentationText.quality) ?? DisplayNumber.noValue)
                    MetricView("時效", value: summary.timeSensitivity ?? DisplayNumber.noValue)
                }
                if let previous = meta.previousReport { previousLine(previous, current: report) }
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("report.conclusion")
    }

    /// The big number is the live price; without a live quote it falls back to the report price and says so.
    private func priceHeadline(_ report: AnalysisReport, tone: ActionTone) -> some View {
        let meta = report.meta
        let live = latestQuote
        let change = live == nil ? meta.changePct : live?.changePercent
        return HStack(alignment: .firstTextBaseline, spacing: 10) {
            Text(DisplayFormat.price(live?.currentPrice ?? meta.currentPrice, currency: meta.currency))
                .font(.system(.largeTitle, design: .rounded, weight: .bold).monospacedDigit())
                .foregroundStyle(Theme.text)
                .accessibilityIdentifier("report.price")
            if change != nil {
                Text(DisplayFormat.percent(change))
                    .font(.headline.monospacedDigit())
                    .foregroundStyle(Theme.changeColor(change, convention: store.colorConvention))
            }
            if live == nil { StatusBadge("報告時價") }
            Spacer(minLength: 0)
            if let action = actionText(report) {
                Text(action)
                    .font(.headline).foregroundStyle(tone.color)
                    .padding(.horizontal, 12).padding(.vertical, 6)
                    .background(tone.color.opacity(0.12), in: RoundedRectangle(cornerRadius: DSARadius.control))
                    .accessibilityIdentifier("report.action")
            }
        }
    }

    /// 「報告時 279.84（10/30）· 報告後 +0.00%」; only with a live quote, so the price never shows twice.
    @ViewBuilder private func sinceReportLine(_ report: AnalysisReport) -> some View {
        if let quote = latestQuote {
            let meta = report.meta
            let change = ReportMath.changePercent(from: meta.currentPrice, to: quote.currentPrice)
            let date = ReportDisplayDate.monthDay(meta.priceDate ?? meta.createdAt).map { "（\($0)）" } ?? ""
            HStack(spacing: 0) {
                Text(verbatim: "報告時 \(DisplayFormat.price(meta.currentPrice, currency: meta.currency))\(date)")
                    .foregroundStyle(Theme.secondary)
                if let change {
                    Text(verbatim: " · 報告後 ").foregroundStyle(Theme.secondary)
                    Text(verbatim: DisplayFormat.percent(change))
                        .foregroundStyle(Theme.changeColor(change, convention: store.colorConvention))
                }
            }
            .font(.caption.monospacedDigit())
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("report.sinceReport")
        }
    }

    /// One collapsed line; the reason and the other wording only show when expanded.
    private func guardrailRow(_ display: ReportGuardrailDisplay) -> some View {
        let color = display.tone == .warning ? Theme.warning : Theme.secondary
        return DisclosureGroup(isExpanded: $guardrailExpanded) {
            VStack(alignment: .leading, spacing: 6) {
                ForEach(Array(display.details.enumerated()), id: \.offset) { _, line in
                    Text(line).font(.caption).foregroundStyle(Theme.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.top, 4)
        } label: {
            Label(display.label, systemImage: "shield.lefthalf.filled")
                .font(.caption.weight(.semibold)).foregroundStyle(color)
                .lineLimit(1)
                .frame(minHeight: 44)
        }
        .tint(color)
        .accessibilityIdentifier("report.guardrail")
    }

    /// Structured sniper prices only (legacy text is never parsed): stop loss and take profit with distance and an alert shortcut.
    @ViewBuilder private func keyLevelsBar(_ report: AnalysisReport) -> some View {
        let levels = report.strategy.map(PriceLevel.levels(from:)) ?? []
        let stop = levels.first { $0.kind == .stopLoss }?.value
        let target = levels.first { $0.kind == .takeProfit }?.value
        if stop != nil || target != nil {
            let meta = report.meta
            let current = latestQuote?.currentPrice ?? meta.currentPrice
            // take_profit is the rebound-reduce price when the decision is reduce/sell (analyzer prompt).
            let resolved = DecisionAction.resolve(action: report.summary.action, label: report.summary.actionLabel)
            let targetTitle = resolved == .reduce || resolved == .sell ? "反彈減碼" : "停利"
            let parts = [
                stop.map { keyLevelText("停損", value: $0, current: current, currency: meta.currency) },
                target.map { keyLevelText(targetTitle, value: $0, current: current, currency: meta.currency) },
            ].compactMap { $0 }
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(verbatim: parts.joined(separator: "｜"))
                    .font(.caption.monospacedDigit()).foregroundStyle(Theme.text)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 0)
                Menu {
                    if let stop {
                        Button("跌破停損 \(DisplayFormat.price(stop, currency: meta.currency)) 提醒") {
                            alertRoute = AlertRoute(path: ToolLinks.alertPath(code: meta.stockCode, direction: .below, price: stop))
                        }
                    }
                    if let target {
                        Button("漲到\(targetTitle) \(DisplayFormat.price(target, currency: meta.currency)) 提醒") {
                            alertRoute = AlertRoute(path: ToolLinks.alertPath(code: meta.stockCode, direction: .above, price: target))
                        }
                    }
                } label: {
                    Label("設警報", systemImage: "bell")
                        .font(.caption.weight(.semibold)).foregroundStyle(Theme.accent)
                        .padding(.horizontal, 10).frame(height: 28)
                        .background(Theme.accent.opacity(0.12), in: Capsule())
                        .frame(minHeight: 44)
                        .contentShape(Rectangle())
                        .fixedSize()
                }
                .accessibilityIdentifier("report.setAlert")
            }
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("report.keyLevels")
        }
    }

    private func keyLevelText(_ title: String, value: Double, current: Double?, currency: String?) -> String {
        let distance = ReportMath.changePercent(from: current, to: value).map { "（\(DisplayFormat.percent($0))）" } ?? ""
        return "\(title) \(DisplayFormat.price(value, currency: currency))\(distance)"
    }

    private func previousLine(_ previous: ReportPreviousSummary, current report: AnalysisReport) -> some View {
        let date = ReportDisplayDate.monthDay(previous.createdAt)
        let before = DecisionAction.resolve(action: previous.action, label: nil)
        let now = DecisionAction.resolve(action: report.summary.action, label: report.summary.actionLabel)
        let text: String
        if let before, before == now {
            text = date.map { "與前次（\($0)）相同" } ?? "與前次相同"
        } else {
            let action = PresentationText.action(previous.action, label: nil) ?? DisplayNumber.noValue
            let score = previous.score.map { " · 評分 \($0)" } ?? ""
            text = "前次判斷：\(action)\(score)\(date.map { " · \($0)" } ?? "")"
        }
        return Text(verbatim: text).font(.caption).foregroundStyle(Theme.secondary)
    }

    private func summaryCard(_ report: AnalysisReport) -> some View {
        DSACard {
            VStack(alignment: .leading, spacing: 12) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    SectionHeading("這份分析怎麼看")
                    Spacer(minLength: 0)
                    if let trend = ReportText.firstNonEmpty(report.summary.trendPrediction) {
                        StatusBadge(trend, tone: .information)
                            .lineLimit(1)
                            .accessibilityLabel("趨勢：\(trend)")
                    }
                }
                if let summary = report.summary.analysisSummary, !summary.isEmpty {
                    Text(MarkdownParser.inline(summary))
                        .font(.subheadline).foregroundStyle(Theme.text.opacity(0.9))
                        .lineLimit(summaryExpanded ? nil : 4)
                        .accessibilityIdentifier("report.summary")
                    Button(summaryExpanded ? "收起" : "展開摘要") { summaryExpanded.toggle() }
                        .font(.caption.weight(.semibold)).tint(Theme.accent)
                        .frame(minHeight: 44, alignment: .leading)
                } else {
                    Text("這份報告沒有摘要，可閱讀下方的研究論點或完整報告。")
                        .font(.subheadline).foregroundStyle(Theme.secondary)
                }
                if let bullish = ReportText.firstNonEmpty(report.summary.strongestBullishSignal) {
                    ReportLabeledLine("最強看多信號", value: bullish)
                }
                if let bearish = ReportText.firstNonEmpty(report.summary.strongestBearishSignal) {
                    ReportLabeledLine("最強看空信號", value: bearish)
                }
            }
        }
    }

    /// meta.held 為 nil 代表無法判定：兩邊都列，不標「你目前」。
    @ViewBuilder private func positionAdviceCard(_ report: AnalysisReport) -> some View {
        // data_unavailable guardrail: show the model's own advice; the guarded one stays in the disclosure.
        let advice = guardrail(report)?.positionAdvice ?? report.summary.positionAdvice ?? report.structuredReport?.thesis.positionAdvice
        let holding = ReportText.firstNonEmpty(advice?.hasPosition)
        let flat = ReportText.firstNonEmpty(advice?.noPosition)
        if holding != nil || flat != nil {
            DSACard {
                VStack(alignment: .leading, spacing: 12) {
                    SectionHeading("分持股建議", systemImage: "person.crop.circle.badge.questionmark")
                    // 手上有就先看持股那段。
                    if report.meta.held == false {
                        adviceRow("空手", text: flat, current: true)
                        adviceRow("持股", text: holding, current: false)
                    } else {
                        adviceRow("持股", text: holding, current: report.meta.held == true)
                        adviceRow("空手", text: flat, current: false)
                    }
                }
            }
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("report.positionAdvice")
        }
    }

    @ViewBuilder private func adviceRow(_ title: String, text: String?, current: Bool) -> some View {
        if let text {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 6) {
                    Text(title).font(.caption.weight(.semibold)).foregroundStyle(current ? Theme.accent : Theme.secondary)
                    if current { StatusBadge("你目前", tone: .ai) }
                }
                Text(text).font(.subheadline).foregroundStyle(Theme.text)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    // MARK: 價位

    private func priceCard(_ strategy: ReportStrategy, report: AnalysisReport) -> some View {
        let levels = PriceLevel.levels(from: strategy)
        let current = latestQuote?.currentPrice ?? report.meta.currentPrice
        let ruler = PriceRuler(values: levels.map(\.value) + [current])
        let hasNumbers = levels.contains { $0.value != nil }
        return DSACard {
            VStack(alignment: .leading, spacing: 12) {
                SectionHeading("模型規劃價位", systemImage: "slider.horizontal.3")
                if hasNumbers, let ruler {
                    PriceRulerView(ruler: ruler, levels: levels, current: current)
                        .accessibilityIdentifier("report.price.ruler")
                }
                ForEach(levels) { level in
                    priceRow(level, current: current, currency: report.meta.currency)
                }
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("report.prices")
    }

    /// 結構化才算距離；legacy 的句子照原文顯示，不解析。
    private func priceRow(_ level: PriceLevel, current: Double?, currency: String?) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Text(level.kind.title).font(.caption).foregroundStyle(level.kind.tint).frame(width: 64, alignment: .leading)
            if let value = level.value {
                Text(DisplayFormat.price(value, currency: currency)).font(.subheadline.weight(.semibold).monospacedDigit()).foregroundStyle(Theme.text)
                Spacer(minLength: 0)
                if let distance = ReportMath.changePercent(from: current, to: value) {
                    Text("距現價 \(DisplayFormat.percent(distance))").font(.caption.monospacedDigit()).foregroundStyle(Theme.secondary)
                }
            } else {
                Text(level.text ?? "未提供").font(.subheadline).foregroundStyle(level.text == nil ? Theme.secondary : Theme.text)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 0)
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("report.price.\(level.kind.rawValue)")
    }

    // MARK: 事件與條件

    @ViewBuilder private func eventCard(_ report: AnalysisReport) -> some View {
        if let outlook = report.eventOutlook {
            EventOutlookCard(outlook: outlook)
        }
        if let gap = report.structuredReport?.eventGap, gap.triggered == true {
            DSACard {
                VStack(alignment: .leading, spacing: 8) {
                    SectionHeading("重大波動事件", systemImage: "bolt")
                    HStack(spacing: 8) {
                        if let date = gap.eventDate { Text(date).font(.subheadline.monospacedDigit()).foregroundStyle(Theme.text) }
                        Text(DisplayFormat.percent(gap.changePct)).font(.subheadline.monospacedDigit())
                            .foregroundStyle(Theme.changeColor(gap.changePct, convention: store.colorConvention))
                        if gap.eventLowBroken == true { StatusBadge("已跌破事件低點", tone: .warning) }
                    }
                    if let reason = ReportText.firstNonEmpty(gap.reason) {
                        Text(reason).font(.subheadline).foregroundStyle(Theme.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("report.eventGap")
        }
    }

    /// One「接下來怎麼做」card: the summary's conditions plus the artifact's invalidation conditions and
    /// next actions, grouped and de-duplicated (the same sentence is listed once).
    @ViewBuilder private func nextStepsCard(_ report: AnalysisReport) -> some View {
        let summary = report.summary
        let artifact = report.structuredReport
        let invalidations = artifact?.invalidationConditions ?? []
        let exits = ReportNextSteps.unique(summary.exitTriggers, excluding: invalidations.map(\.description))
        let entries = ReportNextSteps.unique(summary.entryConditions, summary.phaseWatchConditions,
                                             excluding: exits + invalidations.map(\.description))
        let actions = (artifact?.nextActions ?? []).filter {
            !(entries + exits).contains($0.label.trimmingCharacters(in: .whitespacesAndNewlines))
        }
        let pending = ReportNextSteps.unique(summary.pendingEvents,
                                             excluding: exits + entries + invalidations.map(\.description) + actions.map(\.label))
        let nextCheck = ReportText.firstNonEmpty(summary.nextCheckTime)
        let hasRevision = !exits.isEmpty || !invalidations.isEmpty
        let hasEntry = !entries.isEmpty || !actions.isEmpty
        if hasRevision || hasEntry || !pending.isEmpty || nextCheck != nil || artifact != nil {
            DSACard {
                VStack(alignment: .leading, spacing: 16) {
                    SectionHeading("接下來怎麼做", systemImage: "scope")
                    if hasRevision {
                        VStack(alignment: .leading, spacing: 8) {
                            if exits.isEmpty {
                                Text("改判條件").font(.subheadline.weight(.semibold)).foregroundStyle(Theme.warning)
                            } else {
                                ReportBulletList(title: "改判條件", items: exits, symbol: "arrow.triangle.branch", color: Theme.warning)
                            }
                            ForEach(invalidations) { InvalidationRow(condition: $0) }
                        }
                    } else if artifact != nil {
                        Text("模型未提供明確失效條件。")
                            .font(.subheadline).foregroundStyle(Theme.secondary)
                    }
                    if hasEntry {
                        VStack(alignment: .leading, spacing: 10) {
                            if entries.isEmpty {
                                Text("進場或觀察條件").font(.subheadline.weight(.semibold)).foregroundStyle(Theme.accent)
                            } else {
                                ReportBulletList(title: "進場或觀察條件", items: entries, symbol: "eye", color: Theme.accent)
                            }
                            ForEach(Array(actions.enumerated()), id: \.offset) { _, action in
                                nextActionRow(action)
                            }
                        }
                    }
                    if !pending.isEmpty {
                        ReportBulletList(title: "待確認事件", items: pending, symbol: "calendar", color: Theme.secondary)
                    }
                    if let nextCheck {
                        Text("下次檢查：\(nextCheck)").font(.caption).foregroundStyle(Theme.secondary)
                    }
                }
            }
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("report.conditions")
        }
    }

    private func nextActionRow(_ action: ResearchNextAction) -> some View {
        HStack(alignment: .top, spacing: 9) {
            Image(systemName: "checklist")
                .font(.caption).foregroundStyle(Theme.accent)
                .padding(.top, 3)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 4) {
                Text(action.label).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.text)
                    .fixedSize(horizontal: false, vertical: true)
                if let reason = ReportText.firstNonEmpty(action.reason) { NativeMarkdownText(text: reason) }
                if let dueAt = action.dueAt {
                    Text("時間：\(DisplayFormat.time(dueAt))").font(.caption).foregroundStyle(Theme.secondary)
                }
            }
        }
    }

    // MARK: 全文

    /// 全文失敗放在收合區外，不展開也看得到。
    private func fullReportCard(_ report: AnalysisReport) -> some View {
        DSACard {
            VStack(alignment: .leading, spacing: 12) {
                if let markdownError {
                    ErrorStateView(message: "完整報告讀取失敗：\(markdownError)") { Task { await loadMarkdown() } }
                        .accessibilityIdentifier("report.fullText.error")
                }
                DisclosureGroup(isExpanded: $fullReportExpanded) {
                    VStack(alignment: .leading, spacing: 12) {
                        if let markdown, !markdown.isEmpty {
                            MarkdownReportBody(
                                text: markdown,
                                alreadyShown: [report.summary.analysisSummary, oneSentence(report)].compactMap { $0 }
                            )
                            .id(markdown)
                        } else if markdownLoading {
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
                        // 掛在標題：掛在 DisclosureGroup 會蓋掉內容裡的識別子（report.table）。
                        .accessibilityIdentifier("report.fullText")
                }
                .tint(Theme.accent)
            }
        }
    }

    private func reportFooter(_ report: AnalysisReport) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            // verbatim：LocalizedStringKey 會把數字加上千分位。
            Text(verbatim: "報告編號 #\(reportID) · 價格與判讀以報告產生時間為準")
            Text(verbatim: "產生時間 \(DisplayFormat.time(report.meta.createdAt))")
            if let model = report.meta.modelUsed, !model.isEmpty {
                Text(verbatim: "分析模型：\(model)")
            }
        }
        .font(.caption2)
        .foregroundStyle(Theme.secondary)
        .textSelection(.enabled)
    }

    // MARK: 載入

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
            await loadQuote(result)
            await loadMarkdown()
        } catch let error as URLError where error.code == .cancelled {
            // 下拉更新被框架取消，不當錯誤顯示。
        } catch {
            guard !Task.isCancelled else { return }
            errorMessage = error.localizedDescription
        }
    }

    /// 報告後漲跌只是輔助資訊，失敗就不顯示那一行。
    @MainActor
    private func loadQuote(_ report: AnalysisReport) async {
        guard !isMarketReview(report), let client = store.client else { return }
        let items = try? await client.quotes([report.meta.stockCode])
        guard !Task.isCancelled else { return }
        latestQuote = items?.first?.quote
    }

    @MainActor
    private func loadMarkdown() async {
        guard let client = store.client else { return }
        markdownError = nil
        markdownLoading = true
        defer { markdownLoading = false }
        do {
            let result = try await client.reportMarkdown(reportID)
            guard !Task.isCancelled else { return }
            markdown = result
        } catch let error as URLError where error.code == .cancelled {
        } catch {
            guard !Task.isCancelled else { return }
            markdownError = error.localizedDescription
        }
    }
}

private extension PriceLevel.Kind {
    var tint: Color {
        switch self {
        case .stopLoss: return Theme.warning
        case .secondaryBuy, .idealBuy: return Theme.accent
        case .takeProfit: return Theme.information
        }
    }
}

/// 價位由低到高畫在一條線上；顏色不用紅綠，紅綠只給行情方向。
private struct PriceRulerView: View {
    let ruler: PriceRuler
    let levels: [PriceLevel]
    let current: Double?

    var body: some View {
        GeometryReader { geometry in
            let width = geometry.size.width
            ZStack(alignment: .topLeading) {
                Rectangle().fill(Theme.border).frame(width: width, height: 2).offset(y: 21)
                ForEach(Array(levels.filter { $0.value != nil }.enumerated()), id: \.element.id) { index, level in
                    marker(level.kind.title, color: level.kind.tint, below: index % 2 == 1)
                        .position(x: clamp(width * ruler.fraction(level.value ?? ruler.lower), width), y: 22)
                }
                if let current {
                    Circle().stroke(Theme.text, lineWidth: 2).frame(width: 12, height: 12)
                        .position(x: clamp(width * ruler.fraction(current), width), y: 22)
                }
            }
        }
        .frame(height: 56)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("價位尺，數值見下方各列")
    }

    /// 文字置中會超出兩端，圓點留在原位、位置收進 24pt 內。
    private func clamp(_ x: CGFloat, _ width: CGFloat) -> CGFloat {
        min(max(x, 24), max(24, width - 24))
    }

    private func marker(_ title: String, color: Color, below: Bool) -> some View {
        VStack(spacing: 2) {
            if !below { Text(title).font(.caption2).foregroundStyle(color).lineLimit(1) } else { Color.clear.frame(height: 13) }
            Circle().fill(color).frame(width: 8, height: 8)
            if below { Text(title).font(.caption2).foregroundStyle(color).lineLimit(1) } else { Color.clear.frame(height: 13) }
        }
        .fixedSize()
    }
}

struct ResearchArtifactView: View {
    let artifact: ResearchArtifact
    @State private var expandedEvidence: Set<String> = []

    var body: some View {
        // Invalidation conditions and next actions live in ResearchReportView's「接下來怎麼做」card.
        VStack(alignment: .leading, spacing: 20) {
            thesisCard
            evidenceCard
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
                if !artifact.thesis.reasons.isEmpty {
                    ReportBulletList(title: "支持這個判斷", items: artifact.thesis.reasons, symbol: "plus.circle", color: Theme.accent)
                }
                if !artifact.thesis.risks.isEmpty {
                    ReportBulletList(title: "同時需要留意", items: artifact.thesis.risks, symbol: "exclamationmark.circle", color: Theme.warning)
                }
            }
        }
    }

    private var evidenceCard: some View {
        DSACard {
            VStack(alignment: .leading, spacing: 14) {
                SectionHeading("判斷依據", subtitle: "\(artifact.evidence.count) 項證據 · 點一下看摘要與來源", systemImage: "text.magnifyingglass")
                if artifact.evidence.isEmpty {
                    Text("這份研究沒有列出可追溯的證據。")
                        .font(.subheadline).foregroundStyle(Theme.secondary)
                }
                ForEach(EvidenceGroup.groups(artifact.evidence)) { group in
                    VStack(alignment: .leading, spacing: 6) {
                        Text(group.title).font(.caption.weight(.semibold)).foregroundStyle(Theme.secondary)
                        ForEach(group.items) { evidenceRow($0) }
                    }
                    .accessibilityElement(children: .contain)
                    .accessibilityIdentifier("report.evidence.group.\(group.key)")
                }
            }
        }
    }

    /// 收合時固定兩行：標題、來源與資料日。
    private func evidenceRow(_ evidence: ResearchEvidence) -> some View {
        let expanded = expandedEvidence.contains(evidence.id)
        return VStack(alignment: .leading, spacing: 8) {
            Button {
                if expanded { expandedEvidence.remove(evidence.id) } else { expandedEvidence.insert(evidence.id) }
            } label: {
                HStack(spacing: 8) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(PresentationText.evidenceTitle(evidence.title))
                            .font(.subheadline.weight(.semibold)).foregroundStyle(Theme.text).lineLimit(1)
                        Text(evidenceMeta(evidence)).font(.caption).foregroundStyle(Theme.secondary).lineLimit(1)
                    }
                    Spacer(minLength: 0)
                    Image(systemName: expanded ? "chevron.up" : "chevron.down")
                        .font(.caption).foregroundStyle(Theme.secondary).accessibilityHidden(true)
                }
                .frame(minHeight: 44)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("report.evidence.\(evidence.id)")
            if expanded {
                if let summary = evidence.summary, !summary.isEmpty {
                    NativeMarkdownText(text: summary)
                }
                if let excerpt = ReportText.firstNonEmpty(evidence.excerpt) {
                    Text(excerpt).font(.caption).foregroundStyle(Theme.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                HStack(spacing: 8) {
                    freshnessBadge(evidence.freshness)
                    Text("品質：\(PresentationText.quality(evidence.qualityLevel))").font(.caption).foregroundStyle(Theme.secondary)
                }
                if let rawURL = evidence.url, let url = URL(string: rawURL), ["https", "http"].contains(url.scheme?.lowercased() ?? "") {
                    Link(destination: url) {
                        Label("開啟來源", systemImage: "arrow.up.right")
                            .font(.caption.weight(.semibold))
                            .frame(minHeight: 44)
                    }
                    .tint(Theme.accent)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func evidenceMeta(_ evidence: ResearchEvidence) -> String {
        var parts = [PresentationText.source(evidence.source)]
        if let date = evidence.observedAt ?? evidence.asOf { parts.append(DisplayFormat.time(date)) }
        if evidence.freshness == "stale" { parts.append("過期") }
        if evidence.complete == false { parts.append("僅部分資料") }
        if evidence.countsTowardScore == false { parts.append("未計分") }
        return parts.joined(separator: " · ")
    }

    private var qualityCard: some View {
        let gaps = ReportGaps.of(artifact)
        return DSACard {
            VStack(alignment: .leading, spacing: 16) {
                SectionHeading("資料完整度", systemImage: "checkmark.shield")
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: 10) { qualityBadges }
                    VStack(alignment: .leading, spacing: 8) { qualityBadges }
                }
                if gaps.incomplete {
                    Label("部分資料缺漏，這份結論可能不完整。", systemImage: "exclamationmark.triangle")
                        .font(.subheadline).foregroundStyle(Theme.warning)
                }
                if !gaps.items.isEmpty {
                    Text("這份報告缺：\(gaps.items.map(PresentationText.evidenceTitle).joined(separator: "、"))")
                        .font(.subheadline).foregroundStyle(Theme.warning)
                        .accessibilityIdentifier("report.gaps")
                }
                if !artifact.dataQuality.limitations.isEmpty {
                    ReportBulletList(title: "解讀限制", items: artifact.dataQuality.limitations.map(PresentationText.limitation), symbol: "info.circle", color: Theme.secondary)
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

/// 一條失效條件；status 只由後端的事實設定，App 不自己判定是否觸發。
struct InvalidationRow: View {
    let condition: InvalidationCondition

    var body: some View {
        let triggered = condition.status == "triggered"
        let lines = InvalidationDisplay.lines(
            description: condition.description,
            trigger: condition.trigger.map(PresentationText.limitation),
            threshold: condition.threshold,
            metric: condition.metric
        )
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(lines.primary)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(Theme.text)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 0)
                if triggered { StatusBadge("已觸發", tone: .warning) }
            }
            if let detail = lines.detail {
                // Amber is reserved for conditions that have already triggered.
                Text(detail)
                    .font(.caption).foregroundStyle(triggered ? Theme.warning : Theme.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let dueAt = condition.dueAt {
                Text("觀察期限：\(DisplayFormat.time(dueAt))")
                    .font(.caption).foregroundStyle(Theme.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(Theme.warning.opacity(0.06), in: RoundedRectangle(cornerRadius: 14))
        .overlay(alignment: .leading) {
            RoundedRectangle(cornerRadius: 2).fill(Theme.warning.opacity(0.7)).frame(width: 3).padding(.vertical, 12)
        }
    }
}

/// Caption label over a subheadline value (summary signals).
private struct ReportLabeledLine: View {
    let label: String
    let value: String

    init(_ label: String, value: String) {
        self.label = label
        self.value = value
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(label).font(.caption).foregroundStyle(Theme.secondary)
            Text(value).font(.subheadline).foregroundStyle(Theme.text)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }
}

struct ReportBulletList: View {
    let title: String
    let items: [String]
    let symbol: String
    let color: Color

    var body: some View {
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
}

// MARK: - Markdown

/// 全文：拆成可收合段落加跳轉膠囊；頁面上已顯示的段落略過。首段預設展開。
private struct MarkdownReportBody: View {
    private let sections: [MarkdownSection]
    @State private var expanded: Set<Int>

    init(text: String, alreadyShown: [String]) {
        let parsed = MarkdownParser.sections(text, alreadyShown: alreadyShown)
        sections = parsed
        // 沒標題的開場段一律顯示，所以預設展開的是第一個有標題的段落。
        _expanded = State(initialValue: Set(parsed.first { $0.title != nil }.map { [$0.id] } ?? []))
    }

    var body: some View {
        ScrollViewReader { proxy in
            VStack(alignment: .leading, spacing: 12) {
                if sections.isEmpty {
                    Text("完整報告的內容都已顯示在上方。").font(.subheadline).foregroundStyle(Theme.secondary)
                }
                if sections.filter({ $0.title != nil }).count > 1 {
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 8) {
                            ForEach(sections.filter { $0.title != nil }) { section in
                                Button {
                                    expanded.insert(section.id)
                                    withAnimation { proxy.scrollTo("report.section.\(section.id)", anchor: .top) }
                                } label: {
                                    Text(section.title ?? "")
                                        .font(.caption.weight(.semibold)).foregroundStyle(Theme.text).lineLimit(1)
                                        .padding(.horizontal, 12).frame(minHeight: 44)
                                        .background(Theme.elevated, in: Capsule())
                                }
                                .buttonStyle(.plain)
                                .accessibilityIdentifier("report.jump.\(section.id)")
                            }
                        }
                    }
                }
                ForEach(sections) { section in
                    sectionView(section).id("report.section.\(section.id)")
                }
            }
        }
    }

    @ViewBuilder private func sectionView(_ section: MarkdownSection) -> some View {
        if let title = section.title {
            let isOpen = expanded.contains(section.id)
            VStack(alignment: .leading, spacing: 8) {
                Button {
                    if isOpen { expanded.remove(section.id) } else { expanded.insert(section.id) }
                } label: {
                    HStack {
                        Text(MarkdownParser.inline(title)).font(.headline).foregroundStyle(Theme.text)
                            .multilineTextAlignment(.leading)
                        Spacer(minLength: 8)
                        Image(systemName: isOpen ? "chevron.up" : "chevron.down")
                            .font(.caption).foregroundStyle(Theme.secondary).accessibilityHidden(true)
                    }
                    .frame(minHeight: 44)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(.isHeader)
                .accessibilityIdentifier("report.section.toggle.\(section.id)")
                if isOpen { MarkdownBlocksView(blocks: section.blocks) }
                Divider().overlay(Theme.border)
            }
        } else {
            MarkdownBlocksView(blocks: section.blocks)
        }
    }
}

/// 短文字（摘要、理由）也走同一套區塊渲染，但不分段。
private struct NativeMarkdownText: View {
    let text: String

    var body: some View {
        MarkdownBlocksView(blocks: MarkdownParser.parse(text))
    }
}

private struct MarkdownBlocksView: View {
    let blocks: [MarkdownBlock]

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(Array(blocks.enumerated()), id: \.offset) { _, block in
                blockView(block)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .textSelection(.enabled)
        .tint(Theme.accent)
        .environment(\.openURL, OpenURLAction { url in
            ["https", "http"].contains(url.scheme?.lowercased() ?? "") ? .systemAction : .discarded
        })
    }

    @ViewBuilder private func blockView(_ block: MarkdownBlock) -> some View {
        switch block {
        case let .heading(level, text):
            Text(MarkdownParser.inline(text))
                .font(headingFont(level))
                .foregroundStyle(Theme.text)
                .padding(.top, 6)
                .accessibilityAddTraits(.isHeader)
        case let .paragraph(text):
            bodyText(text)
        case let .list(items):
            VStack(alignment: .leading, spacing: 6) {
                ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                    listRow(item)
                }
            }
        case let .quote(text):
            HStack(alignment: .top, spacing: 10) {
                RoundedRectangle(cornerRadius: 2).fill(Theme.accent.opacity(0.7)).frame(width: 3)
                bodyText(text)
            }
            .fixedSize(horizontal: false, vertical: true)
        case .divider:
            Divider().overlay(Theme.border).padding(.vertical, 4)
        case let .table(headers, rows):
            MarkdownTableView(headers: headers, rows: rows)
        case let .code(text):
            ScrollView(.horizontal, showsIndicators: false) {
                Text(verbatim: text).font(.caption.monospaced()).foregroundStyle(Theme.text.opacity(0.9))
                    .padding(10)
            }
            .background(Theme.background.opacity(0.55), in: RoundedRectangle(cornerRadius: DSARadius.control))
        }
    }

    private func bodyText(_ text: String) -> some View {
        Text(MarkdownParser.inline(text))
            .font(.subheadline)
            .foregroundStyle(Theme.text.opacity(0.9))
            .fixedSize(horizontal: false, vertical: true)
            .lineSpacing(4)
    }

    /// 符號獨立一欄，換行的文字才會對齊在符號右邊（懸掛縮排）。
    private func listRow(_ item: MarkdownListItem) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            if let status = item.status {
                statusIcon(status)
            } else {
                Text(verbatim: item.marker).font(.subheadline.monospacedDigit()).foregroundStyle(Theme.secondary)
                    .accessibilityHidden(item.marker == "•")
            }
            bodyText(item.text)
        }
        .padding(.leading, CGFloat(item.level) * 16)
    }

    private func statusIcon(_ status: ChecklistStatus) -> some View {
        let style = checklistStyle(status)
        return Image(systemName: style.symbol).font(.caption).foregroundStyle(style.color).accessibilityLabel(style.label)
    }

    private func checklistStyle(_ status: ChecklistStatus) -> (symbol: String, color: Color, label: String) {
        switch status {
        case .passed: return ("checkmark.circle.fill", Theme.accent, "符合")
        case .warning: return ("exclamationmark.triangle.fill", Theme.warning, "注意")
        case .failed: return ("xmark.circle.fill", Theme.warning, "不符合")
        case .pending: return ("circle", Theme.secondary, "待確認")
        }
    }

    private func headingFont(_ level: Int) -> Font {
        if level <= 1 { return Font.title3.weight(.bold) }
        return level == 2 ? Font.headline : Font.subheadline.weight(.semibold)
    }
}

/// 表格不橫捲：兩欄是左右對齊的列，三欄以上每列展開成「首欄標題＋欄名：值」。
private struct MarkdownTableView: View {
    let headers: [String]
    let rows: [[String]]

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if headers.count <= 2 {
                twoColumnRow(headers, header: true)
                ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                    Divider().overlay(Theme.border)
                    twoColumnRow(row, header: false)
                }
            } else {
                ForEach(Array(rows.enumerated()), id: \.offset) { index, row in
                    if index > 0 { Divider().overlay(Theme.border) }
                    wideRow(row)
                }
            }
        }
        .padding(.horizontal, 10)
        .background(Theme.background.opacity(0.55), in: RoundedRectangle(cornerRadius: DSARadius.control))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("report.table")
    }

    private func twoColumnRow(_ cells: [String], header: Bool) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Text(MarkdownParser.inline(cells.first ?? ""))
                .foregroundStyle(header ? Theme.secondary : Theme.text)
                .frame(maxWidth: .infinity, alignment: .leading)
            Text(MarkdownParser.inline(cells.count > 1 ? cells[1] : ""))
                .foregroundStyle(header ? Theme.secondary : Theme.text)
                .multilineTextAlignment(.trailing)
                .frame(maxWidth: .infinity, alignment: .trailing)
        }
        .font(header ? Font.caption : Font.subheadline.monospacedDigit())
        .fixedSize(horizontal: false, vertical: true)
        .padding(.vertical, 8)
    }

    private func wideRow(_ cells: [String]) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(MarkdownParser.inline(cells.first ?? "")).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.text)
            ForEach(Array(zip(headers, cells).dropFirst().enumerated()), id: \.offset) { _, pair in
                HStack(alignment: .firstTextBaseline, spacing: 12) {
                    Text(MarkdownParser.inline(pair.0)).font(.caption).foregroundStyle(Theme.secondary)
                    Spacer(minLength: 8)
                    Text(MarkdownParser.inline(pair.1)).font(.subheadline.monospacedDigit()).foregroundStyle(Theme.text)
                        .multilineTextAlignment(.trailing)
                }
            }
        }
        .fixedSize(horizontal: false, vertical: true)
        .padding(.vertical, 8)
    }
}
