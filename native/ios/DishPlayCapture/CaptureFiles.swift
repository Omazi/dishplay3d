import Foundation
import CryptoKit

struct CaptureRecord: Codable, Identifiable {
    var id: UUID
    var createdAt: Date
    var dishReference: String
    var mode: String
    var state: String
    var device: String
    var systemVersion: String
    var imageCount: Int = 0
    var error: String?
    var modelPath: String?
    var sourceVideoPath: String?
    var remoteScanId: String?
    var metricScaleVerified = false
    var physicallyReviewed = false
}

enum CaptureFiles {
    static var base: URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Captures", isDirectory: true)
    }
    static func root(_ record: CaptureRecord) -> URL {
        base.appendingPathComponent(record.id.uuidString, isDirectory: true)
    }
    static func images(_ record: CaptureRecord) -> URL {
        root(record).appendingPathComponent("Images", isDirectory: true)
    }
    static func checkpoints(_ record: CaptureRecord) -> URL {
        root(record).appendingPathComponent("Checkpoints", isDirectory: true)
    }
    static func create(_ record: CaptureRecord) throws {
        try FileManager.default.createDirectory(at: images(record), withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: checkpoints(record), withIntermediateDirectories: true)
        try save(record)
    }
    static func save(_ record: CaptureRecord) throws {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        encoder.dateEncodingStrategy = .iso8601
        try encoder.encode(record).write(to: root(record).appendingPathComponent("capture.json"), options: .atomic)
    }
    static func library() -> [CaptureRecord] {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let folders = (try? FileManager.default.contentsOfDirectory(at: base, includingPropertiesForKeys: nil)) ?? []
        return folders.compactMap { folder in
            guard let data = try? Data(contentsOf: folder.appendingPathComponent("capture.json")) else { return nil }
            return try? decoder.decode(CaptureRecord.self, from: data)
        }.sorted { $0.createdAt > $1.createdAt }
    }
    static func photos(_ record: CaptureRecord) -> [URL] {
        let entries = (try? FileManager.default.contentsOfDirectory(at: images(record), includingPropertiesForKeys: nil)) ?? []
        return entries.filter { ["jpg", "jpeg", "heic", "png"].contains($0.pathExtension.lowercased()) }
            .sorted { $0.lastPathComponent < $1.lastPathComponent }
    }
    static func archive(_ record: CaptureRecord) throws -> URL {
        // Hash actual saved files without loading the whole acquisition into RAM.
        let entries: [[String: Any]] = try photos(record).map { url in
            let handle = try FileHandle(forReadingFrom: url)
            defer { try? handle.close() }
            var hash = SHA256()
            var size = 0
            while let data = try handle.read(upToCount: 1_048_576), !data.isEmpty {
                hash.update(data: data)
                size += data.count
            }
            return ["file": "Images/" + url.lastPathComponent, "bytes": size,
                    "sha256": hash.finalize().map { String(format: "%02x", $0) }.joined()]
        }
        let manifest: [String: Any] = ["schema": 1, "captureId": record.id.uuidString,
            "dishReference": record.dishReference, "pairedWithServer": record.remoteScanId != nil,
            "mode": record.mode, "frames": entries, "metricScaleVerified": false]
        try JSONSerialization.data(withJSONObject: manifest, options: [.prettyPrinted, .sortedKeys])
            .write(to: root(record).appendingPathComponent("manifest.json"), options: .atomic)
        let exportFolder = FileManager.default.temporaryDirectory.appendingPathComponent("DishPlayExports", isDirectory: true)
        try FileManager.default.createDirectory(at: exportFolder, withIntermediateDirectories: true)
        let destination = exportFolder.appendingPathComponent("DishPlay-\(record.id.uuidString)-\(UUID().uuidString).zip")
        var coordinationError: NSError?
        var copyError: Error?
        NSFileCoordinator(filePresenter: nil).coordinate(readingItemAt: root(record), options: .forUploading, error: &coordinationError) { snapshot in
            do { try FileManager.default.copyItem(at: snapshot, to: destination) }
            catch { copyError = error }
        }
        if let error = coordinationError { throw error }
        if let error = copyError { throw error }
        return destination
    }
}
