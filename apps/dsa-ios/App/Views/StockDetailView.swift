import SwiftUI
import DSACore

/// 外層只管目前看哪一檔；上下檔切換換掉 id，內層所有狀態（報價、分頁、任務）重新來過，不會留著上一檔的資料。
struct StockDetailView: View {
    let code: String
    @State private var selected: String?

    var body: some View {
        let current = selected ?? code
        StockDetailContent(code: current, onSwitch: { selected = $0 }).id(current)
    }
}

private struct StockDetailContent: View {
    let code: String
    let onSwitch: (String) -> Void
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
    @State private var showsTimeNote = false
    @State private var earningsCalendar: EventCalendarResponse?
    @State private var calendarError: String?
    @State private var session: MarketSessionStatus?
    @State private var selectedTab: StockDetailTab = .ai
    @State private var headerScrolledAway = false
    @State private var adviceHeld: Bool?
    @State private var showsReasons = false
    @State private var strategy: ReportStrategy?
    @State private var route: StockRoute?
    @State private var confirmsReanalysis = false

    /// 頁首底邊滑過導覽列（約 106pt）後，標題改帶現價。
    private let headerThreshold: CGFloat = 110

    var body: some View {
        PageScroll {
            ScrollViewReader { proxy in
                VStack(alignment: .leading, spacing: 16) {
                    if loading && profile == nil { skeleton }
                    if let error { errorBanner(error) }
                    if let profile {
                        quoteHeader(profile)
                        if let position = profile.position { positionStrip(position) }
                        aiSummaryRow(profile, proxy: proxy)
                        nextEarningsSection
                        MarketChart(candles: profile.history.data.compactMap { bar in
                            guard let date = DisplayFormat.date(bar.date) else { return nil }
                            return ChartCandle(date: date, open: bar.open, high: bar.high, low: bar.low, close: bar.close, volume: bar.volume, isProvisional: bar.provisional == true)
                        }, convention: store.colorConvention, market: profile.market,
                                    loadIntraday: store.client.map { client in
                                        IntradayLoaders(day: { try await client.stockTrend(code, range: "day") },
                                                        daily: { try await client.stockTrend(code, range: "month") })
                                    },
                                    latestChangePercent: profile.quote.data?.changePercent)
                        if let quote = profile.quote.data { tradingMetrics(quote) }
                        contentTabs(profile)
                        dataStatusFooter(profile)
                    }
                }
            }
        }
        .navigationTitle(displayName).navigationBarTitleDisplayMode(.inline)
        .toolbar(.hidden, for: .tabBar)
        .toolbar {
            ToolbarItem(placement: .principal) { titleView }
            ToolbarItemGroup(placement: .topBarTrailing) {
                let neighbors = StockNeighbors.of(code, in: store.watchlist.filter { store.isInMarket($0) })
                if neighbors.previous != nil || neighbors.next != nil {
                    Button { if let code = neighbors.previous { onSwitch(code) } } label: { Image(systemName: "chevron.up") }
                        .disabled(neighbors.previous == nil)
                        .accessibilityLabel("上一檔").accessibilityIdentifier("stock.previous")
                    Button { if let code = neighbors.next { onSwitch(code) } } label: { Image(systemName: "chevron.down") }
                        .disabled(neighbors.next == nil)
                        .accessibilityLabel("下一檔").accessibilityIdentifier("stock.next")
                }
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
                moreMenu
            }
        }
        .navigationDestination(item: $route) { route in
            switch route {
            case .askAI(let path):
                ToolWebView(path: path, title: "AI 問股")
            case .alert(let path):
                ToolWebView(path: path, title: "價格警報")
            case .dossier:
                // Title kept: UI tests navigate back from「四維度個股檔案」.
                ToolWebView(path: dossierPath, title: "四維度個股檔案")
            }
        }
        .confirmationDialog("重新分析這檔股票？", isPresented: $confirmsReanalysis, titleVisibility: .visible) {
            Button("開始重新分析") { Task { await startAnalysis() } }
                .accessibilityIdentifier("stock.reanalyze.confirm")
            Button("取消", role: .cancel) {}
        } message: {
            Text("會重新抓取行情與新聞並產生新報告，約需數分鐘；舊報告仍保留在研究紀錄。")
        }
        .refreshable { await load() }
        .task {
            taskID = UserDefaults.standard.string(forKey: taskKey)
            await load()
        }
        .task(id: taskID) { if let taskID { await followTask(taskID) } }
    }

    private var displayName: String { profile?.quote.data?.stockName ?? code }

    private var dossierPath: String { "/api/v1/stocks/\(code)/dossier?theme=dark" }

    // MARK: 情境捷徑

    /// Pushed from the toolbar menu and the price-level capsules; NavigationLink inside a Menu does not push reliably.
    private enum StockRoute: Hashable, Identifiable {
        case askAI(path: String)
        case alert(path: String)
        case dossier

        var id: String {
            switch self {
            case .askAI(let path), .alert(let path): return path
            case .dossier: return "dossier"
            }
        }
    }

    private var moreMenu: some View {
        Menu {
            Button {
                let name = profile?.quote.data?.stockName
                route = .askAI(path: ToolLinks.chatPath(code: code, name: name, recordID: profile?.research.data.latestReport?.id))
            } label: {
                Label("問 AI 這檔", systemImage: "sparkles")
            }
            .accessibilityIdentifier("stock.askAI")
            Button {
                route = .alert(path: ToolLinks.alertPath(code: code, direction: .above, price: nil))
            } label: {
                Label("設價格警報", systemImage: "bell")
            }
            .accessibilityIdentifier("stock.setAlert")
            if profile?.market == "tw" {
                Button {
                    route = .dossier
                } label: {
                    Label("完整個股檔案", systemImage: "doc.text.magnifyingglass")
                }
            }
        } label: {
            Image(systemName: "ellipsis.circle")
        }
        .accessibilityLabel("更多動作")
        .accessibilityIdentifier("stock.more")
    }

    // MARK: 標題與狀態

    /// navigationTitle 維持股名（返回鍵與 UI 測試靠它）；第二行才隨捲動換成現價。
    private var titleView: some View {
        let quote = profile?.quote.data
        let scrolled = headerScrolledAway && quote != nil
        return VStack(spacing: 0) {
            Text(displayName).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.text).lineLimit(1)
            Group {
                if scrolled, let quote {
                    Text("\(priceText(quote.currentPrice)) \(DisplayFormat.percent(quote.changePercent))")
                        .foregroundStyle(Theme.changeColor(quote.changePercent, convention: store.colorConvention))
                } else {
                    Text(verbatim: code).foregroundStyle(Theme.secondary)
                }
            }
            .font(.caption2.monospacedDigit()).lineLimit(1)
        }
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("stock.title")
    }

    private var skeleton: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("000.00").font(.largeTitle.weight(.bold))
            Text("+0.00 +0.00%").font(.headline)
            Text("讀取行情與研究，請稍候").font(.caption)
            RoundedRectangle(cornerRadius: DSARadius.card).fill(Theme.surface).frame(height: 56)
            RoundedRectangle(cornerRadius: DSARadius.card).fill(Theme.surface).frame(height: 260)
            RoundedRectangle(cornerRadius: DSARadius.card).fill(Theme.surface).frame(height: 88)
        }
        .redacted(reason: .placeholder)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("讀取行情與研究…")
        .accessibilityIdentifier("stock.skeleton")
    }

    /// 還沒有資料才佔整塊；已有舊資料時只放一條橫幅，不把畫面清掉。
    @ViewBuilder private func errorBanner(_ message: String) -> some View {
        if profile == nil {
            ErrorStateView(message: message, retry: { Task { await load() } })
        } else {
            HStack(spacing: 8) {
                Image(systemName: "exclamationmark.circle").foregroundStyle(Theme.warning).accessibilityHidden(true)
                Text("更新失敗，顯示的是上次資料").font(.caption).foregroundStyle(Theme.text)
                Spacer(minLength: 0)
                Button("重試") { Task { await load() } }
                    .font(.caption.weight(.semibold)).tint(Theme.accent).frame(minHeight: 44)
            }
            .padding(.horizontal, 12)
            .background(Theme.warning.opacity(0.08), in: RoundedRectangle(cornerRadius: DSARadius.control))
            .accessibilityIdentifier("stock.errorBanner")
        }
    }

    private var currency: String? {
        switch profile?.market {
        case "tw": return "TWD"
        case "us": return "USD"
        default: return nil
        }
    }

    private func priceText(_ value: Double?) -> String { DisplayFormat.price(value, currency: currency) }

    private func signed(_ value: Double?, digits: Int = 2) -> String {
        guard let value, value.isFinite else { return DisplayNumber.noValue }
        return (value > 0 ? "+" : "") + DisplayFormat.number(value, digits: digits)
    }

    // MARK: 頁首

    /// 三行：價、漲跌額與％、開收盤與來源時間；「資料參考時間」的說明收在 ⓘ 裡。
    private func quoteHeader(_ profile: StockProfile) -> some View {
        let quote = profile.quote.data
        let tint = Theme.changeColor(quote?.changePercent, convention: store.colorConvention)
        return VStack(alignment: .leading, spacing: 4) {
            Text(priceText(quote?.currentPrice))
                // One step below largeTitle: the price should not outweigh the AI conclusion, and the chart needs the room.
                .font(.system(.title, design: .rounded, weight: .bold).monospacedDigit()).foregroundStyle(Theme.text)
                .accessibilityIdentifier("stock.price")
            HStack(spacing: 8) {
                Text(signed(quote?.change)).monospacedDigit()
                Text(DisplayFormat.percent(quote?.changePercent)).monospacedDigit()
            }
            .font(.headline).foregroundStyle(tint)
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("stock.change")
            HStack(spacing: 6) {
                Text(referenceLine(quote)).lineLimit(1).minimumScaleFactor(0.8)
                if quote?.isStale == true { StatusBadge("已過期", tone: .warning) }
                Button {
                    withAnimation(.easeOut(duration: 0.15)) { showsTimeNote.toggle() }
                } label: {
                    Image(systemName: "info.circle")
                }
                .buttonStyle(.plain)
                .accessibilityLabel("資料參考時間說明")
                Spacer(minLength: 0)
            }
            .font(.caption).foregroundStyle(Theme.secondary)
            if showsTimeNote {
                Text(MarketDataPresentation.referenceTimeExplanation)
                    .font(.caption2).foregroundStyle(Theme.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let actionError { ErrorStateView(message: actionError) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .background {
            GeometryReader { geometry in
                let away = geometry.frame(in: .global).maxY < headerThreshold
                Color.clear.onChange(of: away) { _, value in headerScrolledAway = value }
            }
        }
    }

    private func referenceLine(_ quote: StockQuote?) -> String {
        var parts: [String] = []
        if let phase = StockSessionLabel.text(session?.marketPhase) { parts.append(phase) }
        parts.append(DisplayFormat.source(quote?.sourceCode ?? quote?.source))
        parts.append("資料參考時間 \(DisplayFormat.time(quote?.asOf ?? quote?.updateTime))")
        return parts.joined(separator: " · ")
    }

    private func positionStrip(_ position: StockProfilePosition) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text("我的持股").font(.caption).foregroundStyle(Theme.secondary)
                Text("\(DisplayFormat.number(position.quantity, digits: 0)) 股 · 成本 \(DisplayFormat.price(position.avgCost, currency: position.currency))")
                    .font(.subheadline.monospacedDigit()).foregroundStyle(Theme.text)
                    .lineLimit(1).minimumScaleFactor(0.8)
            }
            Spacer(minLength: 8)
            VStack(alignment: .trailing, spacing: 2) {
                Text("\(signed(position.unrealizedPnl, digits: 0)) \(DisplayFormat.percent(position.unrealizedPnlPct))")
                    .font(.subheadline.weight(.semibold).monospacedDigit())
                    .foregroundStyle(Theme.changeColor(position.unrealizedPnl, convention: store.colorConvention))
                    .lineLimit(1).minimumScaleFactor(0.8)
                if let weight = position.weightPct {
                    Text("佔持股 \(DisplayFormat.number(weight, digits: 1))%").font(.caption).foregroundStyle(Theme.secondary)
                }
            }
        }
        .padding(12)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: DSARadius.card, style: .continuous))
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("stock.position")
    }

    private struct Conclusion {
        let action: String?
        let tone: ActionTone
        let text: String?
        /// Stored enum and label, fed to ActionBadge.
        let rawAction: String?
        let rawLabel: String?
    }

    /// 結構化報告優先；只有歷史列時讀列表欄位。動作一律走枚舉，不顯示存檔標籤。
    private func conclusion(_ profile: StockProfile) -> Conclusion? {
        let latest = profile.research.data.latestReport
        if let thesis = profile.research.data.structuredReport?.thesis {
            return Conclusion(
                action: PresentationText.action(thesis.action, label: thesis.actionLabel),
                tone: ActionTone.of(action: thesis.action, label: thesis.actionLabel),
                text: ReportText.firstNonEmpty(thesis.oneSentence, latest?.oneSentence, thesis.summary, latest?.analysisSummary),
                rawAction: thesis.action, rawLabel: thesis.actionLabel
            )
        }
        guard let latest else { return nil }
        return Conclusion(
            action: PresentationText.action(latest.action, label: latest.actionLabel, advice: latest.operationAdvice),
            tone: ActionTone.of(action: latest.action, label: latest.actionLabel ?? latest.operationAdvice),
            text: ReportText.firstNonEmpty(latest.oneSentence, latest.analysisSummary),
            rawAction: latest.action, rawLabel: latest.actionLabel ?? latest.operationAdvice
        )
    }

    /// 兩行結論＋動作膠囊；有結構化價位時，下方接停損與目標價，可直接設警報。
    @ViewBuilder private func aiSummaryRow(_ profile: StockProfile, proxy: ScrollViewProxy) -> some View {
        if let conclusion = conclusion(profile) {
            VStack(alignment: .leading, spacing: 10) {
                Button {
                    selectedTab = .ai
                    withAnimation { proxy.scrollTo("stock.tabs", anchor: .top) }
                } label: {
                    HStack(alignment: .top, spacing: 10) {
                        if let badge = ActionBadge(action: conclusion.rawAction, label: conclusion.rawLabel, size: .regular) {
                            badge
                        } else {
                            StatusBadge(conclusion.action ?? "AI", tone: conclusion.tone.statusTone)
                        }
                        Text(conclusion.text ?? "完整分析已保存，點開查看。")
                            .font(.subheadline).foregroundStyle(Theme.text)
                            .lineLimit(2).multilineTextAlignment(.leading)
                            .frame(maxWidth: .infinity, alignment: .leading)
                        Image(systemName: "chevron.right").font(.caption).foregroundStyle(Theme.secondary)
                            .padding(.top, 3).accessibilityHidden(true)
                    }
                    .frame(minHeight: 44, alignment: .top)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("stock.aiSummary")
                priceLevelRow(profile, tone: conclusion.tone)
            }
            .padding(12)
            .background(conclusion.tone.color.opacity(0.08), in: RoundedRectangle(cornerRadius: DSARadius.card, style: .continuous))
        }
    }

    /// 停損與目標（減碼類動作叫「反彈減碼」）；只用結構化數字，legacy 原文不解析。
    @ViewBuilder private func priceLevelRow(_ profile: StockProfile, tone: ActionTone) -> some View {
        let levels = strategy.map(PriceLevel.levels(from:))?
            .filter { ($0.kind == .stopLoss || $0.kind == .takeProfit) && $0.value != nil } ?? []
        if !levels.isEmpty {
            let current = profile.quote.data?.currentPrice
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 16) { priceLevelItems(levels, current: current, tone: tone) }
                VStack(alignment: .leading, spacing: 8) { priceLevelItems(levels, current: current, tone: tone) }
            }
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("stock.priceLevels")
        }
    }

    @ViewBuilder private func priceLevelItems(_ levels: [PriceLevel], current: Double?, tone: ActionTone) -> some View {
        ForEach(levels) { level in
            if let value = level.value {
                HStack(spacing: 6) {
                    Text(levelTitle(level.kind, tone: tone))
                        .font(.caption).foregroundStyle(Theme.secondary)
                    Text(priceText(value)).font(.subheadline.weight(.semibold).monospacedDigit()).foregroundStyle(Theme.text)
                    Button {
                        route = .alert(path: ToolLinks.alertPath(code: code, direction: alertDirection(level.kind, value: value, current: current), price: value))
                    } label: {
                        Label("設警報", systemImage: "bell")
                            .font(.caption2.weight(.semibold))
                            .foregroundStyle(Theme.accent)
                            .padding(.horizontal, 8)
                            .frame(minHeight: 28)
                            .background(Theme.accent.opacity(0.12), in: Capsule())
                            .frame(minHeight: 44)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("\(levelTitle(level.kind, tone: tone)) \(priceText(value)) 設警報")
                    .accessibilityIdentifier("stock.setAlert.\(level.kind.rawValue)")
                }
                .fixedSize()
            }
        }
    }

    private func levelTitle(_ kind: PriceLevel.Kind, tone: ActionTone) -> String {
        kind == .takeProfit ? (tone == .caution ? "反彈減碼" : "目標") : kind.title
    }

    /// 停損一律跌破；其他價位依與現價的相對位置決定（現價未知時當跌破）。
    private func alertDirection(_ kind: PriceLevel.Kind, value: Double, current: Double?) -> ToolLinks.AlertDirection {
        if kind == .stopLoss { return .below }
        guard let current, current.isFinite else { return .below }
        return value > current ? .above : .below
    }

    private var nextEarnings: CalendarEvent? {
        earningsCalendar?.events.nextCompanyEvent()
    }

    /// 44pt 提示條：只在有已排定的公司事件時出現；7 天內改琥珀色。
    @ViewBuilder private var nextEarningsSection: some View {
        if let event = nextEarnings {
            let soon = event.isWithinSevenDays()
            let label = earningsLabel(event)
            // Container keeps `stock.nextEarnings`; the link itself carries `stock.earnings.soon` within 7 days.
            VStack(spacing: 0) {
                NavigationLink { EventCalendarView() } label: {
                    HStack(spacing: 8) {
                        Image(systemName: "calendar").accessibilityHidden(true)
                        Text(label).font(.subheadline.weight(soon ? .semibold : .regular).monospacedDigit())
                            .lineLimit(1).minimumScaleFactor(0.8)
                        if event.status == "estimated" { StatusBadge(event.statusLabel, tone: .warning) }
                        Spacer(minLength: 0)
                        Image(systemName: "chevron.right").font(.caption).accessibilityHidden(true)
                    }
                    .foregroundStyle(soon ? Theme.warning : Theme.secondary)
                    .padding(.horizontal, 12)
                    .frame(height: 44)
                    .background((soon ? Theme.warning.opacity(0.10) : Theme.surface),
                                in: RoundedRectangle(cornerRadius: DSARadius.card, style: .continuous))
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(event.status == "estimated" ? "\(label)，\(event.statusLabel)" : label)
                .accessibilityHint("開啟事件行事曆")
                .accessibilityIdentifier(soon ? "stock.earnings.soon" : "stock.earnings.link")
            }
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("stock.nextEarnings")
        }
    }

    /// 「法說會 11/3（3 天後）」；非台北時區的事件補上時區，美股財報日跟台灣日曆差一天。
    private func earningsLabel(_ event: CalendarEvent) -> String {
        let kind = event.type == "investor_conference" ? "法說會" : "財報"
        var date = event.date
        if let day = EventCalendarDate.parse(event.date) {
            let parts = EventCalendarDate.calendar.dateComponents([.month, .day], from: day)
            if let month = parts.month, let dayOfMonth = parts.day { date = "\(month)/\(dayOfMonth)" }
        }
        var text = "\(kind) \(date)"
        if let days = event.daysAway() {
            text += "（\(days == 0 ? "今天" : days == 1 ? "明天" : "\(days) 天後")）"
        }
        if event.timezone == "America/New_York" { text += " · \(event.timezoneLabel)" }
        return text
    }

    private var taskKey: String { "analysisTask.\(store.baseURL?.absoluteString ?? "").\(code)" }

    // MARK: 成交資訊

    /// 兩列四欄；有委買賣時再多一列，不撐成大卡。
    private func tradingMetrics(_ quote: StockQuote) -> some View {
        let columns = Array(repeating: GridItem(.flexible(), alignment: .leading), count: dynamicTypeSize.isAccessibilitySize ? 2 : 4)
        return VStack(alignment: .leading, spacing: 12) {
            LazyVGrid(columns: columns, alignment: .leading, spacing: 12) {
                CompactMetric("開盤", DisplayFormat.number(quote.open))
                CompactMetric("最高", DisplayFormat.number(quote.high))
                CompactMetric("最低", DisplayFormat.number(quote.low))
                CompactMetric("昨收", DisplayFormat.number(quote.prevClose))
                CompactMetric("成交量（股）", DisplayNumber.compact(quote.volume))
                CompactMetric("成交值", DisplayNumber.compact(quote.amount))
                CompactMetric("量比", DisplayFormat.number(quote.volumeRatio))
                CompactMetric("均價", DisplayFormat.number(quote.averagePrice))
            }
            if quote.bestBid != nil || quote.bestAsk != nil {
                HStack(spacing: 12) {
                    CompactMetric("最佳買價", MarketDataPresentation.orderBookPrice(quote.bestBid, volume: quote.bestBidVolume))
                    CompactMetric("最佳賣價", MarketDataPresentation.orderBookPrice(quote.bestAsk, volume: quote.bestAskVolume))
                }
            }
        }
        .padding(12)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: DSARadius.card, style: .continuous))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("stock.metrics")
    }

    // MARK: 內容分頁

    private func contentTabs(_ profile: StockProfile) -> some View {
        let reportID = profile.research.data.latestReport?.id
        let tabs = StockDetailTab.available(market: profile.market, hasChips: profile.chips != nil, hasReport: reportID != nil)
        let active = tabs.contains(selectedTab) ? selectedTab : .ai
        return VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 0) {
                ForEach(tabs) { tab in
                    Button {
                        selectedTab = tab
                    } label: {
                        VStack(spacing: 6) {
                            Text(tab.title)
                                .font(.subheadline.weight(tab == active ? .semibold : .regular))
                                .foregroundStyle(tab == active ? Theme.text : Theme.secondary)
                            Rectangle().fill(tab == active ? Theme.accent : Color.clear).frame(height: 2)
                        }
                        .frame(maxWidth: .infinity, minHeight: 44, alignment: .bottom)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("stock.tab.\(tab.rawValue)")
                    .accessibilityAddTraits(tab == active ? .isSelected : [])
                }
            }
            .id("stock.tabs")
            switch active {
            case .ai:
                aiTab(profile)
            case .chips:
                if let chips = profile.chips { chipsTab(chips) }
            case .financials:
                FinancialsSection(code: code)
            case .news:
                if let reportID { ReportNewsView(reportID: reportID).id(reportID) }
            }
        }
    }

    @ViewBuilder private func aiTab(_ profile: StockProfile) -> some View {
        let research = profile.research.data
        let artifact = research.structuredReport
        let hasReport = research.latestReport?.id != nil
        // With a report and no running task,「重新分析」is a text button beside the analysis time.
        let inlineReanalysis = hasReport && taskID == nil
        if let conclusion = conclusion(profile) {
            actionBlock(conclusion, createdAt: artifact?.createdAt ?? research.latestReport?.createdAt, showsReanalysis: inlineReanalysis)
        } else {
            EmptyStateView(title: "這檔股票還沒有 AI 研究", message: "產生分析後，這裡會顯示核心論點、證據與需要持續追蹤的風險。", systemImage: "text.magnifyingglass")
        }
        if let advice = artifact?.thesis.positionAdvice { adviceSwitch(advice, profile: profile) }
        if let artifact, !artifact.invalidationConditions.isEmpty { invalidationSummary(artifact) }
        if let outlook = research.eventOutlook { EventOutlookCard(outlook: outlook) }
        if let artifact { reasonsSection(artifact) }
        if let id = research.latestReport?.id {
            NavigationLink { ResearchReportView(reportID: id) } label: {
                Label("閱讀完整報告", systemImage: "doc.text").frame(maxWidth: .infinity)
            }.buttonStyle(PressableButtonStyle()).accessibilityIdentifier("stock-report-link")
        }
        if let taskMessage {
            DSACard {
                VStack(alignment: .leading, spacing: 10) {
                    Text(taskMessage).font(.subheadline).foregroundStyle(Theme.text)
                    if let progress { ProgressView(value: Double(progress), total: 100).tint(Theme.accent) }
                    if let taskID {
                        DisclosureGroup("任務詳情") {
                            Text(verbatim: taskID).font(.caption2.monospaced()).foregroundStyle(Theme.secondary)
                                .textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .font(.caption).tint(Theme.secondary)
                    }
                }
            }
        }
        if !(inlineReanalysis && conclusion(profile) != nil) {
            analysisButton(hasReport: hasReport)
        }
        Text("分析在伺服器執行，會保存至研究紀錄。這次操作不發送 Telegram 通知。")
            .font(.caption2).foregroundStyle(Theme.secondary)
        if profile.market == "tw" {
            NavigationLink {
                ToolWebView(path: dossierPath, title: "四維度個股檔案")
            } label: {
                HStack(spacing: 12) {
                    Image(systemName: "doc.text.magnifyingglass").foregroundStyle(Theme.accent).accessibilityHidden(true)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("完整個股檔案").font(.subheadline.weight(.semibold)).foregroundStyle(Theme.text)
                        Text("基本面・籌碼・估值・技術").font(.caption).foregroundStyle(Theme.secondary)
                    }
                    Spacer(minLength: 0)
                    Image(systemName: "chevron.right").font(.caption).foregroundStyle(Theme.secondary).accessibilityHidden(true)
                }
                .padding(.horizontal, 12)
                .frame(minHeight: 56)
                .background(Theme.surface, in: RoundedRectangle(cornerRadius: DSARadius.card, style: .continuous))
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("stock-dossier-link")
        }
    }

    private func actionBlock(_ conclusion: Conclusion, createdAt: String?, showsReanalysis: Bool) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(conclusion.action ?? "AI 觀點")
                .font(DSAType.title).foregroundStyle(conclusion.tone.color)
                .accessibilityIdentifier("stock.ai.action")
            Text(conclusion.text ?? "完整分析已保存，點下方閱讀報告。")
                .font(.body).foregroundStyle(Theme.text)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 8) {
                Text("分析 · \(DisplayFormat.time(createdAt))").font(.caption).foregroundStyle(Theme.secondary)
                if showsReanalysis {
                    Button {
                        confirmsReanalysis = true
                    } label: {
                        HStack(spacing: 4) {
                            if starting { ProgressView().controlSize(.mini).tint(Theme.accent) }
                            Text("重新分析")
                        }
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(Theme.accent)
                        .frame(minHeight: 44)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .disabled(starting || polling)
                    .accessibilityIdentifier("analysis-start")
                }
                Spacer(minLength: 0)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(conclusion.tone.color.opacity(0.10), in: RoundedRectangle(cornerRadius: DSARadius.card, style: .continuous))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("stock.ai.block")
    }

    @ViewBuilder private func adviceSwitch(_ advice: ReportPositionAdvice, profile: StockProfile) -> some View {
        let held = adviceHeld ?? profile.holdingKnown
        let text = held.flatMap { ReportText.firstNonEmpty($0 ? advice.hasPosition : advice.noPosition) }
        if ReportText.firstNonEmpty(advice.hasPosition, advice.noPosition) != nil {
            VStack(alignment: .leading, spacing: 10) {
                Picker("持股狀態", selection: Binding(get: { held }, set: { adviceHeld = $0 })) {
                    Text("持股").tag(Bool?.some(true))
                    Text("空手").tag(Bool?.some(false))
                }
                .pickerStyle(.segmented)
                .accessibilityIdentifier("stock.advice.picker")
                if held == nil {
                    // 持股查不到時不替使用者選，兩邊都列出來。
                    Text("讀不到持股資料，兩種情況都列出來。").font(.caption).foregroundStyle(Theme.secondary)
                    ForEach([("持股", advice.hasPosition), ("空手", advice.noPosition)], id: \.0) { label, value in
                        if let value = ReportText.firstNonEmpty(value) {
                            Text("\(label)：\(value)").font(.subheadline).foregroundStyle(Theme.text)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                } else {
                    Text(text ?? "這份報告沒有給這個狀態的建議。")
                        .font(.subheadline).foregroundStyle(text == nil ? Theme.secondary : Theme.text)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityIdentifier("stock.advice.text")
                }
            }
        }
    }

    private func invalidationSummary(_ artifact: ResearchArtifact) -> some View {
        DSACard {
            VStack(alignment: .leading, spacing: 12) {
                SectionHeading("改判條件", systemImage: "arrow.triangle.branch")
                ForEach(artifact.invalidationConditions.prefix(3)) { InvalidationRow(condition: $0) }
                if artifact.invalidationConditions.count > 3 {
                    Text("還有 \(artifact.invalidationConditions.count - 3) 項，見完整報告。")
                        .font(.caption).foregroundStyle(Theme.secondary)
                }
            }
        }
    }

    /// 依據預設收起；完整的證據與來源在報告頁。
    private func reasonsSection(_ artifact: ResearchArtifact) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Button {
                withAnimation(.easeOut(duration: 0.15)) { showsReasons.toggle() }
            } label: {
                HStack {
                    Text("依據與風險（\(artifact.thesis.reasons.count + artifact.thesis.risks.count)）")
                        .font(.subheadline.weight(.semibold)).foregroundStyle(Theme.text)
                    Spacer()
                    Image(systemName: showsReasons ? "chevron.up" : "chevron.down")
                        .font(.caption).foregroundStyle(Theme.secondary).accessibilityHidden(true)
                }
                .frame(minHeight: 44)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("stock.ai.reasons")
            if showsReasons {
                if !artifact.thesis.reasons.isEmpty {
                    ReportBulletList(title: "支持這個判斷", items: artifact.thesis.reasons, symbol: "plus.circle", color: Theme.accent)
                }
                if !artifact.thesis.risks.isEmpty {
                    ReportBulletList(title: "同時需要留意", items: artifact.thesis.risks, symbol: "exclamationmark.circle", color: Theme.warning)
                }
            }
        }
    }

    /// 已有報告時「重新分析」降成次要按鈕，主按鈕讓給閱讀報告；重新分析一律先確認。
    @ViewBuilder private func analysisButton(hasReport: Bool) -> some View {
        let button = Button {
            if let taskID {
                Task { await followTask(taskID) }
            } else if hasReport {
                confirmsReanalysis = true
            } else {
                Task { await startAnalysis() }
            }
        } label: {
            HStack {
                if starting || polling { ProgressView().tint(hasReport ? Theme.accent : Theme.background) }
                Label(taskID != nil ? "查看分析進度" : (hasReport ? "重新分析" : "產生 AI 分析"), systemImage: "waveform.path")
            }
            .frame(maxWidth: .infinity)
        }
        .disabled(starting || polling)
        .accessibilityIdentifier("analysis-start")
        if hasReport {
            button.buttonStyle(SecondaryButtonStyle())
        } else {
            button.buttonStyle(PressableButtonStyle())
        }
    }

    private func chipsTab(_ chips: StockProfileChips) -> some View {
        DSACard {
            VStack(alignment: .leading, spacing: 16) {
                VStack(alignment: .leading, spacing: 10) {
                    SectionHeading("三大法人", subtitle: chips.institutionalDate.map { "資料日 \($0) · 買賣超（張）" }, systemImage: "person.3")
                    LazyVGrid(columns: Array(repeating: GridItem(.flexible(), alignment: .leading), count: 2), alignment: .leading, spacing: 12) {
                        chipMetric("外資", shares: chips.foreignNet)
                        chipMetric("投信", shares: chips.trustNet)
                        chipMetric("自營商", shares: chips.dealerNet)
                        chipMetric("合計", shares: chips.totalNet)
                    }
                }
                Divider().overlay(Theme.border)
                VStack(alignment: .leading, spacing: 10) {
                    SectionHeading("融資融券", subtitle: chips.marginDate.map { "資料日 \($0) · 單位張" }, systemImage: "percent")
                    LazyVGrid(columns: Array(repeating: GridItem(.flexible(), alignment: .leading), count: 2), alignment: .leading, spacing: 12) {
                        CompactMetric("融資餘額", DisplayFormat.number(chips.marginBalance, digits: 0))
                        CompactMetric("融券餘額", DisplayFormat.number(chips.shortBalance, digits: 0))
                        CompactMetric("融資 5 日增減", signed(chips.marginChg5, digits: 0))
                        CompactMetric("融資 20 日增減", signed(chips.marginChg20, digits: 0))
                        CompactMetric("券資比", chips.shortMarginRatio.map { "\(DisplayFormat.number($0))%" } ?? DisplayNumber.noValue)
                    }
                }
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("stock.chips")
    }

    /// 後端法人單位是股，畫面統一換成張。
    private func chipMetric(_ label: String, shares: Double?) -> some View {
        let lots = shares.map { $0 / 1000 }
        return CompactMetric(label, signed(lots, digits: 0), tint: Theme.changeColor(lots, convention: store.colorConvention))
    }

    /// 限制說明收成頁尾一列，需要時才展開。
    @ViewBuilder private func dataStatusFooter(_ profile: StockProfile) -> some View {
        let values = uniqueLimitations(profile)
        if !values.isEmpty {
            DisclosureGroup {
                VStack(alignment: .leading, spacing: 7) {
                    ForEach(Array(values.enumerated()), id: \.offset) { _, text in
                        Label(PresentationText.limitation(text), systemImage: "info.circle")
                            .font(.caption).foregroundStyle(Theme.secondary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                .padding(.top, 8)
            } label: {
                Text("資料狀態 · \(values.count) 項說明").font(.caption).foregroundStyle(Theme.secondary)
            }
            .tint(Theme.secondary)
            .accessibilityIdentifier("stock.dataStatus")
        }
    }

    private func uniqueLimitations(_ profile: StockProfile) -> [String] {
        var seen = Set<String>()
        return (profile.quote.limitations + profile.history.limitations + profile.research.limitations + profile.evidenceQuality.limitations)
            .filter { seen.insert($0).inserted }
    }

    // MARK: 載入

    private func load() async {
        guard let client = store.client else { return }
        loading = true
        defer { loading = false }
        do { profile = try await client.stockProfile(code, historyDays: 1100); error = nil }
        catch is CancellationError { }
        catch let error as URLError where error.code == .cancelled { }
        catch { self.error = error.localizedDescription }
        // 開收盤狀態只是標示，取不到就不顯示，不影響報價。
        if let market = profile?.market {
            session = (try? await client.marketSession(region: market)) ?? session
        }
        // Price levels live only in the full report; a failure just hides the price row.
        if let reportID = profile?.research.data.latestReport?.id {
            do { strategy = try await client.report(reportID).strategy }
            catch is CancellationError { }
            catch let error as URLError where error.code == .cancelled { }
            catch { strategy = nil }
        } else {
            strategy = nil
        }
        // 財報快取失敗不遮住已取得的行情與研究。
        let today = EventCalendarDate.parse(EventCalendarDate.key(Date(), timezone: "America/New_York"))!
        let until = EventCalendarDate.calendar.date(byAdding: .day, value: 365, to: today)!
        do {
            earningsCalendar = try await client.calendarEvents(from: EventCalendarDate.key(today), to: EventCalendarDate.key(until), code: code)
            calendarError = nil
        } catch is CancellationError { }
        catch let error as URLError where error.code == .cancelled { }
        catch { calendarError = error.localizedDescription }
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

/// 四欄窄格用的小讀數：放不下就縮字，不換行撐高。
private struct CompactMetric: View {
    let label: String
    let value: String
    let tint: Color

    init(_ label: String, _ value: String, tint: Color = Theme.text) {
        self.label = label
        self.value = value
        self.tint = tint
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(label).font(.caption2).foregroundStyle(Theme.secondary).lineLimit(1).minimumScaleFactor(0.8)
            Text(value).font(.subheadline.monospacedDigit()).foregroundStyle(tint).lineLimit(1).minimumScaleFactor(0.7)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }
}
