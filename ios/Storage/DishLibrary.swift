import Foundation
import UIKit

/// One scanned dish kept on the iPhone (a session folder).
struct DishRecord: Identifiable, Hashable {
    enum State: Hashable { case ready, processing, interrupted }

    let id: String
    let root: URL
    var name: String
    let date: Date?
    let state: State
    let frames: Int
    let picture: URL?
    let model: URL?
}

/// Reads the dishes from the session folders. Several dishes can be scanned one after another; each keeps
/// its own folder, name and results.
enum DishLibrary {
    static func all() -> [DishRecord] {
        let fm = FileManager.default
        let names = (try? fm.contentsOfDirectory(atPath: SessionStore.sessionsDirectory.path)) ?? []
        var out: [DishRecord] = []
        for id in names.sorted(by: >) {
            let root = SessionStore.sessionsDirectory.appendingPathComponent(id, isDirectory: true)
            let results = root.appendingPathComponent("results", isDirectory: true)
            let picture = results.appendingPathComponent("apercu.png")
            let model = results.appendingPathComponent("model.glb")
            let hasPicture = fm.fileExists(atPath: picture.path)
            let hasModel = fm.fileExists(atPath: model.path)
            let frameNames = (try? fm.contentsOfDirectory(atPath: root.appendingPathComponent("frames").path)) ?? []
            let frames = frameNames.filter { $0.hasSuffix(".jpg") }.count
            let abandoned = fm.fileExists(atPath: root.appendingPathComponent("abandoned").path)
            let ready = hasPicture || hasModel
            if !ready && (abandoned || frames == 0) { continue }
            let state: DishRecord.State
            if ready {
                state = .ready
            } else if fm.fileExists(atPath: root.appendingPathComponent("finish.requested").path) {
                state = .processing
            } else {
                state = .interrupted
            }
            let date = parseDate(id)
            let stored = (try? String(contentsOf: root.appendingPathComponent("name.txt"), encoding: .utf8))?
                .trimmingCharacters(in: .whitespacesAndNewlines)
            let name = (stored?.isEmpty == false) ? stored! : defaultName(date)
            out.append(DishRecord(id: id, root: root, name: name, date: date, state: state, frames: frames,
                                  picture: hasPicture ? picture : nil, model: hasModel ? model : nil))
        }
        return out
    }

    static func rename(_ dish: DishRecord, to name: String) {
        let clean = name.trimmingCharacters(in: .whitespacesAndNewlines)
        try? Data(clean.utf8).write(to: dish.root.appendingPathComponent("name.txt"), options: .atomic)
    }

    static func delete(_ dish: DishRecord) {
        try? FileManager.default.removeItem(at: dish.root)
        cache.removeObject(forKey: dish.id as NSString)
    }

    /// Session folders are named after their start time, e.g. 2026-11-16T19-52-03Z.
    static func parseDate(_ id: String) -> Date? {
        let parts = id.split(separator: "T")
        guard parts.count == 2 else { return nil }
        let day = String(parts[0])
        let time = String(parts[1]).replacingOccurrences(of: "-", with: ":")
        return ISO8601DateFormatter().date(from: day + "T" + time)
    }

    private static func defaultName(_ date: Date?) -> String {
        guard let date else { return "Plat" }
        return "Plat du " + date.formatted(.dateTime.day().month(.abbreviated).hour().minute())
    }

    private static let cache = NSCache<NSString, UIImage>()

    /// The result picture holds four views of the model; the card shows the first one.
    static func thumbnail(for dish: DishRecord) -> UIImage? {
        if let hit = cache.object(forKey: dish.id as NSString) { return hit }
        guard let url = dish.picture, let image = UIImage(contentsOfFile: url.path), let cg = image.cgImage else { return nil }
        let w = cg.width / 2, h = cg.height / 2
        let top = min(24, h / 8)   // skip the caption line at the top of the sheet
        guard w > 8, h > 8, let cropped = cg.cropping(to: CGRect(x: 0, y: top, width: w, height: h - top)) else { return image }
        let thumb = UIImage(cgImage: cropped)
        cache.setObject(thumb, forKey: dish.id as NSString)
        return thumb
    }
}
