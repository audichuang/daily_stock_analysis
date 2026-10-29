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

struct DSACard<Content: View>: View {
    private let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        content
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(18)
            .background {
                RoundedRectangle(cornerRadius: 22, style: .continuous)
                    .fill(Theme.surface.gradient)
            }
            .overlay {
                RoundedRectangle(cornerRadius: 22, style: .continuous)
                    .strokeBorder(Theme.border, lineWidth: 1)
            }
    }
}

struct SectionHeading: View {
    let title: String
    let subtitle: String?
    let eyebrow: String?
    let systemImage: String?

    init(_ title: String, subtitle: String? = nil, eyebrow: String? = nil, systemImage: String? = nil) {
        self.title = title
        self.subtitle = subtitle
        self.eyebrow = eyebrow
        self.systemImage = systemImage
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if let eyebrow {
                Text(eyebrow)
                    .font(.caption.weight(.semibold))
                    .tracking(1.5)
                    .foregroundStyle(Theme.accent)
            }
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
            .foregroundStyle(Theme.background)
            .padding(.horizontal, 18)
            .padding(.vertical, 12)
            .frame(minHeight: 44)
            .background(tint.opacity(isEnabled ? 1 : 0.4), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            .opacity(configuration.isPressed ? 0.84 : 1)
            .scaleEffect(configuration.isPressed && !reduceMotion ? 0.98 : 1)
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
