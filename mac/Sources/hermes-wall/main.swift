// hermes-wall: draws chat.json as the Lock Screen and serves it to the iPhone.
//   hermes-wall serve                     the server (run by launchd)
//   hermes-wall render [chat.json] out    draw once to a .jpg or .png
//   hermes-wall sample out                draw a made-up conversation, to check the drawing without Messages
//
// The phone's Hermes Lock Screen posts {"input": <what started it>} to /wall with the token in X-Hermes-Token and
// sets the image it gets back as the wallpaper. Anything but an image (an error) leaves the wall as it was.
import AppKit
import ChatModel
import Foundation
import Network
import UniformTypeIdentifiers

func log(_ s: String) {
    FileHandle.standardError.write("\(ISO8601DateFormatter().string(from: Date())) \(s)\n".data(using: .utf8)!)
}

func loadPainter(_ config: Config?) throws -> Painter {
    let repo = URL(fileURLWithPath: #filePath).deletingLastPathComponent().appendingPathComponent("../../..").standardized
    let assets = config?.assets.map { URL(fileURLWithPath: $0) } ?? repo.appendingPathComponent("assets")
    let tokens = config?.tokens.map { URL(fileURLWithPath: $0) } ?? repo.appendingPathComponent("design/tokens.json")
    return try Painter(tokens: tokens, assets: assets)
}

func loadChat(_ url: URL = Paths.chat) -> ChatExport? {
    guard let data = try? Data(contentsOf: url) else { return nil }
    return try? JSONDecoder().decode(ChatExport.self, from: data)
}

func loadTranscripts() -> [String: String] {
    guard let data = try? Data(contentsOf: Paths.transcripts) else { return [:] }
    return (try? JSONDecoder().decode([String: String].self, from: data)) ?? [:]
}

func write(_ image: CGImage, to path: String) throws {
    let type: UTType = path.lowercased().hasSuffix(".png") ? .png : .jpeg
    try encode(image, as: type).write(to: URL(fileURLWithPath: path))
}

// MARK: - A made-up conversation

func sample() -> ChatExport {
    let now = unixMillis()
    func m(_ minutesAgo: Double, _ me: Bool, _ text: String, kind: String = "text", reactions: [Reaction] = [],
           read: Bool = false) -> Message {
        let at = now - Int64(minutesAgo * 60_000)
        return Message(id: UUID().uuidString, at: at, me: me, text: text, kind: kind,
                       attachments: kind == "audio" ? [Attachment(name: "Audio Recording sample.m4a", mime: "audio/x-m4a", seconds: 6)] : [],
                       delivered: me ? at + 1000 : nil, read: me && read ? at + 5000 : nil, edited: false, reactions: reactions)
    }
    return ChatExport(agent: "Hermes", handles: [], messages: [
        m(95, true, "remind me to call the dentist tomorrow morning"),
        m(94.5, false, "Done — I’ll remind you at 9:00 AM tomorrow to call Dr. Lee’s office.", reactions: [Reaction(me: true, emoji: "👍", at: now - 94 * 60_000)]),
        m(40, true, "", kind: "audio", reactions: [Reaction(me: false, emoji: "👀", at: now - 39 * 60_000)]),
        m(39, false, "UA 1149 is on time. Departs 8:05 AM from gate C4, boarding at 7:25.\n\nTraffic to SFO looks light, so leaving by 6:45 gives you a comfortable buffer. Want me to set a 6:30 alarm?"),
        m(2, true, "😎"),
        m(1.5, true, "yes set the alarm and also remind me to pack my charger", reactions: [Reaction(me: false, emoji: "👀", at: now - 60_000)], read: true),
    ])
}

// MARK: - HTTP

struct Request { var method = "", path = "", query: [String: String] = [:], headers: [String: String] = [:], body = Data() }
struct Response { var status: Int; var type: String; var body: Data; var extra: [String: String] = [:] }

func parse(_ data: Data) -> Request? {
    guard let end = data.range(of: Data("\r\n\r\n".utf8)) else { return nil }
    guard let head = String(data: data[..<end.lowerBound], encoding: .utf8) else { return nil }
    var lines = head.components(separatedBy: "\r\n")
    let first = lines.removeFirst().split(separator: " ")
    guard first.count >= 2 else { return nil }
    var r = Request()
    r.method = String(first[0])
    let target = String(first[1])
    let comps = URLComponents(string: "http://x" + target)
    r.path = comps?.path ?? target
    for item in comps?.queryItems ?? [] { r.query[item.name] = item.value ?? "" }
    for line in lines {
        guard let colon = line.firstIndex(of: ":") else { continue }
        r.headers[line[..<colon].lowercased()] = line[line.index(after: colon)...].trimmingCharacters(in: .whitespaces)
    }
    let length = Int(r.headers["content-length"] ?? "0") ?? 0
    guard data.count - end.upperBound >= length else { return nil }
    r.body = data[end.upperBound..<(end.upperBound + length)]
    return r
}

final class Server {
    let config: Config
    let painter: Painter
    let io = DispatchQueue(label: "hermes-wall.io")
    let drawing = DispatchQueue(label: "hermes-wall.draw")   // one drawing at a time
    var listener: NWListener!
    let lock = NSLock()
    var served: [Bool: String] = [:]   // per side (true = you), the newest message or tapback in the last image

    init(config: Config, painter: Painter) { self.config = config; self.painter = painter }

    func start() throws {
        let port = NWEndpoint.Port(rawValue: UInt16(config.port ?? 7337))!
        listener = try NWListener(using: .tcp, on: port)
        listener.newConnectionHandler = { conn in
            conn.start(queue: self.io)
            self.receive(conn, Data())
        }
        listener.stateUpdateHandler = { state in log("listener: \(state)") }
        listener.start(queue: io)
    }

    func receive(_ conn: NWConnection, _ buffer: Data) {
        conn.receive(minimumIncompleteLength: 1, maximumLength: 1 << 20) { data, _, done, error in
            var buf = buffer
            if let data { buf.append(data) }
            if let req = parse(buf) {
                DispatchQueue.global().async {
                    let started = Date()
                    let res = self.handle(req)
                    log("\(req.method) \(req.path) → \(res.status) \(res.body.count) bytes in \(Int(Date().timeIntervalSince(started) * 1000)) ms\(res.extra["X-Hermes-Note"].map { " (\($0))" } ?? "")")
                    self.send(conn, res)
                }
                return
            }
            if done || error != nil || buf.count > 4 << 20 { conn.cancel(); return }
            self.receive(conn, buf)
        }
    }

    func send(_ conn: NWConnection, _ res: Response) {
        let reason = [200: "OK", 401: "Unauthorized", 404: "Not Found", 503: "Service Unavailable"][res.status] ?? "Error"
        var head = "HTTP/1.1 \(res.status) \(reason)\r\nContent-Type: \(res.type)\r\nContent-Length: \(res.body.count)\r\nConnection: close\r\nCache-Control: no-store\r\n"
        for (k, v) in res.extra { head += "\(k): \(v)\r\n" }
        var out = Data((head + "\r\n").utf8)
        out.append(res.body)
        conn.send(content: out, completion: .contentProcessed { _ in conn.cancel() })
    }

    func text(_ status: Int, _ s: String) -> Response { Response(status: status, type: "text/plain; charset=utf-8", body: Data((s + "\n").utf8)) }

    func handle(_ req: Request) -> Response {
        if req.path == "/health" { return text(200, "ok") }
        guard let token = config.token, !token.isEmpty, req.headers["x-hermes-token"] == token || req.query["token"] == token else {
            return text(401, "unauthorized")
        }
        switch req.path {
        case "/wall", "/wall.jpg", "/wall.png": return wall(req)
        case "/chat.json": return (try? Data(contentsOf: Paths.chat)).map { Response(status: 200, type: "application/json", body: $0) } ?? text(503, "no chat yet")
        case "/status": return Response(status: 200, type: "application/json", body: (try? Data(contentsOf: Paths.readerStatus)) ?? Data("{}".utf8))
        default: return text(404, "not found")
        }
    }

    /// The newest message or tapback from one side: changes when that side says something new.
    func newest(_ chat: ChatExport, me: Bool) -> String {
        var best: (Int64, String) = (0, "")
        for m in chat.messages {
            if m.me == me, m.at >= best.0 { best = (m.at, m.id) }
            for r in m.reactions where r.me == me && r.at >= best.0 { best = (r.at, m.id + r.emoji) }
        }
        return "\(best.0):\(best.1)"
    }

    func wall(_ req: Request) -> Response {
        var input = req.query["input"] ?? ""
        if let json = try? JSONSerialization.jsonObject(with: req.body) as? [String: Any], let s = json["input"] as? String { input = s }
        input = input.trimmingCharacters(in: .whitespacesAndNewlines)
        // What started the update: your voice note (Talk to Hermes), your words, the time of day, a run by hand, or
        // (anything else) a message from your agent.
        var side: Bool? = false
        if let m = input.range(of: #"^me-audio\[([^\]]*)\]:\s*([\s\S]*)$"#, options: .regularExpression) {
            let match = String(input[m])
            let name = match.replacingOccurrences(of: #"^me-audio\[([^\]]*)\][\s\S]*$"#, with: "$1", options: .regularExpression)
            let words = match.replacingOccurrences(of: #"^me-audio\[[^\]]*\]:\s*"#, with: "", options: .regularExpression)
            if !name.isEmpty && !words.isEmpty { saveTranscript(name, words) }
            side = true
        } else if input.hasPrefix("me:") {
            side = true
        } else if input.isEmpty || ["dawn", "day", "dusk", "night", "sync", "sync by hand"].contains(input.lowercased()) {
            side = nil
        }
        // Wait (up to 10 s) for the message that started this to reach this Mac: the phone often hears of it first.
        var chat = loadChat()
        var note = "now"
        if let side, chat != nil {
            let deadline = Date().addingTimeInterval(10)
            let before = lock.withLock { served[side] }
            while let c = chat, newest(c, me: side) == before, Date() < deadline {
                Thread.sleep(forTimeInterval: 0.25)
                chat = loadChat()
            }
            note = chat.map { newest($0, me: side) == before } == true ? "nothing new in 10 s" : "waited for it"
        }
        guard let chat else { return text(503, "no chat yet: is the reader running with Full Disk Access?") }
        let transcripts = loadTranscripts()
        let image = drawing.sync { painter.render(chat, transcripts: transcripts, now: Date()) }
        lock.withLock { served[true] = newest(chat, me: true); served[false] = newest(chat, me: false) }
        let png = req.path.hasSuffix(".png")
        return Response(status: 200, type: png ? "image/png" : "image/jpeg", body: encode(image, as: png ? .png : .jpeg),
                        extra: ["X-Hermes-Note": note])
    }

    func saveTranscript(_ name: String, _ words: String) {
        lock.withLock {
            var all = loadTranscripts()
            all[voiceKey(name)] = words
            if let data = try? JSONEncoder().encode(all) { try? data.write(to: Paths.transcripts, options: .atomic) }
        }
    }
}

// MARK: - Main

let args = Array(CommandLine.arguments.dropFirst())
let config = try? Config.load()
do {
    switch args.first {
    case "serve":
        guard let config else { throw NSError(domain: "HermesWall", code: 2, userInfo: [NSLocalizedDescriptionKey: "no config at \(Paths.config.path)"]) }
        let server = Server(config: config, painter: try loadPainter(config))
        try server.start()
        log("serving on port \(config.port ?? 7337)")
        dispatchMain()
    case "render":
        let input = args.count > 2 ? URL(fileURLWithPath: args[1]) : Paths.chat
        let out = args.last ?? "wall.jpg"
        let started = Date()
        try write(loadPainter(config).render(loadChat(input), transcripts: loadTranscripts(), now: Date()), to: out)
        print("drew \(out) in \(Int(Date().timeIntervalSince(started) * 1000)) ms")
    case "sample":
        try write(loadPainter(config).render(sample(), transcripts: ["Audio Recording sample": "Can you check if my flight is still on time and text me the gate"], now: Date()),
                  to: args.count > 1 ? args[1] : "sample.png")
        print("drew \(args.count > 1 ? args[1] : "sample.png")")
    default:
        print("usage: hermes-wall serve | render [chat.json] out.jpg | sample out.png")
    }
} catch {
    log("error: \(error)")
    exit(1)
}
