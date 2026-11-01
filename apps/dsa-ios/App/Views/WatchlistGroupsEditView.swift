import SwiftUI
import DSACore

/// 自選分組編輯頁：在草稿上增刪移，按儲存才整份送出；取消不留痕跡。
struct WatchlistGroupsEditView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.dismiss) private var dismiss
    @State private var draft: [WatchlistGroup] = []
    @State private var newName = ""
    @State private var saving = false
    @State private var error: String?

    var body: some View {
        List {
            if let error { Section { ErrorStateView(message: error) } }
            Section("新增分組") {
                HStack {
                    TextField("組名", text: $newName)
                        .accessibilityIdentifier("watchlist-group-name")
                    Button("新增") { addGroup() }
                        .disabled(WatchlistGroupEditing.problem(addingName: newName, to: draft) != nil)
                        .accessibilityIdentifier("watchlist-group-add")
                }
                if let hint = nameHint { Text(hint).font(.caption).foregroundStyle(Theme.secondary) }
            }
            if !draft.isEmpty {
                Section("分組順序") {
                    ForEach(draft) { group in
                        Text(group.name).accessibilityIdentifier("watchlist-group-order.\(group.name)")
                    }
                    .onMove { draft.move(fromOffsets: $0, toOffset: $1) }
                    .onDelete { draft.remove(atOffsets: $0) }
                }
            }
            ForEach(draft) { group in
                Section(group.name) {
                    if group.codes.isEmpty {
                        Text("這個分組還沒有個股").font(.caption).foregroundStyle(Theme.secondary)
                    }
                    ForEach(group.codes, id: \.self) { code in row(code: code, current: group.name) }
                        .onMove { moveCodes(in: group.name, from: $0, to: $1) }
                }
            }
            Section("未分組") {
                ForEach(ungrouped, id: \.self) { code in row(code: code, current: nil) }
            }
        }
        // 常駐編輯模式，排序與刪除的把手不用再多按一次。
        .environment(\.editMode, .constant(.active))
        .navigationTitle("編輯分組").navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button("取消") { dismiss() }.accessibilityIdentifier("watchlist-groups-cancel")
            }
            ToolbarItem(placement: .confirmationAction) {
                Button("儲存") { Task { await save() } }
                    .disabled(saving)
                    .accessibilityIdentifier("watchlist-groups-save")
            }
        }
        .onAppear { if draft.isEmpty { draft = store.watchlistGroups } }
    }

    private func row(code: String, current: String?) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(store.quote(for: code)?.stockName ?? code).foregroundStyle(Theme.text)
                Text(code).font(.caption.monospaced()).foregroundStyle(Theme.secondary)
            }
            Spacer()
            Menu {
                ForEach(draft.filter { $0.name != current }) { group in
                    Button("移到 \(group.name)") { draft = WatchlistGroupEditing.moving(code: code, to: group.name, in: draft) }
                }
                if current != nil {
                    Button("移到 未分組") { draft = WatchlistGroupEditing.moving(code: code, to: nil, in: draft) }
                }
            } label: {
                Image(systemName: "folder").foregroundStyle(Theme.accent)
            }
            .accessibilityLabel("移動 \(code)")
            .accessibilityIdentifier("watchlist-group-move.\(code)")
        }
    }

    private var ungrouped: [String] {
        store.watchlist.filter { code in !draft.contains { $0.codes.contains(code) } }
    }

    private var nameHint: String? {
        switch WatchlistGroupEditing.problem(addingName: newName, to: draft) {
        case .tooLong: return "組名最多 \(WatchlistGroupEditing.maxNameLength) 個字。"
        case .duplicate: return "已經有這個分組。"
        case .tooManyGroups: return "最多 \(WatchlistGroupEditing.maxGroups) 個分組。"
        case .empty, nil: return nil
        }
    }

    private func addGroup() {
        draft = WatchlistGroupEditing.adding(name: newName, to: draft)
        newName = ""
    }

    private func moveCodes(in name: String, from source: IndexSet, to destination: Int) {
        guard let index = draft.firstIndex(where: { $0.name == name }) else { return }
        draft[index].codes.move(fromOffsets: source, toOffset: destination)
    }

    private func save() async {
        saving = true
        defer { saving = false }
        do {
            try await store.saveWatchlistGroups(draft)
            error = nil
            dismiss()
        } catch {
            self.error = error.localizedDescription
        }
    }
}
