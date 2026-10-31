import SwiftUI
import DSACore

/// 以來源市場的日期畫月曆；事件清單不做裝置時區換算。
struct EventCalendarView: View {
    @EnvironmentObject private var store: AppStore
    @State private var month = EventCalendarDate.monthStart(Date())
    @State private var selected = EventCalendarDate.key(Date())
    @State private var response: EventCalendarResponse?
    @State private var loading = false
    @State private var error: String?

    private var monthKey: String { String(EventCalendarDate.key(month).prefix(7)) }
    private var selectedEvents: [CalendarEvent] { response?.events.filter { $0.date == selected } ?? [] }

    var body: some View {
        PageScroll {
            SectionHeading("持股與自選的重要日期", subtitle: "美股以美東 ET 日期、台股以台北日期顯示；法定期限不代表實際發布日。", eyebrow: "EVENT CALENDAR")
            DSACard {
                VStack(spacing: 15) {
                    HStack {
                        Button { move(-1) } label: { Image(systemName: "chevron.left").frame(width: 44, height: 44) }
                            .accessibilityLabel("上個月").accessibilityIdentifier("calendar.previous")
                        Spacer()
                        Text(monthKey).font(.title3.monospacedDigit().weight(.semibold))
                            .accessibilityIdentifier("calendar.month")
                        Spacer()
                        Button { move(1) } label: { Image(systemName: "chevron.right").frame(width: 44, height: 44) }
                            .accessibilityLabel("下個月").accessibilityIdentifier("calendar.next")
                    }
                    HStack(spacing: 0) {
                        ForEach(["日", "一", "二", "三", "四", "五", "六"], id: \.self) { day in
                            Text(day).font(.caption).foregroundStyle(Theme.secondary).frame(maxWidth: .infinity)
                        }
                    }
                    LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 0), count: 7), spacing: 8) {
                        ForEach(Array(EventCalendarDate.cells(month).enumerated()), id: \.offset) { _, day in
                            if let day { dayCell(day) } else { Color.clear.frame(height: 44) }
                        }
                    }
                    HStack {
                        Label("財報／期限", systemImage: "circle.fill").foregroundStyle(Theme.accent)
                        Label("總經", systemImage: "circle.fill").foregroundStyle(Theme.warning)
                        Spacer()
                    }.font(.caption2)
                }
            }
            if loading { ProgressView("讀取快取…") }
            if let error { ErrorStateView(message: error, retry: { Task { await load() } }) }
            SectionHeading(selected, subtitle: "當日事件 · 來源市場日期")
            if !loading && error == nil && selectedEvents.isEmpty {
                Text("當日沒有已快取事件").font(.subheadline).foregroundStyle(Theme.secondary)
                    .accessibilityIdentifier("calendar.empty")
            }
            ForEach(selectedEvents) { event in eventRow(event) }
            if let response, !response.undated.isEmpty {
                DSACard {
                    VStack(alignment: .leading, spacing: 10) {
                        SectionHeading("下次財報未定")
                        ForEach(response.undated) { stock in
                            VStack(alignment: .leading, spacing: 4) {
                                Text("\(stock.code) · \(stock.name)").font(.subheadline.weight(.semibold))
                                Text(stock.detail).font(.caption).foregroundStyle(Theme.secondary)
                            }
                        }
                    }
                }
            }
            if let updated = response?.cacheUpdatedAt {
                Text("快取更新：\(DisplayFormat.time(updated))").font(.caption2).foregroundStyle(Theme.secondary)
            }
        }
        .navigationTitle("事件行事曆").navigationBarTitleDisplayMode(.inline)
        .task(id: monthKey) { await load() }
        .refreshable { await load() }
    }

    private func dayCell(_ day: String) -> some View {
        let events = response?.events.filter { $0.date == day } ?? []
        let company = events.contains { $0.type == "earnings" || $0.isStatutoryDeadline }
        let macro = events.contains { $0.type != "earnings" && !$0.isStatutoryDeadline }
        return Button { selected = day } label: {
            VStack(spacing: 3) {
                Text(String(Int(day.suffix(2))!))
                    .font(.body.monospacedDigit())
                    .foregroundStyle(day == selected ? Theme.background : Theme.text)
                    .frame(width: 34, height: 34)
                    .background(day == selected ? Theme.accent : Color.clear, in: Circle())
                HStack(spacing: 3) {
                    if company { Circle().fill(Theme.accent).frame(width: 5, height: 5) }
                    if macro { Circle().fill(Theme.warning).frame(width: 5, height: 5) }
                }.frame(height: 5)
            }.frame(maxWidth: .infinity, minHeight: 44)
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(day)\(events.isEmpty ? "" : "，有事件")")
        .accessibilityIdentifier("calendar.day.\(day)")
        .accessibilityAddTraits(day == selected ? .isSelected : [])
    }

    private func eventRow(_ event: CalendarEvent) -> some View {
        DSACard {
            VStack(alignment: .leading, spacing: 10) {
                HStack(alignment: .top) {
                    Text(event.code.map { "\($0) · \(event.name)" } ?? event.name)
                        .font(.headline).foregroundStyle(Theme.text)
                    Spacer()
                    StatusBadge(event.statusLabel, tone: event.isStatutoryDeadline || event.status == "estimated" ? .warning : .neutral)
                }
                Text("\(event.date) · \(event.timezoneLabel)").font(.caption.monospacedDigit()).foregroundStyle(Theme.secondary)
                Text(event.detail).font(.subheadline).foregroundStyle(Theme.secondary)
                if let url = URL(string: event.sourceUrl), ["http", "https"].contains(url.scheme) {
                    Link("查看來源", destination: url).font(.caption)
                }
            }
        }.accessibilityIdentifier("calendar.event.\(event.id)")
    }

    private func move(_ value: Int) {
        month = EventCalendarDate.calendar.date(byAdding: .month, value: value, to: month)!
        selected = EventCalendarDate.key(month)
        response = nil
    }

    private func load() async {
        guard let client = store.client else { return }
        loading = true
        defer { loading = false }
        do {
            response = try await client.calendarEvents(from: EventCalendarDate.key(month), to: EventCalendarDate.key(EventCalendarDate.monthEnd(month)))
            error = nil
        } catch is CancellationError { }
        catch let error as URLError where error.code == .cancelled { }
        catch { self.error = error.localizedDescription }
    }
}
