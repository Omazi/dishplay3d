import QuickLook
import RealityKit
import SwiftUI
import UIKit

struct CaptureScreen: View {
    @ObservedObject var model: CaptureModel
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    Text("From your dish. From real observations.")
                        .font(.title2.bold())
                    Text("Capture stays on this device. Export to Files when you are ready.")
                        .foregroundStyle(.secondary)
                    if let session = model.captureSession {
                        ObjectCaptureView(session: session)
                            .frame(height: 390)
                            .clipShape(RoundedRectangle(cornerRadius: 20))
                            .accessibilityLabel("Native dish capture camera and adjustable spatial volume")
                        if model.phase == .capturing {
                            ObjectCapturePointCloudView(session: session)
                                .frame(height: 170)
                                .clipShape(RoundedRectangle(cornerRadius: 16))
                                .accessibilityLabel("Real points observed by the capture session")
                            Text("Observed points · \(model.imageCount) saved shots")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        nativeControls
                    } else if model.phase != .processing {
                        setup
                    }

                    Label(model.message, systemImage: model.phase == .failed ? "exclamationmark.triangle" : "info.circle")
                        .font(.callout)
                        .padding()
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color.blue.opacity(0.08), in: RoundedRectangle(cornerRadius: 16))
                        .accessibilityIdentifier("capture-status")
                    if !model.feedback.isEmpty {
                        Text(model.feedback).font(.headline).accessibilityAddTraits(.updatesFrequently)
                    }
                    if model.phase == .preparing || model.phase == .finishing {
                        ProgressView(model.phase == .finishing ? "Saving capture…" : "Preparing camera…")
                    }
                    if model.phase == .processing {
                        if let progress = model.sdkProgress {
                            ProgressView("RealityKit reconstruction", value: progress)
                            Text(progress, format: .percent.precision(.fractionLength(0)))
                                .monospacedDigit()
                        } else { ProgressView("Waiting for reconstruction progress…") }
                        Button("Cancel reconstruction", role: .cancel) { model.cancelReconstruction() }
                            .buttonStyle(.bordered)
                    }
                    if let record = model.record, model.captureSession == nil {
                        savedCapture(record)
                    }
                    if !model.library.isEmpty && !model.busy {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("Saved captures").font(.headline)
                            ForEach(model.library) { record in
                                Button {
                                    model.open(record)
                                } label: {
                                    VStack(alignment: .leading, spacing: 4) {
                                        Text(record.dishReference.isEmpty ? "Untitled dish" : record.dishReference)
                                        Text(record.createdAt, format: .dateTime.month().day().hour().minute())
                                            .font(.caption).foregroundStyle(.secondary)
                                        Text("\(record.imageCount) photos · \(record.mode == "apple-object-capture" ? "Object Capture" : "Photos")")
                                            .font(.caption).foregroundStyle(.secondary)
                                    }
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .padding(12)
                                    .background(Color.secondary.opacity(0.08), in: RoundedRectangle(cornerRadius: 12))
                                }.buttonStyle(.plain)
                            }
                        }
                    }
                    Text("Pilot build · physical device acceptance is pending. A generated model still needs review for food fidelity, orientation and scale.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                .padding(20)
                .frame(maxWidth: 700)
                .frame(maxWidth: .infinity)
            }
            .navigationTitle("DishPlay Capture")
            .navigationBarTitleDisplayMode(.inline)
            .sheet(isPresented: $model.showCamera) {
                CameraPicker(onImage: model.savePhoto, onCancel: { model.showCamera = false })
                    .ignoresSafeArea()
                    .interactiveDismissDisabled()
            }
            .sheet(item: $model.exportFile) { file in
                ExportPicker(url: file.url, onFinish: { model.exportFile = nil })
            }
            .quickLookPreview($model.previewURL)
            .onChange(of: scenePhase) { _, value in
                if value != .active { model.pauseForInterruption() }
            }
        }
        .tint(.blue)
    }

    private var setup: some View {
        VStack(alignment: .leading, spacing: 12) {
            TextField("Dish reference (optional, saved locally)", text: $model.dishReference)
                .textFieldStyle(.roundedBorder)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .disabled(model.busy)
            Text("This label does not pair the capture with a restaurant account.")
                .font(.caption).foregroundStyle(.secondary)
            if model.nativeSupported {
                Button("Start native Object Capture", systemImage: "viewfinder") { model.start(native: true) }
                    .buttonStyle(.borderedProminent).disabled(model.busy)
            } else {
                Label("Object Capture is unavailable here. Guided photos remain available.", systemImage: "camera")
                    .font(.callout)
            }
            Button("Start a photo capture", systemImage: "camera") { model.start(native: false) }
                .buttonStyle(.bordered).disabled(model.busy)
            if model.cameraDenied {
                Button("Open camera permission settings") {
                    if let url = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(url) }
                }
            }
        }
    }

    @ViewBuilder
    private var nativeControls: some View {
        switch model.phase {
        case .ready:
            Button("Detect dish volume") { model.detect() }.buttonStyle(.borderedProminent)
        case .detecting:
            HStack {
                Button("Start capturing") { model.beginCapture() }.buttonStyle(.borderedProminent)
                Button("Reset volume") { model.resetDetection() }.buttonStyle(.bordered)
            }
        case .capturing:
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Button(model.isPaused ? "Resume" : "Pause and inspect points") { model.togglePause() }
                        .buttonStyle(.bordered)
                    Button("Finish capture") { model.finish() }.buttonStyle(.borderedProminent)
                }
                if model.passComplete {
                    Button("Continue at another height") { model.newHeight() }.buttonStyle(.bordered)
                    Text("This scan pass is complete according to the capture SDK.").font(.caption)
                }
            }
        default: EmptyView()
        }
        if model.phase != .finishing {
            Button("Stop this session and keep saved photos", role: .cancel) { model.cancelCapture() }
                .font(.callout)
        }
    }

    private func savedCapture(_ record: CaptureRecord) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Current capture · \(model.imageCount) photos").font(.headline)
            if record.mode == "native-photos" {
                Button("Take another overlapping photo", systemImage: "camera") { model.addPhoto() }
                    .buttonStyle(.bordered)
                    .disabled(model.busy || model.imageCount >= 150)
            }
            if model.reconstructionSupported {
                Button("Build USDZ on this device", systemImage: "cube") { model.reconstruct() }
                    .buttonStyle(.borderedProminent)
                    .disabled(model.busy || model.imageCount < 3)
                Text("At least 3 photos are needed to start; a usable food model usually requires many more overlapping views.")
                    .font(.caption).foregroundStyle(.secondary)
            } else {
                Text("Local reconstruction is unavailable. Export the photos for the separate reconstruction worker.")
                    .font(.callout)
            }
            Button("Export capture ZIP to Files", systemImage: "square.and.arrow.up") { model.exportOriginals() }
                .buttonStyle(.bordered).disabled(model.busy)
            if model.exporting { ProgressView("Preparing a copy of your saved capture…") }
            if let url = model.savedModel {
                Button("Review last saved USDZ", systemImage: "arkit") { model.previewURL = url }
                    .buttonStyle(.bordered).disabled(model.busy)
                Button("Export USDZ to Files") { model.exportModel() }.disabled(model.busy)
            }
        }
    }
}
