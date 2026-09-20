import AVFoundation
import Combine
import Foundation
import RealityKit
import SwiftUI
import UIKit
import PhotosUI
import ImageIO
import UniformTypeIdentifiers

enum CapturePhase: String {
    case idle, preparing, ready, detecting, capturing, finishing, review, processing, failed
}
struct ExportFile: Identifiable {
    let id = UUID()
    let url: URL
}

@MainActor
final class CaptureModel: ObservableObject {
    @Published var phase: CapturePhase = .idle
    @Published var captureSession: ObjectCaptureSession?
    @Published var record: CaptureRecord?
    @Published var library: [CaptureRecord] = CaptureFiles.library()
    @Published var dishReference = ""
    @Published var message = "Keep the dish still. Walk around it at different heights; never turn it over."
    @Published var imageCount = 0
    @Published var isPaused = false
    @Published var passComplete = false
    @Published var currentPass = 1
    @Published var feedback = ""
    @Published var sdkProgress: Double?
    @Published var showCamera = false
    @Published var exporting = false
    @Published var exportFile: ExportFile?
    @Published var previewURL: URL?
    @Published var cameraDenied = false
    @Published var videoProgress: Double?

    let nativeSupported = ObjectCaptureSession.isSupported
    let reconstructionSupported = PhotogrammetrySession.isSupported
    private var observers: [Task<Void, Never>] = []
    private var reconstruction: PhotogrammetrySession?
    private var reconstructionTask: Task<Void, Never>?

    var busy: Bool { captureSession != nil || phase == .preparing || phase == .processing || exporting || showCamera }
    var savedModel: URL? {
        guard let record, let path = record.modelPath else { return nil }
        let url = CaptureFiles.root(record).appendingPathComponent(path)
        return FileManager.default.fileExists(atPath: url.path) ? url : nil
    }
    var savedVideo: URL? {
        guard let record, let path = record.sourceVideoPath else { return nil }
        let url = CaptureFiles.root(record).appendingPathComponent(path)
        return FileManager.default.fileExists(atPath: url.path) ? url : nil
    }

    func prepareAutomatic(mode: String = "arkit-guided") -> CaptureRecord? {
        guard !busy else { return nil }
        if var current = record, current.sourceVideoPath == nil, CaptureFiles.photos(current).isEmpty {
            current.mode = mode
            record = current
            persist(state: current.state)
            return current
        }
        do {
            let fresh = CaptureRecord(id: UUID(), createdAt: Date(), dishReference: String(dishReference.prefix(120)),
                mode: mode, state: "ready", device: UIDevice.current.model, systemVersion: UIDevice.current.systemVersion)
            try CaptureFiles.create(fresh)
            record = fresh; imageCount = 0; phase = .review; sdkProgress = nil
            message = "Your dish is ready to scan. Good views are saved automatically."
            library = CaptureFiles.library()
            return fresh
        } catch { fail(error); return nil }
    }
    func refreshAutomatic() {
        guard let record else { return }
        imageCount = CaptureFiles.photos(record).count
        phase = .review
        persist(state: imageCount > 0 ? "captured" : "ready")
        message = imageCount > 0 ? "Scan saved. Continue to send it and create your 3D model." : "Your dish is ready to scan. Good views are saved automatically."
    }
    func importPhotos(_ items: [PhotosPickerItem], completed: @escaping () -> Void) {
        guard !busy, !items.isEmpty, let record = prepareAutomatic(mode: "photo-import") else { return }
        phase = .preparing
        message = "Preparing selected photos…"
        Task {
            do {
                for item in items {
                    guard let data = try await item.loadTransferable(type: Data.self), data.count <= 25 * 1024 * 1024 else {
                        throw CaptureProblem("One selected photo could not be read. Saved originals remain available.")
                    }
                    let destination = CaptureFiles.images(record).appendingPathComponent(UUID().uuidString + ".jpg")
                    try await Task.detached(priority: .utility) {
                        try autoreleasepool {
                            guard let source = CGImageSourceCreateWithData(data as CFData, [kCGImageSourceShouldCache: false] as CFDictionary),
                                  let image = CGImageSourceCreateThumbnailAtIndex(source, 0, [kCGImageSourceCreateThumbnailFromImageAlways: true,
                                      kCGImageSourceThumbnailMaxPixelSize: 1920, kCGImageSourceCreateThumbnailWithTransform: true] as CFDictionary),
                                  let encoder = CGImageDestinationCreateWithURL(destination as CFURL, UTType.jpeg.identifier as CFString, 1, nil) else {
                                throw CaptureProblem("One selected photo could not be read. Saved originals remain available.")
                            }
                            CGImageDestinationAddImage(encoder, image, [kCGImageDestinationLossyCompressionQuality: 0.9] as CFDictionary)
                            guard CGImageDestinationFinalize(encoder) else { throw CaptureProblem("Could not save a JPEG copy.") }
                        }
                    }.value
                }
                refreshAutomatic()
                completed()
            } catch { refreshAutomatic(); fail(error) }
        }
    }

    func importVideo(_ item: PhotosPickerItem, completed: @escaping (Bool) -> Void) {
        guard !busy else { return }
        phase = .preparing; videoProgress = nil
        message = "Opening selected video…"
        Task {
            do {
                guard let imported = try await item.loadTransferable(type: ImportedVideo.self) else { throw VideoPreparationError.unreadable }
                phase = .review
                acceptVideo(imported.url, completed: completed)
            } catch {
                videoFailed(error, updateRecord: false)
                completed(false)
            }
        }
    }
    func acceptVideo(_ url: URL, completed: @escaping (Bool) -> Void) {
        guard !busy, var current = prepareAutomatic(mode: "video") else { completed(false); return }
        do {
            try VideoFrameExtractor.validateSize(url)
            let filename = "original." + (url.pathExtension.isEmpty ? "mov" : url.pathExtension)
            let destination = CaptureFiles.root(current).appendingPathComponent(filename)
            // Both recording and PhotosPicker provide an app-owned file, not the user's library original.
            try FileManager.default.moveItem(at: url, to: destination)
            current.sourceVideoPath = filename
            current.state = "video-saved"
            record = current
            try CaptureFiles.save(current)
            library = CaptureFiles.library()
            prepareSavedVideo(completed: completed)
        } catch { videoFailed(error); completed(false) }
    }
    func prepareSavedVideo(completed: @escaping (Bool) -> Void) {
        guard !busy, let current = record, let source = savedVideo, imageCount == 0 else { completed(false); return }
        phase = .preparing; videoProgress = 0
        message = "Preparing photos from your video…"
        persist(state: "preparing-video")
        let destination = CaptureFiles.images(current)
        Task {
            do {
                _ = try await Task.detached(priority: .utility) { [self] in
                    try await VideoFrameExtractor.extract(from: source, to: destination) { fraction in
                        await self.updateVideoProgress(fraction)
                    }
                }.value
                videoProgress = nil
                refreshAutomatic()
                message = "Video prepared. Your original stays on this iPhone; only the selected photos are sent."
                completed(true)
            } catch {
                videoFailed(error)
                completed(false)
            }
        }
    }
    private func updateVideoProgress(_ fraction: Double) { videoProgress = fraction }
    private func videoFailed(_ error: Error, updateRecord: Bool = true) {
        phase = .failed; videoProgress = nil
        message = (error as? VideoPreparationError)?.message ?? VideoPreparationError.saveFailed.message
        if updateRecord, var current = record { current.error = message; record = current; persist(state: "video-failed") }
    }

    func start(native: Bool) {
        guard !busy else { return }
        phase = .preparing
        Task {
            let granted: Bool
            switch AVCaptureDevice.authorizationStatus(for: .video) {
            case .authorized: granted = true
            case .notDetermined: granted = await AVCaptureDevice.requestAccess(for: .video)
            default: granted = false
            }
            guard granted else {
                cameraDenied = true
                phase = .idle
                message = "Camera access is off. Enable it in Settings, then try again. Existing captures are preserved."
                return
            }
            do {
                cameraDenied = false
                guard UIImagePickerController.isSourceTypeAvailable(.camera) else {
                    throw CaptureProblem("No camera is available on this device. Use a physical iPhone or iPad.")
                }
                let newRecord = CaptureRecord(id: UUID(), createdAt: Date(), dishReference: String(dishReference.prefix(120)),
                    mode: native && nativeSupported ? "apple-object-capture" : "native-photos",
                    state: "preparing", device: UIDevice.current.model, systemVersion: UIDevice.current.systemVersion)
                try CaptureFiles.create(newRecord)
                record = newRecord
                imageCount = 0
                sdkProgress = nil
                feedback = ""
                passComplete = false
                currentPass = 1
                isPaused = false
                if native && nativeSupported {
                    let session = ObjectCaptureSession()
                    captureSession = session
                    observe(session)
                    var configuration = ObjectCaptureSession.Configuration()
                    configuration.checkpointDirectory = CaptureFiles.checkpoints(newRecord)
                    configuration.isOverCaptureEnabled = false
                    session.start(imagesDirectory: CaptureFiles.images(newRecord), configuration: configuration)
                } else {
                    phase = .review
                    persist(state: "photos")
                    message = "Take overlapping photos around the stationary dish at three heights. This mode has no spatial cube or point cloud."
                    showCamera = true
                }
            } catch { fail(error) }
        }
    }

    private func observe(_ session: ObjectCaptureSession) {
        observers.forEach { $0.cancel() }
        observers = [
            Task { [weak self] in
                self?.handle(session.state)
                for await state in session.stateUpdates {
                    guard !Task.isCancelled, let self else { return }
                    self.handle(state)
                    if case .completed = state { return }
                    if case .failed = state { return }
                }
            },
            Task { [weak self] in
                for await count in session.numberOfShotsTakenUpdates {
                    guard !Task.isCancelled, let self else { return }
                    self.imageCount = count
                    if var record = self.record { record.imageCount = count; self.record = record }
                    self.persist(state: self.phase.rawValue)
                    if count >= min(150, session.maximumNumberOfInputImages), session.state == .capturing {
                        session.finish()
                    }
                }
            },
            Task { [weak self] in
                for await paused in session.isPausedUpdates {
                    guard !Task.isCancelled else { return }
                    self?.isPaused = paused
                }
            },
            Task { [weak self] in
                for await complete in session.userCompletedScanPassUpdates {
                    guard !Task.isCancelled else { return }
                    self?.passComplete = complete
                    if complete, session.state == .capturing {
                        session.pause()
                        self?.message = self?.currentPass == 3 ? "Third pass complete. Finish to save the capture." : "Pass complete. Raise the phone for the next view, then continue. Keep the dish still."
                    }
                }
            },
            Task { [weak self] in
                for await values in session.feedbackUpdates {
                    guard !Task.isCancelled else { return }
                    if values.contains(.movingTooFast) { self?.feedback = "Move more slowly." }
                    else if values.contains(.environmentTooDark) || values.contains(.environmentLowLight) { self?.feedback = "Use brighter, diffuse lighting." }
                    else if values.contains(.objectTooClose) { self?.feedback = "Move a little farther away." }
                    else if values.contains(.objectTooFar) { self?.feedback = "Move a little closer." }
                    else if values.contains(.outOfFieldOfView) { self?.feedback = "Keep the whole dish inside the frame." }
                    else { self?.feedback = "" }
                }
            }
        ]
    }

    private func handle(_ state: ObjectCaptureSession.CaptureState) {
        switch state {
        case .initializing: phase = .preparing
        case .ready:
            phase = .ready
            message = "Aim at the dish and move gently until the table can be detected."
        case .detecting:
            phase = .detecting
            message = "Adjust the native volume to include the dish and its plate or bowl."
        case .capturing:
            phase = .capturing
            message = "Walk around the dish. Complete more views from a different height without moving the food."
        case .finishing:
            phase = .finishing
            message = "Saving the actual capture. Keep the app open."
        case .completed:
            stopObservers()
            captureSession = nil // The SDK has finished writing before teardown or reconstruction.
            phase = .review
            if let record { imageCount = CaptureFiles.photos(record).count }
            message = "Capture saved. Review the photos or reconstruct on this device when supported."
        case .failed(let error):
            stopObservers()
            captureSession = nil
            fail(error)
        @unknown default:
            message = "The capture SDK reported an unknown state. Keep this capture and start a new session if needed."
        }
        persist(state: phase.rawValue)
    }

    func detect() {
        guard let session = captureSession, session.state == .ready else { return }
        if !session.startDetecting() {
            message = "The table was not detected. Move gently, improve the lighting, then try again."
        }
    }
    func beginCapture() {
        guard let session = captureSession, session.state == .detecting else { return }
        session.startCapturing()
    }
    func resetDetection() {
        guard let session = captureSession, session.state == .detecting else { return }
        session.resetDetection()
    }
    func togglePause() {
        guard let session = captureSession, session.state == .capturing else { return }
        if session.isPaused { session.resume() } else { session.pause() }
    }
    func newHeight() {
        guard let session = captureSession, session.state == .capturing,
              session.userCompletedScanPass, currentPass < 3 else { return }
        currentPass += 1
        passComplete = false
        session.beginNewScanPass() // Deliberately never calls beginNewScanPassAfterFlip for food.
        session.resume()
        message = currentPass == 2 ? "Second pass: raise the phone to an oblique view. Keep the plate centered and walk around it." : "Third pass: look down into the dish from above. Walk around it without moving the food."
    }
    func finish() {
        guard let session = captureSession, session.state == .capturing else { return }
        session.finish()
    }
    func cancelCapture() {
        captureSession?.cancel() // A terminal SDK event drives teardown; no originals are removed.
    }
    func pauseForInterruption() {
        guard let session = captureSession, session.state == .capturing else { return }
        session.pause()
        message = "Capture paused after leaving the app. Return to the previous view and choose Resume."
        persist(state: "paused")
    }

    func addPhoto() {
        guard let record, record.mode == "native-photos", !busy, imageCount < 150 else { return }
        showCamera = true
    }
    func savePhoto(_ image: UIImage) {
        guard let record else { return }
        do {
            guard let bytes = image.jpegData(compressionQuality: 0.95) else { throw CaptureProblem("The camera photo could not be encoded.") }
            let url = CaptureFiles.images(record).appendingPathComponent(UUID().uuidString + ".jpg")
            try bytes.write(to: url, options: .atomic)
            imageCount = CaptureFiles.photos(record).count
            phase = .review
            persist(state: "photos")
            message = "Photo saved. Move to the next overlapping view. Native photo mode records no camera poses or depth."
        } catch { fail(error) }
        showCamera = false
    }

    func open(_ saved: CaptureRecord) {
        guard !busy else { return }
        record = saved
        dishReference = saved.dishReference
        imageCount = CaptureFiles.photos(saved).count
        phase = .review
        sdkProgress = nil
        message = saved.mode == "apple-object-capture" ? "Saved capture opened. An interrupted spatial session requires a new capture; its old photos remain here." : "Saved photos opened. Add more views or export the originals."
    }

    func reconstruct() {
        guard !busy, reconstructionSupported, let record, imageCount >= 3 else { return }
        phase = .processing
        sdkProgress = nil
        message = "Reconstructing the saved observations. Progress comes from RealityKit."
        persist(state: "processing")
        reconstructionTask = Task {
            do {
                let runID = UUID().uuidString
                let folder = CaptureFiles.root(record).appendingPathComponent("Outputs/" + runID, isDirectory: true)
                try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
                let output = folder.appendingPathComponent("model.usdz")
                var configuration = PhotogrammetrySession.Configuration()
                if record.mode == "apple-object-capture" { configuration.checkpointDirectory = CaptureFiles.checkpoints(record) }
                let session = try PhotogrammetrySession(input: CaptureFiles.images(record), configuration: configuration)
                reconstruction = session
                var produced: URL?
                try session.process(requests: [.modelFile(url: output, detail: .reduced)])
                for try await update in session.outputs {
                    if Task.isCancelled { session.cancel(); return }
                    switch update {
                    case .requestProgress(_, let fraction):
                        if fraction.isFinite { sdkProgress = min(1, max(0, fraction)) }
                    case .requestComplete(_, let result):
                        if case .modelFile(let url) = result { produced = url }
                    case .requestError(_, let error): throw error
                    case .processingComplete:
                        guard let url = produced, url == output,
                              let size = try FileManager.default.attributesOfItem(atPath: url.path)[.size] as? NSNumber,
                              size.intValue > 0 else { throw CaptureProblem("RealityKit completed without a readable USDZ output.") }
                        if var current = self.record {
                            current.modelPath = "Outputs/\(runID)/model.usdz"
                            self.record = current
                        }
                        phase = .review
                        persist(state: "model-ready-for-review")
                        message = "A real USDZ was generated. Review texture, orientation and scale before publishing. GLB conversion remains a separate worker step."
                        reconstruction = nil
                        return
                    case .processingCancelled:
                        phase = .review
                        persist(state: "processing-cancelled")
                        message = "Reconstruction cancelled. All source photos and previous outputs remain saved."
                        reconstruction = nil
                        return
                    case .invalidSample(_, let reason): message = "RealityKit rejected a photo: \(reason). Originals remain saved."
                    case .skippedSample: message = "RealityKit skipped an input photo. The original remains saved."
                    default: break
                    }
                }
                throw CaptureProblem("Reconstruction ended before a completion event. Source photos remain saved.")
            } catch {
                reconstruction?.cancel()
                reconstruction = nil
                fail(error)
            }
        }
    }
    func cancelReconstruction() { reconstruction?.cancel() }

    func exportOriginals() {
        guard !busy, let record else { return }
        exporting = true
        Task {
            do {
                try CaptureFiles.save(record)
                let url = try await Task.detached(priority: .utility) { try CaptureFiles.archive(record) }.value
                exportFile = ExportFile(url: url)
            } catch { message = "Export failed: \(error.localizedDescription). The original capture remains saved." }
            exporting = false
        }
    }
    func exportModel() {
        guard let url = savedModel, !busy else { return }
        exportFile = ExportFile(url: url)
    }
    func receiveModel(_ url: URL) {
        guard var current = record else { return }
        let prefix = CaptureFiles.root(current).path + "/"
        guard url.path.hasPrefix(prefix) else { return }
        current.modelPath = String(url.path.dropFirst(prefix.count))
        record = current
        persist(state: "model-ready-for-review")
    }
    func markRemote(_ scanId: String?) {
        guard var current = record else { return }
        current.remoteScanId = scanId
        record = current
        persist(state: current.state)
    }
    private func stopObservers() { observers.forEach { $0.cancel() }; observers.removeAll() }
    private func persist(state: String) {
        guard var current = record else { return }
        current.state = state
        current.imageCount = imageCount
        record = current
        do { try CaptureFiles.save(current) }
        catch { message = "Could not save capture metadata: \(error.localizedDescription). Existing photos are still in Files." }
        library = CaptureFiles.library()
    }
    private func fail(_ error: Error) {
        phase = .failed
        message = "\(error.localizedDescription) Your saved photos and any previous model are preserved."
        if var current = record { current.error = error.localizedDescription; record = current }
        persist(state: "failed")
    }
}

struct CaptureProblem: LocalizedError {
    let description: String
    init(_ description: String) { self.description = description }
    var errorDescription: String? { description }
}
