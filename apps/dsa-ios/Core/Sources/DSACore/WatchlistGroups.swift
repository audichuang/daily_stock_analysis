import Foundation

/// 鏡像 `api/v1/schemas/stocks.py` 的 WatchlistGroup。
public struct WatchlistGroup: Codable, Hashable, Identifiable, Sendable {
    public let name: String
    public var codes: [String]
    public var id: String { name }

    public init(name: String, codes: [String] = []) {
        self.name = name
        self.codes = codes
    }
}

public struct WatchlistGroupsResponse: Decodable, Sendable {
    public let groups: [WatchlistGroup]
    public let ungrouped: [String]
}

/// 自選頁目前看的範圍。
public enum WatchlistGroupFilter: Hashable, Sendable {
    case all
    case ungrouped
    case group(String)

    /// 選中的分組已不存在時退回全部；沒有任何分組時也只有全部。
    public func resolved(in groups: [WatchlistGroup]) -> WatchlistGroupFilter {
        if groups.isEmpty { return .all }
        if case .group(let name) = self, !groups.contains(where: { $0.name == name }) { return .all }
        return self
    }

    /// 全部與未分組照自選順序；單組照組內順序。成員一律以 `watchlist` 為準。
    public func codes(from watchlist: [String], groups: [WatchlistGroup]) -> [String] {
        switch resolved(in: groups) {
        case .all:
            return watchlist
        case .ungrouped:
            let grouped = Set(groups.flatMap(\.codes))
            return watchlist.filter { !grouped.contains($0) }
        case .group(let name):
            let members = Set(watchlist)
            return groups.first { $0.name == name }?.codes.filter(members.contains) ?? []
        }
    }
}

/// 編輯頁的草稿操作；伺服器只收整份，所以都是純函式，存檔時一次送出。
public enum WatchlistGroupEditing {
    public static let maxNameLength = 32
    public static let maxGroups = 30

    public enum NameProblem: Equatable, Sendable { case empty, tooLong, duplicate, tooManyGroups }

    public static func problem(addingName raw: String, to groups: [WatchlistGroup]) -> NameProblem? {
        let name = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if name.isEmpty { return .empty }
        if name.count > maxNameLength { return .tooLong }
        if groups.contains(where: { $0.name == name }) { return .duplicate }
        if groups.count >= maxGroups { return .tooManyGroups }
        return nil
    }

    public static func adding(name raw: String, to groups: [WatchlistGroup]) -> [WatchlistGroup] {
        guard problem(addingName: raw, to: groups) == nil else { return groups }
        return groups + [WatchlistGroup(name: raw.trimmingCharacters(in: .whitespacesAndNewlines))]
    }

    /// 一檔只屬於一組：先從所有組拿掉，`target` 為 nil 就是回到未分組。
    public static func moving(code: String, to target: String?, in groups: [WatchlistGroup]) -> [WatchlistGroup] {
        groups.map { group in
            var next = group
            next.codes.removeAll { $0 == code }
            if group.name == target { next.codes.append(code) }
            return next
        }
    }
}
