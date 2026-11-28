// Draws the DMG window background: a soft light canvas, an arrow from the app to Applications,
// and a bilingual hint. Finder doesn't theme DMG backgrounds, so it is light in both appearances.
// Usage: swift dmg/make-background.swift out.png scale   (scale 1 or 2; content area is 600×360 pt)
// Everything sits in the top 280 pt, so a Finder that also shows the tab bar and path bar (which eat
// the bottom of the window) still shows the whole layout.
import AppKit

let W: CGFloat = 600, H: CGFloat = 360
let out = CommandLine.arguments[1]
let scale = CGFloat(Double(CommandLine.arguments[2]) ?? 1)
let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(W * scale), pixelsHigh: Int(H * scale), bitsPerSample: 8,
                           samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
                           bytesPerRow: 0, bitsPerPixel: 0)!
rep.size = NSSize(width: W, height: H)          // drawing is in points; 72 dpi at 1×, 144 dpi at 2×
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
let ctx = NSGraphicsContext.current!.cgContext

func rgb(_ hex: UInt32, _ a: CGFloat = 1) -> CGColor {
    CGColor(srgbRed: CGFloat((hex >> 16) & 0xff) / 255, green: CGFloat((hex >> 8) & 0xff) / 255,
            blue: CGFloat(hex & 0xff) / 255, alpha: a)
}

// Background: near-white with a faint vertical gradient.
let grad = CGGradient(colorsSpace: CGColorSpace(name: CGColorSpace.sRGB),
                      colors: [rgb(0xF7F7F9), rgb(0xECEDF1)] as CFArray, locations: [0, 1])!
ctx.drawLinearGradient(grad, start: CGPoint(x: 0, y: H), end: CGPoint(x: 0, y: 0), options: [])

// Arrow between the two icons (icon centres at x = 160 and 440, y = 130 from the top).
let y = H - 130
ctx.setStrokeColor(rgb(0x8E8E96)); ctx.setLineWidth(3); ctx.setLineCap(.round); ctx.setLineJoin(.round)
ctx.move(to: CGPoint(x: 252, y: y)); ctx.addLine(to: CGPoint(x: 346, y: y)); ctx.strokePath()
ctx.move(to: CGPoint(x: 334, y: y + 11)); ctx.addLine(to: CGPoint(x: 348, y: y)); ctx.addLine(to: CGPoint(x: 334, y: y - 11)); ctx.strokePath()

// Hint text, centred near the bottom.
func text(_ s: String, size: CGFloat, weight: NSFont.Weight, color: UInt32, baselineFromTop: CGFloat) {
    let str = NSAttributedString(string: s, attributes: [.font: NSFont.systemFont(ofSize: size, weight: weight),
                                                          .foregroundColor: NSColor(cgColor: rgb(color))!])
    let w = str.size().width
    str.draw(at: NSPoint(x: (W - w) / 2, y: H - baselineFromTop))
}
text("Drag Timetrace to Applications", size: 14, weight: .medium, color: 0x3A3A40, baselineFromTop: 252)
text("把 Timetrace（时间看板）拖到「应用程序」", size: 13, weight: .regular, color: 0x6E6E76, baselineFromTop: 274)

NSGraphicsContext.current = nil
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: out))
