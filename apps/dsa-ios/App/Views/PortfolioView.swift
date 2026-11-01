import SwiftUI
import DSACore

/// 左滑只有 List 才有，所以整頁是 List；每個區塊都是一列。
struct PortfolioView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @State private var snapshot: PortfolioSnapshot?
    @State private var risk: PortfolioRiskReport?
    @State private var loading = false
    @State private var error: String?
    @State private var market = PortfolioView.allMarkets
    @State private var mode: ViewMode = .accounts
    @State private var sort: PortfolioHoldingSort = .marketValue
    @State private var collapsedAccounts: Set<Int> = []
    @State private var expandedHoldings: Set<String> = []
    @State private var route: Route?

    private static let allMarkets = "all"

    private enum ViewMode: String, CaseIterable, Identifiable {
        case accounts, merged
        var id: String { rawValue }
        var title: String { self == .accounts ? "依帳戶" : "合併持股" }
    }

    private enum Route: Hashable {
        case stock(String)
        case ledger
    }

    var body: some View {
        List {
            if let error {
                ErrorStateView(title: snapshot == nil ? "資產載入失敗" : "更新失敗，顯示上次資料", message: error) {
                    Task { await load() }
                }
                .plainRow()
            }
            if let snapshot {
                content(snapshot)
            } else if loading {
                LoadingStateView("正在讀取資產與持股…").plainRow()
            }
            PageBottomAnchor().plainRow()
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
        .dsaPageBottomInset()
        .background(Theme.background)
        .navigationTitle("我的資產")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) { addMenu }
        }
        .navigationDestination(item: $route) { target in
            switch target {
            case let .stock(code): StockDetailView(code: code)
            case .ledger: ToolWebView(path: "/portfolio", title: "帳本管理")
            }
        }
        .task(id: store.baseURL) {
            snapshot = nil
            risk = nil
            collapsedAccounts = []
            expandedHoldings = []
            await load()
        }
        .refreshable { await load() }
    }

    /// Web 的帳本頁沒有深連結，選單的每一項都開同一頁，在那裡完成。
    private var addMenu: some View {
        Menu {
            Button("新增交易", systemImage: "arrow.left.arrow.right") { route = .ledger }
            Button("資金異動", systemImage: "banknote") { route = .ledger }
            Button("新增帳戶", systemImage: "person.crop.circle.badge.plus") { route = .ledger }
        } label: {
            Image(systemName: "plus")
        }
        .accessibilityLabel("新增")
        .accessibilityIdentifier("portfolio.add")
    }

    @ViewBuilder
    private func content(_ value: PortfolioSnapshot) -> some View {
        if !value.hasAnyAssets {
            emptyPortfolio.plainRow()
        } else {
            summary(value).plainRow()
            let insights = PortfolioInsights.make(snapshot: value, risk: risk)
            if !insights.isEmpty { insightRow(insights).plainRow() }
            controls(value).plainRow()
            let accounts = visibleAccounts(in: value)
            switch mode {
            case .accounts:
                ForEach(accounts) { account in
                    accountRows(account)
                }
            case .merged:
                mergedRows(accounts)
            }
            footer(value, accounts: accounts).plainRow()
        }
    }

    private func visibleAccounts(in value: PortfolioSnapshot) -> [PortfolioAccount] {
        guard market != Self.allMarkets else { return value.accounts }
        return value.accounts.filter { $0.market.lowercased() == market }
    }

    private var emptyPortfolio: some View {
        VStack(spacing: 12) {
            EmptyStateView(
                title: "尚未建立投資帳戶",
                message: "建立帳戶並記錄入金與交易，就能查看資產與持股。",
                systemImage: "chart.pie"
            )
            Button("開啟帳本管理") { route = .ledger }
                .buttonStyle(.plain)
                .font(.subheadline.weight(.medium))
                .foregroundStyle(Theme.accent)
                .frame(maxWidth: .infinity, minHeight: 44)
                .accessibilityIdentifier("portfolio.openLedger")
        }
    }

    // MARK: 總覽

    private func summary(_ value: PortfolioSnapshot) -> some View {
        DSACard {
            VStack(alignment: .leading, spacing: 10) {
                if let overview = value.overview {
                    overviewContent(overview)
                    if overview.fxMissing || overview.totalAssets == nil { nativeTotals(value.currencyTotals) }
                } else {
                    nativeTotals(value.currencyTotals)
                }
                quoteStatus(value)
            }
        }
    }

    @ViewBuilder
    private func overviewContent(_ overview: PortfolioOverview) -> some View {
        Text("全部資產（\(currencyName(overview.currency))折合）")
            .font(.subheadline.weight(.semibold)).foregroundStyle(Theme.text)
        Text(wholeMoney(overview.totalAssets, currency: overview.currency))
            .font(.title.weight(.bold).monospacedDigit())
            .foregroundStyle(Theme.text)
            .minimumScaleFactor(0.75).lineLimit(dynamicTypeSize.isAccessibilitySize ? nil : 1)
            .accessibilityLabel("全部資產 \(wholeMoney(overview.totalAssets, currency: overview.currency))")
            .accessibilityIdentifier("portfolio.summary.totalEquity")
        LazyVGrid(columns: columns, alignment: .leading, spacing: 10) {
            compactMetric("今日損益", value: overview.dayPnl, currency: overview.currency, isChange: true)
            compactMetric("未實現損益", value: overview.unrealizedPnl, currency: overview.currency, isChange: true,
                          detail: overview.unrealizedPct.map { DisplayFormat.percent($0) })
            compactMetric("已實現損益", value: overview.realizedPnl, currency: overview.currency, isChange: true)
            compactMetric("現金", value: overview.cash, currency: overview.currency)
        }
        if overview.fxMissing {
            qualityNotice("缺少換算匯率，折合金額暫不顯示；以下是各幣別原幣合計。")
        } else if overview.fxStale {
            qualityNotice("折合使用過期匯率，僅供參考。")
        }
        if overview.hasNegativeCash {
            Button { route = .ledger } label: {
                qualityNotice("淨現金為負，可能有入金還沒記帳，點這裡補記。")
                    .frame(minHeight: 44)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("portfolio.negativeCash")
        }
        if let fund = overview.fundValue, fund > 0 {
            Text("含基金 \(wholeMoney(fund, currency: overview.currency))")
                .font(.caption2).foregroundStyle(Theme.secondary)
        } else if !overview.fundsIncluded {
            Text("基金暫時讀不到，總額只算帳本。")
                .font(.caption2).foregroundStyle(Theme.warning)
        }
    }

    private func nativeTotals(_ totals: [PortfolioCurrencyTotal]) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(totals) { total in
                HStack(alignment: .firstTextBaseline) {
                    Text("\(currencyName(total.currency))帳戶").font(.caption).foregroundStyle(Theme.secondary)
                    Spacer(minLength: 8)
                    Text(money(total.totalEquity, currency: total.currency))
                        .font(.subheadline.weight(.semibold).monospacedDigit()).foregroundStyle(Theme.text)
                }
            }
        }
    }

    private func quoteStatus(_ value: PortfolioSnapshot) -> some View {
        var delayed = 0, stale = 0, missing = 0, live = 0
        for position in value.accounts.flatMap(\.positions) {
            switch PresentationText.quoteWarning(available: position.priceAvailable, stale: position.priceStale,
                                                 source: position.priceProvider ?? position.priceSource) {
            case nil: live += 1
            case "可能延遲": delayed += 1
            case "價格過期": stale += 1
            default: missing += 1
            }
        }
        var parts: [String] = []
        if live > 0 { parts.append("正常 \(live)") }
        if delayed > 0 { parts.append("延遲 \(delayed)") }
        if stale > 0 { parts.append("過期 \(stale)") }
        if missing > 0 { parts.append("無報價 \(missing)") }
        return Text("報價：" + (parts.isEmpty ? "沒有持股" : parts.joined(separator: " · ")))
            .font(.caption2)
            .foregroundStyle(delayed + stale + missing > 0 ? Theme.warning : Theme.secondary)
            .accessibilityIdentifier("portfolio.quoteStatus")
    }

    private func insightRow(_ insights: [PortfolioInsight]) -> some View {
        HStack(alignment: .top, spacing: 8) {
            ForEach(insights) { insight in
                VStack(alignment: .leading, spacing: 3) {
                    Text(insight.title).font(.caption2).foregroundStyle(Theme.secondary)
                    Text(insight.value)
                        .font(.subheadline.weight(.semibold).monospacedDigit())
                        .foregroundStyle(insight.isAlert ? Theme.warning : Theme.text)
                        .lineLimit(1).minimumScaleFactor(0.75)
                    Text(insight.detail).font(.caption2).foregroundStyle(Theme.secondary).lineLimit(1)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(10)
                .background(Theme.surface, in: RoundedRectangle(cornerRadius: DSARadius.card))
                .accessibilityElement(children: .combine)
                .accessibilityIdentifier("portfolio.insight.\(insight.id)")
            }
        }
    }

    // MARK: 篩選與排序

    private func controls(_ value: PortfolioSnapshot) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            if value.marketKeys.count > 1 {
                Picker("市場", selection: $market) {
                    Text("全部").tag(Self.allMarkets)
                    ForEach(value.marketKeys, id: \.self) { key in
                        Text(marketName(key)).tag(key)
                    }
                }
                .pickerStyle(.segmented)
                .accessibilityIdentifier("portfolio.market-picker")
            }
            HStack(spacing: 12) {
                Picker("檢視方式", selection: $mode) {
                    ForEach(ViewMode.allCases) { item in
                        Text(item.title).tag(item)
                    }
                }
                .pickerStyle(.segmented)
                .accessibilityIdentifier("portfolio.view-mode")
                Menu {
                    Picker("排序", selection: $sort) {
                        ForEach(PortfolioHoldingSort.allCases) { item in
                            Text(item.title).tag(item)
                        }
                    }
                } label: {
                    Label(sort.title, systemImage: "arrow.up.arrow.down")
                        .font(.caption.weight(.medium))
                        .frame(minHeight: 44)
                }
                .accessibilityIdentifier("portfolio.sort")
            }
        }
    }

    // MARK: 帳戶

    @ViewBuilder
    private func accountRows(_ account: PortfolioAccount) -> some View {
        let missingFX = account.fxMissing == true
        let isCollapsed = collapsedAccounts.contains(account.accountId)
        Button {
            if isCollapsed { collapsedAccounts.remove(account.accountId) } else { collapsedAccounts.insert(account.accountId) }
        } label: {
            accountHeader(account, missingFX: missingFX, collapsed: isCollapsed)
        }
        .buttonStyle(.plain)
        .plainRow(top: 10, bottom: 4)
        .accessibilityValue(isCollapsed ? "已收合" : "已展開")
        .accessibilityIdentifier("portfolio.account.\(account.accountId)")
        if !isCollapsed {
            if missingFX {
                qualityNotice("帳戶缺少換算匯率，合計暫不顯示。").plainRow(top: 0, bottom: 4)
            } else if account.fxStale == true {
                qualityNotice("帳戶使用過期匯率，換算值僅供參考。").plainRow(top: 0, bottom: 4)
            }
            let holdings = PortfolioHoldings.forAccount(account, sort: sort)
            if holdings.isEmpty {
                Text("目前沒有持股").font(.subheadline).foregroundStyle(Theme.secondary).plainRow(top: 4, bottom: 8)
            } else {
                ForEach(holdings) { holding in
                    holdingRow(holding, identifier: "portfolio.position.\(account.accountId).\(holding.symbol)")
                }
            }
        }
    }

    private func accountHeader(_ account: PortfolioAccount, missingFX: Bool, collapsed: Bool) -> some View {
        HStack(alignment: .center, spacing: 8) {
            VStack(alignment: .leading, spacing: 3) {
                Text(account.accountName).font(.headline).foregroundStyle(Theme.text)
                    .fixedSize(horizontal: false, vertical: true)
                Text("\(marketName(account.market)) · 現金 \(money(missingFX ? nil : account.totalCash, currency: account.baseCurrency))")
                    .font(.caption2.monospacedDigit())
                    .foregroundStyle(!missingFX && account.totalCash < 0 ? Theme.warning : Theme.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 8)
            VStack(alignment: .trailing, spacing: 3) {
                Text(money(missingFX ? nil : account.totalEquity, currency: account.baseCurrency))
                    .font(.subheadline.weight(.semibold).monospacedDigit()).foregroundStyle(Theme.text)
                if let day = account.dayPnl, !missingFX {
                    Text("今日 " + signedMoney(day, currency: account.baseCurrency))
                        .font(.caption2.monospacedDigit())
                        .foregroundStyle(Theme.changeColor(day, convention: store.colorConvention))
                }
            }
            Image(systemName: collapsed ? "chevron.down" : "chevron.up")
                .font(.caption2.weight(.semibold)).foregroundStyle(Theme.secondary)
                .accessibilityHidden(true)
        }
        .frame(minHeight: 44)
        .contentShape(Rectangle())
    }

    @ViewBuilder
    private func mergedRows(_ accounts: [PortfolioAccount]) -> some View {
        ForEach(PortfolioHoldings.merged(accounts, sort: sort)) { group in
            Text("\(currencyName(group.currency))持股")
                .font(.subheadline.weight(.semibold)).foregroundStyle(Theme.text)
                .plainRow(top: 10, bottom: 2)
                .accessibilityAddTraits(.isHeader)
            ForEach(group.holdings) { holding in
                holdingRow(holding, identifier: "portfolio.merged.\(holding.symbol)")
            }
        }
    }

    // MARK: 持股列

    private func holdingRow(_ holding: PortfolioHolding, identifier: String) -> some View {
        let expanded = expandedHoldings.contains(holding.id)
        return VStack(alignment: .leading, spacing: 0) {
            Button { route = .stock(holding.symbol) } label: { holdingColumns(holding) }
                .buttonStyle(.plain)
                .accessibilityIdentifier(identifier)
            if expanded { holdingDetails(holding) }
        }
        .plainRow(top: 0, bottom: 0, separator: true)
        .swipeActions(edge: .trailing, allowsFullSwipe: false) {
            Button(expanded ? "收起" : "明細") {
                if expanded { expandedHoldings.remove(holding.id) } else { expandedHoldings.insert(holding.id) }
            }
            .tint(Theme.information)
            Button("帳本") { route = .ledger }
                .tint(Theme.elevated)
        }
    }

    /// 四欄：名稱、現價與今日、市值與佔比、損益最粗。大字級改單欄，不截金額。
    @ViewBuilder
    private func holdingColumns(_ holding: PortfolioHolding) -> some View {
        let identity = holdingIdentity(holding)
        let price = numberColumn(
            DisplayFormat.price(holding.lastPrice, currency: holding.currency),
            detail: DisplayFormat.percent(holding.dayChangePct),
            detailColor: Theme.changeColor(holding.dayChangePct, convention: store.colorConvention),
            primaryColor: Theme.text, weight: .regular
        )
        let value = numberColumn(
            DisplayFormat.number(holding.marketValue, digits: 0),
            detail: holding.sharePct.map { DisplayFormat.number($0, digits: 1) + "%" } ?? "—",
            detailColor: Theme.secondary,
            primaryColor: Theme.text, weight: .regular
        )
        let pnl = numberColumn(
            signedWhole(holding.unrealizedPnl),
            detail: DisplayFormat.percent(holding.unrealizedPct),
            detailColor: Theme.changeColor(holding.unrealizedPnl, convention: store.colorConvention),
            primaryColor: Theme.changeColor(holding.unrealizedPnl, convention: store.colorConvention),
            weight: .bold
        )
        Group {
            if dynamicTypeSize.isAccessibilitySize {
                VStack(alignment: .leading, spacing: 8) {
                    identity
                    price
                    value
                    pnl
                }
            } else {
                HStack(spacing: 8) {
                    identity.frame(maxWidth: .infinity, alignment: .leading)
                    price.frame(width: 64, alignment: .trailing)
                    value.frame(width: 72, alignment: .trailing)
                    pnl.frame(width: 72, alignment: .trailing)
                }
            }
        }
        .padding(.vertical, 6)
        .frame(minHeight: 56)
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
    }

    private func holdingIdentity(_ holding: PortfolioHolding) -> some View {
        let warning = PresentationText.quoteWarning(available: holding.priceAvailable, stale: holding.priceStale, source: holding.priceSource)
        let subtitle = warning.map { "\(holding.symbol) · \($0)" } ?? holding.symbol
        return VStack(alignment: .leading, spacing: 3) {
            Text(holding.name ?? holding.symbol)
                .font(.subheadline.weight(.semibold)).foregroundStyle(Theme.text)
                .lineLimit(dynamicTypeSize.isAccessibilitySize ? nil : 1)
            Text(subtitle)
                .font(.caption2).foregroundStyle(warning == nil ? Theme.secondary : Theme.warning)
                .lineLimit(dynamicTypeSize.isAccessibilitySize ? nil : 1)
        }
    }

    private func numberColumn(_ primary: String, detail: String, detailColor: Color, primaryColor: Color, weight: Font.Weight) -> some View {
        VStack(alignment: dynamicTypeSize.isAccessibilitySize ? .leading : .trailing, spacing: 3) {
            Text(primary)
                .font(.footnote.weight(weight).monospacedDigit())
                .foregroundStyle(primaryColor)
                .lineLimit(dynamicTypeSize.isAccessibilitySize ? nil : 1).minimumScaleFactor(0.7)
            Text(detail)
                .font(.caption2.monospacedDigit())
                .foregroundStyle(detailColor)
                .lineLimit(dynamicTypeSize.isAccessibilitySize ? nil : 1).minimumScaleFactor(0.7)
        }
    }

    private func holdingDetails(_ holding: PortfolioHolding) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            LazyVGrid(columns: columns, alignment: .leading, spacing: 8) {
                compactMetric("平均成本", value: holding.avgCost, currency: holding.currency)
                compactMetric("持有股數", text: DisplayFormat.number(holding.quantity, digits: 4))
            }
            let accounts = holding.accountCount > 1 ? " · \(holding.accountCount) 個帳戶" : ""
            Text("\(PresentationText.source(holding.priceSource)) · \(DisplayFormat.time(holding.priceDate))\(accounts)")
                .font(.caption2).foregroundStyle(Theme.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.bottom, 10)
    }

    private func signedWhole(_ value: Double?) -> String {
        guard let value, value.isFinite else { return "—" }
        return (value > 0 ? "+" : "") + DisplayFormat.number(value, digits: 0)
    }

    // MARK: 頁尾

    @ViewBuilder
    private func footer(_ value: PortfolioSnapshot, accounts: [PortfolioAccount]) -> some View {
        let limitations = Array(Set(accounts.flatMap { account in
            account.limitations + account.positions.flatMap(\.limitations)
        })).sorted()
        VStack(alignment: .leading, spacing: 4) {
            if !limitations.isEmpty {
                DisclosureGroup {
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(limitations, id: \.self) { limitation in
                            Text(PresentationText.limitation(limitation))
                                .font(.caption).foregroundStyle(Theme.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    .padding(.top, 8)
                } label: {
                    Label("資料說明", systemImage: "info.circle")
                        .font(.caption).foregroundStyle(Theme.secondary)
                        .frame(minHeight: 44)
                }
                .tint(Theme.secondary)
                .accessibilityIdentifier("portfolio.data-notes")
            }
            Text("更新於 \(DisplayFormat.time(value.asOf)) · \(value.costMethod.uppercased()) 成本法")
                .font(.caption2)
                .foregroundStyle(Theme.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    // MARK: 共用小元件

    private func compactMetric(_ label: String, value: Double?, currency: String, isChange: Bool = false, detail: String? = nil) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label).font(.caption2).foregroundStyle(Theme.secondary)
            Text(isChange ? value.map { signedMoney($0, currency: currency) } ?? "—" : money(value, currency: currency))
                .font(.callout.weight(.semibold).monospacedDigit())
                .foregroundStyle(isChange ? Theme.changeColor(value, convention: store.colorConvention) : (value ?? 0) < 0 ? Theme.warning : Theme.text)
                .lineLimit(dynamicTypeSize.isAccessibilitySize ? nil : 1).minimumScaleFactor(0.75)
                .fixedSize(horizontal: false, vertical: true)
            if let detail {
                Text(detail)
                    .font(.caption2.monospacedDigit())
                    .foregroundStyle(Theme.changeColor(value, convention: store.colorConvention))
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }

    private func compactMetric(_ label: String, text: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label).font(.caption2).foregroundStyle(Theme.secondary)
            Text(text).font(.callout.weight(.semibold).monospacedDigit()).foregroundStyle(Theme.text)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }

    private func qualityNotice(_ text: String) -> some View {
        Label(text, systemImage: "exclamationmark.triangle")
            .font(.caption).foregroundStyle(Theme.warning)
            .fixedSize(horizontal: false, vertical: true)
    }

    private var columns: [GridItem] {
        Array(repeating: GridItem(.flexible(), alignment: .leading),
              count: dynamicTypeSize.isAccessibilitySize ? 1 : 2)
    }

    private func currencyName(_ currency: String) -> String {
        switch currency {
        case "TWD": return "新臺幣"
        case "USD": return "美元"
        case "CNY": return "人民幣"
        case "HKD": return "港幣"
        default: return currency
        }
    }

    private func moneyPrefix(_ currency: String) -> String {
        switch currency {
        case "TWD": return "NT$"
        case "USD": return "US$"
        case "CNY": return "CN¥"
        case "HKD": return "HK$"
        default: return currency + " "
        }
    }

    private func money(_ value: Double?, currency: String) -> String {
        guard let value, value.isFinite else { return "—" }
        return (value < 0 ? "−" : "") + moneyPrefix(currency) + DisplayFormat.number(abs(value))
    }

    private func wholeMoney(_ value: Double?, currency: String) -> String {
        guard let value, value.isFinite else { return "—" }
        return (value < 0 ? "−" : "") + moneyPrefix(currency) + DisplayFormat.number(abs(value), digits: 0)
    }

    private func signedMoney(_ value: Double, currency: String) -> String {
        (value > 0 ? "+" : "") + money(value, currency: currency)
    }

    private func marketName(_ market: String) -> String {
        switch market.lowercased() {
        case "tw": return "台股"
        case "us": return "美股"
        case "hk": return "港股"
        case "cn": return "A 股"
        default: return market.uppercased()
        }
    }

    @MainActor
    private func load() async {
        guard !loading, let client = store.client else { return }
        loading = true
        error = nil
        defer { loading = false }
        do {
            let result = try await client.portfolioSnapshot()
            guard !Task.isCancelled else { return }
            snapshot = result
        } catch {
            if !Task.isCancelled { self.error = error.localizedDescription }
            return
        }
        // 洞察卡是加值，快照先畫出來再補；舊服務沒有這條路由或失敗時，只少集中度與產業。
        if let report = try? await client.portfolioRisk(), !Task.isCancelled {
            risk = report
        }
    }
}

private extension View {
    /// List 列去掉系統底色與分隔線，看起來跟其他捲動頁一樣。
    func plainRow(top: CGFloat = 6, bottom: CGFloat = 6, separator: Bool = false) -> some View {
        listRowBackground(Color.clear)
            .listRowInsets(EdgeInsets(top: top, leading: 16, bottom: bottom, trailing: 16))
            .listRowSeparator(separator ? .visible : .hidden)
            .listRowSeparatorTint(Theme.border)
    }
}
