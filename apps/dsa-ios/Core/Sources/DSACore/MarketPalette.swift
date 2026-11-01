import Foundation

/// sRGB components in 0...1, shared by the app's market colours and their tests.
public struct PaletteRGB: Equatable, Sendable {
    public let red: Double
    public let green: Double
    public let blue: Double

    public init(red: Double, green: Double, blue: Double) {
        self.red = red
        self.green = green
        self.blue = blue
    }
}

/// Market direction colours (same values as Web W01). Which one means "up" is still
/// decided by the red-up / green-up convention in the app layer.
public enum MarketPalette {
    /// #FF7075
    public static let up = PaletteRGB(red: 1.0, green: 0.44, blue: 0.46)
    /// #2EB877
    public static let down = PaletteRGB(red: 0.18, green: 0.72, blue: 0.47)

    /// WCAG 2.x relative luminance of an sRGB colour.
    public static func relativeLuminance(_ color: PaletteRGB) -> Double {
        func linear(_ channel: Double) -> Double {
            channel <= 0.04045 ? channel / 12.92 : pow((channel + 0.055) / 1.055, 2.4)
        }
        return 0.2126 * linear(color.red) + 0.7152 * linear(color.green) + 0.0722 * linear(color.blue)
    }
}
