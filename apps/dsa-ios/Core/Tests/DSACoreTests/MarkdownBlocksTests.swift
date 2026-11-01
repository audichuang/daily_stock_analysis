import XCTest
@testable import DSACore

final class MarkdownBlocksTests: XCTestCase {
    func testTableBecomesHeadersAndRows() {
        let blocks = MarkdownParser.parse("| 指標 | 數值 |\n| --- | :--: |\n| 毛利率 | 50% |\n| 僅一欄 |")
        XCTAssertEqual(blocks, [.table(headers: ["指標", "數值"], rows: [["毛利率", "50%"], ["僅一欄", ""]])])
    }

    func testExtraCellsMergeIntoLastColumn() {
        let blocks = MarkdownParser.parse("| a | b |\n|---|---|\n| 1 | 2 | 3 |")
        XCTAssertEqual(blocks, [.table(headers: ["a", "b"], rows: [["1", "2 | 3"]])])
    }

    func testPipeWithoutSeparatorStaysParagraph() {
        XCTAssertEqual(MarkdownParser.parse("A | B"), [.paragraph("A | B")])
    }

    func testEscapedPipeStaysInCell() {
        XCTAssertEqual(MarkdownParser.parse("| a |\n|---|\n| x\\|y |"), [.table(headers: ["a"], rows: [["x|y"]])])
    }

    func testListKeepsNestingAndOrderedMarkers() {
        XCTAssertEqual(MarkdownParser.parse("- 一\n  - 二\n1. 三"), [.list([
            MarkdownListItem(marker: "•", level: 0, text: "一"),
            MarkdownListItem(marker: "•", level: 1, text: "二"),
            MarkdownListItem(marker: "1.", level: 0, text: "三")
        ])])
    }

    func testChecklistStatuses() {
        XCTAssertEqual(MarkdownParser.parse("- ✅ 站上月線\n- ⚠️ 量能不足\n- ❌ 跌破\n- [x] 完成\n- [ ] 待辦"), [.list([
            MarkdownListItem(marker: "•", level: 0, text: "站上月線", status: .passed),
            MarkdownListItem(marker: "•", level: 0, text: "量能不足", status: .warning),
            MarkdownListItem(marker: "•", level: 0, text: "跌破", status: .failed),
            MarkdownListItem(marker: "•", level: 0, text: "完成", status: .passed),
            MarkdownListItem(marker: "•", level: 0, text: "待辦", status: .pending)
        ])])
    }

    func testBoldStatusLabelIsNotAChecklistItem() {
        XCTAssertEqual(MarkdownParser.parse("✅ **檢查清單**"), [.paragraph("✅ **檢查清單**")])
    }

    func testQuoteDividerHeadingCode() {
        XCTAssertEqual(MarkdownParser.parse("# 標\n\n> 引一\n> 引二\n\n---\n\n```json\n- 不是清單\n```"), [
            .heading(level: 1, text: "標"), .quote("引一\n引二"), .divider, .code("- 不是清單")
        ])
    }

    func testHashWithoutSpaceIsNotHeading() {
        XCTAssertEqual(MarkdownParser.parse("#標籤"), [.paragraph("#標籤")])
    }

    func testSectionsSplitOnRepeatedLevelAndDropStockTitle() {
        let sections = MarkdownParser.sections("## 台積電 (2330.TW)\n\n### 結論\n\n內容一\n\n### 風險\n\n內容二")
        XCTAssertEqual(sections.map(\.title), ["結論", "風險"])
    }

    func testPreambleBeforeFirstHeadingIsKept() {
        let sections = MarkdownParser.sections("開場\n\n## 一\n\nA\n\n## 二\n\nB")
        XCTAssertEqual(sections.map(\.title), [nil, "一", "二"])
    }

    func testSingleHeadingStillOneSection() {
        XCTAssertEqual(MarkdownParser.sections("# 只有一個\n\n內容").map(\.title), ["只有一個"])
    }

    func testNoHeadingsYieldsUntitledSection() {
        XCTAssertEqual(MarkdownParser.sections("純文字").map(\.title), [nil])
    }

    func testAlreadyShownParagraphIsSkippedAndEmptiedSectionDropped() {
        let sections = MarkdownParser.sections("## 結論\n\n**頁面已顯示**\n\n## 其他\n\n保留", alreadyShown: ["頁面已顯示"])
        XCTAssertEqual(sections.map(\.title), ["其他"])
    }

    func testNearDuplicateParagraphIsKept() {
        let sections = MarkdownParser.sections("## 一\n\n頁面已顯示，但多一句\n\n## 二\n\nB", alreadyShown: ["頁面已顯示"])
        XCTAssertEqual(sections.map(\.title), ["一", "二"])
    }

    func testIdenticalSectionsAppearOnce() {
        let sections = MarkdownParser.sections("## 風險\n\n- 甲\n\n## 風險\n\n- 甲\n\n## 其他\n\n- 甲")
        XCTAssertEqual(sections.map(\.title), ["風險", "其他"])
    }

    func testInlineRemovesItalicKeepsBold() {
        let result = MarkdownParser.inline("*斜* **粗**")
        var intents: [InlinePresentationIntent] = []
        for run in result.runs {
            if let intent = run.inlinePresentationIntent { intents.append(intent) }
        }
        XCTAssertFalse(intents.contains { $0.contains(.emphasized) })
        XCTAssertTrue(intents.contains { $0.contains(.stronglyEmphasized) })
        XCTAssertEqual(String(result.characters), "斜 粗")
    }
}
