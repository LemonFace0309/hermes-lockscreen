// Hermes Wall Reader: copies your conversation with the agent out of Messages' database (chat.db) into chat.json
// whenever it changes, about once a second. It is the only part of Hermes Wall that holds Full Disk Access, and it
// reads only that conversation (and, once, the agent's handles from Contacts). It never logs a message's words.
import AudioToolbox
import ChatModel
import Foundation
import SQLite3

let messagesDB = Paths.home.appendingPathComponent("Library/Messages/chat.db").path
let addressBook = Paths.home.appendingPathComponent("Library/Application Support/AddressBook")

func log(_ s: String) {
    FileHandle.standardError.write("\(ISO8601DateFormatter().string(from: Date())) \(s)\n".data(using: .utf8)!)
}

struct ReaderError: Error, CustomStringConvertible { let description: String }

// MARK: - SQLite, read-only

final class Database {
    private var db: OpaquePointer?

    init(_ path: String) throws {
        guard sqlite3_open_v2(path, &db, SQLITE_OPEN_READONLY, nil) == SQLITE_OK else {
            let message = db.map { String(cString: sqlite3_errmsg($0)) } ?? "can't open"
            sqlite3_close(db)
            throw ReaderError(description: "\(URL(fileURLWithPath: path).lastPathComponent): \(message)")
        }
        sqlite3_busy_timeout(db, 3000)
    }
    deinit { sqlite3_close(db) }

    struct Row {
        let stmt: OpaquePointer
        func int(_ i: Int32) -> Int64 { sqlite3_column_int64(stmt, i) }
        func double(_ i: Int32) -> Double { sqlite3_column_double(stmt, i) }
        func text(_ i: Int32) -> String? { sqlite3_column_text(stmt, i).map { String(cString: $0) } }
        func blob(_ i: Int32) -> Data? {
            guard let p = sqlite3_column_blob(stmt, i) else { return nil }
            return Data(bytes: p, count: Int(sqlite3_column_bytes(stmt, i)))
        }
    }

    func query(_ sql: String, _ args: [Any] = [], _ each: (Row) throws -> Void) throws {
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            throw ReaderError(description: String(cString: sqlite3_errmsg(db)))
        }
        defer { sqlite3_finalize(stmt) }
        let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)
        for (k, arg) in args.enumerated() {
            let i = Int32(k + 1)
            switch arg {
            case let v as Int: sqlite3_bind_int64(stmt, i, Int64(v))
            case let v as Int64: sqlite3_bind_int64(stmt, i, v)
            case let v as String: sqlite3_bind_text(stmt, i, v, -1, transient)
            default: sqlite3_bind_null(stmt, i)
            }
        }
        while true {
            let rc = sqlite3_step(stmt)
            if rc == SQLITE_DONE { break }
            guard rc == SQLITE_ROW else { throw ReaderError(description: String(cString: sqlite3_errmsg(db))) }
            try each(Row(stmt: stmt))
        }
    }

    func columns(_ table: String) throws -> Set<String> {
        var names = Set<String>()
        try query("PRAGMA table_info(\(table))") { names.insert($0.text(1) ?? "") }
        return names
    }
}

// MARK: - The agent's handles, from Contacts

func normalizedName(_ s: String) -> String {
    s.lowercased().split(whereSeparator: \.isWhitespace).joined(separator: " ")
}

/// Phone numbers and emails of every contact called `name` (as "First Last", "First Last Suffix", a nickname or a
/// company), from each Contacts database on this Mac (the local one and each account's under Sources/).
func contactHandles(named name: String) -> [String] {
    var files = [addressBook.appendingPathComponent("AddressBook-v22.abcddb")]
    let sources = addressBook.appendingPathComponent("Sources")
    for source in (try? FileManager.default.contentsOfDirectory(at: sources, includingPropertiesForKeys: nil)) ?? [] {
        files.append(source.appendingPathComponent("AddressBook-v22.abcddb"))
    }
    let wanted = normalizedName(name)
    var handles: [String] = []
    for file in files where FileManager.default.fileExists(atPath: file.path) {
        do {
            let ab = try Database(file.path)
            let have = try ab.columns("ZABCDRECORD")
            let fields = ["ZFIRSTNAME", "ZMIDDLENAME", "ZLASTNAME", "ZSUFFIX", "ZNICKNAME", "ZORGANIZATION"]
            let select = fields.map { have.contains($0) ? $0 : "NULL" }.joined(separator: ", ")
            var owners: [Int64] = []
            try ab.query("SELECT Z_PK, \(select) FROM ZABCDRECORD") { r in
                let v = (1...6).map { r.text(Int32($0)) ?? "" }
                let (first, middle, last, suffix, nick, org) = (v[0], v[1], v[2], v[3], v[4], v[5])
                let names = [[first, last], [first, middle, last], [first, last, suffix], [first, suffix], [first],
                             [nick], [org]].map { normalizedName($0.filter { !$0.isEmpty }.joined(separator: " ")) }
                if names.contains(wanted) { owners.append(r.int(0)) }
            }
            guard !owners.isEmpty else { continue }
            let list = owners.map(String.init).joined(separator: ",")
            try ab.query("SELECT ZFULLNUMBER FROM ZABCDPHONENUMBER WHERE ZOWNER IN (\(list))") { if let n = $0.text(0) { handles.append(n) } }
            try ab.query("SELECT ZADDRESS FROM ZABCDEMAILADDRESS WHERE ZOWNER IN (\(list))") { if let e = $0.text(0) { handles.append(e) } }
        } catch {
            log("contacts: \(error)")
        }
    }
    return Array(Set(handles)).sorted()
}

/// A chat identifier is the agent's when it's one of its emails, or a phone number with the same last ten digits.
func matches(_ identifier: String, _ handles: [String]) -> Bool {
    let id = identifier.lowercased()
    if id.contains("@") { return handles.contains { $0.lowercased() == id } }
    let digits = String(id.filter(\.isNumber).suffix(10))
    guard digits.count >= 7 else { return false }
    return handles.contains { !$0.contains("@") && String($0.filter(\.isNumber).suffix(10)) == digits }
}

// MARK: - Messages

/// Messages counts time in nanoseconds since 2001 (seconds in old rows).
func unixMs(_ appleTime: Int64) -> Int64? {
    guard appleTime > 0 else { return nil }
    let seconds = appleTime > 100_000_000_000 ? Double(appleTime) / 1e9 : Double(appleTime)
    return Int64(((seconds + 978_307_200) * 1000).rounded())
}

/// A message's words live in attributedBody (an archived NSAttributedString) when the text column is empty.
func decodeBody(_ data: Data) -> String? {
    // The archive's string, read directly (NSUnarchiver raises on anything unexpected, which would end the reader):
    // after "NSString", 5 bytes, then a length (one byte, or 0x81 and two bytes little-endian, or 0x82 and four) and
    // the UTF-8.
    guard let r = data.range(of: Data("NSString".utf8)) else { return nil }
    var i = r.upperBound + 5
    guard i < data.count else { return nil }
    var length = Int(data[i]); i += 1
    if length == 0x81, i + 2 <= data.count { length = Int(data[i]) | Int(data[i + 1]) << 8; i += 2 }
    else if length == 0x82, i + 4 <= data.count {
        length = Int(data[i]) | Int(data[i + 1]) << 8 | Int(data[i + 2]) << 16 | Int(data[i + 3]) << 24; i += 4
    }
    guard i + length <= data.count else { return nil }
    return String(data: data[i..<(i + length)], encoding: .utf8)
}

var durations: [String: Double] = [:]
func audioSeconds(_ path: String) -> Double? {
    if let d = durations[path] { return d }
    var file: AudioFileID?
    guard AudioFileOpenURL(URL(fileURLWithPath: path) as CFURL, .readPermission, 0, &file) == noErr, let file else { return nil }
    defer { AudioFileClose(file) }
    var seconds: Float64 = 0, size = UInt32(MemoryLayout<Float64>.size)
    guard AudioFileGetProperty(file, kAudioFilePropertyEstimatedDuration, &size, &seconds) == noErr else { return nil }
    durations[path] = seconds
    return seconds
}

let tapbackEmoji: [Int64: String] = [0: "❤️", 1: "👍", 2: "👎", 3: "😂", 4: "‼️", 5: "❓"]

final class Reader {
    var db: Database?
    var messageColumns = Set<String>()
    var chatIDs: [Int64] = []
    var handles: [String] = []
    var resolvedFor = "", resolvedAt = Date.distantPast
    var fingerprint = ""
    var written: ChatExport?

    func connect() throws {
        if db == nil {
            let d = try Database(messagesDB)
            messageColumns = try d.columns("message")   // also the first read: fails here without Full Disk Access
            db = d
        }
    }

    /// The agent's chats, looked up again every five minutes (or when the configured name or handles change).
    func resolve(_ config: Config) throws {
        let key = config.agent + "|" + (config.handles ?? []).joined(separator: ",")
        guard key != resolvedFor || Date().timeIntervalSince(resolvedAt) > 300 else { return }
        handles = config.handles?.isEmpty == false ? config.handles! : contactHandles(named: config.agent)
        var ids: [Int64] = []
        try db!.query("SELECT ROWID, chat_identifier FROM chat") { r in
            if let id = r.text(1), matches(id, self.handles) { ids.append(r.int(0)) }
        }
        chatIDs = ids
        resolvedFor = key
        resolvedAt = Date()
        fingerprint = ""
        log("agent: \(handles.count) handle(s) in Contacts, \(ids.count) chat(s) in Messages")
    }

    func column(_ name: String, _ fallback: String = "0") -> String {
        messageColumns.contains(name) ? "COALESCE(m.\(name), 0)" : fallback
    }

    /// Changes whenever a message, tapback, edit, unsend, delivery or read lands in the agent's chats.
    func currentFingerprint() throws -> String {
        let ids = chatIDs.map(String.init).joined(separator: ",")
        var fp = ""
        try db!.query("""
            SELECT COUNT(*), MAX(m.ROWID), MAX(m.date_delivered), MAX(m.date_read), MAX(\(column("date_edited"))),
                   MAX(\(column("date_retracted")))
            FROM message m JOIN chat_message_join j ON j.message_id = m.ROWID WHERE j.chat_id IN (\(ids))
            """) { r in fp = (0..<6).map { String(r.int(Int32($0))) }.joined(separator: ":") }
        return fp
    }

    func export(_ config: Config) throws -> ChatExport {
        let ids = chatIDs.map(String.init).joined(separator: ",")
        let limit = max(config.limit ?? 60, 1)
        var messages: [Message] = []
        var rowIDs: [String: Int64] = [:]
        try db!.query("""
            SELECT m.ROWID, m.guid, m.date, m.is_from_me, m.text, m.attributedBody, m.cache_has_attachments,
                   \(column("is_audio_message")), m.date_delivered, m.date_read, \(column("date_edited")),
                   \(column("date_retracted"))
            FROM message m JOIN chat_message_join j ON j.message_id = m.ROWID
            WHERE j.chat_id IN (\(ids)) AND COALESCE(m.associated_message_type, 0) = 0 AND COALESCE(m.item_type, 0) = 0
            ORDER BY m.date DESC LIMIT ?
            """, [limit]) { r in
            guard r.int(11) == 0, let guid = r.text(1), let at = unixMs(r.int(2)) else { return }   // unsent: gone
            let raw = r.text(4).flatMap { $0.isEmpty ? nil : $0 } ?? r.blob(5).flatMap(decodeBody) ?? ""
            let text = raw.replacingOccurrences(of: "\u{FFFC}", with: "").trimmingCharacters(in: .whitespacesAndNewlines)
            let me = r.int(3) == 1
            messages.append(Message(id: guid, at: at, me: me, text: text, kind: r.int(7) == 1 ? "audio" : "text",
                                    attachments: [], delivered: me ? unixMs(r.int(8)) : nil,
                                    read: me ? unixMs(r.int(9)) : nil, edited: r.int(10) > 0, reactions: []))
            rowIDs[guid] = r.int(0)
        }
        messages.reverse()

        for k in messages.indices {
            guard let rowID = rowIDs[messages[k].id] else { continue }
            var files: [Attachment] = []
            try db!.query("""
                SELECT a.filename, a.mime_type, a.transfer_name FROM attachment a
                JOIN message_attachment_join j ON j.attachment_id = a.ROWID WHERE j.message_id = ?
                """, [rowID]) { r in
                let name = r.text(2) ?? ""
                guard !name.hasSuffix(".pluginPayloadAttachment") else { return }   // a link preview's card
                let mime = r.text(1) ?? ""
                var seconds: Double?
                if mime.hasPrefix("audio/") || messages[k].kind == "audio", let path = r.text(0) {
                    seconds = audioSeconds((path as NSString).expandingTildeInPath)
                }
                files.append(Attachment(name: name, mime: mime, seconds: seconds))
            }
            messages[k].attachments = files
            if messages[k].kind == "text", !files.isEmpty {
                messages[k].kind = files.allSatisfy { $0.mime.hasPrefix("audio/") } && messages[k].text.isEmpty ? "audio" : "attachment"
            }
        }
        messages.removeAll { $0.text.isEmpty && $0.attachments.isEmpty && $0.kind == "text" }

        // Tapbacks, in the order they were made: each person keeps at most one on a message; a removal takes it off.
        if let oldest = messages.first?.at {
            let since = Int64((Double(oldest) / 1000 - 978_307_200) * 1e9)
            let emoji = messageColumns.contains("associated_message_emoji") ? "m.associated_message_emoji" : "NULL"
            var index: [String: Int] = [:]
            for (k, m) in messages.enumerated() { index[m.id] = k }
            try db!.query("""
                SELECT m.associated_message_guid, m.associated_message_type, \(emoji), m.is_from_me, m.date
                FROM message m JOIN chat_message_join j ON j.message_id = m.ROWID
                WHERE j.chat_id IN (\(ids)) AND m.associated_message_type BETWEEN 2000 AND 3999 AND m.date >= ?
                ORDER BY m.date ASC
                """, [since]) { r in
                guard let target = r.text(0), let at = unixMs(r.int(4)) else { return }
                let guid = target.contains("/") ? String(target.split(separator: "/").last!) :
                    (target.hasPrefix("bp:") ? String(target.dropFirst(3)) : target)
                guard let k = index[guid] else { return }
                let type = r.int(1), me = r.int(3) == 1
                messages[k].reactions.removeAll { $0.me == me }
                if type < 3000, let e = type == 2006 ? r.text(2) : tapbackEmoji[type - 2000], !e.isEmpty {
                    messages[k].reactions.append(Reaction(me: me, emoji: e, at: at))
                }
            }
        }
        return ChatExport(agent: config.agent, handles: handles, messages: messages)
    }

    func writeStatus(_ fields: [String: Any]) {
        var all = fields
        all["at"] = unixMillis()
        if let data = try? JSONSerialization.data(withJSONObject: all, options: [.sortedKeys]) {
            try? data.write(to: Paths.readerStatus, options: .atomic)
        }
    }

    func tick() throws {
        let config = try Config.load()
        try connect()
        try resolve(config)
        guard !chatIDs.isEmpty else {
            writeStatus(["ok": false, "error": "no chat with \(config.agent) found", "handles": handles.count, "chats": 0])
            return
        }
        let fp = try currentFingerprint()
        guard fp != fingerprint else { return }
        let chat = try export(config)
        if chat != written {
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.sortedKeys]
            try encoder.encode(chat).write(to: Paths.chat, options: .atomic)
            written = chat
        }
        fingerprint = fp
        writeStatus(["ok": true, "handles": handles.count, "chats": chatIDs.count, "messages": chat.messages.count,
                     "changedAt": unixMillis()])
    }
}

try? FileManager.default.createDirectory(at: Paths.support, withIntermediateDirectories: true)
log("started")
let reader = Reader()
var lastError = ""
while true {
    autoreleasepool {
        do {
            try reader.tick()
            lastError = ""
        } catch {
            let message = "\(error)"
            if message != lastError { log("error: \(message)") }
            lastError = message
            reader.db = nil
            reader.writeStatus(["ok": false, "error": message])
        }
    }
    Thread.sleep(forTimeInterval: lastError.isEmpty ? 1 : 5)
}
