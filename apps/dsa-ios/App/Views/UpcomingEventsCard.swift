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
                    Text("近期事件").font(.headline).foregroundStyle(Theme.text)
                    Spacer()
                    NavigationLink("全部") { EventCalendarView() }
                        .font(.subheadline)
                        .accessibilityIdentifier("today.calendar")
                }
                ForEach(visible) { event in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(event.name).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.text)
                        Text("\(event.type == "investor_conference" ? "法說會" : "財報") · \(event.date) · \(event.timezoneLabel) · \(event.statusLabel)")
                            .font(.caption.monospacedDigit()).foregroundStyle(Theme.secondary)
                    }
                    .accessibilityElement(children: .combine)
                }
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
