import DSACore
import SwiftUI

/// 事件展望：判斷與理由放最前面，接著是各情境怎麼做，佐證資料放最後。
struct EventOutlookCard: View {
    let outlook: EventOutlook

    var body: some View {
        DSACard {
            VStack(alignment: .leading, spacing: 14) {
                SectionHeading("事件展望", subtitle: subtitle, systemImage: "calendar.badge.exclamationmark")
                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    Text(outlook.expectationLabel)
                        .font(.title3.weight(.bold))
                        .foregroundStyle(expectationColor)
                    if let confidence = outlook.confidenceLabel {
                        Text(confidence).font(.caption).foregroundStyle(Theme.secondary)
                    }
                }
                .accessibilityElement(children: .combine)
                .accessibilityIdentifier("event-outlook.expectation")
                if let reasoning = outlook.reasoning {
                    Text(reasoning).font(.subheadline).foregroundStyle(Theme.text)
                }
                ForEach(outlook.scenarios ?? [], id: \.case) { scenario in
                    VStack(alignment: .leading, spacing: 5) {
                        Text(EventOutlook.caseLabel(scenario.case)).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.text)
                        if let reaction = scenario.expectedReaction {
                            Text(reaction).font(.subheadline).foregroundStyle(Theme.secondary)
                        }
                        if let holding = scenario.actionIfHolding {
                            Text("持有：\(holding)").font(.subheadline).foregroundStyle(Theme.text)
                        }
                        if let flat = scenario.actionIfFlat {
                            Text("空手：\(flat)").font(.subheadline).foregroundStyle(Theme.text)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(12)
                    .background(Theme.background.opacity(0.55), in: RoundedRectangle(cornerRadius: 14))
                }
                if let impact = outlook.newsImpact {
                    MetricView("新聞影響", value: impact)
                }
                Divider().overlay(Theme.border)
                Text(outlook.consensusSummary ?? "目前沒有可靠的法人預估")
                    .font(.caption).foregroundStyle(Theme.secondary)
                note("過往實績", outlook.trackRecord)
                note("預估修正", outlook.revisionTrend)
                note("事後驗證", outlook.verifyAfter)
            }
        }
        .accessibilityIdentifier("event-outlook.card")
    }

    private var subtitle: String {
        "\(outlook.event ?? "近期事件") · \(outlook.eventDate ?? "日期未定")"
    }

    private var expectationColor: Color {
        switch outlook.expectation {
        case "beat": return StatusTone.positive.color
        case "miss": return StatusTone.negative.color
        case "inline": return Theme.accent
        default: return Theme.secondary
        }
    }

    @ViewBuilder private func note(_ label: String, _ value: String?) -> some View {
        if let value {
            Text("\(label)：\(value)").font(.caption).foregroundStyle(Theme.secondary)
        }
    }
}
