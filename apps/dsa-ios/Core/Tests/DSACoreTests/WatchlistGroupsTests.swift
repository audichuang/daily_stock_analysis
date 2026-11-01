import Foundation
import XCTest
@testable import DSACore

final class WatchlistGroupsTests: XCTestCase {
    private let groups = [
        WatchlistGroup(name: "科技", codes: ["2317.TW", "2330.TW"]),
        WatchlistGroup(name: "空組"),
    ]
    private let watchlist = ["2330.TW", "2317.TW", "AAPL"]

    func testDecodesSnakeCaseResponseAndEmptyGroups() throws {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let json = #"{"groups":[{"name":"科技","codes":["2330.TW"]},{"name":"空組","codes":[]}],"ungrouped":["AAPL"]}"#
        let response = try decoder.decode(WatchlistGroupsResponse.self, from: Data(json.utf8))
        XCTAssertEqual(response.groups, [WatchlistGroup(name: "科技", codes: ["2330.TW"]), WatchlistGroup(name: "空組")])
        XCTAssertEqual(response.ungrouped, ["AAPL"])
    }

    func testEncodedGroupCarriesOnlyNameAndCodes() throws {
        let data = try JSONEncoder().encode(WatchlistGroup(name: "科技", codes: ["2330.TW"]))
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual(Set(object.keys), ["name", "codes"])
    }

    func testAllKeepsWatchlistOrderAndIgnoresGroups() {
        XCTAssertEqual(WatchlistGroupFilter.all.codes(from: watchlist, groups: groups), watchlist)
    }

    func testGroupUsesGroupOrderAndDropsCodesNoLongerInWatchlist() {
        let filter = WatchlistGroupFilter.group("科技")
        XCTAssertEqual(filter.codes(from: watchlist, groups: groups), ["2317.TW", "2330.TW"])
        XCTAssertEqual(filter.codes(from: ["2330.TW"], groups: groups), ["2330.TW"])
    }

    func testUngroupedIsWatchlistMinusEveryGroup() {
        XCTAssertEqual(WatchlistGroupFilter.ungrouped.codes(from: watchlist, groups: groups), ["AAPL"])
    }

    func testMissingGroupFallsBackToAll() {
        XCTAssertEqual(WatchlistGroupFilter.group("已刪").resolved(in: groups), .all)
        XCTAssertEqual(WatchlistGroupFilter.group("已刪").codes(from: watchlist, groups: groups), watchlist)
        XCTAssertEqual(WatchlistGroupFilter.group("科技").resolved(in: groups), .group("科技"))
    }

    func testNoGroupsMeansOnlyAll() {
        XCTAssertEqual(WatchlistGroupFilter.ungrouped.resolved(in: []), .all)
    }

    func testMovingKeepsSingleMembershipAndNilReturnsToUngrouped() {
        let moved = WatchlistGroupEditing.moving(code: "2330.TW", to: "空組", in: groups)
        XCTAssertEqual(moved[0].codes, ["2317.TW"])
        XCTAssertEqual(moved[1].codes, ["2330.TW"])
        let back = WatchlistGroupEditing.moving(code: "2330.TW", to: nil, in: moved)
        XCTAssertEqual(back.flatMap(\.codes), ["2317.TW"])
    }

    func testAddingNameRejectsWhatTheServerWouldReject() {
        XCTAssertEqual(WatchlistGroupEditing.problem(addingName: "  ", to: groups), .empty)
        XCTAssertEqual(WatchlistGroupEditing.problem(addingName: " 科技 ", to: groups), .duplicate)
        XCTAssertEqual(WatchlistGroupEditing.problem(addingName: String(repeating: "x", count: 33), to: groups), .tooLong)
        let full = (0..<WatchlistGroupEditing.maxGroups).map { WatchlistGroup(name: "組\($0)") }
        XCTAssertEqual(WatchlistGroupEditing.problem(addingName: "新組", to: full), .tooManyGroups)
        XCTAssertNil(WatchlistGroupEditing.problem(addingName: String(repeating: "x", count: 32), to: groups))
        XCTAssertEqual(WatchlistGroupEditing.adding(name: " 新組 ", to: groups).last?.name, "新組")
        XCTAssertEqual(WatchlistGroupEditing.adding(name: "科技", to: groups), groups)
    }
}
