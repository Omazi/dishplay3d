import Foundation

/// Bounded local startup events only: no photos, poses, dish names, credentials or network upload.
final class ScanDiagnostics {
    struct Event: Codable { let time: Date; let name: String; let details: String }
    private let url: URL
    private var events: [Event] = []
    init(folder: URL) { url = folder.appendingPathComponent("camera-diagnostics.json") }
    func record(_ name: String, _ details: String = "") {
        events.append(Event(time: Date(), name: String(name.prefix(80)), details: String(details.prefix(240))))
        if events.count > 64 { events.removeFirst(events.count-64) }
        let encoder = JSONEncoder(); encoder.dateEncodingStrategy = .iso8601
        if let data = try? encoder.encode(events) { try? data.write(to: url, options: .atomic) }
    }
    var summary: String { events.map { "\($0.name): \($0.details)" }.joined(separator: "\n") }
}
