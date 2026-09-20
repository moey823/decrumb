// SPDX-License-Identifier: AGPL-3.0-only
// Original Decrumb artwork. The icon and optional brand exports share these paths.
import AppKit

let indigo = NSColor(srgbRed: 74 / 255, green: 87 / 255, blue: 209 / 255, alpha: 1)
let ink = NSColor(srgbRed: 34 / 255, green: 37 / 255, blue: 67 / 255, alpha: 1)
let amber = NSColor(srgbRed: 245 / 255, green: 183 / 255, blue: 108 / 255, alpha: 1)

enum Segment {
    case move(CGFloat, CGFloat), line(CGFloat, CGFloat)
    case curve(CGFloat, CGFloat, CGFloat, CGFloat, CGFloat, CGFloat)
}

// Coordinates use a 100 × 100 canvas with the origin at the upper left.
let linkSegments: [[Segment]] = [
    [.move(44, 40), .line(53, 31), .curve(59, 25, 69, 25, 75, 31),
     .curve(81, 37, 81, 47, 75, 53), .line(66, 62)],
    [.move(52, 62), .line(43, 71), .curve(37, 77, 27, 77, 21, 71),
     .curve(15, 65, 15, 55, 21, 49), .line(30, 40)],
    [.move(35, 63), .line(61, 37)]
]
let crumbs: [(x: CGFloat, y: CGFloat, size: CGFloat, angle: CGFloat)] = [
    (80, 17, 7, 14), (89, 7, 4, -9), (70, 7, 3, 8)
]

// Original lowercase lettering: each curve and stroke is authored here, not
// extracted from a typeface. Rounded ends echo the link's open geometry.
let bowl: [Segment] = [.move(37, 55), .curve(37, 44.51, 29.84, 36, 21, 36),
    .curve(12.16, 36, 5, 44.51, 5, 55), .curve(5, 65.49, 12.16, 74, 21, 74),
    .curve(29.84, 74, 37, 65.49, 37, 55)]
let letters: [(x: CGFloat, strokes: [[Segment]])] = [
    (0, [bowl, [.move(37, 19), .line(37, 74)]]), // d
    (49, [[.move(34, 67), .curve(31, 72, 25, 75, 18, 74),
        .curve(9, 73, 5, 66, 5, 56), .curve(5, 43, 11, 36, 21, 36),
        .curve(31, 36, 36, 44, 36, 54), .line(6, 54)]]), // e
    (94, [[.move(34, 43), .curve(30, 38, 25, 36, 20, 36),
        .curve(10, 36, 5, 44, 5, 55), .curve(5, 66, 10, 74, 20, 74),
        .curve(25, 74, 30, 72, 34, 67)]]), // c
    (138, [[.move(6, 74), .line(6, 37)],
        [.move(6, 50), .curve(8, 42, 14, 36, 22, 36), .curve(26, 36, 29, 37, 31, 39)]]), // r
    (177, [[.move(6, 38), .line(6, 58), .curve(6, 68, 11, 74, 20, 74),
        .curve(29, 74, 35, 68, 35, 58), .line(35, 38)]]), // u
    (224, [[.move(6, 74), .line(6, 38)],
        [.move(6, 48), .curve(7, 40, 12, 36, 19, 36), .curve(26, 36, 31, 41, 31, 50), .line(31, 74)],
        [.move(31, 50), .curve(31, 41, 36, 36, 43, 36), .curve(51, 36, 56, 41, 56, 50), .line(56, 74)]]), // m
    (292, [bowl, [.move(5, 19), .line(5, 74)]]) // b
]
let letteringScale: CGFloat = 0.82
let wordmarkWidth: CGFloat = 393

func path(_ segments: [Segment]) -> NSBezierPath {
    let result = NSBezierPath()
    for segment in segments {
        switch segment {
        case let .move(x, y): result.move(to: NSPoint(x: x, y: y))
        case let .line(x, y): result.line(to: NSPoint(x: x, y: y))
        case let .curve(x1, y1, x2, y2, x, y):
            result.curve(to: NSPoint(x: x, y: y), controlPoint1: NSPoint(x: x1, y: y1), controlPoint2: NSPoint(x: x2, y: y2))
        }
    }
    result.lineWidth = 8
    result.lineCapStyle = .round
    result.lineJoinStyle = .round
    return result
}

func inCanvas(_ rect: NSRect, _ body: () -> Void) {
    NSGraphicsContext.saveGraphicsState()
    let transform = NSAffineTransform()
    transform.translateX(by: rect.minX, yBy: rect.maxY)
    transform.scaleX(by: rect.width / 100, yBy: -rect.height / 100)
    transform.concat()
    body()
    NSGraphicsContext.restoreGraphicsState()
}

func drawMark(_ rect: NSRect, color: NSColor = indigo, accent: NSColor = amber) {
    inCanvas(rect) {
        color.setStroke()
        for segments in linkSegments { path(segments).stroke() }
        accent.setFill()
        for crumb in crumbs {
            NSGraphicsContext.saveGraphicsState()
            let transform = NSAffineTransform()
            transform.translateX(by: crumb.x, yBy: crumb.y)
            transform.rotate(byDegrees: crumb.angle)
            transform.concat()
            NSBezierPath(roundedRect: NSRect(x: -crumb.size / 2, y: -crumb.size / 2,
                                            width: crumb.size, height: crumb.size),
                         xRadius: crumb.size * 0.24, yRadius: crumb.size * 0.24).fill()
            NSGraphicsContext.restoreGraphicsState()
        }
    }
}

func drawIcon(_ rect: NSRect) {
    inCanvas(rect) {
        let background = NSBezierPath(roundedRect: NSRect(x: 6, y: 6, width: 88, height: 88), xRadius: 20, yRadius: 20)
        NSGradient(starting: NSColor(srgbRed: 102 / 255, green: 115 / 255, blue: 228 / 255, alpha: 1),
                   ending: NSColor(srgbRed: 62 / 255, green: 76 / 255, blue: 193 / 255, alpha: 1))!
            .draw(in: background, angle: -90)
        // The nested canvas flips a second time, so compensate before drawing.
        let transform = NSAffineTransform()
        transform.translateX(by: 0, yBy: 100)
        transform.scaleX(by: 1, yBy: -1)
        transform.concat()
        drawMark(NSRect(x: 10, y: 11, width: 80, height: 80), color: .white)
    }
}

func renderPNG(_ size: NSSize, to url: URL, _ draw: () -> Void) throws {
    let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(size.width), pixelsHigh: Int(size.height),
        bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
        colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
    draw()
    NSGraphicsContext.restoreGraphicsState()
    try bitmap.representation(using: .png, properties: [:])!.write(to: url)
}

func number(_ value: CGFloat) -> String { String(format: "%.2f", Double(value)) }

func svgPath(_ segments: [Segment]) -> String {
    segments.map { segment in
        switch segment {
        case let .move(x, y): return "M\(number(x)) \(number(y))"
        case let .line(x, y): return "L\(number(x)) \(number(y))"
        case let .curve(x1, y1, x2, y2, x, y):
            return "C\(number(x1)) \(number(y1)) \(number(x2)) \(number(y2)) \(number(x)) \(number(y))"
        }
    }.joined(separator: " ")
}

func svgMark(color: String, accent: String = "#F5B76C") -> String {
    let links = linkSegments.map { "<path d=\"\(svgPath($0))\"/>" }.joined(separator: "\n")
    let particles = crumbs.map { crumb in
        "<rect x=\"\(number(-crumb.size / 2))\" y=\"\(number(-crumb.size / 2))\" width=\"\(number(crumb.size))\" height=\"\(number(crumb.size))\" rx=\"\(number(crumb.size * 0.24))\" transform=\"translate(\(number(crumb.x)) \(number(crumb.y))) rotate(\(number(crumb.angle)))\"/>"
    }.joined(separator: "\n")
    return "<g fill=\"none\" stroke=\"\(color)\" stroke-width=\"8\" stroke-linecap=\"round\" stroke-linejoin=\"round\">\n\(links)\n</g>\n<g fill=\"\(accent)\">\n\(particles)\n</g>"
}

func svgDocument(width: CGFloat, height: CGFloat, title: String, contents: String) -> String {
    """
    <?xml version="1.0" encoding="UTF-8"?>
    <!-- SPDX-License-Identifier: AGPL-3.0-only. Original Decrumb artwork. -->
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 \(number(width)) \(number(height))" role="img" aria-labelledby="title">
    <title id="title">\(title)</title>
    \(contents)
    </svg>

    """
}

func svgLettering(color: String) -> String {
    let paths = letters.map { letter in
        let strokes = letter.strokes.map { "<path d=\"\(svgPath($0))\"/>" }.joined(separator: "\n")
        return "<g transform=\"translate(\(number(letter.x)) 0)\">\(strokes)</g>"
    }.joined(separator: "\n")
    return "<g transform=\"translate(110 10) scale(\(number(letteringScale)))\" fill=\"none\" stroke=\"\(color)\" stroke-width=\"7\" stroke-linecap=\"round\" stroke-linejoin=\"round\">\n\(paths)\n</g>"
}

func brandExports(_ folder: URL) throws {
    try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
    func write(_ name: String, _ content: String) throws {
        try content.write(to: folder.appendingPathComponent(name), atomically: true, encoding: .utf8)
    }
    try write("decrumb-mark.svg", svgDocument(width: 100, height: 100, title: "Decrumb", contents: svgMark(color: "#4A57D1")))
    try write("decrumb-mark-inverse.svg", svgDocument(width: 100, height: 100, title: "Decrumb", contents: svgMark(color: "#FFFFFF")))
    try write("decrumb-mark-mono.svg", svgDocument(width: 100, height: 100, title: "Decrumb", contents: svgMark(color: "currentColor", accent: "currentColor")))
    let iconSVG = """
    <defs><linearGradient id="surface" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#3E4CC1"/><stop offset="1" stop-color="#6673E4"/></linearGradient></defs>
    <rect x="6" y="6" width="88" height="88" rx="20" fill="url(#surface)"/>
    <g transform="translate(10 9) scale(.8)">\(svgMark(color: "#FFFFFF"))</g>
    """
    try write("decrumb-app-icon.svg", svgDocument(width: 100, height: 100, title: "Decrumb app icon", contents: iconSVG))
    let width = wordmarkWidth
    for (name, color, textColor) in [("decrumb-wordmark", "#4A57D1", "#222543"), ("decrumb-wordmark-inverse", "#FFFFFF", "#FFFFFF")] {
        let content = svgMark(color: color) + "\n" + svgLettering(color: textColor)
        try write(name + ".svg", svgDocument(width: width, height: 100, title: "Decrumb", contents: content))
    }
    func drawWordmark(_ rect: NSRect, inverse: Bool = false) {
        NSGraphicsContext.saveGraphicsState()
        let context = NSGraphicsContext.current!.cgContext
        context.translateBy(x: rect.minX, y: rect.minY)
        context.scaleBy(x: rect.width / width, y: rect.height / 100)
        drawMark(NSRect(x: 0, y: 0, width: 100, height: 100), color: inverse ? .white : indigo)
        context.translateBy(x: 110, y: 90)
        context.scaleBy(x: letteringScale, y: -letteringScale)
        (inverse ? NSColor.white : ink).setStroke()
        for letter in letters {
            context.saveGState()
            context.translateBy(x: letter.x, y: 0)
            for segments in letter.strokes {
                let stroke = path(segments)
                stroke.lineWidth = 7
                stroke.stroke()
            }
            context.restoreGState()
        }
        NSGraphicsContext.restoreGraphicsState()
    }
    try renderPNG(NSSize(width: 1024, height: 1024), to: folder.appendingPathComponent("decrumb-app-icon.png")) {
        drawIcon(NSRect(x: 0, y: 0, width: 1024, height: 1024))
    }
    try renderPNG(NSSize(width: 512, height: 512), to: folder.appendingPathComponent("decrumb-mark.png")) {
        drawMark(NSRect(x: 0, y: 0, width: 512, height: 512))
    }
    try renderPNG(NSSize(width: width * 3, height: 300), to: folder.appendingPathComponent("decrumb-wordmark.png")) {
        drawWordmark(NSRect(x: 0, y: 0, width: width * 3, height: 300))
    }
    try renderPNG(NSSize(width: 1400, height: 920), to: folder.appendingPathComponent("decrumb-brand-preview.png")) {
        NSColor(srgbRed: 0.97, green: 0.97, blue: 0.95, alpha: 1).setFill()
        NSRect(x: 0, y: 0, width: 1400, height: 920).fill()
        func text(_ value: String, x: CGFloat, y: CGFloat, size: CGFloat, color: NSColor = ink, weight: NSFont.Weight = .regular) {
            NSAttributedString(string: value, attributes: [.font: NSFont.systemFont(ofSize: size, weight: weight), .foregroundColor: color]).draw(at: NSPoint(x: x, y: y))
        }
        text("DECRUMB", x: 72, y: 828, size: 18, weight: .semibold)
        text("A little cleaner for your links.", x: 72, y: 770, size: 36, weight: .medium)
        text("Original vector identity · macOS app + web", x: 72, y: 732, size: 17, color: .secondaryLabelColor)
        drawIcon(NSRect(x: 55, y: 335, width: 370, height: 370))
        text("App icon", x: 85, y: 320, size: 16, color: .secondaryLabelColor)
        drawWordmark(NSRect(x: 525, y: 540, width: width * 1.85, height: 185))
        ink.setFill()
        NSBezierPath(roundedRect: NSRect(x: 485, y: 313, width: 840, height: 198), xRadius: 24, yRadius: 24).fill()
        drawWordmark(NSRect(x: 525, y: 323, width: width * 1.85, height: 185), inverse: true)
        text("Small-size check", x: 85, y: 235, size: 16, color: .secondaryLabelColor)
        var x: CGFloat = 85
        for size: CGFloat in [16, 24, 32, 48, 64] {
            drawIcon(NSRect(x: x, y: 125, width: size, height: size))
            text("\(Int(size))", x: x, y: 95, size: 12, color: .secondaryLabelColor)
            x += size + 34
        }
        for (offset, color, label) in [(CGFloat(0), indigo, "Indigo · #4A57D1"), (CGFloat(270), amber, "Crumb · #F5B76C"), (CGFloat(535), ink, "Ink · #222543")] {
            color.setFill()
            NSBezierPath(roundedRect: NSRect(x: 535 + offset, y: 152, width: 44, height: 44), xRadius: 12, yRadius: 12).fill()
            text(label, x: 535 + offset, y: 115, size: 14)
        }
    }
}

guard CommandLine.arguments.count >= 2 else {
    fatalError("Usage: make-icon ICONSET_DIRECTORY [BRANDING_EXPORT_DIRECTORY]")
}
let folder = URL(fileURLWithPath: CommandLine.arguments[1])
try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
for (name, size) in [("icon_16x16", 16), ("icon_16x16@2x", 32), ("icon_32x32", 32), ("icon_32x32@2x", 64), ("icon_128x128", 128), ("icon_128x128@2x", 256), ("icon_256x256", 256), ("icon_256x256@2x", 512), ("icon_512x512", 512), ("icon_512x512@2x", 1024)] {
    try renderPNG(NSSize(width: size, height: size), to: folder.appendingPathComponent(name + ".png")) {
        drawIcon(NSRect(x: 0, y: 0, width: size, height: size))
    }
}
if CommandLine.arguments.count >= 3 { try brandExports(URL(fileURLWithPath: CommandLine.arguments[2])) }
