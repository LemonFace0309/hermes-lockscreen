// swift-tools-version:5.9
// Hermes Wall: your chat with your agent, copied from Messages on this Mac and drawn as a Lock Screen image that the
// iPhone fetches and sets. Two programs, so only the small one ever holds Full Disk Access:
//   hermes-wall-reader   copies the one conversation out of Messages' database into chat.json when it changes
//   hermes-wall          draws chat.json as the Lock Screen and serves it to the phone
import PackageDescription

let package = Package(
    name: "HermesWall",
    platforms: [.macOS(.v14)],
    targets: [
        .target(name: "ChatModel"),
        .executableTarget(name: "hermes-wall-reader", dependencies: ["ChatModel"],
                          linkerSettings: [.linkedLibrary("sqlite3")]),
        .executableTarget(name: "hermes-wall", dependencies: ["ChatModel"]),
    ]
)
