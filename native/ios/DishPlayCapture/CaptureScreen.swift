import QuickLook
import RealityKit
import SwiftUI
import UIKit

struct CaptureScreen: View {
    @ObservedObject var model: CaptureModel
    @StateObject private var transfer = CaptureTransfer()
    @State private var showForget = false
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    Text("From your dish. From real observations.")
                        .font(.title2.bold())
                    Text("Originals stay on this iPhone. Pair a dish and choose when to send photo copies to the website.")
                        .foregroundStyle(.secondary)
                    if let session = model.captureSession {
                        captureSteps
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
                        setup.disabled(transfer.busy)
                    }

                    Label(LocalizedStringKey(model.message), systemImage: model.phase == .failed ? "exclamationmark.triangle" : "info.circle")
                        .font(.callout)
                        .padding()
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color.blue.opacity(0.08), in: RoundedRectangle(cornerRadius: 16))
                        .accessibilityIdentifier("capture-status")
                    if !model.feedback.isEmpty {
                        Text(LocalizedStringKey(model.feedback)).font(.headline).accessibilityAddTraits(.updatesFrequently)
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
                        savedCapture(record).disabled(transfer.busy)
                        transferPanel(record)
                    }
                    if !model.library.isEmpty && !model.busy && !transfer.busy {
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
                if value != .active { model.pauseForInterruption(); transfer.pause() }
            }
            .onAppear { transfer.select(model.record) }
            .onChange(of: model.record?.id) { _, _ in transfer.select(model.record) }
            .onChange(of: model.imageCount) { _, _ in transfer.readyToFinalize = false }
            .onOpenURL { transfer.receive($0) }
        }
        .tint(.blue)
    }

    private var captureSteps: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                ForEach(1...3, id: \.self) { pass in
                    Text(pass == 1 ? "1 · Low" : pass == 2 ? "2 · Oblique" : "3 · Above")
                        .font(.caption.bold())
                        .padding(.vertical, 10).frame(maxWidth: .infinity)
                        .background(model.currentPass == pass ? Color.blue.opacity(0.15) : Color.secondary.opacity(0.08), in: RoundedRectangle(cornerRadius: 10))
                }
            }
            Text(model.phase == .ready ? "1. Detect the dish on the table." : model.phase == .detecting ? "2. Adjust the volume to include the whole plate, then start." : model.currentPass == 1 ? "3. First pass: circle the plate at about 30°. Move the phone, not the food." : model.currentPass == 2 ? "Second pass: circle from an oblique view, about 45°." : "Third pass: look down into the bowl, about 65–80°. Keep walking around it.")
                .font(.headline)
            Text("Follow the native capture dial. A completed circle pauses the camera so you can change height. Finish early only if you want to keep a partial series.")
                .font(.caption).foregroundStyle(.secondary)
        }
    }

    private func transferPanel(_ record: CaptureRecord) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Divider()
            Label("Pair with website", systemImage: "link").font(.headline)
            if let snapshot = transfer.snapshot {
                Text(snapshot.restaurantName).font(.subheadline)
                Text(snapshot.dishName).font(.title3.bold())
                Text("Only this dish can receive these photos. Sending does not publish the menu.")
                    .font(.caption).foregroundStyle(.secondary)
                if snapshot.scan.state == "capturing" {
                    Button("Confirm dish and send / resume", systemImage: "icloud.and.arrow.up") { transfer.upload(record) }
                        .buttonStyle(.borderedProminent).disabled(model.busy || transfer.busy || model.imageCount == 0)
                    if transfer.readyToFinalize {
                        Button("Finalize transferred series") { transfer.finalize(record) }
                            .buttonStyle(.bordered).disabled(model.busy || transfer.busy)
                        Text("Finalizing closes the series to new photos. It does not generate or publish a 3D model.").font(.caption)
                    }
                } else { Text(snapshot.scan.state == "finalized" ? "Series finalized on the website." : "Series cancelled on the website.") }
                Link("Review photos on DishPlay", destination: URL(string: "https://dishplay3d.vercel.app/dashboard")!)
                Button("Change association", role: .destructive) { showForget = true }
                    .disabled(model.busy || transfer.busy)
            } else {
                TextField("Private code from the dish page", text: $transfer.code)
                    .textFieldStyle(.roundedBorder).textInputAutocapitalization(.characters).autocorrectionDisabled()
                    .disabled(model.busy || transfer.busy)
                Button("Pair with website") { transfer.pair(record, onPaired: { model.markRemote($0) }) }
                    .buttonStyle(.bordered).disabled(model.busy || transfer.busy)
                Text("On DishPlay, open the saved dish → Prepare new photos → Create a code for iPhone. Codes last 10 minutes.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            if transfer.busy {
                ProgressView()
                if transfer.total > 0 { Text("\(transfer.completed) / \(transfer.total) photos checked").monospacedDigit() }
                Button("Pause transfer", role: .cancel) { transfer.pause() }
            }
            if !transfer.status.isEmpty { Text(LocalizedStringKey(transfer.status)).font(.callout).accessibilityAddTraits(.updatesFrequently) }
            Text("JPEG copies are sent one at a time. HEIC originals, depth and checkpoints stay on this device. Keep the app open during transfer.")
                .font(.caption).foregroundStyle(.secondary)
        }
        .padding(16).background(Color.blue.opacity(0.05), in: RoundedRectangle(cornerRadius: 16))
        .confirmationDialog("Change this capture’s association?", isPresented: $showForget, titleVisibility: .visible) {
            Button("Remove local association", role: .destructive) { transfer.forget(record); if transfer.snapshot == nil { model.markRemote(nil) } }
            Button("Cancel", role: .cancel) {}
        } message: { Text("Photos already sent remain on the website. Revoke the old access there, then create a fresh code. Local originals are kept.") }
    }

    private var setup: some View {
        VStack(alignment: .leading, spacing: 12) {
            TextField("Dish reference (optional, saved locally)", text: $model.dishReference)
                .textFieldStyle(.roundedBorder)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .disabled(model.busy)
            Text("First capture or open a saved series. Then use the code from your dish page to pair it with the website.")
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
                    if !model.passComplete {
                        Button(model.isPaused ? "Resume" : "Pause and inspect points") { model.togglePause() }
                            .buttonStyle(.bordered)
                    }
                    Button("Finish capture") { model.finish() }.buttonStyle(.borderedProminent)
                }
                if model.passComplete {
                    if model.currentPass < 3 {
                        Button(model.currentPass == 1 ? "Raise to 45° and continue" : "Raise to 65–80° and continue") { model.newHeight() }.buttonStyle(.borderedProminent)
                    }
                    Text("This scan pass is complete according to Object Capture. The angle suggestions are guidance, not measured coverage.").font(.caption)
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
