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
    static let up = Color(red: 1.0, green: 0.43, blue: 0.48)
    static let down = Color(red: 0.28, green: 0.83, blue: 0.61)
    static let warning = Color(red: 1.0, green: 0.76, blue: 0.39)
    static let information = Color(red: 0.48, green: 0.69, blue: 1.0)

    static func changeColor(_ change: Double?, convention: MarketColorConvention = .taiwan) -> Color {
        guard let change, change.isFinite, change != 0 else { return secondary }
        let positive = change > 0
        return (positive == (convention == .taiwan)) ? up : down
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
    func dsaPageBottomInset() -> some View {
        contentMargins(.bottom, DSASpacing.tabBarClearance, for: .scrollContent)
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

struct DSACard<Content: View>: View {
    private let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        content
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(14)
            .background {
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .fill(Theme.surface)
            }
            .overlay {
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .strokeBorder(Theme.border, lineWidth: 1)
            }
    }
}

struct SectionHeading: View {
    let title: String
    let subtitle: String?
    let systemImage: String?

    // 眉標已全 App 移除。參數暫留給 feat/tools-today-overview 上的 ToolsView，該分支合併後刪掉。
    init(_ title: String, subtitle: String? = nil, eyebrow: String? = nil, systemImage: String? = nil) {
        self.title = title
        self.subtitle = subtitle
        self.systemImage = systemImage
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                if let systemImage {
                    Image(systemName: systemImage)
                        .foregroundStyle(Theme.accent)
                        .accessibilityHidden(true)
                }
                Text(title)
                    .foregroundStyle(Theme.text)
            }
            .font(.title3.weight(.bold))
            if let subtitle {
                Text(subtitle)
                    .font(.subheadline)
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
    case neutral, positive, warning, negative, information, ai

    var color: Color {
        switch self {
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
                .background(Theme.accent.opacity(0.08), in: RoundedRectangle(cornerRadius: 24))
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
    let message: String
    let retry: (() -> Void)?

    init(message: String, retry: (() -> Void)? = nil) {
        self.message = message
        self.retry = retry
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("暫時無法取得資料", systemImage: "exclamationmark.circle")
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
        .background(Theme.warning.opacity(0.06), in: RoundedRectangle(cornerRadius: 16))
        .overlay(RoundedRectangle(cornerRadius: 16).strokeBorder(Theme.warning.opacity(0.18), lineWidth: 1))
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
