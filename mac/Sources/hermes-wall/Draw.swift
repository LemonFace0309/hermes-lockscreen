// Draws the Lock Screen from chat.json: the same design the Shortcuts renderer draws (design/tokens.json), laid out
// with real text measurement. Positions are in pixels with y running down from the top of the screen.
import AppKit
import ChatModel
import ImageIO
import UniformTypeIdentifiers

struct Face: Decodable { let font: String; let size: Double; let pitch: Double }
struct Tokens: Decodable {
    struct Canvas: Decodable { let width: Int; let height: Int }
    struct Zones: Decodable { let chatTop, chatBottom, fadeOpaque, fadeClear, textCut: Double }
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
    struct Audio: Decodable {
        let width, play, playX, barW, barGap, barsX, barMin, barMax: Double; let bars: Int; let seed: UInt32
    }
    let canvas: Canvas; let zones: Zones; let type: Faces; let color: Colors; let bubble: Bubble; let stamp: Stamp
    let receipt: Receipt; let typing: Typing; let empty: Empty; let tapback: Tapback; let jumbo: Jumbo; let audio: Audio
    let hours: [String: Int]
}

let srgb = CGColorSpace(name: CGColorSpace.sRGB)!

func color(_ hex: String, _ alpha: Double = 1) -> NSColor {
    let v = UInt32(hex, radix: 16)!
    return NSColor(srgbRed: Double((v >> 16) & 0xff) / 255, green: Double((v >> 8) & 0xff) / 255,
                   blue: Double(v & 0xff) / 255, alpha: alpha)
}
func smootherstep(_ u: Double) -> Double { let u = min(max(u, 0), 1); return u * u * u * (u * (u * 6 - 15) + 10) }

/// A transparent RGBA canvas whose y runs down from the top, for shapes, text and images alike.
final class Canvas {
    let w: Int, h: Int
    let ctx: CGContext
    init(_ w: Int, _ h: Int) {
        self.w = max(w, 1); self.h = max(h, 1)
        ctx = CGContext(data: nil, width: self.w, height: self.h, bitsPerComponent: 8, bytesPerRow: 0, space: srgb,
                        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
        ctx.translateBy(x: 0, y: CGFloat(self.h))
        ctx.scaleBy(x: 1, y: -1)
    }
    var image: CGImage { ctx.makeImage()! }
    /// Draws an image upright at `rect`.
    func draw(_ image: CGImage, _ rect: CGRect) {
        ctx.saveGState()
        ctx.translateBy(x: rect.minX, y: rect.maxY)
        ctx.scaleBy(x: 1, y: -1)
        ctx.draw(image, in: CGRect(x: 0, y: 0, width: rect.width, height: rect.height))
        ctx.restoreGState()
    }
    /// Text from its top-left, one line at a time at `pitch` (as Overlay Text places it).
    func text(_ lines: [String], _ font: NSFont, _ ink: NSColor, x: Double, y: Double, pitch: Double,
              width: Double = 100_000, align: NSTextAlignment = .left) {
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(cgContext: ctx, flipped: true)
        let p = NSMutableParagraphStyle(); p.alignment = align
        for (i, line) in lines.enumerated() {
            NSAttributedString(string: line, attributes: [.font: font, .foregroundColor: ink, .paragraphStyle: p])
                .draw(with: NSRect(x: x, y: y + Double(i) * pitch, width: width, height: 1000),
                      options: [.usesLineFragmentOrigin, .usesFontLeading])
        }
        NSGraphicsContext.restoreGraphicsState()
    }
}

/// What Messages shows for a message, cleaned the way the Shortcuts renderer cleans it.
let cleanups: [(String, String)] = [
    (#"\r\n?"#, "\n"), (#"\*\*|__|`"#, ""), (#"(?m)^#{1,6}[ \t]+"#, ""), (#"(?m)^[ \t]*[-*][ \t]+"#, "• "),
    (#"\n{3,}"#, "\n\n"), (#"\.\.\."#, "…"), (#"(^|[\s(\[{])""#, "$1“"), (#"""#, "”"), (#"(^|[\s(\[{])'"#, "$1‘"),
    (#"'"#, "’"),
]
func cleaned(_ s: String) -> String {
    cleanups.reduce(s) { $0.replacingOccurrences(of: $1.0, with: $1.1, options: .regularExpression) }
}
let emojiPattern = #"\p{Extended_Pictographic}(?:\x{FE0F}|\x{200D}\p{Extended_Pictographic}\x{FE0F}?|[\x{1F3FB}-\x{1F3FF}])*"#
/// A voice note's name as Talk to Hermes and Messages both know it: no file extension, and the narrow no-break
/// space iOS puts before AM/PM (or any other run of spaces) as one plain space.
func voiceKey(_ name: String) -> String {
    name.replacingOccurrences(of: #"\.(?:m4a|caf|aac|amr|mp3|wav|opus)$"#, with: "", options: [.regularExpression, .caseInsensitive])
        .replacingOccurrences(of: #"\s+"#, with: " ", options: .regularExpression)
        .trimmingCharacters(in: .whitespaces)
}
/// Hermes's progress lines ("⏳ Working…", "💻 `ls`..."): it is still at work after one.
let statusPattern = #"^(?:⏳|⚡|⏩)|^[^\p{L}\p{N}\s]{1,4}\s[^\n]{0,120}(?:\.\.\.|…)$"#

final class Painter {
    let t: Tokens
    let W: Int, H: Int
    let walls: [String: CGImage]
    let body, jumbo, dayFont, timeFont, monogram, nameFont, hint, emoji: NSFont
    let ink, sentInk, stampInk: NSColor
    let lineH: Double
    let audioMe: CGImage, audioThem: CGImage
    let fadeMask: CGImage

    init(tokens: URL, assets: URL) throws {
        t = try JSONDecoder().decode(Tokens.self, from: Data(contentsOf: tokens))
        W = t.canvas.width; H = t.canvas.height
        var walls: [String: CGImage] = [:]
        for (name, file) in [("night", "wall.png"), ("dawn", "wall-dawn.png"), ("day", "wall-day.png"), ("dusk", "wall-dusk.png")] {
            let url = assets.appendingPathComponent(file)
            if let src = CGImageSourceCreateWithURL(url as CFURL, nil), let img = CGImageSourceCreateImageAtIndex(src, 0, nil) {
                walls[name] = img
            }
        }
        guard walls["night"] != nil else { throw NSError(domain: "HermesWall", code: 1, userInfo: [NSLocalizedDescriptionKey: "no wall.png in \(assets.path)"]) }
        self.walls = walls
        func font(_ f: Face) -> NSFont { NSFont(name: f.font, size: f.size)! }
        body = font(t.type.body); dayFont = font(t.type.day); timeFont = font(t.type.time)
        monogram = font(t.type.monogram); nameFont = font(t.type.name); hint = font(t.type.hint)
        jumbo = NSFont(name: t.type.body.font, size: t.jumbo.size)!
        emoji = NSFont(name: t.type.body.font, size: t.tapback.emoji)!
        ink = color(t.color.ink); sentInk = color(t.color.sentInk); stampInk = color(t.color.stamp)
        lineH = (t.type.body.pitch).rounded(.up) + t.bubble.padTop + t.bubble.padBottom
        audioMe = Painter.audioGlyphs(t, lineH, color(t.color.sentInk, 0.92))
        audioThem = Painter.audioGlyphs(t, lineH, color(t.color.ink, 0.82))
        // Screen-space alpha that fades the column into the wall under the clock (grey: white keeps, black hides).
        let mask = CGContext(data: nil, width: W, height: H, bitsPerComponent: 8, bytesPerRow: 0,
                             space: CGColorSpaceCreateDeviceGray(), bitmapInfo: CGImageAlphaInfo.none.rawValue)!
        for y in 0..<H {
            let a = smootherstep((Double(y) - t.zones.fadeOpaque) / (t.zones.fadeClear - t.zones.fadeOpaque))
            mask.setFillColor(gray: a, alpha: 1)
            mask.fill(CGRect(x: 0, y: H - 1 - y, width: W, height: 1))   // the context's y runs up
        }
        fadeMask = mask.makeImage()!
    }

    // MARK: Text

    func width(_ s: String, _ font: NSFont) -> Double {
        let line = CTLineCreateWithAttributedString(NSAttributedString(string: s, attributes: [.font: font]))
        return CTLineGetTypographicBounds(line, nil, nil, nil)
    }

    /// Lines as Messages would break them at `limit` px wide, paragraph by paragraph.
    func breakLines(_ text: String, _ font: NSFont, _ limit: Double) -> [String] {
        var lines: [String] = []
        for para in text.components(separatedBy: "\n") {
            guard !para.isEmpty else { lines.append(""); continue }
            let attr = NSAttributedString(string: para, attributes: [.font: font])
            let setter = CTTypesetterCreateWithAttributedString(attr)
            var start = 0
            while start < attr.length {
                let count = max(CTTypesetterSuggestLineBreak(setter, start, limit), 1)
                lines.append((para as NSString).substring(with: NSRange(location: start, length: count))
                    .trimmingCharacters(in: .whitespaces))
                start += count
            }
        }
        return lines
    }

    /// Wrapped to the bubble's width; a paragraph ending in a word or two is wrapped a little narrower when that
    /// doesn't add a line, and very long messages stop at maxLines with an ellipsis.
    func wrap(_ text: String) -> [String] {
        let b = t.bubble
        var lines: [String] = []
        for para in text.components(separatedBy: "\n") {
            var best = breakLines(para, body, b.maxText)
            if best.count > 1, best.last!.count < b.widowChars {
                var limit = b.maxText
                for _ in 0..<4 {
                    limit -= Double(b.widowStep) * 22
                    let narrower = breakLines(para, body, limit)
                    if narrower.count > best.count { break }
                    if narrower.last!.count >= b.widowChars { best = narrower; break }
                }
            }
            lines += best
        }
        if lines.count > b.maxLines {
            lines = Array(lines.prefix(b.maxLines))
            lines[b.maxLines - 1] = lines[b.maxLines - 1].replacingOccurrences(of: #"[\s,.;:—-]+$"#, with: "",
                                                                               options: .regularExpression) + "…"
        }
        return lines
    }

    // MARK: Pieces

    static func audioGlyphs(_ t: Tokens, _ lineH: Double, _ ink: NSColor) -> CGImage {
        let a = t.audio
        let c = Canvas(Int(a.width), Int(lineH))
        var state = a.seed
        func next() -> Double {   // mulberry32, so the waveform is the same shape every time
            state &+= 0x6D2B79F5
            var z = state
            z = (z ^ (z >> 15)) &* (z | 1)
            z ^= z &+ ((z ^ (z >> 7)) &* (z | 61))
            return Double(z ^ (z >> 14)) / 4294967296
        }
        c.ctx.setFillColor(ink.cgColor); c.ctx.setStrokeColor(ink.cgColor)
        let cy = lineH / 2, ph = a.play, pw = a.play * 0.87
        let tri = CGMutablePath()
        tri.move(to: CGPoint(x: a.playX, y: cy - ph / 2)); tri.addLine(to: CGPoint(x: a.playX + pw, y: cy))
        tri.addLine(to: CGPoint(x: a.playX, y: cy + ph / 2)); tri.closeSubpath()
        c.ctx.addPath(tri); c.ctx.setLineJoin(.round); c.ctx.setLineWidth(5); c.ctx.drawPath(using: .fillStroke)
        for k in 0..<a.bars {
            let u = Double(k) / Double(a.bars - 1)
            let envelope = 0.45 + 0.55 * sin(.pi * min(max(u * 1.1 - 0.05, 0), 1))
            let h = (a.barMin + (a.barMax - a.barMin) * envelope * (0.35 + 0.65 * next())).rounded()
            c.ctx.addPath(CGPath(roundedRect: CGRect(x: a.barsX + Double(k) * (a.barW + a.barGap), y: cy - h / 2, width: a.barW, height: h),
                                 cornerWidth: a.barW / 2, cornerHeight: a.barW / 2, transform: nil))
            c.ctx.fillPath()
        }
        return c.image
    }

    /// Messages' tail at a bubble's bottom corner (edge x, bottom y).
    func tailPath(edge: Double, bottom: Double, right: Bool) -> CGPath {
        let s: Double = right ? 1 : -1, reach = t.bubble.tailReach, tip = t.bubble.tailTip
        let p = { (dx: Double, dy: Double) in CGPoint(x: edge + s * dx, y: bottom + dy) }
        let path = CGMutablePath()
        path.move(to: p(0, -reach))
        path.addLine(to: p(0, -30))
        path.addCurve(to: p(tip, 1), control1: p(0, -10), control2: p(5, -1))
        path.addCurve(to: p(-reach, 0), control1: p(3, -3.5), control2: p(-26, 0))
        path.addLine(to: p(-reach, -reach))
        path.closeSubpath()
        return path
    }

    // MARK: Rows

    struct Row {
        var me: Bool
        var kind: String              // text, audio, jumbo
        var lines: [String]
        var stamp: (day: String, time: String)?
        var gapTop = 0.0, stampY = 0.0, by = 0.0, bx = 0.0, bw = 0.0, bh = 0.0, rowH = 0.0
        var tail = false
        var reaction: Reaction?
        var at: Int64
    }

    func stampText(_ ms: Int64, now: Date) -> (String, String) {
        let date = Date(timeIntervalSince1970: Double(ms) / 1000), cal = Calendar.current
        let time = DateFormatter(); time.dateFormat = "h:mm a"
        let day: String
        if cal.isDate(date, inSameDayAs: now) { day = "Today" }
        else if let y = cal.date(byAdding: .day, value: -1, to: now), cal.isDate(date, inSameDayAs: y) { day = "Yesterday" }
        else if now.timeIntervalSince(date) < 6 * 86400 { let f = DateFormatter(); f.dateFormat = "EEEE"; day = f.string(from: date) }
        else { let f = DateFormatter(); f.dateFormat = "EEE, MMM d"; day = f.string(from: date) }
        return (day, time.string(from: date))
    }

    func label(for m: Message) -> String {
        let images = m.attachments.filter { $0.mime.hasPrefix("image/") }.count
        let videos = m.attachments.filter { $0.mime.hasPrefix("video/") }.count
        let label = images > 0 ? (images > 1 ? "📷 \(images) Photos" : "📷 Photo") :
            videos > 0 ? (videos > 1 ? "🎬 \(videos) Videos" : "🎬 Video") : "📎 Attachment"
        return m.text.isEmpty ? label : label + "\n" + m.text
    }

    func rows(_ messages: [Message], transcripts: [String: String], now: Date) -> [Row] {
        let b = t.bubble, tb = t.tapback, j = t.jumbo
        var rows: [Row] = []
        var lastAt: Int64?
        for m in messages {
            var r = Row(me: m.me, kind: m.kind == "audio" ? "audio" : "text", lines: [], at: m.at)
            var words = m.kind == "attachment" ? label(for: m) : m.text
            if m.kind == "audio" {
                words = m.attachments.compactMap { transcripts[voiceKey($0.name)] }.first ?? ""
            }
            words = cleaned(words)
            if r.kind == "text", words.range(of: "^\\s*(?:\(emojiPattern)\\s*){1,\(j.max)}$", options: .regularExpression) != nil {
                r.kind = "jumbo"
                r.lines = [words.trimmingCharacters(in: .whitespacesAndNewlines)]
            } else if !words.isEmpty {
                r.lines = wrap(words)
            }
            let first = rows.isEmpty
            if first || (lastAt.map { m.at - $0 >= Int64(t.stamp.gapMinutes) * 60_000 } ?? true) {
                r.stamp = stampText(m.at, now: now)
            }
            lastAt = m.at
            r.gapTop = first ? 0 : (rows.last!.me == m.me ? b.sameGap : b.turnGap) - b.tailRoom
            r.stampY = r.gapTop + (first ? 0 : t.stamp.above)
            let stampBlock = r.stamp == nil ? 0 : (first ? 0 : t.stamp.above) + t.type.time.pitch + t.stamp.below
            // The tapback shown: the other person's on your bubble or yours on theirs, else the newest.
            r.reaction = m.reactions.last { $0.me != m.me } ?? m.reactions.last
            let textW = r.lines.map { width($0, body) }.max() ?? 0, textH = (Double(r.lines.count) * t.type.body.pitch).rounded(.up)
            switch r.kind {
            case "jumbo":
                r.bw = width(r.lines[0], jumbo).rounded(.up)
                r.bh = j.pitch + j.padTop + j.padBottom
            case "audio":
                r.bw = max(t.audio.width, textW.rounded(.up) + 2 * b.padX)
                r.bh = r.lines.isEmpty ? lineH : textH + (lineH - 18) + b.padBottom
            default:
                r.bw = textW.rounded(.up) + 2 * b.padX
                r.bh = textH + b.padTop + b.padBottom
            }
            r.by = r.gapTop + stampBlock + (r.reaction == nil ? 0 : tb.room)
            r.bx = m.me ? Double(W) - b.side - r.bw : b.side
            r.rowH = r.by + r.bh + b.tailRoom
            if let prev = rows.indices.last, rows[prev].me != m.me, rows[prev].kind != "jumbo" { rows[prev].tail = true }
            rows.append(r)
        }
        return rows
    }

    func drawRow(_ r: Row) -> CGImage {
        let b = t.bubble, tb = t.tapback
        let c = Canvas(W, Int(r.rowH.rounded(.up)))
        if let (day, time) = r.stamp {
            let dayW = width(day, dayFont), space = width(" ", timeFont), timeW = width(time, timeFont)
            let x = ((Double(W) - dayW - space - timeW) / 2).rounded()
            c.text([day], dayFont, stampInk, x: x, y: r.stampY, pitch: t.type.day.pitch)
            c.text([time], timeFont, stampInk, x: x + dayW + space, y: r.stampY, pitch: t.type.time.pitch)
        }
        let rect = CGRect(x: r.bx, y: r.by, width: r.bw, height: r.bh)
        if r.kind == "jumbo" {
            c.text(r.lines, jumbo, ink, x: r.bx, y: r.by + t.jumbo.padTop, pitch: t.jumbo.pitch)
        } else {
            // Bubble and tail as one shape, so the translucent glass never doubles where they meet.
            let radius = min(b.radius, min(r.bw, r.bh) / 2)
            c.ctx.saveGState()
            c.ctx.setAlpha(r.me ? 1 : t.color.veil)
            c.ctx.beginTransparencyLayer(auxiliaryInfo: nil)
            c.ctx.setFillColor((r.me ? color(t.color.blue) : NSColor.white).cgColor)
            c.ctx.addPath(CGPath(roundedRect: rect, cornerWidth: radius, cornerHeight: radius, transform: nil))
            c.ctx.fillPath()
            if r.tail {   // filled on its own: as one path, its overlap with the corner would wind back to empty
                c.ctx.addPath(tailPath(edge: r.me ? rect.maxX : rect.minX, bottom: rect.maxY, right: r.me))
                c.ctx.fillPath()
            }
            c.ctx.endTransparencyLayer()
            c.ctx.restoreGState()
            let words = r.me ? sentInk : ink
            if r.kind == "audio" {
                c.draw(r.me ? audioMe : audioThem, CGRect(x: r.bx, y: r.by, width: t.audio.width, height: lineH))
                c.text(r.lines, body, words, x: r.bx + b.padX, y: r.by + lineH - 18, pitch: t.type.body.pitch)
            } else {
                c.text(r.lines, body, words, x: r.bx + b.padX, y: r.by + b.padTop, pitch: t.type.body.pitch)
            }
        }
        if let reaction = r.reaction {
            // On the bubble's top corner toward the middle: grey for theirs, blue for yours, with a ring cut out of
            // the bubble around it so the wall shows between them.
            let cx = r.me ? r.bx + tb.inset : r.bx + r.bw - tb.inset, cy = r.by + tb.drop
            let badgeR = tb.size / 2, outerR = badgeR + tb.ring, dotR = tb.dot / 2
            c.ctx.saveGState()
            c.ctx.setBlendMode(.clear)
            c.ctx.fillEllipse(in: CGRect(x: cx - outerR, y: cy - outerR, width: outerR * 2, height: outerR * 2))
            c.ctx.restoreGState()
            let fill = color(reaction.me ? tb.me : tb.them).cgColor
            let angle = (reaction.me ? 55.0 : 125.0) * .pi / 180, dist = badgeR + dotR + 4
            c.ctx.setFillColor(fill)
            c.ctx.fillEllipse(in: CGRect(x: cx - badgeR, y: cy - badgeR, width: badgeR * 2, height: badgeR * 2))
            c.ctx.fillEllipse(in: CGRect(x: cx + cos(angle) * dist - dotR, y: cy + sin(angle) * dist - dotR, width: dotR * 2, height: dotR * 2))
            let box = NSAttributedString(string: reaction.emoji, attributes: [.font: emoji]).size()
            c.text([reaction.emoji], emoji, ink, x: (cx - box.width / 2).rounded(), y: (cy - box.height / 2 + 3).rounded(),
                   pitch: t.tapback.emoji)
        }
        return c.image
    }

    func typingRow(gapTop: Double) -> CGImage {
        let b = t.bubble, x = b.side, y = gapTop, w = t.typing.width, below = 32.0
        let c = Canvas(W, Int(gapTop + lineH + below))
        c.ctx.saveGState()
        c.ctx.setAlpha(t.color.veil)
        c.ctx.beginTransparencyLayer(auxiliaryInfo: nil)
        c.ctx.setFillColor(.white)
        c.ctx.addPath(CGPath(roundedRect: CGRect(x: x, y: y, width: w, height: lineH), cornerWidth: lineH / 2, cornerHeight: lineH / 2, transform: nil))
        c.ctx.fillPath()
        c.ctx.fillEllipse(in: CGRect(x: x - 4, y: y + lineH - 24, width: 34, height: 34))
        c.ctx.fillEllipse(in: CGRect(x: b.side - b.tailTip, y: y + lineH + 14, width: 16, height: 16))
        c.ctx.endTransparencyLayer()
        c.ctx.restoreGState()
        for (k, hex) in t.color.dots.enumerated() {
            c.ctx.setFillColor(color(hex).cgColor)
            c.ctx.fillEllipse(in: CGRect(x: x + t.typing.dotInset + Double(k) * t.typing.dotPitch, y: y + lineH / 2 - t.typing.dot / 2,
                                         width: t.typing.dot, height: t.typing.dot))
        }
        return c.image
    }

    // MARK: The screen

    func wallName(_ now: Date) -> String {
        let hour = Calendar.current.component(.hour, from: now), h = t.hours
        if hour >= (h["night"] ?? 20) || hour < (h["dawn"] ?? 5) { return "night" }
        if hour < (h["day"] ?? 8) { return walls["dawn"] != nil ? "dawn" : "night" }
        if hour < (h["dusk"] ?? 17) { return walls["day"] != nil ? "day" : "night" }
        return walls["dusk"] != nil ? "dusk" : "night"
    }

    /// Hermes is at work: it reacted to your newest message (👀) and hasn't answered, or its newest is a progress
    /// line. Only for ten minutes, so a reply that never came doesn't leave the dots up.
    func thinking(_ messages: [Message], now: Date) -> Bool {
        guard let newest = messages.last else { return false }
        let recent = { (ms: Int64) in unixMillis(now) - ms < 10 * 60_000 }
        if newest.me { return newest.reactions.contains { !$0.me && recent($0.at) } }
        return recent(newest.at) && newest.text.range(of: statusPattern, options: .regularExpression) != nil
    }

    func render(_ chat: ChatExport?, transcripts: [String: String], now: Date) -> CGImage {
        let screen = Canvas(W, H)
        screen.draw(walls[wallName(now)]!, CGRect(x: 0, y: 0, width: W, height: H))
        let z = t.zones, b = t.bubble
        let messages = chat?.messages ?? []
        guard !messages.isEmpty else {
            drawEmpty(screen, name: chat?.agent ?? "Hermes")
            return screen.image
        }
        var rows = rows(messages, transcripts: transcripts, now: now)
        let think = thinking(messages, now: now)
        let newest = rows.count - 1
        rows[newest].tail = rows[newest].kind != "jumbo" && !(think && !rows[newest].me)
        var extras: [CGImage] = []
        var below = b.tailRoom
        if let last = messages.last, last.me, last.read != nil || last.delivered != nil {
            let c = Canvas(W, Int(t.receipt.gap + t.receipt.height))
            let right = Double(W) - b.side
            if let read = last.read {
                let time = stampText(read, now: now).1
                c.text([time], timeFont, stampInk, x: 0, y: t.receipt.gap, pitch: t.type.time.pitch, width: right, align: .right)
                c.text(["Read"], dayFont, stampInk, x: 0, y: t.receipt.gap, pitch: t.type.day.pitch,
                       width: right - width(time, timeFont) - width(" ", timeFont), align: .right)
            } else {
                c.text(["Delivered"], dayFont, stampInk, x: 0, y: t.receipt.gap, pitch: t.type.day.pitch, width: right, align: .right)
            }
            extras.append(c.image)
            below += Double(c.h)
        }
        if think {
            extras.append(typingRow(gapTop: (messages.last!.me ? b.turnGap : b.sameGap) - b.tailRoom))
            below = 32
        }
        var total = Double(extras.reduce(0) { $0 + $1.height }), k = 0
        for r in rows.reversed() {
            total += r.rowH.rounded(.up); k += 1
            if total - below >= z.chatBottom - z.fadeOpaque { break }
        }
        let overflow = total - below > z.chatBottom - z.chatTop
        let colY = overflow ? z.chatBottom - (total - below) : z.chatTop
        let column = Canvas(W, Int(total.rounded(.up)))
        var y = 0.0
        for r in rows.suffix(k) {
            let img = drawRow(r)
            column.draw(img, CGRect(x: 0, y: y, width: Double(img.width), height: Double(img.height)))
            y += Double(img.height)
        }
        for img in extras {
            column.draw(img, CGRect(x: 0, y: y, width: Double(img.width), height: Double(img.height)))
            y += Double(img.height)
        }
        let rect = CGRect(x: 0, y: colY, width: Double(W), height: Double(column.h))
        if overflow {
            // The mask is an image, so it's laid in the context's own (y up) space, then drawing goes on y down.
            screen.ctx.saveGState()
            screen.ctx.translateBy(x: 0, y: CGFloat(H)); screen.ctx.scaleBy(x: 1, y: -1)
            screen.ctx.clip(to: CGRect(x: 0, y: 0, width: W, height: H), mask: fadeMask)
            screen.ctx.translateBy(x: 0, y: CGFloat(H)); screen.ctx.scaleBy(x: 1, y: -1)
            screen.draw(column.image, rect)
            screen.ctx.restoreGState()
        } else {
            screen.draw(column.image, rect)
        }
        return screen.image
    }

    func drawEmpty(_ screen: Canvas, name: String) {
        let e = t.empty, ad = e.avatar, ax = ((Double(W) - ad) / 2).rounded(), ay = t.zones.chatTop + e.top
        screen.ctx.saveGState()
        screen.ctx.addEllipse(in: CGRect(x: ax, y: ay, width: ad, height: ad)); screen.ctx.clip()
        let g = CGGradient(colorsSpace: srgb, colors: [color(t.color.avatarTop).cgColor, color(t.color.avatarBottom).cgColor] as CFArray, locations: [0, 1])!
        screen.ctx.drawLinearGradient(g, start: CGPoint(x: 0, y: ay), end: CGPoint(x: 0, y: ay + ad), options: [])
        screen.ctx.restoreGState()
        let initials = name.split(separator: " ").compactMap(\.first).map(String.init)
        let mono = (initials.count > 1 ? initials.first! + initials.last! : initials.first ?? "").uppercased()
        screen.text([mono], monogram, .white, x: ax, y: ay + ((ad - t.type.monogram.pitch) / 2).rounded() + 2, pitch: t.type.monogram.pitch, width: ad, align: .center)
        screen.text([name], nameFont, ink, x: 0, y: ay + ad + e.nameGap, pitch: t.type.name.pitch, width: Double(W), align: .center)
        screen.text(["Hold the Action button to talk."], hint, stampInk, x: 0, y: ay + ad + e.hintGap, pitch: t.type.hint.pitch,
                    width: Double(W), align: .center)
    }
}

func encode(_ image: CGImage, as type: UTType, quality: Double = 0.95) -> Data {
    let data = NSMutableData()
    let dest = CGImageDestinationCreateWithData(data, type.identifier as CFString, 1, nil)!
    CGImageDestinationAddImage(dest, image, [kCGImageDestinationLossyCompressionQuality: quality] as CFDictionary)
    CGImageDestinationFinalize(dest)
    return data as Data
}
