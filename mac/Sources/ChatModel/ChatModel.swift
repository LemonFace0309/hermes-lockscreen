import Foundation

/// One conversation as the reader exports it: the newest messages, oldest first, each with its tapbacks as they stand
/// now. Times are Unix milliseconds.
public struct ChatExport: Codable, Equatable {
    public var agent: String
    public var handles: [String]
    public var messages: [Message]
    public init(agent: String, handles: [String], messages: [Message]) {
        self.agent = agent; self.handles = handles; self.messages = messages
    }
}

public struct Message: Codable, Equatable {
    public var id: String                 // Messages' guid
    public var at: Int64                  // when it was sent
    public var me: Bool                   // you sent it
    public var text: String               // its words, as Messages has them now (after any edit)
    public var kind: String               // "text", "audio" or "attachment"
    public var attachments: [Attachment]
    public var delivered: Int64?          // yours: when it was delivered
    public var read: Int64?               // yours: when it was read
    public var edited: Bool
    public var reactions: [Reaction]      // tapbacks still on it, oldest first
    public init(id: String, at: Int64, me: Bool, text: String, kind: String, attachments: [Attachment],
                delivered: Int64?, read: Int64?, edited: Bool, reactions: [Reaction]) {
        self.id = id; self.at = at; self.me = me; self.text = text; self.kind = kind; self.attachments = attachments
        self.delivered = delivered; self.read = read; self.edited = edited; self.reactions = reactions
    }
}

public struct Attachment: Codable, Equatable {
    public var name: String               // as sent, e.g. "Audio Recording 2026-10-29 at 3.45.56 PM.m4a"
    public var mime: String
    public var seconds: Double?           // a voice note's length
    public init(name: String, mime: String, seconds: Double?) { self.name = name; self.mime = mime; self.seconds = seconds }
}

public struct Reaction: Codable, Equatable {
    public var me: Bool
    public var emoji: String
    public var at: Int64
    public init(me: Bool, emoji: String, at: Int64) { self.me = me; self.emoji = emoji; self.at = at }
}

/// Settings shared by both programs, in ~/Library/Application Support/Hermes Wall/config.json.
public struct Config: Codable {
    public var agent: String              // the agent's name as its contact is called (its handles are found there)
    public var handles: [String]?         // or its phone numbers / emails, when Contacts doesn't have them
    public var limit: Int?                // how many messages to export (default 60)
    public var port: Int?                 // the server's port (default 7337)
    public var token: String?             // the phone sends it in X-Hermes-Token
    public var assets: String?            // folder with the walls and drawing assets (the repo's assets/)
    public var tokens: String?            // design/tokens.json

    public static func load() throws -> Config {
        try JSONDecoder().decode(Config.self, from: Data(contentsOf: Paths.config))
    }
}

public enum Paths {
    public static let home = FileManager.default.homeDirectoryForCurrentUser
    public static let support = home.appendingPathComponent("Library/Application Support/Hermes Wall")
    public static let config = support.appendingPathComponent("config.json")
    public static let chat = support.appendingPathComponent("chat.json")
    public static let readerStatus = support.appendingPathComponent("reader-status.json")
    public static let transcripts = support.appendingPathComponent("transcripts.json")
}

public func unixMillis(_ date: Date = Date()) -> Int64 { Int64((date.timeIntervalSince1970 * 1000).rounded()) }
