import DSACore
import SwiftUI

/// 今日頁的近期事件總覽；完整月曆從這裡進，不放在工具頁。
struct UpcomingEventsCard: View {
    private static let windowDays = 45
    private static let visibleCount = 4

    @EnvironmentObject private var store: AppStore
    @State private var events: [CalendarEvent] = []
    @State private var failed = false

    private var visible: [CalendarEvent] {
        events.filter { store.isInMarket($0.code ?? "") }.upcomingCompanyEvents(limit: Self.visibleCount)
    }

    var body: some View {
        DSACard {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Text("近期事件").font(.headline).foregroundStyle(Theme.text)
                    Spacer()
                    NavigationLink("全部") { EventCalendarView() }
                        .font(.subheadline)
                        .accessibilityIdentifier("today.calendar")
                }
                if visible.isEmpty {
                    Text(failed ? "暫時無法讀取行事曆" : "近期沒有已排定的財報或法說會")
                        .font(.caption).foregroundStyle(Theme.secondary)
                }
                ForEach(visible) { event in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(event.name).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.text)
                        Text("\(event.type == "investor_conference" ? "法說會" : "財報") · \(event.date) · \(event.timezoneLabel) · \(event.statusLabel)")
                            .font(.caption.monospacedDigit()).foregroundStyle(Theme.secondary)
                    }
                    .accessibilityElement(children: .combine)
                }
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("today.events")
        .task(id: store.baseURL) { await load() }
    }

    private func load() async {
        guard let client = store.client, let today = EventCalendarDate.parse(EventCalendarDate.deviceToday()),
              let until = EventCalendarDate.calendar.date(byAdding: .day, value: Self.windowDays, to: today)
        else { return }
        do {
            events = try await client.calendarEvents(from: EventCalendarDate.key(today), to: EventCalendarDate.key(until))
                .events
            failed = false
        } catch is CancellationError {
        } catch let error as URLError where error.code == .cancelled {
        } catch {
            failed = true
        }
    }
}
