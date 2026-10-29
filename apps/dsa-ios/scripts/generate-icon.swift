#!/usr/bin/env swift
import AppKit
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

// 以原生向量繪製不透明圖示；幾何與 App/Design/BrandMark.swift 保持一致。
// 執行：swift apps/dsa-ios/scripts/generate-icon.swift
let script = URL(fileURLWithPath: #filePath)
let output = script.deletingLastPathComponent().deletingLastPathComponent()
    .appendingPathComponent("App/Assets.xcassets/AppIcon.appiconset")
try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)

let width = 1024
let colorSpace = CGColorSpace(name: CGColorSpace.sRGB)!
guard let context = CGContext(
    data: nil, width: width, height: width, bitsPerComponent: 8, bytesPerRow: width * 4,
    space: colorSpace, bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue
) else { fatalError("無法建立圖示繪圖畫布") }
context.translateBy(x: 0, y: CGFloat(width))
context.scaleBy(x: 1, y: -1)

func color(_ red: CGFloat, _ green: CGFloat, _ blue: CGFloat, _ alpha: CGFloat = 1) -> CGColor {
    CGColor(colorSpace: colorSpace, components: [red, green, blue, alpha])!
}
let accent = color(0.34, 0.89, 0.78)
let inner = color(0.040, 0.078, 0.127)
let gradient = CGGradient(colorsSpace: colorSpace, colors: [color(0.065, 0.118, 0.180), color(0.020, 0.043, 0.082)] as CFArray, locations: [0, 1])!
context.drawLinearGradient(gradient, start: .zero, end: CGPoint(x: 1024, y: 1024), options: [.drawsBeforeStartLocation, .drawsAfterEndLocation])
let glow = CGGradient(colorsSpace: colorSpace, colors: [color(0.34, 0.89, 0.78, 0.12), color(0.34, 0.89, 0.78, 0)] as CFArray, locations: [0, 1])!
context.drawRadialGradient(glow, startCenter: CGPoint(x: 804, y: 302), startRadius: 0, endCenter: CGPoint(x: 804, y: 302), endRadius: 150, options: [])

func stroke(_ path: CGPath, opacity: CGFloat, width: CGFloat) {
    context.addPath(path)
    context.setStrokeColor(color(0.34, 0.89, 0.78, opacity))
    context.setLineWidth(width)
    context.setLineCap(.round)
    context.setLineJoin(.round)
    context.strokePath()
}
let upper = CGMutablePath()
upper.move(to: CGPoint(x: 190, y: 350))
upper.addCurve(to: CGPoint(x: 414, y: 430), control1: CGPoint(x: 310, y: 350), control2: CGPoint(x: 330, y: 430))
upper.addCurve(to: CGPoint(x: 592, y: 500), control1: CGPoint(x: 490, y: 430), control2: CGPoint(x: 510, y: 500))
stroke(upper, opacity: 0.42, width: 26)

let lower = CGMutablePath()
lower.move(to: CGPoint(x: 190, y: 716))
lower.addCurve(to: CGPoint(x: 414, y: 594), control1: CGPoint(x: 338, y: 716), control2: CGPoint(x: 318, y: 594))
lower.addCurve(to: CGPoint(x: 592, y: 500), control1: CGPoint(x: 490, y: 594), control2: CGPoint(x: 510, y: 500))
stroke(lower, opacity: 0.68, width: 26)

let main = CGMutablePath()
main.move(to: CGPoint(x: 190, y: 550))
main.addCurve(to: CGPoint(x: 414, y: 500), control1: CGPoint(x: 270, y: 550), control2: CGPoint(x: 280, y: 500))
main.addLine(to: CGPoint(x: 592, y: 500))
main.addCurve(to: CGPoint(x: 804, y: 302), control1: CGPoint(x: 668, y: 500), control2: CGPoint(x: 688, y: 302))
stroke(main, opacity: 1, width: 34)

for (point, opacity): (CGPoint, CGFloat) in [(CGPoint(x: 190, y: 350), 0.5), (CGPoint(x: 190, y: 550), 1.0), (CGPoint(x: 190, y: 716), 0.75)] {
    context.setFillColor(color(0.34, 0.89, 0.78, opacity))
    context.fillEllipse(in: CGRect(x: point.x - 21, y: point.y - 21, width: 42, height: 42))
}
func node(center: CGPoint, radius: CGFloat, lineWidth: CGFloat, coreRadius: CGFloat, coreColor: CGColor) {
    let bounds = CGRect(x: center.x - radius, y: center.y - radius, width: radius * 2, height: radius * 2)
    context.setFillColor(inner)
    context.fillEllipse(in: bounds)
    context.setStrokeColor(accent)
    context.setLineWidth(lineWidth)
    context.strokeEllipse(in: bounds)
    context.setFillColor(coreColor)
    context.fillEllipse(in: CGRect(x: center.x - coreRadius, y: center.y - coreRadius, width: coreRadius * 2, height: coreRadius * 2))
}
node(center: CGPoint(x: 592, y: 500), radius: 38, lineWidth: 16, coreRadius: 12, coreColor: accent)
node(center: CGPoint(x: 804, y: 302), radius: 46, lineWidth: 17, coreRadius: 18, coreColor: color(0.85, 1.0, 0.96))

let imageURL = output.appendingPathComponent("AppIcon.png")
guard let image = context.makeImage(),
      let destination = CGImageDestinationCreateWithURL(imageURL as CFURL, UTType.png.identifier as CFString, 1, nil) else {
    fatalError("無法建立圖示輸出")
}
CGImageDestinationAddImage(destination, image, nil)
guard CGImageDestinationFinalize(destination) else { fatalError("無法儲存圖示") }
let contents = """
{
  "images" : [
    {
      "filename" : "AppIcon.png",
      "idiom" : "universal",
      "platform" : "ios",
      "size" : "1024x1024"
    }
  ],
  "info" : { "author" : "xcode", "version" : 1 }
}
"""
try contents.write(to: output.appendingPathComponent("Contents.json"), atomically: true, encoding: .utf8)
print("已產生不透明 1024×1024 圖示：\(imageURL.path)")
