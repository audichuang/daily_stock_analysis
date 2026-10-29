import SwiftUI
import DSACore

struct PortfolioView: View {
    @EnvironmentObject private var store: AppStore
    @State private var snapshot: PortfolioSnapshot?
    @State private var loading = false
    @State private var error: String?

    var body: some View {
        PageScroll {
            SectionHeading("資產，放回全局看。", subtitle: "從帳戶與持股，理解每一筆曝險。", eyebrow: "MY PORTFOLIO")

            if let error {
                ErrorStateView(message: error) { Task { await load() } }
            }

            if let snapshot {
                if snapshot.accounts.isEmpty {
                    emptyPortfolio
                } else {
                    summary(snapshot)
                    SectionHeading("我的帳戶", subtitle: "各帳戶依自己的基準幣別列示。")
                    ForEach(snapshot.accounts) { account in
                        accountCard(account, snapshot: snapshot)
                    }
                    ledgerLink
                }
                Text("資料時間 · \(DisplayFormat.time(snapshot.asOf))\n\(snapshot.costMethod.uppercased()) 成本法 · 下拉重新讀取帳本與報價")
                    .font(.caption2)
                    .foregroundStyle(Theme.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            } else if loading {
                LoadingStateView("正在整理帳戶與持股…")
            }
        }
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
            await load()
        }
        .refreshable { await load() }
    }

    private var emptyPortfolio: some View {
        DSACard {
            VStack(spacing: 18) {
                EmptyStateView(
                    title: "從第一個帳戶開始",
                    message: "目前服務尚未建立投資帳戶。建立帳戶、記錄入金與交易後，就能在這裡查看資產與持股。",
                    systemImage: "chart.pie"
                )
                ledgerLink
            }
        }
    }

    private var ledgerLink: some View {
        NavigationLink {
            ToolWebView(path: "/portfolio", title: "帳本管理")
        } label: {
            Label("開啟帳本管理", systemImage: "square.and.pencil")
                .frame(maxWidth: .infinity)
        }
        .buttonStyle(SecondaryButtonStyle())
        .accessibilityIdentifier("portfolio.openLedger")
    }

    private func summary(_ value: PortfolioSnapshot) -> some View {
        DSACard {
            VStack(alignment: .leading, spacing: 18) {
                HStack {
                    Text("總資產").font(.subheadline).foregroundStyle(Theme.secondary)
                    Spacer()
                    StatusBadge(value.currency, tone: .information)
                }
                Text(DisplayFormat.number(value.fxMissing == true ? nil : value.totalEquity))
                    .font(.system(.largeTitle, design: .rounded, weight: .semibold).monospacedDigit())
                    .foregroundStyle(Theme.text)
                    .minimumScaleFactor(0.7)
                    .lineLimit(1)
                    .accessibilityLabel("總資產 \(money(value.fxMissing == true ? nil : value.totalEquity, currency: value.currency))")

                LazyVGrid(columns: columns, alignment: .leading, spacing: 18) {
                    MetricView("現金", value: money(value.fxMissing == true ? nil : value.totalCash, currency: value.currency))
                    MetricView("持股市值", value: money(value.fxMissing == true ? nil : value.totalMarketValue, currency: value.currency))
                    MetricView("未實現損益", value: money(value.fxMissing == true ? nil : value.unrealizedPnl, currency: value.currency),
                               tint: Theme.changeColor(value.fxMissing == true ? nil : value.unrealizedPnl, convention: store.colorConvention))
                    MetricView("已實現損益", value: money(value.fxMissing == true ? nil : value.realizedPnl, currency: value.currency),
                               tint: Theme.changeColor(value.fxMissing == true ? nil : value.realizedPnl, convention: store.colorConvention))
                }
                Divider().overlay(Theme.border)
                Text("\(value.accountCount) 個帳戶 · 合計以 \(value.currency) 換算")
                    .font(.caption).foregroundStyle(Theme.secondary)
                if value.fxMissing == true {
                    qualityNotice("缺少匯率，跨幣別合計暫不顯示。請在帳本管理確認匯率後重新整理。")
                } else if value.fxStale {
                    qualityNotice("合計使用過期匯率，僅供參考；請在帳本管理更新匯率。")
                }
                dataQuality(value.dataQuality, limitations: value.limitations)
            }
        }
    }

    private func accountCard(_ account: PortfolioAccount, snapshot: PortfolioSnapshot) -> some View {
        // 舊服務未提供帳戶匯率狀態時，沿用總覽已明確回報的缺匯率狀態。
        let missingFX = account.fxMissing ?? (snapshot.fxMissing == true)
        let staleFX = account.fxStale ?? snapshot.fxStale
        return DSACard {
            VStack(alignment: .leading, spacing: 18) {
                VStack(alignment: .leading, spacing: 8) {
                    Text(account.accountName).font(.headline).foregroundStyle(Theme.text)
                    Text("\(marketName(account.market)) · 基準幣別 \(account.baseCurrency)")
                        .font(.caption).foregroundStyle(Theme.secondary)
                }
                LazyVGrid(columns: columns, alignment: .leading, spacing: 16) {
                    MetricView("帳戶資產", value: money(missingFX ? nil : account.totalEquity, currency: account.baseCurrency))
                    MetricView("帳戶現金", value: money(missingFX ? nil : account.totalCash, currency: account.baseCurrency))
                    MetricView("持股市值", value: money(missingFX ? nil : account.totalMarketValue, currency: account.baseCurrency))
                    MetricView("未實現損益", value: money(missingFX ? nil : account.unrealizedPnl, currency: account.baseCurrency),
                               tint: Theme.changeColor(missingFX ? nil : account.unrealizedPnl, convention: store.colorConvention))
                }
                if missingFX {
                    qualityNotice("帳戶缺少換算匯率，合計暫不顯示；個股原幣報價仍可查看。")
                } else if staleFX {
                    qualityNotice("帳戶使用過期匯率，換算值僅供參考。")
                }
                dataQuality(account.dataQuality, limitations: account.limitations)
                if account.positions.isEmpty {
                    Text("這個帳戶目前沒有持股。")
                        .font(.subheadline).foregroundStyle(Theme.secondary)
                } else {
                    ForEach(account.positions) { position in
                        Divider().overlay(Theme.border)
                        NavigationLink {
                            StockDetailView(code: position.symbol)
                        } label: {
                            positionRow(position, accountCurrency: account.baseCurrency, missingFX: missingFX)
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
        }
    }

    private func positionRow(_ position: PortfolioPosition, accountCurrency: String, missingFX: Bool) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .top, spacing: 12) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(position.name ?? position.symbol).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.text)
                    Text("\(position.symbol) · \(DisplayFormat.number(position.quantity, digits: 4)) 股")
                        .font(.caption).foregroundStyle(Theme.secondary)
                }
                Spacer(minLength: 4)
                Image(systemName: "chevron.right").font(.caption.weight(.semibold)).foregroundStyle(Theme.secondary)
            }
            LazyVGrid(columns: columns, alignment: .leading, spacing: 12) {
                MetricView("參考價格", value: money(position.priceAvailable ? position.lastPrice : nil, currency: position.currency))
                MetricView("平均成本", value: money(position.avgCost, currency: position.currency))
                MetricView("持股市值", value: money(missingFX || !position.priceAvailable ? nil : position.marketValueBase,
                                                   currency: position.valuationCurrency ?? accountCurrency))
                MetricView("未實現損益", value: money(missingFX || !position.priceAvailable ? nil : position.unrealizedPnlBase,
                                                    currency: position.valuationCurrency ?? accountCurrency),
                           detail: position.priceAvailable ? DisplayFormat.percent(position.unrealizedPnlPct) : "報價不可用",
                           tint: Theme.changeColor(missingFX || !position.priceAvailable ? nil : position.unrealizedPnlBase,
                                                   convention: store.colorConvention))
            }
            if !position.priceAvailable {
                StatusBadge("報價不可用", tone: .warning, systemImage: "exclamationmark.circle")
            } else if position.priceStale {
                StatusBadge("報價已過期", tone: .warning, systemImage: "clock")
            }
            Text("\(DisplayFormat.source(position.priceProvider ?? position.priceSource)) · \(DisplayFormat.time(position.priceDate))")
                .font(.caption2).foregroundStyle(Theme.secondary)
                .fixedSize(horizontal: false, vertical: true)
            dataQuality(position.dataQuality, limitations: position.limitations)
        }
        .padding(.vertical, 2)
        .contentShape(Rectangle())
    }

    @ViewBuilder
    private func dataQuality(_ quality: String, limitations: [String]) -> some View {
        if quality != "ok" || !limitations.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                Label(quality == "partial" ? "資料不完整" : "資料狀態：\(quality)", systemImage: "info.circle")
                    .font(.caption.weight(.medium)).foregroundStyle(Theme.warning)
                ForEach(Array(limitations.enumerated()), id: \.offset) { _, limitation in
                    Text(limitation).font(.caption2).foregroundStyle(Theme.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }

    private func qualityNotice(_ text: String) -> some View {
        Label(text, systemImage: "exclamationmark.triangle")
            .font(.caption).foregroundStyle(Theme.warning)
            .fixedSize(horizontal: false, vertical: true)
    }

    private var columns: [GridItem] {
        [GridItem(.flexible(), alignment: .leading), GridItem(.flexible(), alignment: .leading)]
    }

    private func money(_ value: Double?, currency: String) -> String {
        "\(DisplayFormat.number(value)) \(currency)"
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
        }
    }
}
