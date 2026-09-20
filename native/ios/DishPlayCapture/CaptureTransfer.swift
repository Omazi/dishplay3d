import Combine
import CryptoKit
import Foundation
import ImageIO
import Security
import UniformTypeIdentifiers

struct NativeSnapshot: Codable {
    struct Scan: Codable { let id: String; let state: String; let frameCount: Int }
    let scan: Scan
    let dishName: String
    let restaurantName: String
    let expiresAt: String
    var hashes: [String]
}

struct ReconstructionSnapshot: Decodable {
    struct Job: Decodable { let id: String; let state: String; let stage: String?; let errorCode: String? }
    let job: Job?
    let enabled: Bool
    let workerAvailable: Bool
}

private struct CaptureCredential: Codable {
    let code: String
    let secret: String
    var snapshot: NativeSnapshot?
}

// Credentials are never saved in Documents, capture.json or exported ZIPs.
private enum CaptureKeychain {
    static func query(_ id: UUID) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: "app.dishplay.capture.transfer",
         kSecAttrAccount as String: id.uuidString]
    }
    static func load(_ id: UUID) throws -> CaptureCredential? {
        var query = query(id)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let data = result as? Data else { throw CaptureProblem("Unlock this iPhone to access the capture association.") }
        return try JSONDecoder().decode(CaptureCredential.self, from: data)
    }
    static func save(_ value: CaptureCredential, id: UUID) throws {
        let data = try JSONEncoder().encode(value)
        let query = query(id)
        let status = SecItemUpdate(query as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        if status == errSecItemNotFound {
            var item = query
            item[kSecValueData as String] = data
            item[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
            guard SecItemAdd(item as CFDictionary, nil) == errSecSuccess else { throw CaptureProblem("Could not securely save the association. No photos were sent.") }
        } else if status != errSecSuccess { throw CaptureProblem("Could not securely save the association.") }
    }
    static func remove(_ id: UUID) throws {
        let status = SecItemDelete(query(id) as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else { throw CaptureProblem("Could not remove the local association.") }
    }
    static func randomSecret() throws -> String {
        var bytes = [UInt8](repeating: 0, count: 32)
        guard SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) == errSecSuccess else { throw CaptureProblem("Could not create a secure association.") }
        return bytes.map { String(format: "%02x", $0) }.joined()
    }
}

// No redirect can forward a capture capability to another destination.
private final class CaptureNetworkDelegate: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}

private enum NativeAPI {
    static let session: URLSession = {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpCookieStorage = nil
        configuration.httpShouldSetCookies = false
        configuration.urlCache = nil
        configuration.timeoutIntervalForRequest = 60
        configuration.timeoutIntervalForResource = 120
        return URLSession(configuration: configuration, delegate: CaptureNetworkDelegate(), delegateQueue: nil)
    }()
    static func request(_ path: String, method: String = "GET", secret: String? = nil) -> URLRequest {
        // An association URI cannot change the server receiving credentials or images.
        var request = URLRequest(url: URL(string: "https://dishplay3d.vercel.app/api/native/" + path)!)
        request.httpMethod = method
        if let secret { request.setValue("Bearer " + secret, forHTTPHeaderField: "Authorization") }
        return request
    }
    static func checked(_ result: (Data, URLResponse)) throws -> Data {
        guard let response = result.1 as? HTTPURLResponse else { throw CaptureProblem("No server response. Resume when your connection is available.") }
        guard (200...299).contains(response.statusCode) else {
            let value = (try? JSONSerialization.jsonObject(with: result.0)) as? [String: Any]
            throw CaptureProblem(String((value?["error"] as? String ?? "The transfer could not complete. Resume to retry.").prefix(500)))
        }
        return result.0
    }
    static func snapshot(_ secret: String) async throws -> NativeSnapshot {
        let data = try checked(await session.data(for: request("session", secret: secret)))
        return try JSONDecoder().decode(NativeSnapshot.self, from: data)
    }
    static func pair(_ credential: CaptureCredential) async throws -> NativeSnapshot {
        var request = request("pair", method: "POST")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: ["code": credential.code, "deviceSecret": credential.secret])
        return try JSONDecoder().decode(NativeSnapshot.self, from: checked(await session.data(for: request)))
    }
    static func upload(_ url: URL, hash: String, secret: String) async throws {
        var request = request("frames", method: "POST", secret: secret)
        request.setValue("image/jpeg", forHTTPHeaderField: "Content-Type")
        request.setValue(hash, forHTTPHeaderField: "X-Content-SHA256")
        _ = try checked(await session.upload(for: request, fromFile: url))
    }
    static func finalize(_ secret: String) async throws {
        _ = try checked(await session.data(for: request("finalize", method: "POST", secret: secret)))
    }    static func reconstruction(_ secret: String, start: Bool = false) async throws -> ReconstructionSnapshot {
        if start { _ = try checked(await session.data(for: request("reconstruction", method: "POST", secret: secret))) }
        return try JSONDecoder().decode(ReconstructionSnapshot.self, from: checked(await session.data(for: request("reconstruction", secret: secret))))
    }
    static func download(_ job: String, secret: String, record: CaptureRecord) async throws -> URL {
        guard UUID(uuidString: job) != nil else { throw CaptureProblem("Invalid model reference.") }
        let folder = CaptureFiles.root(record).appendingPathComponent("Outputs/Remote-" + job, isDirectory: true)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let pending = folder.appendingPathComponent(UUID().uuidString + ".partial")
        FileManager.default.createFile(atPath: pending.path, contents: nil)
        let handle = try FileHandle(forWritingTo: pending)
        defer { try? handle.close(); try? FileManager.default.removeItem(at: pending) }
        var hash = SHA256(), total = 0, expectedBytes = 0, expectedHash = "", parts = 1
        var index = 0
        while index < parts {
            try Task.checkCancellation()
            let response = try await session.data(for: request("reconstruction/" + job + "/usdz?part=\(index)", secret: secret))
            let bytes = try checked(response)
            guard let http = response.1 as? HTTPURLResponse,
                  let count = Int(http.value(forHTTPHeaderField: "X-Artifact-Parts") ?? ""), (1...128).contains(count),
                  let size = Int(http.value(forHTTPHeaderField: "X-Artifact-Bytes") ?? ""), size > 0, size <= 128 * 1024 * 1024,
                  let checksum = http.value(forHTTPHeaderField: "X-Artifact-SHA256"), bytes.count <= 1024 * 1024 else {
                throw CaptureProblem("The model download could not be verified.")
            }
            if index == 0 { parts = count; expectedBytes = size; expectedHash = checksum }
            guard parts == count, expectedBytes == size, expectedHash == checksum else { throw CaptureProblem("The model changed during download. Please retry.") }
            try handle.write(contentsOf: bytes)
            hash.update(data: bytes); total += bytes.count; index += 1
        }
        guard total == expectedBytes, hash.finalize().map({ String(format: "%02x", $0) }).joined() == expectedHash else {
            throw CaptureProblem("The model download could not be verified.")
        }
        try handle.close()
        let output = folder.appendingPathComponent(UUID().uuidString + ".usdz")
        try FileManager.default.moveItem(at: pending, to: output)
        return output
    }

}

private enum UploadCopy {
    static func prepare(_ original: URL, capture: UUID) throws -> (URL, String) {
        try autoreleasepool {
            let root = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
                .appendingPathComponent("UploadCopies/" + capture.uuidString, isDirectory: true)
            try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
            // Content identity invalidates a cached copy if an original was edited through Files.
            let sourceHash = try hashFile(original)
            let copy = root.appendingPathComponent(sourceHash + "-1920-v1.jpg")
            if !FileManager.default.fileExists(atPath: copy.path) {
                guard let source = CGImageSourceCreateWithURL(original as CFURL, [kCGImageSourceShouldCache: false] as CFDictionary),
                      let image = CGImageSourceCreateThumbnailAtIndex(source, 0, [kCGImageSourceCreateThumbnailFromImageAlways: true,
                        kCGImageSourceThumbnailMaxPixelSize: 1920, kCGImageSourceCreateThumbnailWithTransform: true,
                        kCGImageSourceShouldCacheImmediately: true] as CFDictionary) else { throw CaptureProblem("One saved photo could not be read. Originals are preserved.") }
                var encoded: Data?
                for quality in [0.85, 0.7, 0.55] {
                    let output = NSMutableData()
                    guard let destination = CGImageDestinationCreateWithData(output, UTType.jpeg.identifier as CFString, 1, nil) else { throw CaptureProblem("Could not prepare a JPEG copy.") }
                    CGImageDestinationAddImage(destination, image, [kCGImageDestinationLossyCompressionQuality: quality] as CFDictionary)
                    guard CGImageDestinationFinalize(destination) else { throw CaptureProblem("Could not save a JPEG copy.") }
                    if output.length <= 3 * 1024 * 1024 { encoded = output as Data; break }
                }
                guard let encoded else { throw CaptureProblem("A photo is too large for transfer. Export the original capture instead.") }
                try encoded.write(to: copy, options: .atomic)
            }
            return (copy, try hashFile(copy))
        }
    }
    static func hashFile(_ url: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var hash = SHA256()
        while let bytes = try handle.read(upToCount: 1_048_576), !bytes.isEmpty { hash.update(data: bytes) }
        return hash.finalize().map { String(format: "%02x", $0) }.joined()
    }
}

@MainActor
final class CaptureTransfer: ObservableObject {
    @Published var code = ""
    @Published var snapshot: NativeSnapshot?
    @Published var busy = false
    @Published var status = ""
    @Published var completed = 0
    @Published var total = 0
    @Published var readyToFinalize = false
    @Published var remoteState = ""
    @Published var modelURL: URL?
    var onModel: ((URL) -> Void)?
    private var task: Task<Void, Never>?
    private var selected: UUID?

    func select(_ record: CaptureRecord?) {
        guard !busy, selected != record?.id else { return }
        selected = record?.id
        snapshot = nil; modelURL = nil; remoteState = ""; completed = 0; total = 0; readyToFinalize = false; status = ""
        guard let record else { return }
        do {
            let credential = try CaptureKeychain.load(record.id)
            snapshot = credential?.snapshot
            if snapshot == nil, let pending = credential?.code { code = pending }
        } catch { status = error.localizedDescription }
    }
    func receive(_ url: URL) {
        guard !busy, url.scheme == "dishplaycapture", url.host == "pair",
              let value = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?.first(where: { $0.name == "code" })?.value,
              value.replacingOccurrences(of: "-", with: "").range(of: "^[A-Fa-f0-9]{16}$", options: .regularExpression) != nil else { return }
        code = value
        status = "Association code received. Open or capture a series, then choose Pair with website. No photos have been sent."
    }
    func pair(_ record: CaptureRecord, onPaired: @escaping (String) -> Void) {
        guard !busy, snapshot == nil else { return }
        let normalized = code.replacingOccurrences(of: "-", with: "").replacingOccurrences(of: " ", with: "").uppercased()
        guard normalized.range(of: "^[A-F0-9]{16}$", options: .regularExpression) != nil else { status = "Enter the 16-character code from the dish page."; return }
        run {
            var credential: CaptureCredential
            if let saved = try CaptureKeychain.load(record.id), saved.code == normalized { credential = saved }
            else {
                credential = CaptureCredential(code: normalized, secret: try CaptureKeychain.randomSecret())
                // Persist before requesting so a lost response can be retried with the same secret.
                try CaptureKeychain.save(credential, id: record.id)
            }
            let received = try await NativeAPI.pair(credential)
            credential.snapshot = received
            try CaptureKeychain.save(credential, id: record.id)
            self.snapshot = received
            onPaired(received.scan.id)
            self.status = "Check the restaurant and dish below before sending. No photos have been sent."
        }
    }
    func upload(_ record: CaptureRecord) {
        guard !busy, snapshot != nil else { return }
        readyToFinalize = false
        run {
            guard var credential = try CaptureKeychain.load(record.id) else { throw CaptureProblem("Pair this capture again from the website.") }
            var received = try await NativeAPI.snapshot(credential.secret)
            self.snapshot = received
            credential.snapshot = received
            try CaptureKeychain.save(credential, id: record.id)
            if received.scan.state == "finalized" {
                try await self.track(credential, record: record)
                return
            }
            guard received.scan.state == "capturing" else { throw CaptureProblem("This series was cancelled. Your photos remain saved.") }
            let files = CaptureFiles.photos(record)
            guard !files.isEmpty, files.count <= 150 else { throw CaptureProblem("A transfer requires between 1 and 150 saved photos.") }
            self.total = files.count; self.completed = 0
            var known = Set(received.hashes)
            for (index, file) in files.enumerated() {
                try Task.checkCancellation()
                let (copy, hash) = try await Task.detached(priority: .utility) { try UploadCopy.prepare(file, capture: record.id) }.value
                try Task.checkCancellation()
                if !known.contains(hash) {
                    try await NativeAPI.upload(copy, hash: hash, secret: credential.secret)
                    known.insert(hash)
                }
                self.completed = index + 1
            }
            received = try await NativeAPI.snapshot(credential.secret)
            credential.snapshot = received
            try CaptureKeychain.save(credential, id: record.id)
            self.snapshot = received
            self.readyToFinalize = received.scan.state == "capturing" && received.hashes.count >= 3
            guard self.readyToFinalize else { throw CaptureProblem("More overlapping views are needed. Your photos remain saved.") }
            try await NativeAPI.finalize(credential.secret)
            received = try await NativeAPI.snapshot(credential.secret)
            credential.snapshot = received
            try CaptureKeychain.save(credential, id: record.id)
            self.snapshot = received
            self.readyToFinalize = false
            try await self.track(credential, record: record)
        }
    }
    func finalize(_ record: CaptureRecord) {
        guard !busy, readyToFinalize else { return }
        run {
            guard var credential = try CaptureKeychain.load(record.id) else { throw CaptureProblem("Capture association unavailable.") }
            try await NativeAPI.finalize(credential.secret)
            let received = try await NativeAPI.snapshot(credential.secret)
            credential.snapshot = received
            try CaptureKeychain.save(credential, id: record.id)
            self.snapshot = received
            self.readyToFinalize = false
            self.status = "Series finalized on the website. Review the photos there; a model still needs reconstruction and review."
        }
    }
    private func track(_ credential: CaptureCredential, record: CaptureRecord) async throws {
        var state = try await NativeAPI.reconstruction(credential.secret, start: true)
        while true {
            try Task.checkCancellation()
            guard let job = state.job else {
                remoteState = "unavailable"
                status = state.enabled ? "The scan is saved, but reconstruction could not start. Check the capture on DishPlay." : "Photos are saved. Connect the DishPlay service on your PC to enable reconstruction."
                return
            }
            remoteState = job.state
            switch job.state {
            case "ready_for_review":
                status = "Your 3D model is ready. Downloading…"
                let url = try await NativeAPI.download(job.id, secret: credential.secret, record: record)
                self.modelURL = url
                onModel?(url)
                status = "Your 3D model is ready. Rotate it and check the result."
                return
            case "failed", "cancelled":
                status = "Reconstruction stopped. Your photos are saved. Check the result on DishPlay before trying again."
                return
            case "queued":
                status = state.workerAvailable ? "Your scan is waiting for its turn on your PC." : "Waiting for your PC. Keep it on, connected, with DishPlay running and enough free memory."
            default:
                status = "Your PC is reconstructing the dish. You can check the result here or on DishPlay."
            }
            try await Task.sleep(for: .seconds(10))
            state = try await NativeAPI.reconstruction(credential.secret)
        }
    }
    func forget(_ record: CaptureRecord) {
        guard !busy else { return }
        do {
            try CaptureKeychain.remove(record.id)
            snapshot = nil; code = ""; readyToFinalize = false
            status = "Local association removed. Revoke its access on the website if needed. Saved photos remain in both places."
        } catch { status = error.localizedDescription }
    }
    func pause() { task?.cancel() }
    private func run(_ work: @escaping @MainActor () async throws -> Void) {
        busy = true; status = ""
        task = Task {
            defer { busy = false; task = nil }
            do { try await work() }
            catch {
                status = Task.isCancelled ? "Transfer paused. Resume to skip photos already received. Originals are preserved." : error.localizedDescription
            }
        }
    }
}
