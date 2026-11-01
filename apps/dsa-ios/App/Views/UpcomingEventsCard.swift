import DSACore
import SwiftUI

/// 今日頁的近期事件總覽；完整月曆從這裡進，不放在工具頁。
struct UpcomingEventsCard: View {
    private static let windowDays = 45
    private static let visibleCount = 4

    private enum LoadState { case loading, loaded, failed }

    @EnvironmentObject private var store: AppStore
    @State private var events: [CalendarEvent] = []
    @State private var state = LoadState.loading
    @State private var retryCount = 0

    private var visible: [CalendarEvent] {
        events.filter { store.isInMarket($0.code ?? "") }.upcomingCompanyEvents(limit: Self.visibleCount)
    }

    /// 首頁更新完成會改 refreshedAt，事件跟著重抓；下拉與回到前景都走這條。
    private var loadKey: String {
        "\(store.baseURL?.absoluteString ?? "")|\(store.refreshedAt?.timeIntervalSince1970 ?? 0)|\(retryCount)"
    }

    var body: some View {
        DSACard {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    SectionHeading("近期事件", level: .card)
                    Spacer()
                    NavigationLink("全部") { EventCalendarView() }
                        .font(.subheadline)
                        .accessibilityIdentifier("today.calendar")
                }
                ForEach(visible) { event in eventRow(event) }
                switch state {
                case .failed:
                    HStack {
                        Text(visible.isEmpty ? "暫時無法讀取行事曆" : "暫時無法更新，顯示上次結果")
                            .font(.caption).foregroundStyle(Theme.secondary)
                        Spacer()
                        Button("重試") { state = .loading; retryCount += 1 }
                            .font(.caption)
                            .frame(minHeight: 44)
                            .accessibilityIdentifier("today.events.retry")
                    }
                case .loading where visible.isEmpty:
                    Text("讀取中…").font(.caption).foregroundStyle(Theme.secondary)
                case .loaded where visible.isEmpty:
                    Text("近期沒有已排定的財報或法說會").font(.caption).foregroundStyle(Theme.secondary)
                default:
                    EmptyView()
                }
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("today.events")
        .task(id: loadKey) { await load() }
    }

    /// 左側 44pt 日期塊，右側名稱與「法說會 · 3 天後」；只有推估才掛琥珀字標。
    private func eventRow(_ event: CalendarEvent) -> some View {
        let block = event.dayBlock
        let detail = [event.type == "investor_conference" ? "法說會" : "財報", event.relativeDayText(), event.timezoneLabel]
            .compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " · ")
        return HStack(alignment: .center, spacing: 12) {
            VStack(spacing: 1) {
                Text(block?.day ?? event.date)
                    .font(.subheadline.weight(.semibold).monospacedDigit()).foregroundStyle(Theme.text)
                    .lineLimit(1).minimumScaleFactor(0.7)
                if let weekday = block?.weekday {
                    Text(weekday).font(.caption2).foregroundStyle(Theme.secondary)
                }
            }
            .frame(width: 44)
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(event.name).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.text)
                        .lineLimit(1)
                    if let code = event.code, store.isHeld(code) {
                        Text("持股").font(.caption2.weight(.semibold)).foregroundStyle(Theme.accent)
                    }
                }
                Text(detail).font(.caption.monospacedDigit()).foregroundStyle(Theme.secondary)
            }
            Spacer(minLength: 8)
            if event.status == "estimated" && !event.isStatutoryDeadline {
                StatusBadge("推估", tone: .warning)
            }
        }
        .accessibilityElement(children: .combine)
    }

    private func load() async {
        guard let client = store.client,
              let range = EventCalendarDate.upcomingQueryRange(days: Self.windowDays) else { return }
        do {
            events = try await client.calendarEvents(from: range.from, to: range.to).events
            state = .loaded
        } catch is CancellationError {
        } catch let error as URLError where error.code == .cancelled {
        } catch {
            state = .failed
        }
    }
}
