import SwiftUI

/// 三條觀測訊號匯成一個判讀節點；幾何與 generate-icon.swift 保持一致。
struct BrandMark: View {
    var size: CGFloat = 52
    var showsBackground = true

    var body: some View {
        Canvas { context, canvasSize in
            let scale = canvasSize.width / 1024
            context.scaleBy(x: scale, y: scale)
            if showsBackground {
                context.fill(
                    Path(CGRect(x: 0, y: 0, width: 1024, height: 1024)),
                    with: .linearGradient(
                        Gradient(colors: [Color(red: 0.065, green: 0.118, blue: 0.180), Color(red: 0.020, green: 0.043, blue: 0.082)]),
                        startPoint: .zero,
                        endPoint: CGPoint(x: 1024, y: 1024)
                    )
                )
            }

            context.fill(
                Path(ellipseIn: CGRect(x: 654, y: 152, width: 300, height: 300)),
                with: .radialGradient(
                    Gradient(colors: [Theme.accent.opacity(0.12), Theme.accent.opacity(0)]),
                    center: CGPoint(x: 804, y: 302), startRadius: 0, endRadius: 150
                )
            )
            let stroke = StrokeStyle(lineWidth: 26, lineCap: .round, lineJoin: .round)
            var upper = Path()
            upper.move(to: CGPoint(x: 190, y: 350))
            upper.addCurve(to: CGPoint(x: 414, y: 430), control1: CGPoint(x: 310, y: 350), control2: CGPoint(x: 330, y: 430))
            upper.addCurve(to: CGPoint(x: 592, y: 500), control1: CGPoint(x: 490, y: 430), control2: CGPoint(x: 510, y: 500))
            context.stroke(upper, with: .color(Theme.accent.opacity(0.42)), style: stroke)

            var lower = Path()
            lower.move(to: CGPoint(x: 190, y: 716))
            lower.addCurve(to: CGPoint(x: 414, y: 594), control1: CGPoint(x: 338, y: 716), control2: CGPoint(x: 318, y: 594))
            lower.addCurve(to: CGPoint(x: 592, y: 500), control1: CGPoint(x: 490, y: 594), control2: CGPoint(x: 510, y: 500))
            context.stroke(lower, with: .color(Theme.accent.opacity(0.68)), style: stroke)

            var main = Path()
            main.move(to: CGPoint(x: 190, y: 550))
            main.addCurve(to: CGPoint(x: 414, y: 500), control1: CGPoint(x: 270, y: 550), control2: CGPoint(x: 280, y: 500))
            main.addLine(to: CGPoint(x: 592, y: 500))
            main.addCurve(to: CGPoint(x: 804, y: 302), control1: CGPoint(x: 668, y: 500), control2: CGPoint(x: 688, y: 302))
            context.stroke(main, with: .color(Theme.accent), style: StrokeStyle(lineWidth: 34, lineCap: .round, lineJoin: .round))

            for (point, opacity) in [(CGPoint(x: 190, y: 350), 0.5), (CGPoint(x: 190, y: 550), 1.0), (CGPoint(x: 190, y: 716), 0.75)] {
                context.fill(Path(ellipseIn: CGRect(x: point.x - 21, y: point.y - 21, width: 42, height: 42)), with: .color(Theme.accent.opacity(opacity)))
            }

            context.fill(Path(ellipseIn: CGRect(x: 554, y: 462, width: 76, height: 76)), with: .color(Color(red: 0.040, green: 0.078, blue: 0.127)))
            context.stroke(Path(ellipseIn: CGRect(x: 554, y: 462, width: 76, height: 76)), with: .color(Theme.accent), lineWidth: 16)
            context.fill(Path(ellipseIn: CGRect(x: 580, y: 488, width: 24, height: 24)), with: .color(Theme.accent))

            context.fill(Path(ellipseIn: CGRect(x: 758, y: 256, width: 92, height: 92)), with: .color(Color(red: 0.040, green: 0.078, blue: 0.127)))
            context.stroke(Path(ellipseIn: CGRect(x: 758, y: 256, width: 92, height: 92)), with: .color(Theme.accent), lineWidth: 17)
            context.fill(Path(ellipseIn: CGRect(x: 786, y: 284, width: 36, height: 36)), with: .color(Color(red: 0.85, green: 1.0, blue: 0.96)))
        }
        .frame(width: size, height: size)
        .clipShape(RoundedRectangle(cornerRadius: showsBackground ? size * 0.24 : 0, style: .continuous))
        .accessibilityHidden(true)
    }
}
