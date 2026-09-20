import AVFoundation
import Combine
import SwiftUI
import UIKit

private enum RecordingEvent: Sendable {
    case ready, recording(Date), finishing, saved(URL), problem(String)
}

/// All session configuration and recording operations stay on one queue, off the UI thread.
/// No microphone input is installed: the source movie contains video only.
private final class VideoRecordingEngine: NSObject, AVCaptureFileOutputRecordingDelegate, @unchecked Sendable {
    let session = AVCaptureSession()
    private let output = AVCaptureMovieFileOutput()
    private let queue = DispatchQueue(label: "app.dishplay.video-camera", qos: .userInitiated)
    private let event: @Sendable (RecordingEvent) -> Void
    private var configured = false
    private var closed = false
    private var finishing = false
    private var observers: [NSObjectProtocol] = []

    init(event: @escaping @Sendable (RecordingEvent) -> Void) {
        self.event = event
        super.init()
        for name in [AVCaptureSession.wasInterruptedNotification, AVCaptureSession.runtimeErrorNotification] {
            observers.append(NotificationCenter.default.addObserver(forName: name, object: session, queue: nil) { [weak self] _ in
                guard let self else { return }
                self.queue.async {
                    if self.output.isRecording { self.finishRecording() }
                    else if !self.finishing && !self.closed {
                        self.event(.problem("Camera interrupted. Close the camera and open it again. Your saved captures are preserved."))
                    }
                }
            })
        }
    }
    deinit { observers.forEach { NotificationCenter.default.removeObserver($0) } }

    func start() {
        queue.async { [self] in
            guard !closed, !configured else { return }
            session.beginConfiguration()
            do {
                guard let device = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back) else {
                    throw VideoPreparationError.unreadable
                }
                let input = try AVCaptureDeviceInput(device: device)
                guard session.canAddInput(input), session.canAddOutput(output) else { throw VideoPreparationError.unreadable }
                session.sessionPreset = session.canSetSessionPreset(.hd1920x1080) ? .hd1920x1080 : .high
                session.addInput(input)
                session.addOutput(output)
                try device.lockForConfiguration()
                if device.isFocusModeSupported(.continuousAutoFocus) { device.focusMode = .continuousAutoFocus }
                if device.isExposureModeSupported(.continuousAutoExposure) { device.exposureMode = .continuousAutoExposure }
                if device.activeFormat.videoSupportedFrameRateRanges.contains(where: { $0.minFrameRate <= 30 && $0.maxFrameRate >= 30 }) {
                    device.activeVideoMinFrameDuration = CMTime(value: 1, timescale: 30)
                    device.activeVideoMaxFrameDuration = CMTime(value: 1, timescale: 30)
                }
                device.unlockForConfiguration()
                output.maxRecordedDuration = CMTime(seconds: 60, preferredTimescale: 600)
                output.maxRecordedFileSize = 180 * 1024 * 1024
                if let connection = output.connection(with: .video), output.availableVideoCodecTypes.contains(.h264) {
                    output.setOutputSettings([AVVideoCodecKey: AVVideoCodecType.h264], for: connection)
                    if connection.isVideoStabilizationSupported { connection.preferredVideoStabilizationMode = .standard }
                }
                configured = true
                session.commitConfiguration()
                session.startRunning()
                event(session.isRunning ? .ready : .problem("The camera could not start. Close it and try again, or import a video."))
            } catch {
                session.commitConfiguration()
                event(.problem("The camera could not start. Close it and try again, or import a video."))
            }
        }
    }
    func record(rotation: CGFloat) {
        queue.async { [self] in
            guard !closed, !finishing, !output.isRecording else { return }
            guard configured, session.isRunning else {
                event(.problem("The camera could not start. Close it and try again, or import a video."))
                return
            }
            if let connection = output.connection(with: .video), connection.isVideoRotationAngleSupported(rotation) {
                connection.videoRotationAngle = rotation
            }
            let url = FileManager.default.temporaryDirectory.appendingPathComponent("DishPlay-" + UUID().uuidString + ".mov")
            output.startRecording(to: url, recordingDelegate: self)
        }
    }
    func stop() { queue.async { [self] in finishRecording() } }
    private func finishRecording() {
        guard output.isRecording, !finishing else { return }
        finishing = true
        event(.finishing)
        output.stopRecording()
    }
    func shutdown() {
        queue.async { [self] in
            closed = true
            finishRecording()
            if session.isRunning { session.stopRunning() }
        }
    }
    func fileOutput(_ output: AVCaptureFileOutput, didStartRecordingTo fileURL: URL, from connections: [AVCaptureConnection]) {
        event(.recording(Date()))
    }
    func fileOutput(_ output: AVCaptureFileOutput, didFinishRecordingTo fileURL: URL, from connections: [AVCaptureConnection], error: Error?) {
        queue.async { [self] in
            finishing = false
            let successful = error == nil || ((error as NSError?)?.userInfo[AVErrorRecordingSuccessfullyFinishedKey] as? Bool == true)
            let exists = ((try? fileURL.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0) > 0
            if successful && exists { event(.saved(fileURL)) }
            else { event(.problem("The recording could not be saved. Free some storage and try again, or import a video.")) }
            if session.isRunning { session.stopRunning() }
        }
    }
}

@MainActor
private final class VideoRecorder: ObservableObject {
    enum Phase { case loading, ready, starting, recording, finishing, saved, failed }
    @Published var phase: Phase = .loading
    @Published var startedAt: Date?
    @Published var savedURL: URL?
    @Published var problem = ""
    @Published var denied = false
    private var closed = false
    private lazy var engine: VideoRecordingEngine = VideoRecordingEngine { [weak self] event in
        Task { @MainActor in
            guard let self else { return }
            switch event {
            case .ready: self.phase = .ready
            case .recording(let date):
                self.startedAt = date; self.phase = .recording
                if self.closed || UIApplication.shared.applicationState != .active { self.engine.stop() }
            case .finishing: self.phase = .finishing
            case .saved(let url): self.savedURL = url; self.phase = .saved
            case .problem(let message): self.problem = message; self.phase = .failed
            }
        }
    }
    var session: AVCaptureSession { engine.session }
    func start() async {
        guard phase == .loading else { return }
        let allowed = await AVCaptureDevice.requestAccess(for: .video)
        guard !closed else { return }
        if allowed { engine.start() }
        else {
            denied = true; phase = .failed
            problem = "Camera access is off. Allow it in Settings, or close this screen to import a video."
        }
    }
    func record() {
        guard phase == .ready else { return }
        phase = .starting
        let rotation: CGFloat
        switch UIDevice.current.orientation {
        case .landscapeLeft: rotation = 0
        case .landscapeRight: rotation = 180
        case .portraitUpsideDown: rotation = 270
        default: rotation = 90
        }
        engine.record(rotation: rotation)
    }
    func stop() { engine.stop() }
    func shutdown() { closed = true; engine.shutdown() }
}

private struct VideoCameraPreview: UIViewRepresentable {
    let session: AVCaptureSession
    final class Preview: UIView {
        override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }
        var preview: AVCaptureVideoPreviewLayer { layer as! AVCaptureVideoPreviewLayer }
        override func layoutSubviews() {
            super.layoutSubviews()
            let angle: CGFloat
            switch window?.windowScene?.interfaceOrientation {
            case .landscapeRight: angle = 0
            case .landscapeLeft: angle = 180
            case .portraitUpsideDown: angle = 270
            default: angle = 90
            }
            if let connection = preview.connection, connection.isVideoRotationAngleSupported(angle) { connection.videoRotationAngle = angle }
        }
    }
    func makeUIView(context: Context) -> Preview {
        let view = Preview()
        view.preview.session = session
        view.preview.videoGravity = .resizeAspect
        return view
    }
    func updateUIView(_ view: Preview, context: Context) { view.setNeedsLayout() }
}

struct VideoCaptureScreen: View {
    var onSaved: (URL) -> Void
    @StateObject private var recorder = VideoRecorder()
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        GeometryReader { geometry in
            ScrollView {
                VStack(spacing: 18) {
                    HStack {
                        Text("Film your dish").font(.title2.bold())
                        Spacer()
                        Button("Close", systemImage: "xmark") { dismiss() }
                            .labelStyle(.iconOnly)
                            .disabled([.starting, .recording, .finishing].contains(recorder.phase))
                    }
                    VideoCameraPreview(session: recorder.session)
                        .frame(height: max(200, min(480, geometry.size.height * 0.48)))
                        .clipShape(RoundedRectangle(cornerRadius: 24))
                        .overlay(alignment: .topLeading) {
                            Label("Keep the whole plate in view", systemImage: "viewfinder")
                                .font(.caption).padding(10).background(.black.opacity(0.7), in: Capsule()).padding(12)
                        }.accessibilityLabel("Camera preview")
                    if recorder.phase == .failed {
                        Text(LocalizedStringKey(recorder.problem)).multilineTextAlignment(.center)
                        if recorder.denied {
                            Link("Open Settings", destination: URL(string: UIApplication.openSettingsURLString)!)
                        }
                    } else if [.loading, .starting, .finishing, .saved].contains(recorder.phase) {
                        ProgressView(recorder.phase == .finishing || recorder.phase == .saved ? "Saving your video…" : "Opening camera…")
                    } else if let start = recorder.startedAt, recorder.phase == .recording {
                        TimelineView(.periodic(from: .now, by: 1)) { timeline in
                            let elapsed = max(0, Int(timeline.date.timeIntervalSince(start)))
                            VStack(spacing: 8) {
                                Text(String(format: "%02d:%02d", elapsed / 60, elapsed % 60)).monospacedDigit().font(.title.bold())
                                Text(elapsed < 25 ? "Walk slowly around the plate. Keep it still and in view." : "Finish with a slightly higher view, then tap Stop.")
                                    .multilineTextAlignment(.center)
                            }
                        }
                    } else {
                        VStack(alignment: .leading, spacing: 10) {
                            Label("Place the dish in good light and leave it still.", systemImage: "sun.max")
                            Label("Press Record. Walk slowly around it for 20–40 seconds.", systemImage: "arrow.triangle.2.circlepath")
                            Label("Finish slightly higher to see the top, then press Stop.", systemImage: "arrow.up.right")
                        }.font(.callout)
                    }
                    Text("Video only, without sound. Recording stops after 60 seconds. Keep the phone in the same orientation.")
                        .font(.footnote).foregroundStyle(.secondary).multilineTextAlignment(.center)
                }.padding(20).frame(maxWidth: 650).frame(maxWidth: .infinity)
            }
        }
            .safeAreaInset(edge: .bottom, spacing: 0) {
                if recorder.phase == .ready || recorder.phase == .recording {
                    Button {
                        if recorder.phase == .recording { recorder.stop() } else { recorder.record() }
                    } label: {
                        Label(recorder.phase == .recording ? "Stop and use video" : "Record", systemImage: recorder.phase == .recording ? "stop.fill" : "record.circle")
                            .font(.headline).frame(maxWidth: .infinity).padding(.vertical, 14)
                    }.buttonStyle(.borderedProminent).tint(.red)
                        .padding(20).frame(maxWidth: 650).frame(maxWidth: .infinity).background(.black)
                }
            }
            .background(.black).foregroundStyle(.white).preferredColorScheme(.dark)
            .task { await recorder.start() }
            .onDisappear { recorder.shutdown() }
            .onChange(of: recorder.savedURL) { _, url in
                guard let url else { return }
                onSaved(url)
                dismiss()
            }
            .onChange(of: scenePhase) { _, phase in if phase != .active { recorder.stop() } }
            .interactiveDismissDisabled()
    }
}
