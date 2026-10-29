import Foundation

/// 只翻譯後端已定義的顯示代碼；自由文字與未知值保留原文。
enum PresentationText {
    static func limitation(_ value: String) -> String {
        switch value {
        case "no_reports": return "尚無這檔股票的分析報告"
        case "no_symbol_intelligence": return "尚無這檔股票的相關情報"
        case "cached_positions_only": return "持股關聯僅依快取資料判斷"
        case "realtime_quote_best_effort": return "報價依可用來源更新，部分可能延遲"
        case "fx_and_cost_basis_partial": return "損益估算受匯率與成本計算方式影響"
        case "sector_and_risk_metrics_limited": return "產業分類與風險指標尚未完整提供"
        default: break
        }

        let parts = value.components(separatedBy: ";")
        let translated = parts.map { part -> String in
            let token = part.trimmingCharacters(in: .whitespacesAndNewlines)
            let pair = token.components(separatedBy: ":")
            guard pair.count == 2,
                  let block = blockLabels[pair[0].trimmingCharacters(in: .whitespaces)],
                  let status = limitationStatuses[pair[1].trimmingCharacters(in: .whitespaces)] else {
                return part
            }
            return block + status
        }
        return translated == parts ? value : translated.joined(separator: "；")
    }

    static func quality(_ value: String) -> String {
        switch value {
        case "good": return "良好"
        case "usable": return "可用"
        case "limited": return "有限"
        case "poor": return "不足"
        case "high": return "高"
        case "medium": return "中"
        case "low": return "低"
        case "complete": return "完整"
        case "partial": return "部分資料"
        case "insufficient": return "資料不足"
        case "unknown": return "未確認"
        default: return value
        }
    }

    static func source(_ value: String?) -> String {
        guard let value else { return "未提供" }
        switch value {
        case "storage.get_analysis_context": return "歷史行情資料庫"
        case "realtime_quote": return "行情報價"
        case "fallback": return "備援報價 · 可能延遲"
        case "shioaji": return "Shioaji"
        case "yfinance": return "Yahoo Finance · 可能延遲"
        case "official_close": return "官方收盤"
        case "marketdb": return "歷史行情資料庫"
        default: return value
        }
    }

    static func evidenceTitle(_ value: String) -> String {
        switch value {
        case "日线": return "日線行情"
        case "技术": return "技術面"
        case "筹码": return "籌碼面"
        case "新闻": return "新聞"
        case "News summary": return "新聞摘要"
        case "Financial report": return "財務報表"
        case "Dividend metrics": return "股利指標"
        case "Market structure": return "市場結構"
        default: return blockLabels[value] ?? value
        }
    }

    // 名稱與狀態對應 analysis_context_builder.py 的資料區塊契約。
    private static let blockLabels = [
        "quote": "報價資料", "daily_bars": "日線行情", "technical": "技術面資料",
        "news": "新聞資料", "fundamentals": "基本面資料", "chip": "籌碼資料"
    ]

    private static let limitationStatuses = [
        "stale": "已過期", "partial": "不完整", "missing": "缺漏",
        "fetch_failed": "取得失敗", "not_supported": "目前不支援",
        "fallback": "使用備援來源", "estimated": "包含估計值"
    ]
}
