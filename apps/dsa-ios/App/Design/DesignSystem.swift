import DSACore
import SwiftUI

enum MarketColorConvention: String, CaseIterable, Identifiable {
    case taiwan
    case international

    var id: String { rawValue }
    var title: String { self == .taiwan ? "紅漲綠跌" : "綠漲紅跌" }
}

enum Theme {
    static let background = Color(red: 0.035, green: 0.055, blue: 0.090)
    static let surface = Color(red: 0.065, green: 0.090, blue: 0.135)
    static let elevated = Color(red: 0.095, green: 0.125, blue: 0.180)
    static let accent = Color(red: 0.34, green: 0.89, blue: 0.78)
    static let text = Color(red: 0.94, green: 0.96, blue: 0.99)
    static let secondary = Color(red: 0.64, green: 0.70, blue: 0.79)
    static let border = Color.white.opacity(0.09)
    // Market direction colours live in DSACore (shared with Web W01); changeColor still swaps them per convention.
    static let up = Color(MarketPalette.up)
    static let down = Color(MarketPalette.down)
    /// Destructive / error red. Fixed: never swapped by the red-up / green-up convention.
    static let danger = Color(red: 1.0, green: 0.38, blue: 0.38)
    static let warning = Color(red: 1.0, green: 0.76, blue: 0.39)
    static let information = Color(red: 0.48, green: 0.69, blue: 1.0)

    static func changeColor(_ change: Double?, convention: MarketColorConvention = .taiwan) -> Color {
        guard let change, change.isFinite, change != 0 else { return secondary }
        let positive = change > 0
        return (positive == (convention == .taiwan)) ? up : down
    }
}

private extension Color {
    init(_ rgb: PaletteRGB) {
        self.init(red: rgb.red, green: rgb.green, blue: rgb.blue)
    }
}

enum DSARadius {
    static let control: CGFloat = 8
    static let card: CGFloat = 12
    static let pill: CGFloat = 999
}

enum DSASpacing {
    static let xs: CGFloat = 4
    static let sm: CGFloat = 8
    static let md: CGFloat = 12
    static let lg: CGFloat = 16
    static let xl: CGFloat = 24
    /// 捲動頁底部保留的距離，確保最後一列完整露出、不被分頁列蓋住。
    static let tabBarClearance: CGFloat = 56
}

enum DSAType {
    static let display = Font.system(size: 28, weight: .bold)
    static let title = Font.title3.weight(.bold)
    static let section = Font.headline
    static let body = Font.subheadline
    static let caption = Font.caption
    static let micro = Font.caption2
    /// Group label shown outside cards (SectionHeading .group).
    static let groupLabel = Font.footnote.weight(.semibold)
}

/// 動作語意色：買進類主色、持有觀望灰、減碼賣出與警示琥珀。紅綠只留給行情方向。
enum ActionTone {
    case brand, neutral, caution

    init(_ action: DecisionAction) {
        switch action {
        case .buy, .add: self = .brand
        case .hold, .watch: self = .neutral
        case .avoid, .reduce, .sell, .alert: self = .caution
        }
    }

    var statusTone: StatusTone {
        switch self {
        case .brand: return .ai
        case .neutral: return .neutral
        case .caution: return .warning
        }
    }

    var color: Color { statusTone.color }

    /// 認不得的動作用灰色，不猜語意。
    static func of(action: String?, label: String?) -> ActionTone {
        DecisionAction.resolve(action: action, label: label).map(ActionTone.init) ?? .neutral
    }
}

extension View {
    /// 全 App 捲動頁共用的底部內距；PageScroll 已內建，自己開 ScrollView 的頁面要加這個。
    @ViewBuilder
    func dsaPageBottomInset() -> some View {
        let inset = contentMargins(.bottom, DSASpacing.tabBarClearance, for: .scrollContent)
        if #available(iOS 26, *) {
            inset.scrollEdgeEffectStyle(.hard, for: .bottom)
        } else {
            inset
        }
    }

    /// Shared list row insets: 16pt leading / trailing, top and bottom by role.
    func dsaListRow(_ role: DSAListRowRole) -> some View {
        listRowInsets(EdgeInsets(top: role.top, leading: DSASpacing.lg, bottom: role.bottom, trailing: DSASpacing.lg))
    }

    /// Fades the trailing edge (default 24pt) so a horizontally scrolling chip row hints at more content.
    func dsaTrailingFade(width: CGFloat = 24) -> some View {
        mask {
            HStack(spacing: 0) {
                Rectangle()
                LinearGradient(colors: [.black, .clear], startPoint: .leading, endPoint: .trailing)
                    .frame(width: width)
            }
        }
    }
}

enum DSAListRowRole {
    /// Controls (pickers, segmented filters) at the top of a section.
    case control
    /// Meta lines such as "updated at" under a control.
    case meta
    /// Column header above a data list.
    case columnHeader
    /// Plain content rows that manage their own padding.
    case content
    /// Standalone blocks (cards, banners) inside a list.
    case block

    var top: CGFloat {
        switch self {
        case .control: return 12
        case .meta: return 8
        case .columnHeader: return 10
        case .content: return 0
        case .block: return 6
        }
    }

    var bottom: CGFloat {
        switch self {
        case .control, .meta, .content: return 0
        case .columnHeader: return 4
        case .block: return 6
        }
    }
}

/// 頁面內容的最底端標記，UI 測試用它確認最後一列沒有被分頁列蓋住。
struct PageBottomAnchor: View {
    var body: some View {
        Color.clear
            .frame(height: 1)
            .accessibilityElement()
            .accessibilityIdentifier("page-bottom-anchor")
    }
}

enum DSACardStyle {
    /// Surface fill with a hairline border (default).
    case bordered
    /// Surface fill, no border.
    case flat
    /// Light tint fill and border in the given colour.
    case tinted(Color)
}

struct DSACard<Content: View>: View {
    private let style: DSACardStyle
    private let content: Content

    init(style: DSACardStyle = .bordered, @ViewBuilder content: () -> Content) {
        self.style = style
        self.content = content()
    }

    private var fill: Color {
        switch style {
        case .bordered, .flat: return Theme.surface
        case .tinted(let tint): return tint.opacity(0.08)
        }
    }

    private var stroke: Color? {
        switch style {
        case .bordered: return Theme.border.opacity(0.6)
        case .flat: return nil
        case .tinted(let tint): return tint.opacity(0.22)
        }
    }

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: DSARadius.card, style: .continuous)
        content
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(DSASpacing.md)
            .background { shape.fill(fill) }
            .overlay {
                if let stroke {
                    shape.strokeBorder(stroke, lineWidth: 0.5)
                }
            }
    }
}

struct SectionHeading: View {
    enum Level {
        /// Group label outside cards: footnote semibold, secondary colour.
        case group
        /// Title inside a card: headline, primary text colour.
        case card
    }

    let title: String
    let subtitle: String?
    let systemImage: String?
    let level: Level

    // 眉標已全 App 移除。參數暫留給 feat/tools-today-overview 上的 ToolsView，該分支合併後刪掉。
    init(_ title: String, subtitle: String? = nil, eyebrow: String? = nil, systemImage: String? = nil, level: Level = .card) {
        self.title = title
        self.subtitle = subtitle
        self.systemImage = systemImage
        self.level = level
    }

    private var titleFont: Font { level == .group ? DSAType.groupLabel : DSAType.section }
    private var titleColor: Color { level == .group ? Theme.secondary : Theme.text }

    var body: some View {
        VStack(alignment: .leading, spacing: level == .group ? 2 : 6) {
            HStack(alignment: .firstTextBaseline, spacing: level == .group ? 6 : 8) {
                if let systemImage {
                    Image(systemName: systemImage)
                        .foregroundStyle(level == .group ? Theme.secondary : Theme.accent)
                        .accessibilityHidden(true)
                }
                Text(title)
                    .foregroundStyle(titleColor)
            }
            .font(titleFont)
            if let subtitle {
                Text(subtitle)
                    .font(level == .group ? DSAType.caption : DSAType.body)
                    .foregroundStyle(Theme.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isHeader)
    }
}

struct MetricView: View {
    let label: String
    let value: String
    let detail: String?
    let tint: Color?

    init(_ label: String, value: String, detail: String? = nil, tint: Color? = nil) {
        self.label = label
        self.value = value
        self.detail = detail
        self.tint = tint
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(label)
                .font(.caption)
                .foregroundStyle(Theme.secondary)
            Text(value)
                .font(.headline.monospacedDigit())
                .foregroundStyle(tint ?? Theme.text)
                .fixedSize(horizontal: false, vertical: true)
            if let detail {
                Text(detail)
                    .font(.caption2)
                    .foregroundStyle(Theme.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }
}

enum StatusTone {
    case neutral, positive, warning, negative, information, ai, danger

    var color: Color {
        switch self {
        case .danger: return Theme.danger
        case .neutral: return Theme.secondary
        case .positive: return Theme.down
        case .warning: return Theme.warning
        case .negative: return Theme.up
        case .information: return Theme.information
        case .ai: return Theme.accent
        }
    }
}

struct StatusBadge: View {
    let text: String
    let tone: StatusTone
    let systemImage: String?

    init(_ text: String, tone: StatusTone = .neutral, systemImage: String? = nil) {
        self.text = text
        self.tone = tone
        self.systemImage = systemImage
    }

    var body: some View {
        HStack(spacing: 5) {
            if let systemImage {
                Image(systemName: systemImage).accessibilityHidden(true)
            }
            Text(text)
                .fixedSize(horizontal: false, vertical: true)
        }
        .font(.caption.weight(.semibold))
        .foregroundStyle(tone.color)
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(tone.color.opacity(0.10), in: Capsule())
        .overlay(Capsule().strokeBorder(tone.color.opacity(0.20), lineWidth: 1))
        .accessibilityElement(children: .combine)
    }
}

struct EmptyStateView: View {
    let title: String
    let message: String
    let systemImage: String

    init(title: String, message: String, systemImage: String = "chart.xyaxis.line") {
        self.title = title
        self.message = message
        self.systemImage = systemImage
    }

    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: systemImage)
                .font(.system(size: 30, weight: .light))
                .foregroundStyle(Theme.accent)
                .frame(width: 72, height: 72)
                .background(Theme.accent.opacity(0.08), in: RoundedRectangle(cornerRadius: DSARadius.card, style: .continuous))
                .accessibilityHidden(true)
            Text(title).font(.headline).foregroundStyle(Theme.text)
            Text(message)
                .font(.subheadline)
                .foregroundStyle(Theme.secondary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity)
        .padding(.horizontal, 20)
        .padding(.vertical, 28)
        .accessibilityElement(children: .combine)
    }
}

struct LoadingStateView: View {
    let message: String

    init(_ message: String = "正在載入…") {
        self.message = message
    }

    var body: some View {
        HStack(spacing: 12) {
            ProgressView().tint(Theme.accent)
            Text(message).font(.subheadline).foregroundStyle(Theme.secondary)
        }
        .frame(maxWidth: .infinity)
        .padding(24)
        .accessibilityElement(children: .combine)
    }
}

struct ErrorStateView: View {
    let title: String
    let message: String
    let retry: (() -> Void)?

    init(title: String = "暫時無法取得資料", message: String, retry: (() -> Void)? = nil) {
        self.title = title
        self.message = message
        self.retry = retry
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label(title, systemImage: "exclamationmark.circle")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(Theme.warning)
            Text(message)
                .font(.subheadline)
                .foregroundStyle(Theme.secondary)
                .textSelection(.enabled)
            if let retry {
                Button(action: retry) {
                    Label("重新載入", systemImage: "arrow.clockwise")
                        .font(.subheadline.weight(.semibold))
                        .frame(minHeight: 44)
                }
                .buttonStyle(PressableButtonStyle())
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
        .background(Theme.warning.opacity(0.06), in: RoundedRectangle(cornerRadius: DSARadius.card, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: DSARadius.card, style: .continuous).strokeBorder(Theme.warning.opacity(0.18), lineWidth: 1))
    }
}

/// Compact one-line status (stale data, partial failure) with an optional「重試」button.
struct InlineStatusRow: View {
    let message: String
    let tone: StatusTone
    let retry: (() -> Void)?

    init(message: String, tone: StatusTone = .warning, retry: (() -> Void)? = nil) {
        self.message = message
        self.tone = tone
        self.retry = retry
    }

    var body: some View {
        HStack(spacing: DSASpacing.sm) {
            Circle()
                .fill(tone.color)
                .frame(width: 6, height: 6)
                .accessibilityHidden(true)
            Text(message)
                .foregroundStyle(Theme.secondary)
                .lineLimit(2)
                .frame(maxWidth: .infinity, alignment: .leading)
            if let retry {
                Button("重試", action: retry)
                    .font(DSAType.caption.weight(.semibold))
                    .foregroundStyle(Theme.accent)
                    .frame(minWidth: 44, minHeight: 36)
                    .contentShape(Rectangle())
            }
        }
        .font(DSAType.caption)
        .padding(.horizontal, DSASpacing.md)
        .frame(minHeight: 36)
        .background(tone.color.opacity(0.06), in: RoundedRectangle(cornerRadius: DSARadius.control, style: .continuous))
    }
}

/// Decision action pill. Neutral actions（觀望、續抱）are secondary text only, no fill.
struct ActionBadge: View {
    enum Size {
        case compact, regular, large

        var font: Font {
            switch self {
            case .compact: return DSAType.micro.weight(.semibold)
            case .regular: return DSAType.caption.weight(.semibold)
            case .large: return DSAType.body.weight(.semibold)
            }
        }

        var horizontal: CGFloat {
            switch self {
            case .compact: return 6
            case .regular: return 8
            case .large: return 12
            }
        }

        var vertical: CGFloat {
            switch self {
            case .compact: return 2
            case .regular: return 4
            case .large: return 6
            }
        }
    }

    let text: String
    let tone: ActionTone
    let size: Size

    init(action: DecisionAction, size: Size = .regular) {
        self.text = action.displayLabel
        self.tone = ActionTone(action)
        self.size = size
    }

    /// Stored enum + legacy label; unknown actions stay neutral and show the label as-is.
    init?(action: String?, label: String?, size: Size = .regular) {
        guard let text = DecisionAction.displayText(action: action, label: label) else { return nil }
        self.text = text
        self.tone = ActionTone.of(action: action, label: label)
        self.size = size
    }

    var body: some View {
        let isNeutral = tone == .neutral
        Text(text)
            .font(size.font)
            .foregroundStyle(isNeutral ? Theme.secondary : tone.color)
            .lineLimit(1)
            .padding(.horizontal, isNeutral ? 0 : size.horizontal)
            .padding(.vertical, size.vertical)
            .background(isNeutral ? Color.clear : tone.color.opacity(0.14), in: Capsule())
    }
}

/// Filter chip: 32pt visual height inside a 44pt touch target.
struct DSAChip: View {
    let title: String
    let selected: Bool
    let action: (() -> Void)?

    init(title: String, selected: Bool, action: (() -> Void)? = nil) {
        self.title = title
        self.selected = selected
        self.action = action
    }

    private var label: some View {
        Text(title)
            .font(DSAType.body.weight(selected ? .semibold : .regular))
            .foregroundStyle(selected ? Theme.accent : Theme.secondary)
            .lineLimit(1)
            .padding(.horizontal, DSASpacing.md)
            .frame(height: 32)
            .background(selected ? Theme.accent.opacity(0.14) : Theme.surface, in: Capsule())
            .overlay(Capsule().strokeBorder(selected ? Theme.accent.opacity(0.4) : Theme.border, lineWidth: 1))
            .frame(minHeight: 44)
            .contentShape(Rectangle())
    }

    var body: some View {
        Group {
            if let action {
                Button(action: action) { label }
                    .buttonStyle(.plain)
            } else {
                label
            }
        }
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}

struct PressableButtonStyle: ButtonStyle {
    var tint: Color = Theme.accent
    @Environment(\.isEnabled) private var isEnabled
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.subheadline.weight(.semibold))
            .foregroundStyle(Theme.background.opacity(isEnabled ? 1 : 0.6))
            .padding(.horizontal, 18)
            .padding(.vertical, 12)
            .frame(minHeight: 44)
            .background(tint.opacity(isEnabled ? 1 : 0.4), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            .opacity(configuration.isPressed && isEnabled ? 0.84 : 1)
            .scaleEffect(configuration.isPressed && isEnabled && !reduceMotion ? 0.98 : 1)
            .animation(reduceMotion ? nil : .easeOut(duration: 0.16), value: configuration.isPressed)
    }
}

struct SecondaryButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.subheadline.weight(.semibold))
            .foregroundStyle(Theme.accent.opacity(isEnabled ? 1 : 0.4))
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
            .frame(minHeight: 44)
            .background(Theme.accent.opacity(configuration.isPressed ? 0.18 : 0.08), in: RoundedRectangle(cornerRadius: 14))
            .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(Theme.accent.opacity(0.20), lineWidth: 1))
    }
}
