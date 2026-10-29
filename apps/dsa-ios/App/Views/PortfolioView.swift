import SwiftUI
import DSACore

struct PortfolioView: View {
    @EnvironmentObject private var store: AppStore
    @State private var snapshot: PortfolioSnapshot?
    @State private var loading = false
    @State private var error: String?
    @State private var selectedCurrency = "TWD"
    @State private var expandedAccounts: Set<Int> = []
    @State private var expandedPositions: Set<String> = []
    @ScaledMetric(relativeTo: .title3) private var priceSize: CGFloat = 23

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                if let error {
                    ErrorStateView(message: error) { Task { await load() } }
                }
                if let snapshot {
                    if let total = selectedTotal(in: snapshot) {
                        let accounts = snapshot.accounts.filter { $0.baseCurrency == total.currency }
                        if snapshot.currencyTotals.count > 1 {
                            Picker("顯示幣別", selection: currencySelection(in: snapshot)) {
                                ForEach(snapshot.currencyTotals) { item in
                                    Text(currencyName(item.currency)).tag(item.currency)
                                }
                            }
                            .pickerStyle(.segmented)
                            .accessibilityIdentifier("portfolio.currency-picker")
                        }
                        summary(total)
                        ForEach(accounts) { account in
                            accountSection(account)
                        }
                        dataNotes(total: total, accounts: accounts)
                        ledgerLink
                    } else {
                        emptyPortfolio
                    }
                    Text("更新於 \(DisplayFormat.time(snapshot.asOf)) · \(snapshot.costMethod.uppercased()) 成本法")
                        .font(.caption2)
                        .foregroundStyle(Theme.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                } else if loading {
                    LoadingStateView("正在讀取資產與持股…")
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
            .frame(maxWidth: 900, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
        .background(Theme.background)
        .navigationTitle("我的資產")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                NavigationLink { ToolWebView(path: "/portfolio", title: "帳本管理") } label: {
                    Image(systemName: "square.and.pencil")
                }
                .accessibilityLabel("管理帳本")
            }
        }
        .task(id: store.baseURL) {
            snapshot = nil
            expandedAccounts = []
            expandedPositions = []
            await load()
        }
        .refreshable { await load() }
    }

    private func selectedTotal(in value: PortfolioSnapshot) -> PortfolioCurrencyTotal? {
        value.currencyTotals.first { $0.currency == selectedCurrency } ?? value.currencyTotals.first
    }

    private func currencySelection(in value: PortfolioSnapshot) -> Binding<String> {
        Binding(get: { selectedTotal(in: value)?.currency ?? selectedCurrency }, set: { selectedCurrency = $0 })
    }

    private var emptyPortfolio: some View {
        VStack(spacing: 12) {
            EmptyStateView(
                title: "尚未建立投資帳戶",
                message: "建立帳戶並記錄入金與交易，就能查看資產與持股。",
                systemImage: "chart.pie"
            )
            ledgerLink
        }
    }

    private var ledgerLink: some View {
        NavigationLink { ToolWebView(path: "/portfolio", title: "帳本管理") } label: {
            Label("開啟帳本管理", systemImage: "square.and.pencil")
                .font(.subheadline.weight(.medium))
                .frame(maxWidth: .infinity, minHeight: 44)
        }
        .buttonStyle(.plain)
        .foregroundStyle(Theme.accent)
        .accessibilityIdentifier("portfolio.openLedger")
    }

    private func summary(_ value: PortfolioCurrencyTotal) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                Text("\(currencyName(value.currency))資產")
                    .font(.subheadline.weight(.semibold)).foregroundStyle(Theme.text)
                Spacer()
                Text(value.currency).font(.caption.weight(.medium)).foregroundStyle(Theme.secondary)
            }
            Text(DisplayFormat.number(value.totalEquity))
                .font(.title.weight(.bold).monospacedDigit())
                .foregroundStyle(Theme.text)
                .minimumScaleFactor(0.75).lineLimit(1)
                .accessibilityLabel("\(currencyName(value.currency))資產 \(money(value.totalEquity, currency: value.currency))")
                .accessibilityIdentifier("portfolio.summary.totalEquity")
            LazyVGrid(columns: columns, alignment: .leading, spacing: 10) {
                compactMetric("現金", value: value.totalCash, currency: value.currency)
                compactMetric("持股市值", value: value.totalMarketValue, currency: value.currency)
                compactMetric("未實現損益", value: value.unrealizedPnl, currency: value.currency, isChange: true)
                compactMetric("已實現損益", value: value.realizedPnl, currency: value.currency, isChange: true)
            }
            Text("\(value.accountCount) 個帳戶 · 未跨幣別換算")
                .font(.caption2).foregroundStyle(Theme.secondary)
            if value.fxMissing {
                qualityNotice("缺少帳戶換算匯率，合計暫不顯示；個股原幣報價仍可查看。")
            } else if value.fxStale {
                qualityNotice("帳戶內的換算使用過期匯率，合計僅供參考。")
            }
        }
        .padding(12)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: 14))
        .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(Theme.border, lineWidth: 1))
        .accessibilityIdentifier("portfolio.summary")
    }

    private func accountSection(_ account: PortfolioAccount) -> some View {
        let missingFX = account.fxMissing == true
        return VStack(alignment: .leading, spacing: 0) {
            Button {
                toggle(account.accountId, in: &expandedAccounts)
            } label: {
                HStack(alignment: .center, spacing: 8) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(account.accountName).font(.headline).foregroundStyle(Theme.text)
                            .fixedSize(horizontal: false, vertical: true)
                        Text("\(marketName(account.market)) · \(currencyName(account.baseCurrency)) \(account.baseCurrency)")
                            .font(.caption2).foregroundStyle(Theme.secondary)
                    }
                    Spacer(minLength: 8)
                    VStack(alignment: .trailing, spacing: 3) {
                        Text("帳戶資產").font(.caption2).foregroundStyle(Theme.secondary)
                        Text(money(missingFX ? nil : account.totalEquity, currency: account.baseCurrency))
                            .font(.subheadline.weight(.semibold).monospacedDigit()).foregroundStyle(Theme.text)
                    }
                    Image(systemName: expandedAccounts.contains(account.accountId) ? "chevron.up" : "chevron.down")
                        .font(.caption2.weight(.semibold)).foregroundStyle(Theme.secondary)
                }
                .frame(minHeight: 44)
                .contentShape(Rectangle())
                .padding(.vertical, 10)
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("portfolio.account.\(account.accountId)")
            .accessibilityHint("展開或收起帳戶明細")

            if missingFX {
                qualityNotice("帳戶缺少換算匯率，合計暫不顯示。")
                    .padding(.bottom, 10)
            } else if account.fxStale == true {
                qualityNotice("帳戶使用過期匯率，換算值僅供參考。")
                    .padding(.bottom, 10)
            }
            if expandedAccounts.contains(account.accountId) {
                LazyVGrid(columns: columns, alignment: .leading, spacing: 12) {
                    compactMetric("帳戶現金", value: missingFX ? nil : account.totalCash, currency: account.baseCurrency)
                    compactMetric("持股市值", value: missingFX ? nil : account.totalMarketValue, currency: account.baseCurrency)
                    compactMetric("未實現損益", value: missingFX ? nil : account.unrealizedPnl, currency: account.baseCurrency, isChange: true)
                    compactMetric("已實現損益", value: missingFX ? nil : account.realizedPnl, currency: account.baseCurrency, isChange: true)
                }
                .padding(.bottom, 14)
            }
            if account.positions.isEmpty {
                Text("目前沒有持股")
                    .font(.subheadline).foregroundStyle(Theme.secondary)
                    .padding(.vertical, 12)
            } else {
                ForEach(account.positions) { position in
                    Divider().overlay(Theme.border)
                    positionGroup(position, account: account)
                }
            }
        }
        .padding(.horizontal, 12)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(Theme.border, lineWidth: 1))
    }

    private func positionGroup(_ position: PortfolioPosition, account: PortfolioAccount) -> some View {
        let key = "\(account.accountId):\(position.id)"
        let expanded = expandedPositions.contains(key)
        let missingFX = account.fxMissing == true
        let pnl = missingFX || !position.priceAvailable ? nil : position.unrealizedPnlBase
        let valuationCurrency = position.valuationCurrency ?? account.baseCurrency
        return VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 0) {
                NavigationLink { StockDetailView(code: position.symbol) } label: {
                    HStack(alignment: .center, spacing: 10) {
                        VStack(alignment: .leading, spacing: 5) {
                            Text(position.name ?? position.symbol)
                                .font(.subheadline.weight(.semibold)).foregroundStyle(Theme.text)
                                .fixedSize(horizontal: false, vertical: true)
                            Text("\(position.symbol) · \(DisplayFormat.number(position.quantity, digits: 4)) 股")
                                .font(.caption2).foregroundStyle(Theme.secondary)
                            if !position.priceAvailable {
                                priceStatus("尚無報價", icon: "exclamationmark.circle")
                            } else if position.priceStale {
                                priceStatus("價格過期", icon: "clock")
                            }
                        }
                        .frame(minWidth: 95, alignment: .leading)
                        Spacer(minLength: 0)
                        VStack(alignment: .trailing, spacing: 5) {
                            Text(money(position.priceAvailable ? position.lastPrice : nil, currency: position.currency))
                                .font(.system(size: priceSize, weight: .semibold, design: .rounded).monospacedDigit())
                                .foregroundStyle(Theme.text).lineLimit(1).minimumScaleFactor(0.75)
                            Text(pnl.map { signedMoney($0, currency: valuationCurrency) } ?? "損益暫不可用")
                                .font(.caption.weight(.semibold).monospacedDigit())
                                .foregroundStyle(Theme.changeColor(pnl, convention: store.colorConvention))
                            if pnl != nil, let percentage = position.unrealizedPnlPct {
                                Text(DisplayFormat.percent(percentage))
                                    .font(.caption2.monospacedDigit())
                                    .foregroundStyle(Theme.changeColor(percentage, convention: store.colorConvention))
                            }
                        }
                    }
                    .padding(.vertical, 11)
                    .frame(minHeight: 76)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("portfolio.position.\(account.accountId).\(position.symbol)")
                Button { toggle(key, in: &expandedPositions) } label: {
                    Image(systemName: expanded ? "chevron.up" : "ellipsis")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(Theme.secondary)
                        .frame(width: 44, height: 44)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("\(position.name ?? position.symbol)持股明細")
                .accessibilityIdentifier("portfolio.positionDetails.\(account.accountId).\(position.symbol)")
            }
            if expanded {
                LazyVGrid(columns: columns, alignment: .leading, spacing: 12) {
                    compactMetric("平均成本", value: position.avgCost, currency: position.currency)
                    compactMetric("持股市值", value: missingFX || !position.priceAvailable ? nil : position.marketValueBase,
                                  currency: valuationCurrency)
                }
                .padding(.bottom, 10)
                Text("\(PresentationText.source(position.priceProvider ?? position.priceSource)) · \(DisplayFormat.time(position.priceDate))")
                    .font(.caption2).foregroundStyle(Theme.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.bottom, 12)
            }
        }
    }

    @ViewBuilder
    private func dataNotes(total: PortfolioCurrencyTotal, accounts: [PortfolioAccount]) -> some View {
        let limitations = Array(Set(total.limitations + accounts.flatMap { account in
            account.limitations + account.positions.flatMap(\.limitations)
        })).sorted()
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
                    .font(.subheadline).foregroundStyle(Theme.secondary)
                    .frame(minHeight: 44)
            }
            .tint(Theme.secondary)
            .accessibilityIdentifier("portfolio.data-notes")
        }
    }

    private func compactMetric(_ label: String, value: Double?, currency: String, isChange: Bool = false) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label).font(.caption2).foregroundStyle(Theme.secondary)
            Text(isChange ? value.map { signedMoney($0, currency: currency) } ?? "—" : money(value, currency: currency))
                .font(.callout.weight(.semibold).monospacedDigit())
                .foregroundStyle(isChange ? Theme.changeColor(value, convention: store.colorConvention) : Theme.text)
                .lineLimit(1).minimumScaleFactor(0.75)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }

    private func priceStatus(_ title: String, icon: String) -> some View {
        Label(title, systemImage: icon)
            .font(.caption2).foregroundStyle(Theme.warning)
    }

    private func qualityNotice(_ text: String) -> some View {
        Label(text, systemImage: "exclamationmark.triangle")
            .font(.caption).foregroundStyle(Theme.warning)
            .fixedSize(horizontal: false, vertical: true)
    }

    private var columns: [GridItem] {
        [GridItem(.flexible(), alignment: .leading), GridItem(.flexible(), alignment: .leading)]
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

    private func money(_ value: Double?, currency: String) -> String {
        guard let value, value.isFinite else { return "—" }
        let prefix: String
        switch currency {
        case "TWD": prefix = "NT$"
        case "USD": prefix = "US$"
        case "CNY": prefix = "CN¥"
        case "HKD": prefix = "HK$"
        default: prefix = currency + " "
        }
        return (value < 0 ? "−" : "") + prefix + DisplayFormat.number(abs(value))
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

    private func toggle<Value: Hashable>(_ value: Value, in set: inout Set<Value>) {
        if set.contains(value) { set.remove(value) } else { set.insert(value) }
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
        }
    }
}
