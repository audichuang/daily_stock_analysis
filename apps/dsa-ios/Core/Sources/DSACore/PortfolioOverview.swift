import Foundation

/// 資產頁總覽。金額只讀後端的 consolidated_*，客戶端不換匯、不跨幣別加總；
/// 基金讀不到時只算帳本並標明，不把缺值當 0。與 Web 持股頁同一個口徑。
public struct PortfolioOverview: Equatable, Sendable {
    public let currency: String
    public let totalAssets: Double?
    public let fundValue: Double?
    public let dayPnl: Double?
    public let unrealizedPnl: Double?
    public let unrealizedPct: Double?
    public let realizedPnl: Double?
    public let cash: Double?
    public let marketValue: Double?
    public let fxMissing: Bool
    public let fxStale: Bool

    public var fundsIncluded: Bool { fundValue != nil }
    public var hasNegativeCash: Bool { (cash ?? 0) < 0 }
}

public extension PortfolioSnapshot {
    /// 基金持倉獨立於股票帳戶，只有基金時仍算有資產。
    var hasAnyAssets: Bool { !accounts.isEmpty || hasFundHoldings || (consolidatedFundValueBase ?? 0) > 0 }

    private var hasFundHoldings: Bool { !(funds?.items ?? []).isEmpty }

    /// 只有基金、淨值又讀不到：有資產但金額未知，不能顯示成 0。
    var fundOnlyValueUnknown: Bool { accounts.isEmpty && hasFundHoldings && consolidatedFundValueBase == nil }

    /// 帳本加基金的今日損益。基金有市值卻讀不到當日損益時整體未知，不把缺值當 0。
    var combinedDayPnl: Double? {
        if fundOnlyValueUnknown { return nil }
        if (consolidatedFundValueBase ?? 0) > 0, consolidatedFundDayPnlBase == nil { return nil }
        let stock = consolidatedDayPnlBase ?? (accounts.isEmpty && consolidatedFxMissing != true ? 0 : nil)
        return stock.map { $0 + (consolidatedFundDayPnlBase ?? 0) }
    }

    /// 舊服務沒有 display_currency 時是 nil，由畫面改顯示各幣別原幣合計，不退回 CNY 彙總。
    var overview: PortfolioOverview? {
        guard let displayCurrency, !displayCurrency.isEmpty else { return nil }
        let fund = consolidatedFundValueBase
        let total = fundOnlyValueUnknown ? nil : (consolidatedEquityBase ?? (accounts.isEmpty && consolidatedFxMissing != true ? 0 : nil)).map { $0 + (fund ?? 0) }
        let day = combinedDayPnl
        var percent: Double?
        if let unrealized = consolidatedUnrealizedPnlBase, let value = consolidatedMarketValueBase, value - unrealized > 0 {
            percent = unrealized / (value - unrealized) * 100
        }
        return PortfolioOverview(
            currency: displayCurrency, totalAssets: total, fundValue: fund, dayPnl: day,
            unrealizedPnl: consolidatedUnrealizedPnlBase, unrealizedPct: percent,
            realizedPnl: consolidatedRealizedPnlBase, cash: consolidatedCashBase,
            marketValue: consolidatedMarketValueBase,
            fxMissing: consolidatedFxMissing == true, fxStale: consolidatedFxStale == true
        )
    }

    /// 實際有帳戶的市場，台股、美股優先。
    var marketKeys: [String] {
        let priority = ["tw": 0, "us": 1]
        return Array(Set(accounts.map { $0.market.lowercased() })).sorted {
            (priority[$0] ?? 2, $0) < (priority[$1] ?? 2, $1)
        }
    }
}

public enum PortfolioHoldingSort: String, CaseIterable, Identifiable, Sendable {
    case marketValue, pnl, dayChange, symbol
    public var id: String { rawValue }
    public var title: String {
        switch self {
        case .marketValue: return "市值"
        case .pnl: return "損益"
        case .dayChange: return "今日漲跌"
        case .symbol: return "代號"
        }
    }
}

/// 畫面上的一列持股：可能是單一帳戶的部位，也可能是多帳戶合併。
/// 金額都是 `valuationCurrency`；算不出來是 nil，不是 0。
public struct PortfolioHolding: Identifiable, Equatable, Sendable {
    public let id: String
    public let symbol: String
    public let name: String?
    public let currency: String
    public let valuationCurrency: String
    public let quantity: Double
    public let avgCost: Double?
    public let lastPrice: Double?
    public let marketValue: Double?
    public let unrealizedPnl: Double?
    public let unrealizedPct: Double?
    public let dayChangePct: Double?
    public let sharePct: Double?
    public let priceAvailable: Bool
    public let priceStale: Bool
    public let priceSource: String?
    public let priceDate: String?
    public let accountCount: Int
}

public struct PortfolioHoldingGroup: Identifiable, Equatable, Sendable {
    public var id: String { currency }
    public let currency: String
    public let holdings: [PortfolioHolding]
}

public enum PortfolioHoldings {
    private struct Member {
        let position: PortfolioPosition
        let currency: String
        let usable: Bool
        var marketValue: Double? { usable && position.priceAvailable ? position.marketValueBase : nil }
        var pnl: Double? { usable && position.priceAvailable ? position.unrealizedPnlBase : nil }
    }

    private static func members(of account: PortfolioAccount) -> [Member] {
        account.positions.map {
            Member(position: $0, currency: $0.valuationCurrency ?? account.baseCurrency, usable: account.fxMissing != true)
        }
    }

    /// 單一帳戶的持股；佔比是同帳戶內同幣別市值的比重。
    public static func forAccount(_ account: PortfolioAccount, sort: PortfolioHoldingSort = .marketValue) -> [PortfolioHolding] {
        let rows = members(of: account)
        let holdings = rows.map { row in
            build(id: "\(account.accountId):\(row.position.id)", members: [row], accountCount: 1,
                  denominator: sum(rows, currency: row.currency))
        }
        return sorted(holdings, by: sort)
    }

    /// 跨帳戶合併同一檔。不同幣別的金額不能相加，所以依幣別分組，佔比也只在組內比較。
    public static func merged(_ accounts: [PortfolioAccount], sort: PortfolioHoldingSort = .marketValue) -> [PortfolioHoldingGroup] {
        var perAccount: [String: Set<Int>] = [:]
        var grouped: [String: [Member]] = [:]
        var all: [Member] = []
        for account in accounts {
            for member in members(of: account) {
                let key = "\(member.position.market):\(member.position.symbol):\(member.currency)"
                grouped[key, default: []].append(member)
                perAccount[key, default: []].insert(account.accountId)
                all.append(member)
            }
        }
        let holdings: [PortfolioHolding] = grouped.map { key, members in
            build(id: key, members: members, accountCount: perAccount[key]?.count ?? 1,
                  denominator: sum(all, currency: members[0].currency))
        }
        let priority = ["TWD": 0, "USD": 1]
        return Dictionary(grouping: holdings, by: \.valuationCurrency)
            .map { PortfolioHoldingGroup(currency: $0.key, holdings: sorted($0.value, by: sort)) }
            .sorted { (priority[$0.currency] ?? 2, $0.currency) < (priority[$1.currency] ?? 2, $1.currency) }
    }

    private static func sum(_ members: [Member], currency: String) -> Double {
        members.filter { $0.currency == currency }.reduce(0) { $0 + ($1.marketValue ?? 0) }
    }

    private static func build(id: String, members: [Member], accountCount: Int, denominator: Double) -> PortfolioHolding {
        let first = members[0].position
        let values = members.map(\.marketValue)
        let pnls = members.map(\.pnl)
        // 有一筆算不出就不給合計，免得少算的數字看起來像真的。
        let marketValue: Double? = values.contains { $0 == nil } ? nil : values.compactMap { $0 }.reduce(0, +)
        let pnl: Double? = pnls.contains { $0 == nil } ? nil : pnls.compactMap { $0 }.reduce(0, +)
        let quantity = members.reduce(0) { $0 + $1.position.quantity }
        let cost = members.reduce(0) { $0 + $1.position.totalCost }
        var percent: Double?
        if members.count == 1 {
            percent = pnl == nil ? nil : first.unrealizedPnlPct
        } else if let marketValue, let pnl, marketValue - pnl > 0 {
            percent = pnl / (marketValue - pnl) * 100
        }
        var share: Double?
        if let marketValue, denominator > 0 { share = marketValue / denominator * 100 }
        return PortfolioHolding(
            id: id, symbol: first.symbol, name: first.name, currency: first.currency,
            valuationCurrency: members[0].currency, quantity: quantity,
            avgCost: quantity > 0 ? cost / quantity : nil,
            lastPrice: first.priceAvailable ? first.lastPrice : nil,
            marketValue: marketValue, unrealizedPnl: pnl, unrealizedPct: percent,
            dayChangePct: first.dayChangePct,
            sharePct: share,
            priceAvailable: members.allSatisfy { $0.position.priceAvailable },
            priceStale: members.contains { $0.position.priceStale },
            priceSource: first.priceProvider ?? first.priceSource,
            priceDate: first.priceDate,
            accountCount: accountCount
        )
    }

    private static func sorted(_ holdings: [PortfolioHolding], by sort: PortfolioHoldingSort) -> [PortfolioHolding] {
        // 沒有讀數的列一律排最後；同值依代號，避免每次重新整理跳動。
        func descending(_ value: (PortfolioHolding) -> Double?) -> [PortfolioHolding] {
            holdings.sorted { lhs, rhs in
                switch (value(lhs), value(rhs)) {
                case let (left?, right?): return left == right ? lhs.symbol < rhs.symbol : left > right
                case (_?, nil): return true
                case (nil, _?): return false
                case (nil, nil): return lhs.symbol < rhs.symbol
                }
            }
        }
        switch sort {
        case .marketValue: return descending { $0.marketValue }
        case .pnl: return descending { $0.unrealizedPnl }
        case .dayChange: return descending { $0.dayChangePct }
        case .symbol: return holdings.sorted { $0.symbol < $1.symbol }
        }
    }
}

public struct PortfolioInsight: Identifiable, Equatable, Sendable {
    public let id: String
    public let title: String
    public let value: String
    public let detail: String
    public let isAlert: Bool
}

public enum PortfolioInsights {
    /// 權重用後端算的值（缺匯率時為 null 就不顯示）；最大虧損用百分比，不做跨幣別金額比較。
    public static func make(snapshot: PortfolioSnapshot, risk: PortfolioRiskReport?) -> [PortfolioInsight] {
        let allPositions = snapshot.accounts.flatMap(\.positions)
        let positions = snapshot.accounts.filter { $0.fxMissing != true }.flatMap(\.positions)
        var result: [PortfolioInsight] = []
        if let top = risk?.concentration?.topPositions?.first, let weight = top.weightPct {
            let name = allPositions.first { $0.symbol.uppercased() == top.symbol.uppercased() }?.name
            result.append(PortfolioInsight(id: "concentration", title: "集中度", value: DisplayNumber.number(weight, digits: 1) + "%",
                                           detail: name ?? top.symbol, isAlert: top.isAlert == true))
        }
        let losers = positions.filter { $0.priceAvailable && ($0.unrealizedPnlPct ?? 0) < 0 }
        if let worst = losers.min(by: { ($0.unrealizedPnlPct ?? 0) < ($1.unrealizedPnlPct ?? 0) }) {
            result.append(PortfolioInsight(id: "loss", title: "最大虧損", value: DisplayNumber.percent(worst.unrealizedPnlPct, digits: 1),
                                           detail: worst.name ?? worst.symbol, isAlert: false))
        } else if !positions.isEmpty {
            // 缺報價、損益未知或缺匯率的部位還沒被判定過，不能說沒有虧損。
            let allKnown = allPositions.allSatisfy { $0.priceAvailable && $0.unrealizedPnlPct != nil } && positions.count == allPositions.count
            result.append(PortfolioInsight(id: "loss", title: "最大虧損", value: DisplayNumber.noValue, detail: allKnown ? "目前沒有虧損部位" : "部分部位損益未知", isAlert: false))
        }
        if let sector = risk?.sectorConcentration?.topSectors?.first, let weight = sector.weightPct {
            result.append(PortfolioInsight(id: "sector", title: "最大產業", value: DisplayNumber.number(weight, digits: 1) + "%",
                                           detail: sector.sector, isAlert: sector.isAlert == true))
        }
        return result
    }
}
