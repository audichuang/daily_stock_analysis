import DSACore
import SwiftUI

struct ReportNewsView: View {
    let reportID: Int
    @EnvironmentObject private var store: AppStore
    @State private var items: [ReportNewsItem] = []
    @State private var loading = true
    @State private var error: String?
    @State private var referencesExpanded = false
    @State private var disclaimerShown = false

    var body: some View {
        DSACard {
            VStack(alignment: .leading, spacing: 14) {
                HStack(alignment: .top, spacing: 8) {
                    SectionHeading("相關新聞", subtitle: "分析當下蒐集的新聞與公告", systemImage: "newspaper")
                    Spacer(minLength: 0)
                    disclaimerButton
                }
                if loading {
                    LoadingStateView("正在讀取本次分析的新聞…")
                } else if let error {
                    ErrorStateView(message: "無法讀取本次分析的新聞：\(error)") { Task { await load() } }
                } else {
                    let news = items.filter(\.isNews)
                    let references = items.filter { !$0.isNews }
                    if news.isEmpty {
                        Text("這次分析沒有可顯示的新聞或官方公告。")
                            .font(.subheadline).foregroundStyle(Theme.secondary)
                            .accessibilityIdentifier("report.news.empty")
                    }
                    newsRows(news)
                    if !references.isEmpty {
                        DisclosureGroup(isExpanded: $referencesExpanded) {
                            newsRows(references).padding(.top, 12)
                        } label: {
                            Text("其他參考資料（\(references.count)）")
                                .font(.subheadline.weight(.semibold)).frame(minHeight: 44)
                        }
                        .accessibilityIdentifier("report.news.references")
                        .tint(Theme.accent)
                    }
                }
            }
        }
        .task(id: reportID) {
            items = []
            referencesExpanded = false
            await load()
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("report.news")
    }

    private var disclaimerButton: some View {
        Button {
            disclaimerShown = true
        } label: {
            Image(systemName: "info.circle")
                .font(.subheadline)
                .foregroundStyle(Theme.secondary)
                .frame(minWidth: 44, minHeight: 44)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel("新聞資料說明")
        .accessibilityIdentifier("report.news.info")
        .popover(isPresented: $disclaimerShown) {
            Text("依分析編號保存的搜尋資料，可能包含分析完成後補查、模型未讀過的內容；舊報告可能未完整保留。日期為來源提供，未逐篇核實。")
                .font(.footnote).foregroundStyle(Theme.text)
                .fixedSize(horizontal: false, vertical: true)
                .frame(idealWidth: 300)
                .padding(16)
                .presentationCompactAdaptation(.popover)
        }
    }

    private func newsRows(_ rows: [ReportNewsItem]) -> some View {
        ForEach(Array(rows.enumerated()), id: \.offset) { index, item in
            VStack(alignment: .leading, spacing: 6) {
                if let url = item.externalURL {
                    Link(destination: url) {
                        HStack(alignment: .top, spacing: 8) {
                            Text(item.displayTitle).foregroundStyle(Theme.text).multilineTextAlignment(.leading)
                            Image(systemName: "arrow.up.right").font(.caption).foregroundStyle(Theme.secondary)
                        }.frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
                    }
                    .accessibilityIdentifier("report.news.link.\(index)")
                    .tint(Theme.accent)
                } else {
                    Text(item.displayTitle).foregroundStyle(Theme.text)
                }
                Text([item.sourceLabel, item.dateLabel].compactMap { $0 }.joined(separator: " · "))
                    .font(.caption).foregroundStyle(Theme.secondary)
                if !item.summary.isEmpty {
                    Text(item.summary).font(.subheadline).foregroundStyle(Theme.secondary).lineLimit(1)
                }
                if index < rows.count - 1 { Divider().overlay(Theme.border).padding(.top, 6) }
            }.font(.subheadline.weight(.semibold))
        }
    }

    @MainActor private func load() async {
        guard let client = store.client else { loading = false; error = "請先連接服務。"; return }
        loading = true
        error = nil
        defer { loading = false }
        do {
            let response = try await client.reportNews(reportID)
            guard !Task.isCancelled else { return }
            items = ReportNewsItem.newestFirst(response.items)
        } catch {
            guard !Task.isCancelled else { return }
            self.error = error.localizedDescription
        }
    }
}
