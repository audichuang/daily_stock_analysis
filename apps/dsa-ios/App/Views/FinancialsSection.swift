import DSACore
import SwiftUI

/// 個股財報：數字先出，AI 導讀到了再補上。導讀失敗或關閉時，數字與固定教學照常顯示。
struct FinancialsSection: View {
    let code: String
    @EnvironmentObject private var store: AppStore
    @State private var data: StockFinancials?
    @State private var commentary: FinancialCommentary?
    @State private var loadError: String?
    @State private var generating = false
    @State private var selected: FinancialMetric?
    @State private var loadedCode: String?

    var body: some View {
        Group {
            // 非台美市場不支援：整塊不佔版面。
            if data?.status != "unsupported" {
                DSACard {
                    VStack(alignment: .leading, spacing: 12) {
                        SectionHeading("財報", subtitle: subtitle, systemImage: "doc.text.magnifyingglass")
                        content
                    }
                }
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("stock.financials")
            }
        }
        .task(id: code) { await load() }
        .sheet(item: $selected) { metric in
            if let data {
                FinancialMetricDetail(metric: metric, financials: data, highlights: commentary?.highlights(for: metric.key) ?? [])
            }
        }
    }

    private var subtitle: String? {
        guard let latest = data?.periods.last else { return nil }
        return "最新 \(latest.label)（截至 \(latest.periodEnd)）"
    }

    @ViewBuilder private var content: some View {
        if let loadError {
            ErrorStateView(message: "無法讀取財報：\(loadError)") { Task { await load() } }
        } else if let data {
            if data.status == "ok" {
                numbers(data)
            } else {
                Text(data.statusReason ?? "目前沒有財報資料。")
                    .font(.subheadline).foregroundStyle(Theme.secondary)
                    .accessibilityIdentifier("financials.status")
            }
        } else {
            LoadingStateView("正在讀取財報…")
        }
    }

    @ViewBuilder private func numbers(_ data: StockFinancials) -> some View {
        Text(sourceLine(data)).font(.caption).foregroundStyle(Theme.secondary)
        if commentary?.status == "ready", let headline = commentary?.headline {
            VStack(alignment: .leading, spacing: 6) {
                StatusBadge("AI 導讀", tone: .neutral, systemImage: "sparkles")
                Text(headline).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.text)
                Text("點標了「AI 重點」的欄位，看發生什麼事與怎麼看。").font(.caption).foregroundStyle(Theme.secondary)
            }
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Theme.accent.opacity(0.08), in: RoundedRectangle(cornerRadius: 14))
            .accessibilityIdentifier("financials.headline")
        }
        if generating {
            Text("AI 正在閱讀這份財報，數字可以先看…").font(.caption).foregroundStyle(Theme.secondary)
        }
        if commentary?.status == "failed" {
            Text(commentary?.message ?? "AI 導讀暫時產生失敗，數字不受影響。").font(.caption).foregroundStyle(Theme.secondary)
        }
        ForEach(data.metrics) { metric in
            metricRow(metric, data: data)
        }
        monthly(data)
        if !data.notApplicable.isEmpty {
            DisclosureGroup("\(data.notApplicable.count) 個欄位不顯示") {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(data.notApplicable, id: \.key) { item in
                        Text("\(item.label)：\(item.reason)").font(.caption).foregroundStyle(Theme.secondary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }.padding(.top, 6)
            }.font(.caption).foregroundStyle(Theme.accent)
        }
        ForEach(data.limitations, id: \.self) { text in
            Label(text, systemImage: "info.circle").font(.caption)
                .foregroundStyle(data.isStale ? Theme.warning : Theme.secondary)
        }
        Text("AI 導讀幫你讀懂財報，不是買賣建議；數字由程式從原始資料算出。").font(.caption2).foregroundStyle(Theme.secondary)
    }

    private func sourceLine(_ data: StockFinancials) -> String {
        var parts = ["財報幣別 \(data.currency ?? "—")"]
        if let source = data.source { parts.append(source.label) }
        if let latest = data.periods.last, let date = latest.announceDate {
            parts.append("\(latest.announceDateKind == "filed" ? "申報日" : "法定期限") \(date)")
        }
        return parts.joined(separator: " · ")
    }

    private func metricRow(_ metric: FinancialMetric, data: StockFinancials) -> some View {
        let latest = metric.points.last
        let flagged = !(commentary?.highlights(for: metric.key).isEmpty ?? true)
        return Button {
            selected = metric
        } label: {
            HStack(spacing: 10) {
                if flagged {
                    RoundedRectangle(cornerRadius: 2).fill(Theme.accent).frame(width: 3)
                }
                VStack(alignment: .leading, spacing: 3) {
                    HStack(spacing: 6) {
                        Text(metric.label).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.text)
                        if flagged {
                            StatusBadge("AI 重點", tone: .neutral, systemImage: "sparkles")
                        }
                    }
                    Text(metric.value(latest, currency: data.currency))
                        .font(.headline.monospacedDigit()).foregroundStyle(Theme.text)
                    Text("年增 \(metric.yoy(latest)) · 季增 \(metric.qoq(latest))")
                        .font(.caption.monospacedDigit()).foregroundStyle(Theme.secondary)
                }
                Spacer(minLength: 8)
                FinancialMiniBars(values: metric.points.map(\.value))
                Image(systemName: "chevron.right").font(.caption).foregroundStyle(Theme.secondary)
            }
            .padding(10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Theme.background.opacity(0.55), in: RoundedRectangle(cornerRadius: 12))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("financials.metric.\(metric.key)")
    }

    @ViewBuilder private func monthly(_ data: StockFinancials) -> some View {
        if !data.monthlyRevenue.isEmpty {
            let highlights = commentary?.highlights(for: "monthly_revenue") ?? []
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 6) {
                    Text("月營收").font(.subheadline.weight(.semibold)).foregroundStyle(Theme.text)
                    if !highlights.isEmpty { StatusBadge("AI 重點", tone: .neutral, systemImage: "sparkles") }
                }
                ForEach(highlights, id: \.period) { FinancialHighlightNote(highlight: $0) }
                ForEach(data.monthlyRevenue.suffix(6).reversed(), id: \.month) { row in
                    HStack {
                        Text(row.month).foregroundStyle(Theme.secondary)
                        Spacer()
                        Text(FinancialFormat.amount(row.revenue, currency: data.currency)).foregroundStyle(Theme.text)
                        Text("年增 \(FinancialFormat.change(row.yoyPct))").foregroundStyle(Theme.secondary)
                    }
                    .font(.caption.monospacedDigit())
                }
            }
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("financials.monthly")
        }
    }

    private func load() async {
        guard let client = store.client else { return }
        // 換股先清掉舊值：新請求失敗或還沒回來時，不能留著上一檔的數字與導讀。
        if loadedCode != code {
            data = nil
            commentary = nil
            selected = nil
            generating = false
        }
        loadError = nil
        let requested = code
        do {
            let payload = try await client.stockFinancials(requested)
            guard requested == code else { return }
            loadedCode = requested
            data = payload
            commentary = payload.commentary
            loadError = nil
            if payload.status == "ok", payload.commentary.status == "missing" { generateCommentary(client: client) }
        } catch is CancellationError {
        } catch let error as URLError where error.code == .cancelled {
        } catch {
            loadError = error.localizedDescription
        }
    }

    /// LLM 要等數十秒，不綁 SwiftUI 的 task：離開畫面被取消時伺服器仍會寫快取，下次直接讀到。
    private func generateCommentary(client: DSAClient) {
        guard !generating else { return }
        generating = true
        let stockCode = code
        Task {
            let result: FinancialCommentary
            do {
                result = try await client.financialCommentary(stockCode)
            } catch {
                result = FinancialCommentary(status: "failed")
            }
            // 期間換了股票就丟掉，不把上一檔的導讀蓋到這一檔。
            guard stockCode == code else { return }
            commentary = result
            generating = false
        }
    }
}

/// 走勢縮圖；顏色不用紅綠，紅綠只給漲跌方向與損益。
struct FinancialMiniBars: View {
    let values: [Double?]

    var body: some View {
        let peak = values.compactMap { $0.map(abs) }.max() ?? 0
        HStack(alignment: .center, spacing: 2) {
            ForEach(Array(values.enumerated()), id: \.offset) { index, value in
                let ratio = peak > 0 ? abs(value ?? 0) / peak : 0
                let color = index == values.count - 1 ? Theme.accent : Theme.secondary.opacity(0.4)
                VStack(spacing: 0) {
                    VStack(spacing: 0) {
                        Spacer(minLength: 0)
                        if (value ?? 0) > 0 { Rectangle().fill(color).frame(height: max(1, 15 * ratio)) }
                    }.frame(height: 15)
                    VStack(spacing: 0) {
                        if (value ?? 0) < 0 { Rectangle().fill(color).frame(height: max(1, 15 * ratio)) }
                        Spacer(minLength: 0)
                    }.frame(height: 15)
                }
                .frame(width: 5)
            }
        }
        .accessibilityHidden(true)
    }
}

struct FinancialHighlightNote: View {
    let highlight: FinancialHighlight

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            note("發生什麼事", highlight.whatHappened)
            note("為什麼重要", highlight.whyItMatters)
            note("怎麼看", highlight.howToRead)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.accent.opacity(0.08), in: RoundedRectangle(cornerRadius: 14))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("financials.highlight")
    }

    private func note(_ title: String, _ body: String) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title).font(.caption.weight(.semibold)).foregroundStyle(Theme.accent)
            Text(body).font(.subheadline).foregroundStyle(Theme.text).fixedSize(horizontal: false, vertical: true)
        }
    }
}

struct FinancialMetricDetail: View {
    let metric: FinancialMetric
    let financials: StockFinancials
    let highlights: [FinancialHighlight]
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    ForEach(highlights, id: \.period) { FinancialHighlightNote(highlight: $0) }
                    VStack(alignment: .leading, spacing: 4) {
                        Text("這是什麼").font(.caption.weight(.semibold)).foregroundStyle(Theme.secondary)
                        Text(metric.definition).font(.subheadline).foregroundStyle(Theme.text)
                    }
                    VStack(spacing: 8) {
                        ForEach(Array(metric.points.reversed()), id: \.period) { point in
                            HStack {
                                Text(label(point.period)).foregroundStyle(Theme.secondary)
                                Spacer()
                                Text(metric.value(point, currency: financials.currency)).foregroundStyle(Theme.text)
                                if point.derived { Text("推算").font(.caption2).foregroundStyle(Theme.secondary) }
                                Text("年增 \(metric.yoy(point))").foregroundStyle(Theme.secondary)
                            }
                            .font(.caption.monospacedDigit())
                        }
                    }
                }
                .padding()
            }
            .background(Theme.background.ignoresSafeArea())
            .navigationTitle(metric.label)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) { Button("完成") { dismiss() } }
            }
        }
        .accessibilityIdentifier("financials.detail")
    }

    private func label(_ key: String) -> String {
        financials.periods.first { $0.key == key }?.label ?? key
    }
}
