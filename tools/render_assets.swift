// Renders every image Hermes Chat Renderer draws with, from design/tokens.json, plus previews made the way the
// renderer makes them. The renderer draws each message once, as a "row" image, when it arrives; a redraw only stacks
// the saved rows (Combine Images), fades their top, and lays them on the wall: one full-screen operation.
//   wall.png              the Nocturne wall, graded so text stays legible over the moonlight
//   veil.png, blue.png    solid sources the renderer crops bubbles from (the agent's glass veil, your blue)
//   clear.png             transparent canvas a row is cut from (tall enough for the longest bubble)
//   gap-*.png, receipt-canvas.png, stamp-canvas.png   transparent spacers and canvases at their exact sizes, so the
//                         renderer reads them instead of cutting each from a larger image
//   tail-left/right.png   bubble tails, shaped to meet the bubble's corner without overlapping it
//   typing-*.png          the typing bubble as a ready row (after your message / after one of the agent's)
//   fade-mask.png         alpha ramp that fades the stacked rows into the wall under the clock
//   avatar.png            monogram circle for a new chat (initials are drawn on it at runtime)
//   manifest.json         numbers the renderer needs: character width classes, offsets, sizes
//   preview-*.png, preview.png   the four states, built only from the files above
// Usage: swiftc -O tools/render_assets.swift -o /tmp/render_assets && /tmp/render_assets <project-dir>
import AppKit
import CoreImage

// MARK: - Tokens

struct Face: Decodable { let font: String; let size: Double; let pitch: Double }
struct Tokens: Decodable {
    struct Canvas: Decodable { let width: Int; let height: Int }
    struct Zones: Decodable { let chatTop, chatBottom, fadeOpaque, fadeClear, textCut: Double }
    struct Plate: Decodable {
        let source: String; let rows: [[Double]]; let gain: Double; let lift: [Double]; let dims: [[Double]]
        let grain: Double; let grainSeed: UInt32
    }
    struct Faces: Decodable { let body, day, time, monogram, name, hint: Face }
    struct Colors: Decodable {
        let ink, sentInk, stamp, blue: String; let veil: Double; let dots: [String]; let avatarTop, avatarBottom: String
    }
    struct Bubble: Decodable {
        let side, padX, padTop, padBottom, radius: Double
        let chars, maxLines, widowChars, widowStep: Int
        let sameGap, turnGap, tailReach, tailTip, tailRoom, maxText: Double
    }
    struct Stamp: Decodable { let above, below: Double; let gapMinutes: Int }
    struct Receipt: Decodable { let gap, height: Double }
    struct Typing: Decodable { let width, dot, dotPitch, dotInset: Double }
    struct Empty: Decodable { let avatar, top, nameGap, hintGap: Double }
    struct Tapback: Decodable { let size, ring, dot, room, inset, drop, emoji: Double; let them, me: String }
    struct Jumbo: Decodable { let size, pitch: Double; let max: Int; let padTop, padBottom: Double }
    struct Audio: Decodable { let width, play, playX, barW, barGap, barsX, barMin, barMax: Double; let bars: Int; let seed: UInt32 }
    let canvas: Canvas; let zones: Zones; let plate: Plate; let walls: [String: Plate]; let type: Faces; let color: Colors
    let bubble: Bubble; let stamp: Stamp; let receipt: Receipt; let typing: Typing; let empty: Empty
    let tapback: Tapback; let jumbo: Jumbo; let audio: Audio
}

let root = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "."
let t = try! JSONDecoder().decode(Tokens.self, from: Data(contentsOf: URL(fileURLWithPath: "\(root)/design/tokens.json")))
let outDir = "\(root)/assets"
let W = t.canvas.width, H = t.canvas.height
let srgb = CGColorSpace(name: CGColorSpace.sRGB)!
let ciContext = CIContext(options: [.workingColorSpace: CGColorSpace(name: CGColorSpace.extendedLinearSRGB)!, .outputColorSpace: srgb])

// MARK: - Color

func linear(_ v: Double) -> Double { v <= 0.04045 ? v / 12.92 : pow((v + 0.055) / 1.055, 2.4) }
func luminance(_ r: Double, _ g: Double, _ b: Double) -> Double { 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b) }
func contrast(_ a: Double, _ b: Double) -> Double { (max(a, b) + 0.05) / (min(a, b) + 0.05) }
func rgb(_ hex: String) -> (Double, Double, Double) {
    let v = UInt32(hex, radix: 16)!
    return (Double((v >> 16) & 0xff) / 255, Double((v >> 8) & 0xff) / 255, Double(v & 0xff) / 255)
}
func nsColor(_ hex: String, _ alpha: Double = 1) -> NSColor { let (r, g, b) = rgb(hex); return NSColor(srgbRed: r, green: g, blue: b, alpha: alpha) }
func luminance(_ hex: String) -> Double { let (r, g, b) = rgb(hex); return luminance(r, g, b) }

// MARK: - Pixel buffers (premultiplied RGBA8, row 0 at the top)

struct Bitmap {
    let w: Int, h: Int
    var px: [UInt8]
    init(_ w: Int, _ h: Int) { self.w = w; self.h = h; px = [UInt8](repeating: 0, count: w * h * 4) }
    init(_ cg: CGImage) {
        self.init(cg.width, cg.height)
        let rect = CGRect(x: 0, y: 0, width: cg.width, height: cg.height)
        draw { ctx in ctx.draw(cg, in: rect) }
    }
    /// Runs `body` with a context on these pixels; `flipped` makes y run down from the top.
    mutating func draw(flipped: Bool = false, _ body: (CGContext) -> Void) {
        let (w, h) = (self.w, self.h)
        px.withUnsafeMutableBytes { buf in
            let ctx = CGContext(data: buf.baseAddress, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w * 4,
                                space: srgb, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
            if flipped { ctx.translateBy(x: 0, y: CGFloat(h)); ctx.scaleBy(x: 1, y: -1) }
            body(ctx)
        }
    }
    var cg: CGImage {
        var copy = self
        var image: CGImage?
        copy.draw { ctx in image = ctx.makeImage() }
        return image!
    }
    var ci: CIImage { CIImage(cgImage: cg) }
    func write(_ name: String) {
        try! NSBitmapImageRep(cgImage: cg).representation(using: .png, properties: [:])!
            .write(to: URL(fileURLWithPath: "\(outDir)/\(name)"))
    }
    /// Brightest relative luminance among opaque pixels in a rect (y down).
    func maxLuminance(_ r: CGRect) -> Double {
        var top = 0.0
        for y in max(Int(r.minY), 0)..<min(Int(r.maxY), h) {
            for x in max(Int(r.minX), 0)..<min(Int(r.maxX), w) {
                let i = (y * w + x) * 4
                guard px[i + 3] == 255 else { continue }
                top = max(top, luminance(Double(px[i]) / 255, Double(px[i + 1]) / 255, Double(px[i + 2]) / 255))
            }
        }
        return top
    }
}

/// Seeded PRNG (mulberry32) so every asset is reproducible.
struct Random {
    var state: UInt32
    mutating func next() -> Double {
        state &+= 0x6D2B79F5
        var z = state
        z = (z ^ (z >> 15)) &* (z | 1)
        z ^= z &+ ((z ^ (z >> 7)) &* (z | 61))
        return Double(z ^ (z >> 14)) / 4294967296
    }
    mutating func gaussian() -> Double { (next() + next() + next() + next() - 2) * 1.732 }
}

func render(_ img: CIImage) -> CGImage {
    ciContext.createCGImage(img, from: CGRect(x: 0, y: 0, width: W, height: H), format: .RGBA8, colorSpace: srgb)!
}
func drawing(_ w: Int, _ h: Int, _ body: (CGContext) -> Void) -> Bitmap {
    var b = Bitmap(w, h)
    b.draw(flipped: true, body)
    return b
}
func solid(_ w: Int, _ h: Int, _ hex: String, _ alpha: Double) -> Bitmap {
    drawing(w, h) { ctx in ctx.setFillColor(nsColor(hex, alpha).cgColor); ctx.fill(CGRect(x: 0, y: 0, width: w, height: h)) }
}
/// Scales every channel of a premultiplied bitmap, i.e. makes it `alpha` times as opaque.
func fade(_ b: Bitmap, _ alpha: Double) -> Bitmap {
    var out = b
    for i in 0..<out.px.count { out.px[i] = UInt8((Double(out.px[i]) * alpha).rounded()) }
    return out
}
func smootherstep(_ u: Double) -> Double { let u = min(max(u, 0), 1); return u * u * u * (u * (u * 6 - 15) + 10) }

// MARK: - The wall

/// The generated photograph, filling the screen, then fitted to the Lock Screen and graded in gamma space:
///   rows   moves the picture vertically (screen y → photo y, linear between points): the glow behind the clock is
///          stretched so the moonlight lands behind the flashlight and camera buttons, below every line of text
///   gain   compresses the light; lift raises the floor to an off-black
///   dims   dims band by band (y → factor, eased between points) so text over the chat clears 4.5:1
func makeWall(_ p: Tokens.Plate) -> Bitmap {
    let img = CIImage(contentsOf: URL(fileURLWithPath: "\(root)/\(p.source)"))!
    let s = max(CGFloat(W) / img.extent.width, CGFloat(H) / img.extent.height)
    let scaled = img.applyingFilter("CILanczosScaleTransform", parameters: [kCIInputScaleKey: s, kCIInputAspectRatioKey: 1])
    let dx = (scaled.extent.width - CGFloat(W)) / 2, dy = (scaled.extent.height - CGFloat(H)) / 2
    let photo = Bitmap(render(scaled.transformed(by: CGAffineTransform(translationX: -scaled.extent.minX - dx, y: -scaled.extent.minY - dy))))
    var b = Bitmap(W, H)
    for y in 0..<H {
        var src = Double(y)
        for k in 1..<p.rows.count where Double(y) <= p.rows[k][0] {
            let (a0, s0, a1, s1) = (p.rows[k - 1][0], p.rows[k - 1][1], p.rows[k][0], p.rows[k][1])
            src = s0 + (s1 - s0) * (Double(y) - a0) / (a1 - a0)
            break
        }
        let y0 = min(max(Int(src), 0), H - 1), y1 = min(y0 + 1, H - 1), f = src - Double(y0)
        for x in 0..<W {
            let i = (y * W + x) * 4, i0 = (y0 * W + x) * 4, i1 = (y1 * W + x) * 4
            for c in 0..<3 { b.px[i + c] = UInt8((Double(photo.px[i0 + c]) * (1 - f) + Double(photo.px[i1 + c]) * f).rounded()) }
            b.px[i + 3] = 255
        }
    }
    func dim(_ y: Double) -> Double {
        for k in 1..<p.dims.count where y <= p.dims[k][0] {
            let (y0, d0, y1, d1) = (p.dims[k - 1][0], p.dims[k - 1][1], p.dims[k][0], p.dims[k][1])
            let u = (y - y0) / max(y1 - y0, 1)
            return d0 + (d1 - d0) * u * u * (3 - 2 * u)
        }
        return p.dims.last![1]
    }
    for y in 0..<H {
        let d = dim(Double(y))
        for x in 0..<W {
            let i = (y * W + x) * 4
            for c in 0..<3 {
                let v = Double(b.px[i + c]) / 255 * p.gain * d
                b.px[i + c] = UInt8((min(max(p.lift[c] + v * (1 - p.lift[c]), 0), 1) * 255).rounded())
            }
            b.px[i + 3] = 255
        }
    }
    var rng = Random(state: p.grainSeed)
    for i in stride(from: 0, to: b.px.count, by: 4) {
        let n = rng.gaussian() * p.grain
        for c in 0..<3 { b.px[i + c] = UInt8(min(max(Double(b.px[i + c]) + n, 0), 255).rounded()) }
    }
    return b
}

// MARK: - Shapes

let radius = t.bubble.radius, reach = t.bubble.tailReach, tip = t.bubble.tailTip

/// Messages' tail at a bubble's bottom corner (edge x, bottom y; y down). It owns the corner: the side runs straight
/// down, flares out to a point just past the edge, and the underside bows up a little before landing on the flat
/// bottom past the corner's curve, so the outline never steps.
func tailPath(edge: CGFloat, bottom: CGFloat, right: Bool) -> CGPath {
    let s: CGFloat = right ? 1 : -1, reach = CGFloat(reach), tip = CGFloat(tip)
    let p = { (dx: CGFloat, dy: CGFloat) in CGPoint(x: edge + s * dx, y: bottom + dy) }
    let path = CGMutablePath()
    path.move(to: p(0, -reach))
    path.addLine(to: p(0, -30))
    path.addCurve(to: p(tip, 1), control1: p(0, -10), control2: p(5, -1))
    path.addCurve(to: p(-reach, 0), control1: p(3, -3.5), control2: p(-26, 0))
    path.addLine(to: p(-reach, -reach))
    path.closeSubpath()
    return path
}

/// Tail pieces live in an 82 x 66 box whose inner corner sits 62 px inside the bubble's edge and bottom. A piece is
/// the tail minus the bubble's own rounded corner, so a translucent tail never doubles up where the two meet.
let tailBox = (w: 82, h: 66, inset: 62)
func tailOrigin(x: Double, y: Double, w: Double, h: Double, right: Bool) -> (Int, Int) {
    (right ? Int(x + w) - tailBox.inset : Int(x) - (tailBox.w - tailBox.inset), Int(y + h) - tailBox.inset)
}
func tailPiece(right: Bool, hex: String, alpha: Double) -> Bitmap {
    drawing(tailBox.w, tailBox.h) { ctx in
        let edge = right ? CGFloat(tailBox.inset) : CGFloat(tailBox.w - tailBox.inset), bottom = CGFloat(tailBox.inset)
        // The bubble's corner as Mask Image cuts it (a circular arc), extended past the box, is left out.
        let body = CGPath(roundedRect: CGRect(x: right ? edge - 400 : edge, y: bottom - 400, width: 400, height: 400),
                          cornerWidth: CGFloat(radius), cornerHeight: CGFloat(radius), transform: nil)
        let outside = CGMutablePath()
        outside.addRect(CGRect(x: -10, y: -10, width: tailBox.w + 20, height: tailBox.h + 20))
        outside.addPath(body)
        ctx.addPath(outside); ctx.clip(using: .evenOdd)
        ctx.setFillColor(nsColor(hex, alpha).cgColor)
        ctx.addPath(tailPath(edge: edge, bottom: bottom, right: right)); ctx.fillPath()
    }
}

// MARK: - The renderer's image actions, reproduced (positions y down, from the top-left)

func crop(_ b: Bitmap, _ x: Int, _ y: Int, _ w: Int, _ h: Int) -> Bitmap { Bitmap(b.cg.cropping(to: CGRect(x: x, y: y, width: w, height: h))!) }
/// Mask Image (rounded rectangle): circular corners, radius in pixels, capped at half the shorter side.
func maskRounded(_ b: Bitmap, radius: Double) -> Bitmap {
    let r = CGFloat(min(radius, Double(min(b.w, b.h)) / 2))
    var out = Bitmap(b.w, b.h)
    out.draw { ctx in
        ctx.addPath(CGPath(roundedRect: CGRect(x: 0, y: 0, width: b.w, height: b.h), cornerWidth: r, cornerHeight: r, transform: nil))
        ctx.clip(); ctx.draw(b.cg, in: CGRect(x: 0, y: 0, width: b.w, height: b.h))
    }
    return out
}
/// Mask Image (custom image): keeps pixels where the mask is opaque.
func maskCustom(_ b: Bitmap, _ mask: Bitmap) -> Bitmap {
    var out = b
    for i in stride(from: 0, to: out.px.count, by: 4) {
        let a = Double(mask.px[i + 3]) / 255
        for c in 0..<4 { out.px[i + c] = UInt8((Double(out.px[i + c]) * a).rounded()) }
    }
    return out
}
/// Overlay Image at a custom position, at the overlay's own size.
func overlay(_ base: inout Bitmap, _ img: Bitmap, _ x: Int, _ y: Int) {
    for yy in 0..<img.h {
        let by = y + yy
        guard by >= 0 && by < base.h else { continue }
        for xx in 0..<img.w {
            let bx = x + xx
            guard bx >= 0 && bx < base.w else { continue }
            let s = (yy * img.w + xx) * 4, d = (by * base.w + bx) * 4
            let a = Double(img.px[s + 3]) / 255
            guard a > 0 else { continue }
            for c in 0..<4 { base.px[d + c] = UInt8(min(Double(img.px[s + c]) + Double(base.px[d + c]) * (1 - a), 255).rounded()) }
        }
    }
}
/// Overlay Text: lines from a top-left origin at the face's pitch; `align` places them in a box of `width`.
func overlayText(_ base: inout Bitmap, _ s: String, _ face: Face, _ color: NSColor, x: Double, y: Double,
                 width: Double = 0, align: NSTextAlignment = .left) {
    let font = NSFont(name: face.font, size: face.size)!
    base.draw(flipped: true) { ctx in
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(cgContext: ctx, flipped: true)
        let p = NSMutableParagraphStyle(); p.alignment = align
        for (i, line) in s.components(separatedBy: "\n").enumerated() {
            NSAttributedString(string: line, attributes: [.font: font, .foregroundColor: color, .paragraphStyle: p])
                .draw(with: NSRect(x: x, y: y + Double(i) * face.pitch, width: width > 0 ? width : 100_000, height: 1000),
                      options: [.usesLineFragmentOrigin, .usesFontLeading])
        }
        NSGraphicsContext.restoreGraphicsState()
    }
}
/// Combine Images, vertically, no spacing.
func combine(_ rows: [Bitmap]) -> Bitmap {
    var out = Bitmap(W, rows.reduce(0) { $0 + $1.h })
    var y = 0
    for r in rows { overlay(&out, r, 0, y); y += r.h }
    return out
}

// MARK: - Text measurement (each character becomes its width in marks; the renderer counts them per line)

let unit = 0.01, kern = 0.992, wideUnits = 100, otherUnits = 60
let mark = "\u{E000}"   // private use: no class, emoji pattern or real message contains it
let widePattern = "\\p{Extended_Pictographic}\\x{FE0F}?|[\\p{Han}\\p{Hiragana}\\p{Katakana}\\p{Hangul}]"
let widthClasses: [(units: Int, chars: String)] = {
    let f = NSFont(name: t.type.body.font, size: 1000)!
    var chars: [String] = (32...126).map { String(UnicodeScalar($0)!) }
    chars += ["‘", "’", "“", "”", "—", "–", "…", "•", "é", "è", "á", "à", "ç", "ñ", "ü", "ö", "ä", "°", "·", "×"]
    var groups: [Int: String] = [:]
    for c in chars { groups[Int((Double(NSAttributedString(string: c, attributes: [.font: f]).size().width) / 1000 / unit).rounded()), default: ""] += c }
    return groups.keys.sorted().map { ($0, groups[$0]!) }
}()
func classPattern(_ chars: String) -> String {
    "[" + chars.map { c in c.isASCII && !(c.isLetter || c.isNumber || c == " ") ? "\\" + String(c) : String(c) }.joined() + "]"
}
/// Width of each line in marks (1/100 em of Helvetica Neue Regular), the renderer's way.
func lineUnits(_ text: String) -> [Int] {
    var s = text.replacingOccurrences(of: widePattern, with: String(repeating: mark, count: wideUnits), options: .regularExpression)
    for c in widthClasses {
        s = s.replacingOccurrences(of: classPattern(c.chars), with: String(repeating: mark, count: c.units), options: .regularExpression)
    }
    s = s.replacingOccurrences(of: "[^\(mark)\\n]", with: String(repeating: mark, count: otherUnits), options: .regularExpression)
    return s.components(separatedBy: "\n").map { $0.count }
}
/// Helvetica Neue Medium runs this much wider than Regular on the words set in it.
let mediumScale: Double = {
    let reg = NSFont(name: "HelveticaNeue", size: 100)!, med = NSFont(name: t.type.day.font, size: 100)!
    let words = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday", "Delivered", "Read"]
    let w = { (s: String, f: NSFont) in Double(NSAttributedString(string: s, attributes: [.font: f]).size().width) }
    return words.map { w($0, med) / w($0, reg) }.reduce(0, +) / Double(words.count)
}()
let smallSpace = Double(NSAttributedString(string: " ", attributes: [.font: NSFont(name: t.type.time.font, size: t.type.time.size)!]).size().width)
func smallWidth(_ s: String) -> Double { Double(lineUnits(s)[0]) * unit * t.type.time.size * kern }

// MARK: - Wrapping (the renderer's: last space within `chars`, long words cut, widow re-wrap, line cap)

func wrapLines(_ s: String, _ chars: Int) -> [String] {
    let re = try! NSRegularExpression(pattern: "([^\\n]{1,\(chars)})(?:[ \\t]*(?:\\n|$)|[ \\t]+)|(\\S{\(chars)})")
    var out = re.stringByReplacingMatches(in: s, range: NSRange(s.startIndex..., in: s), withTemplate: "$1$2\n")
    while out.hasSuffix("\n") { out.removeLast() }
    return out.components(separatedBy: "\n")
}
func wrap(_ s: String, chars: Int) -> [String] {
    var lines = wrapLines(s, chars)
    if lines.count > 1 && lines.last!.count < t.bubble.widowChars {
        let narrower = wrapLines(s, chars - t.bubble.widowStep)
        if narrower.count <= lines.count { lines = narrower }
    }
    let cap = t.bubble.maxLines
    if lines.count > cap {
        lines = Array(lines.prefix(cap))
        lines[cap - 1] = lines[cap - 1].replacingOccurrences(of: "[\\s,.;:—-]+$", with: "", options: .regularExpression) + "…"
    }
    return lines
}

// MARK: - Assets

try? FileManager.default.createDirectory(atPath: outDir, withIntermediateDirectories: true)
let wall = makeWall(t.plate)
/// The same wall at other hours (the renderer picks by the time): each graded to the same contrast limits.
let hourWalls: [(String, Bitmap)] = t.walls.keys.sorted().compactMap { name in
    FileManager.default.fileExists(atPath: "\(root)/\(t.walls[name]!.source)") ? ("wall-\(name).png", makeWall(t.walls[name]!)) : nil
}
let veil = solid(W, 1000, "FFFFFF", t.color.veil), blue = solid(W, 1000, t.color.blue, 1), blank = Bitmap(W, 1500)
let tailLeft = tailPiece(right: false, hex: "FFFFFF", alpha: t.color.veil), tailRight = tailPiece(right: true, hex: t.color.blue, alpha: 1)
let side = t.bubble.side, padX = t.bubble.padX, padTop = t.bubble.padTop, padBottom = t.bubble.padBottom
let tailRoom = t.bubble.tailRoom
func bubbleHeight(_ lines: Int) -> Double { (Double(lines) * t.type.body.pitch).rounded(.up) + padTop + padBottom }
let typingH = bubbleHeight(1), typingBelow = 32.0

/// The typing bubble as a ready row: gap above, the capsule with its two trailing circles (kept inside the column,
/// the small one on the tail-tip line), and the dots caught mid-pulse.
func typingRow(gapTop: Double) -> Bitmap {
    let x = side, y = gapTop, w = t.typing.width
    let glass = fade(drawing(W, Int(gapTop + typingH + typingBelow)) { ctx in
        ctx.setFillColor(.white)   // drawn opaque, then made translucent as one shape so overlaps never double up
        ctx.addPath(CGPath(roundedRect: CGRect(x: x, y: y, width: w, height: typingH), cornerWidth: typingH / 2, cornerHeight: typingH / 2, transform: nil))
        ctx.fillPath()
        ctx.fillEllipse(in: CGRect(x: x - 4, y: y + typingH - 24, width: 34, height: 34))
        ctx.fillEllipse(in: CGRect(x: side - tip, y: y + typingH + 14, width: 16, height: 16))
    }, t.color.veil)
    var row = glass
    row.draw(flipped: true) { ctx in
        for (k, hex) in t.color.dots.enumerated() {
            ctx.setFillColor(nsColor(hex).cgColor)
            ctx.fillEllipse(in: CGRect(x: x + t.typing.dotInset + Double(k) * t.typing.dotPitch, y: y + typingH / 2 - t.typing.dot / 2,
                                       width: t.typing.dot, height: t.typing.dot))
        }
    }
    return row
}
let typingTurn = typingRow(gapTop: t.bubble.turnGap - tailRoom), typingSame = typingRow(gapTop: t.bubble.sameGap - tailRoom)

/// Fades the stacked rows under the clock. Row r of the mask is screen y = r - 1000, so the renderer can crop it at
/// any column position, even one that starts above the screen.
let fadeMask: Bitmap = {
    var b = Bitmap(W, H + 1000)
    for r in 0..<b.h {
        let a = smootherstep((Double(r - 1000) - t.zones.fadeOpaque) / (t.zones.fadeClear - t.zones.fadeOpaque))
        let v = UInt8((a * 255).rounded())
        for x in 0..<W { let i = (r * W + x) * 4; b.px[i] = v; b.px[i + 1] = v; b.px[i + 2] = v; b.px[i + 3] = v }
    }
    return b
}()

/// The monogram circle iOS uses for contacts without a photo (initials are drawn on it at runtime).
let avatar: Bitmap = {
    let d = Int(t.empty.avatar)
    return drawing(d, d) { ctx in
        ctx.addEllipse(in: CGRect(x: 0, y: 0, width: d, height: d)); ctx.clip()
        let g = CGGradient(colorsSpace: srgb, colors: [nsColor(t.color.avatarTop).cgColor, nsColor(t.color.avatarBottom).cgColor] as CFArray, locations: [0, 1])!
        ctx.drawLinearGradient(g, start: CGPoint(x: 0, y: 0), end: CGPoint(x: 0, y: d), options: [])
    }
}()

/// A voice note's glyphs, drawn over its bubble: the play triangle and a waveform (the same shape every time).
let lineH = bubbleHeight(1)
func audioGlyphs(_ hex: String, _ alpha: Double) -> Bitmap {
    let a = t.audio
    var rng = Random(state: a.seed)
    return drawing(Int(a.width), Int(lineH)) { ctx in
        ctx.setFillColor(nsColor(hex, alpha).cgColor)
        let cy = lineH / 2, ph = a.play, pw = a.play * 0.87
        let tri = CGMutablePath()
        tri.move(to: CGPoint(x: a.playX, y: cy - ph / 2)); tri.addLine(to: CGPoint(x: a.playX + pw, y: cy))
        tri.addLine(to: CGPoint(x: a.playX, y: cy + ph / 2)); tri.closeSubpath()
        ctx.addPath(tri); ctx.setLineJoin(.round); ctx.setLineWidth(5); ctx.setStrokeColor(nsColor(hex, alpha).cgColor)
        ctx.drawPath(using: .fillStroke)
        for k in 0..<a.bars {
            let u = Double(k) / Double(a.bars - 1)
            let envelope = 0.45 + 0.55 * sin(.pi * min(max(u * 1.1 - 0.05, 0), 1))
            let h = (a.barMin + (a.barMax - a.barMin) * envelope * (0.35 + 0.65 * rng.next())).rounded()
            let x = a.barsX + Double(k) * (a.barW + a.barGap)
            ctx.addPath(CGPath(roundedRect: CGRect(x: x, y: cy - h / 2, width: a.barW, height: h),
                               cornerWidth: a.barW / 2, cornerHeight: a.barW / 2, transform: nil))
            ctx.fillPath()
        }
    }
}
let audioMe = audioGlyphs(t.color.sentInk, 0.92), audioThem = audioGlyphs(t.color.ink, 0.82)

/// Tapback badges: a circle and one small trailing dot, toward the middle of the screen. "them" (grey) sits on the
/// top-left of your bubbles; "me" (blue) on the top-right of theirs. Where a badge overlaps its bubble the renderer
/// cuts a ring out of the bubble (tapback-hole.png), so the wall shows between them as the chat background does in
/// Messages, instead of a drawn outline.
let tb = t.tapback
let badgeR = tb.size / 2, outerR = badgeR + tb.ring, dotR = tb.dot / 2
let badgeBox = Int((outerR * 2 + dotR * 2 + tb.ring * 2 + 8).rounded(.up))
func tapbackBadge(fill: String, dotLeft: Bool) -> (Bitmap, Double, Double) {
    let cx = dotLeft ? Double(badgeBox) - outerR - 2 : outerR + 2, cy = outerR + 2
    let angle = (dotLeft ? 125.0 : 55.0) * .pi / 180   // below the badge, toward the bubble's outer edge
    let dist = badgeR + dotR + 4
    let dx = cx + cos(angle) * dist, dy = cy + sin(angle) * dist
    let b = drawing(badgeBox, badgeBox) { ctx in
        ctx.setFillColor(nsColor(fill).cgColor)
        ctx.fillEllipse(in: CGRect(x: cx - badgeR, y: cy - badgeR, width: badgeR * 2, height: badgeR * 2))
        ctx.fillEllipse(in: CGRect(x: dx - dotR, y: dy - dotR, width: dotR * 2, height: dotR * 2))
    }
    return (b, cx, cy)
}
let (tapbackThem, themCX, themCY) = tapbackBadge(fill: tb.them, dotLeft: true)
let (tapbackMe, _, _) = tapbackBadge(fill: tb.me, dotLeft: false)
/// The cutout: opaque everywhere but a disc a ring wider than the badge, centred at (W, 100). The renderer crops it
/// so the disc lands on the badge's centre in the row and masks the row with it, before laying the badge on.
let holeH = 1700
let tapbackHole = drawing(2 * W, holeH) { ctx in
    ctx.setFillColor(NSColor.white.cgColor)
    ctx.fill(CGRect(x: 0, y: 0, width: 2 * W, height: holeH))
    ctx.setBlendMode(.clear)
    ctx.fillEllipse(in: CGRect(x: Double(W) - outerR, y: 100 - outerR, width: outerR * 2, height: outerR * 2))
}
/// Overlay Text places an emoji's box from its top-left; centre the glyph on the badge from its measured box. The
/// box keeps room for descenders below the glyph, so the emoji sits a little low to look centred.
let emojiFont = NSFont(name: t.type.body.font, size: tb.emoji)!
let emojiBox = NSAttributedString(string: "👍", attributes: [.font: emojiFont]).size()
let emojiDX = -Double(emojiBox.width) / 2, emojiDY = -Double(emojiBox.height) / 2 + 3

let stampH = Int(t.stamp.above + t.type.time.pitch + t.stamp.below)
let spacers = [("gap-same.png", Bitmap(W, Int(t.bubble.sameGap - t.bubble.tailRoom))),
               ("gap-turn.png", Bitmap(W, Int(t.bubble.turnGap - t.bubble.tailRoom))),
               ("receipt-canvas.png", Bitmap(W, Int(t.receipt.gap + t.receipt.height))), ("stamp-canvas.png", Bitmap(W, stampH))]
for (name, b) in [("wall.png", wall), ("veil.png", veil), ("blue.png", blue), ("clear.png", blank), ("tail-left.png", tailLeft),
                  ("tail-right.png", tailRight), ("typing-turn.png", typingTurn), ("typing-same.png", typingSame),
                  ("fade-mask.png", fadeMask), ("avatar.png", avatar), ("audio-me.png", audioMe), ("audio-them.png", audioThem),
                  ("tapback-them.png", tapbackThem), ("tapback-me.png", tapbackMe), ("tapback-hole.png", tapbackHole)]
                  + spacers + hourWalls {
    b.write(name)
}

let manifest: [String: Any] = [
    "widthClasses": widthClasses.map { ["units": $0.units, "pattern": classPattern($0.chars)] },
    "widePattern": widePattern, "wideUnits": wideUnits, "otherUnits": otherUnits, "mark": mark,
    "pxPerUnit": unit * t.type.body.size * kern, "smallPxPerUnit": unit * t.type.time.size * kern,
    "mediumScale": mediumScale, "smallSpace": smallSpace,
    // Overlay Text ignores alignment, so the renderer places right-aligned and centred text from these widths.
    "readW": Double(NSAttributedString(string: "Read", attributes: [.font: NSFont(name: t.type.day.font, size: t.type.day.size)!]).size().width),
    "deliveredW": Double(NSAttributedString(string: "Delivered", attributes: [.font: NSFont(name: t.type.day.font, size: t.type.day.size)!]).size().width),
    "monoPxPerUnit": unit * t.type.monogram.size * kern * mediumScale, "namePxPerUnit": unit * t.type.name.size * kern * mediumScale,
    "hintPxPerUnit": unit * t.type.hint.size * kern,
    "tailBox": ["w": tailBox.w, "h": tailBox.h, "inset": tailBox.inset],
    "typing": ["turnHeight": typingTurn.h, "sameHeight": typingSame.h, "bubbleHeight": typingH, "below": typingBelow],
    // An emoji's width: one wide character (100 marks) at the jumbo size.
    "jumboPxPerEmoji": Double(wideUnits) * unit * t.jumbo.size * kern,
    // The badge image, the badge centre inside it (for the grey one; the blue one is its mirror), and the emoji's box.
    "tapback": ["w": badgeBox, "h": badgeBox, "anchorX": themCX, "anchorY": themCY, "emojiDX": emojiDX, "emojiDY": emojiDY],
]
try! JSONSerialization.data(withJSONObject: manifest, options: [.prettyPrinted, .sortedKeys]).write(to: URL(fileURLWithPath: "\(outDir)/manifest.json"))

// MARK: - The renderer, reproduced: rows are drawn when a message arrives; a redraw stacks them

let ink = nsColor(t.color.ink), sentInk = nsColor(t.color.sentInk), stampInk = nsColor(t.color.stamp)

struct Record {
    let me: Bool; let time: String
    var rowH = 0.0, bx = 0.0, by = 0.0, bw = 0.0, bh = 0.0
    var withText = Bitmap(1, 1)
}

func addTail(_ row: inout Bitmap, _ r: Record) {
    let (x, y) = tailOrigin(x: r.bx, y: r.by, w: r.bw, h: r.bh, right: r.me)
    overlay(&row, r.me ? tailRight : tailLeft, x, y)
}

/// What the renderer does when a message arrives: wrap and measure it, draw its row (stamp, bubble, text) in two
/// versions, and give the previous message its tail if this one starts a new run.
func append(_ log: inout [Record], me: Bool, day: String, time: String, minutes: Int, minutesBefore: Int?, text: String) {
    for (i, para) in text.components(separatedBy: "\n\n").filter({ !$0.isEmpty }).enumerated() {
        var r = Record(me: me, time: time)
        var lines = wrap(para, chars: t.bubble.chars)
        var widest = Double(lineUnits(lines.joined(separator: "\n")).max()!) * unit * t.type.body.size * kern
        if widest > t.bubble.maxText {   // rare: wide letters filled the lines; wrap narrower once
            lines = wrap(para, chars: Int(Double(t.bubble.chars) * t.bubble.maxText / widest))
            widest = Double(lineUnits(lines.joined(separator: "\n")).max()!) * unit * t.type.body.size * kern
        }
        let first = log.isEmpty
        let stamp = i == 0 && (minutesBefore.map { minutes - $0 >= t.stamp.gapMinutes } ?? true)
        let gapTop = first ? 0 : (log.last!.me == me ? t.bubble.sameGap : t.bubble.turnGap) - tailRoom
        let stampBlock = stamp ? (first ? 0 : t.stamp.above) + t.type.time.pitch + t.stamp.below : 0
        r.bw = widest.rounded(.up) + 2 * padX
        r.bh = bubbleHeight(lines.count)
        r.bx = me ? Double(W) - side - r.bw : side
        r.by = gapTop + stampBlock
        r.rowH = r.by + r.bh + tailRoom
        var row = crop(blank, 0, 0, W, Int(r.rowH))
        overlay(&row, maskRounded(crop(me ? blue : veil, 0, 0, Int(r.bw), Int(r.bh)), radius: radius), Int(r.bx), Int(r.by))
        if stamp {
            let dayW = smallWidth(day) * mediumScale, timeW = smallWidth(time)
            let dayX = ((Double(W) - dayW - smallSpace - timeW) / 2).rounded()
            let y = gapTop + (first ? 0 : t.stamp.above)
            overlayText(&row, day, t.type.day, stampInk, x: dayX, y: y)
            overlayText(&row, time, t.type.time, stampInk, x: dayX + dayW + smallSpace, y: y)
        }
        overlayText(&row, lines.joined(separator: "\n"), t.type.body, me ? sentInk : ink, x: r.bx + padX, y: r.by + padTop)
        r.withText = row
        if let prev = log.indices.last, log[prev].me != me { addTail(&log[prev].withText, log[prev]) }
        log.append(r)
    }
}

/// A redraw: from the newest message back until the stack reaches the fade, add the newest tail, the receipt and
/// the typing row, stack, fade into the wall under the clock, lay it on the wall.
var report: [(String, Double)] = []
func redraw(_ log: [Record], thinking: Bool, name: String = "Hermes") -> Bitmap {
    var img = wall
    if log.isEmpty {
        var row = crop(blank, 0, 0, W, 400)
        let ad = t.empty.avatar, ax = ((Double(W) - ad) / 2).rounded(), ay = t.empty.top
        overlay(&row, avatar, Int(ax), Int(ay))
        let initials = name.split(separator: " ").compactMap(\.first).map(String.init)
        let mono = (initials.count > 1 ? initials.first! + initials.last! : initials.first ?? "").uppercased()
        overlayText(&row, mono, t.type.monogram, .white, x: ax, y: ay + ((ad - t.type.monogram.pitch) / 2).rounded() + 2, width: ad, align: .center)
        overlayText(&row, name, t.type.name, ink, x: 0, y: ay + ad + t.empty.nameGap, width: Double(W), align: .center)
        overlayText(&row, "Hold the Action button to talk.", t.type.hint, stampInk, x: 0, y: ay + ad + t.empty.hintGap, width: Double(W), align: .center)
        overlay(&img, row, 0, Int(t.zones.chatTop))
        return img
    }
    let newest = log.last!
    var extras: [Bitmap] = []
    var below = tailRoom   // how far the stack hangs below the line the newest bubble (or typing bubble) sits on
    if newest.me {
        // Messages' receipt under your newest message: "Delivered", then "Read <time>" once the agent is on it.
        var receipt = crop(blank, 0, 0, W, Int(t.receipt.gap + t.receipt.height))
        let time = thinking ? newest.time : ""
        let right = Double(W) - side
        if thinking { overlayText(&receipt, time, t.type.time, stampInk, x: 0, y: t.receipt.gap, width: right, align: .right) }
        overlayText(&receipt, thinking ? "Read" : "Delivered", t.type.day, stampInk, x: 0, y: t.receipt.gap,
                    width: right - (thinking ? smallWidth(time) + smallSpace : 0), align: .right)
        extras.append(receipt)
        below += Double(receipt.h)
    }
    if thinking { extras.append(newest.me ? typingTurn : typingSame); below = typingBelow }
    var total = Double(extras.reduce(0) { $0 + $1.h }), k = 0
    for r in log.reversed() {
        total += r.rowH; k += 1
        if total - below >= t.zones.chatBottom - t.zones.fadeOpaque { break }
    }
    let overflow = total - below > t.zones.chatBottom - t.zones.chatTop
    let colY = overflow ? t.zones.chatBottom - (total - below) : t.zones.chatTop
    var rows: [Bitmap] = [], y = colY
    for (j, r) in log.suffix(k).enumerated() {
        let center = y + r.by + r.bh / 2
        var row = r.withText   // one fade for bubbles and words alike
        if j == k - 1 && !(thinking && !r.me) { addTail(&row, r) }
        if center >= t.zones.textCut && y + r.by > t.zones.fadeClear {
            let fill = r.me ? luminance(t.color.blue) : (1 - t.color.veil) * wall.maxLuminance(CGRect(x: r.bx, y: y + r.by, width: r.bw, height: r.bh)) + t.color.veil
            report.append(("\(r.me ? "sent" : "received") text at y \(Int(y + r.by))", contrast(luminance(r.me ? t.color.sentInk : t.color.ink), fill)))
        }
        rows.append(row); y += Double(row.h)
    }
    rows += extras
    var column = combine(rows)
    if overflow { column = maskCustom(column, crop(fadeMask, 0, Int(colY) + 1000, W, column.h)) }
    overlay(&img, column, 0, Int(colY))
    return img
}

// MARK: - Previews

func lockScreenChrome(_ img: inout Bitmap) {
    img.draw(flipped: true) { ctx in
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(cgContext: ctx, flipped: true)
        let white = NSColor.white
        func label(_ s: String, _ f: NSFont, _ c: NSColor, _ y: CGFloat, x: CGFloat = 0, center: Bool = true) {
            let p = NSMutableParagraphStyle(); p.alignment = center ? .center : .left
            NSAttributedString(string: s, attributes: [.font: f, .foregroundColor: c, .paragraphStyle: p])
                .draw(with: NSRect(x: x, y: y, width: center ? CGFloat(W) : 2000, height: 1000), options: [.usesLineFragmentOrigin, .usesFontLeading])
        }
        for (x, w) in [(894.0, 64.0), (968.0, 50.0), (1036.0, 76.0)] {
            white.withAlphaComponent(0.85).setFill()
            NSBezierPath(roundedRect: NSRect(x: x, y: 86, width: w, height: 32), xRadius: 9, yRadius: 9).fill()
        }
        NSColor.black.setFill(); NSBezierPath(roundedRect: NSRect(x: 456, y: 33, width: 294, height: 108), xRadius: 54, yRadius: 54).fill()
        label("Wednesday, October 28", .systemFont(ofSize: 57, weight: .semibold), white.withAlphaComponent(0.92), 248)
        label("11:24", .systemFont(ofSize: 372, weight: .heavy), white.withAlphaComponent(0.26), 262)   // iOS 26 glass clock, roughly
        for cx in [224.0, 981.0] {
            let c = NSBezierPath(ovalIn: NSRect(x: cx - 86, y: 2297, width: 172, height: 172))
            white.withAlphaComponent(0.1).setFill(); c.fill()
            white.withAlphaComponent(0.16).setStroke(); c.lineWidth = 2; c.stroke()
        }
        white.setFill(); NSBezierPath(roundedRect: NSRect(x: 386, y: 2583, width: 434, height: 14), xRadius: 7, yRadius: 7).fill()
        NSGraphicsContext.restoreGraphicsState()
    }
}

func minutes(_ time: String) -> Int {
    let p = time.split(whereSeparator: { $0 == ":" || $0 == " " })
    return (Int(p[0])! % 12 + (p[2] == "PM" ? 12 : 0)) * 60 + Int(p[1])!
}
func conversation(_ items: [(Bool, String, String)]) -> [Record] {
    var log: [Record] = [], last: Int? = nil
    for (me, time, text) in items {
        append(&log, me: me, day: "Wednesday", time: time, minutes: minutes(time), minutesBefore: last, text: text)
        last = minutes(time)
    }
    return log
}
let historyItems: [(Bool, String, String)] = [
    (true, "9:02 PM", "remind me to call the dentist tomorrow morning"),
    (false, "9:02 PM", "Done — I’ll remind you at 9:00 AM tomorrow to call Dr. Lee’s office."),
    (true, "10:14 PM", "what’s on my calendar tomorrow"),
    (false, "10:14 PM", "Three things: standup at 10:00, lunch with Maya at 12:30, and the design review at 3:00. Your afternoon is otherwise clear."),
    (true, "11:20 PM", "yo Hermes, can you check whether my flight tomorrow is still on time and text me the gate"),
    (false, "11:20 PM", "Checking United now…"),
    (false, "11:21 PM", "UA 1149 is on time. Departs 8:05 AM from gate C4, boarding at 7:25.\n\nTraffic to SFO looks light, so leaving by 6:45 gives you a comfortable buffer. Want me to set a 6:30 alarm?"),
]
let states: [(String, [Record], Bool)] = [
    ("full", conversation(historyItems), false),
    ("thinking", conversation(historyItems + [(true, "11:24 PM", "yes set the alarm and also remind me to pack my charger")]), true),
    ("short", conversation([(true, "11:20 PM", "Yo, Hermes, what’s good? Can you hear me?"),
                           (false, "11:20 PM", "Yooo 😎 Yep—your voice message came through clearly!")]), false),
    ("empty", [], false),
]
var shots: [Bitmap] = []
for (name, log, thinking) in states {
    var img = redraw(log, thinking: thinking)
    img.write("raw-\(name).png")
    lockScreenChrome(&img)
    img.write("preview-\(name).png")
    shots.append(img)
}
let sheet: Bitmap = {
    let sw = 402, sh = 874, gapPx = 32
    var s = Bitmap(sw * 4 + gapPx * 5, sh + gapPx * 2)
    for i in stride(from: 0, to: s.px.count, by: 4) { s.px[i] = 17; s.px[i + 1] = 17; s.px[i + 2] = 19; s.px[i + 3] = 255 }
    for (i, shot) in shots.enumerated() {
        let small = Bitmap(render(shot.ci.applyingFilter("CILanczosScaleTransform", parameters: [kCIInputScaleKey: Double(sw) / Double(W), kCIInputAspectRatioKey: 1])))
        overlay(&s, crop(small, 0, H - sh, sw, sh), gapPx + i * (sw + gapPx), gapPx)
    }
    return s
}()
sheet.write("preview.png")

// MARK: - Checks

// Worst cases over everywhere text can sit in the chat, not just where the sample conversation put it, on every wall.
let chat = CGRect(x: 0, y: t.zones.fadeClear, width: Double(W), height: t.zones.chatBottom + 60 - t.zones.fadeClear)
for (name, w) in [("wall.png", wall)] + hourWalls {
    let top = w.maxLuminance(chat)
    if ProcessInfo.processInfo.environment["PROFILE"] != nil {   // brightest pixel per 100 px band, to tune dims
        let bands = (stride(from: 600, to: 2200, by: 100).map { $0 } + stride(from: 2200, to: 2360, by: 20).map { $0 }).map { y in
            String(format: "%d:%.3f", y, w.maxLuminance(CGRect(x: 0, y: Double(y), width: Double(W), height: y >= 2200 ? 20 : 100))) }
        print(name, bands.joined(separator: " "))
    }
    print(String(format: "%@: timestamps %.2f:1, the agent's text %.2f:1", name, contrast(luminance(t.color.stamp), top),
                 contrast(luminance(t.color.ink), (1 - t.color.veil) * top + t.color.veil)))
    for (what, r) in [("status icons", CGRect(x: 850, y: 60, width: 300, height: 80)), ("date", CGRect(x: 300, y: 245, width: 606, height: 75)),
                      ("clock", CGRect(x: 60, y: 300, width: 1086, height: 316))] {
        print(String(format: "  white over the %@: %.2f:1 at the brightest pixel", what, contrast(1, w.maxLuminance(r))))
    }
}
print(String(format: "your text on the blue: %.2f:1", contrast(luminance(t.color.sentInk), luminance(t.color.blue))))
for (what, ratio) in report where ratio < 4.5 { print(String(format: "LOW CONTRAST %.2f:1  %@", ratio, what)) }
print("wrote assets to \(outDir)")
