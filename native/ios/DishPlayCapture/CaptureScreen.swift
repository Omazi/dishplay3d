import PhotosUI
import QuickLook
import SwiftUI
import UIKit

struct CaptureScreen: View {
    @ObservedObject var model: CaptureModel
    @StateObject private var transfer = CaptureTransfer()
    @State private var scan: GuidedScan?
    @State private var showVideoCamera = false
    @State private var selectedVideo: PhotosPickerItem?
    @State private var selectedPhotos: [PhotosPickerItem] = []
    @State private var advanced = false
    @State private var showForget = false
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("Your dish. In a new dimension.").font(.largeTitle.bold())
                        Text("Follow one gentle orbit. Watch the provisional preview grow. Your PC builds the final model.")
                            .font(.body).foregroundStyle(.secondary)
                    }
                    if let record = model.record, model.imageCount > 0 || model.savedVideo != nil || transfer.delivery.uploadedAt != nil {
                        receipt(record)
                    }
                    TextField("Dish reference (optional, saved locally)", text: $model.dishReference)
                        .textFieldStyle(.roundedBorder).disabled(model.busy || transfer.busy)
                    if let snapshot = transfer.snapshot {
                        Label(snapshot.dishName, systemImage: "checkmark.link").font(.headline)
                        Text(snapshot.restaurantName).font(.subheadline).foregroundStyle(.secondary)
                    }
                    Button {
                        guard let record = model.prepareAutomatic() else { return }
                        let next = GuidedScan(record: record)
                        next.onSaved = { model.refreshAutomatic() }
                        scan = next
                    } label: {
                        Label(model.imageCount > 0 ? "Start a new scan" : "Film and scan my dish", systemImage: "viewfinder")
                            .font(.headline).frame(maxWidth: .infinity).padding(.vertical, 12)
                    }.buttonStyle(.borderedProminent).disabled(model.busy || transfer.busy)
                    Text("Keep the dish still. Follow the highlighted orbit and raise the phone gently. Useful views are saved automatically.")
                        .font(.callout).foregroundStyle(.secondary)
                    if model.phase == .preparing {
                        ProgressView(value: model.videoProgress) { Text(LocalizedStringKey(model.message)) }
                        Text("Keep the app open while the photos are prepared.").font(.caption).foregroundStyle(.secondary)
                    }
                    if model.phase == .failed { Text(LocalizedStringKey(model.message)).foregroundStyle(.red) }
                    connection
                    if !transfer.status.isEmpty {
                        Text(LocalizedStringKey(transfer.status)).font(.callout)
                            .padding(16).frame(maxWidth: .infinity, alignment: .leading)
                            .background(Color.blue.opacity(0.07), in: RoundedRectangle(cornerRadius: 16))
                            .accessibilityIdentifier("capture-status")
                    }
                    if transfer.busy {
                        if transfer.delivery.stage != .uploading { ProgressView("Checking your scan…") }
                        Button("Pause transfer and tracking", role: .cancel) { transfer.pause() }
                    }
                    if !model.library.isEmpty && !model.busy && !transfer.busy {
                        VStack(alignment: .leading, spacing: 12) {
                            Text("My scans").font(.title2.bold())
                            ForEach(model.library) { record in
                                Button { model.open(record) } label: {
                                    HStack {
                                        Image(systemName: record.modelPath == nil ? "viewfinder" : "cube.fill")
                                        VStack(alignment: .leading, spacing: 4) {
                                            let saved = record.id == model.record?.id ? transfer.delivery : CaptureDelivery.read(from: CaptureFiles.root(record))
                                            Text(saved.dishName ?? (record.dishReference.isEmpty ? String(localized: "Untitled dish") : record.dishReference))
                                            Text(LocalizedStringKey(record.modelPath != nil ? "Your 3D dish is ready" : saved.title))
                                                .font(.caption.weight(.semibold)).foregroundStyle(record.modelPath != nil ? Color.green : Color.secondary)
                                            Text(record.createdAt, format: .dateTime.month().day().hour().minute()).font(.caption).foregroundStyle(.secondary)
                                        }
                                        Spacer()
                                        Image(systemName: "chevron.right").font(.caption)
                                    }.padding(14).background(Color.secondary.opacity(0.06), in: RoundedRectangle(cornerRadius: 14))
                                }.buttonStyle(.plain)
                            }
                        }
                    }
                    if let record = model.record {
                        DisclosureGroup("Saved files and options", isExpanded: $advanced) {
                            VStack(alignment: .leading, spacing: 12) {
                                Button("Export capture ZIP to Files") { model.exportOriginals() }
                                if model.savedModel != nil { Button("Export USDZ to Files") { model.exportModel() } }
                                if model.reconstructionSupported && model.imageCount >= 3 {
                                    Button("Build USDZ on this device") { model.reconstruct() }
                                }
                                if model.phase == .processing {
                                    ProgressView(value: model.sdkProgress)
                                    Button("Cancel reconstruction") { model.cancelReconstruction() }
                                }
                                if transfer.snapshot != nil {
                                    Button("Change association", role: .destructive) { showForget = true }
                                }
                                Text(record.createdAt, format: .dateTime).font(.caption)
                            }.padding(.top).disabled(transfer.busy)
                        }
                    }
                    DisclosureGroup("Other capture methods") {
                        VStack(alignment: .leading, spacing: 12) {
                            Button("Video only (without live 3D)", systemImage: "video.fill") { showVideoCamera = true }
                            PhotosPicker(selection: $selectedVideo, matching: .videos) {
                                Label("Use an existing video", systemImage: "film")
                            }
                            PhotosPicker(selection: $selectedPhotos, maxSelectionCount: 24, matching: .images) {
                                Label("Use existing photos", systemImage: "photo.on.rectangle")
                            }
                            Text("Video and photo import prepare views for your PC without a live spatial preview.")
                                .font(.caption).foregroundStyle(.secondary)
                        }.padding(.top).buttonStyle(.bordered).disabled(model.busy || transfer.busy)
                    }
                    Text("Version 0.5 · Live capture and scan history").font(.caption2).foregroundStyle(.secondary)
                    Text("The live preview is provisional. Your saved views are sent to the linked dish; your PC calculates the final 3D model. Check its shape and scale before publishing.")
                        .font(.footnote).foregroundStyle(.secondary)
                }.padding(22).frame(maxWidth: 650).frame(maxWidth: .infinity)
            }
            .navigationTitle("DishPlay Capture").navigationBarTitleDisplayMode(.inline)
            .fullScreenCover(isPresented: $showVideoCamera) {
                VideoCaptureScreen { url in
                    model.acceptVideo(url) { success in if success { sendIfPaired() } }
                }
            }
            .fullScreenCover(item: $scan) { active in
                GuidedScanScreen(scan: active, linked: transfer.snapshot != nil, onContinue: {
                    model.refreshAutomatic()
                    sendIfPaired()
                }).interactiveDismissDisabled()
            }
            .sheet(item: $model.exportFile) { file in ExportPicker(url: file.url, onFinish: { model.exportFile = nil }) }
            .quickLookPreview($model.previewURL)
            .onAppear { transfer.onModel = model.receiveModel; transfer.select(model.record) }
            .onChange(of: model.record?.id) { _, _ in transfer.select(model.record) }
            .onChange(of: selectedPhotos) { _, items in
                guard !items.isEmpty else { return }
                model.importPhotos(items) { selectedPhotos = []; sendIfPaired() }
            }
            .onChange(of: selectedVideo) { _, item in
                guard let item else { return }
                model.importVideo(item) { success in
                    selectedVideo = nil
                    if success { sendIfPaired() }
                }
            }
            .onChange(of: scenePhase) { _, value in
                if value != .active { transfer.pause(); model.pauseForInterruption() }
                else { transfer.refresh(model.record) }
            }
            .onOpenURL { transfer.receive($0) }
            .confirmationDialog("Change this capture’s association?", isPresented: $showForget) {
                Button("Remove local association", role: .destructive) {
                    if let record = model.record { transfer.forget(record); model.markRemote(nil) }
                }
            } message: { Text("Saved photos remain available. Link a new dish before sending another scan.") }
        }.tint(.blue)
    }
    private func receipt(_ record: CaptureRecord) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(transfer.delivery.dishName ?? (record.dishReference.isEmpty ? String(localized: "My captured dish") : record.dishReference))
                .font(.title2.bold())
            Label(LocalizedStringKey(model.savedModel != nil ? "Your 3D dish is ready" : transfer.delivery.title),
                  systemImage: model.savedModel != nil ? "checkmark.circle.fill" : transfer.delivery.stage == .failed ? "exclamationmark.triangle.fill" : "tray.full.fill")
                .font(.headline).foregroundStyle(transfer.delivery.stage == .failed ? Color.red : Color.primary)
                .accessibilityIdentifier("scan-receipt")
            VStack(alignment: .leading, spacing: 10) {
                milestone("Saved on this iPhone", complete: model.imageCount > 0 || model.savedVideo != nil)
                milestone("Upload confirmed", complete: transfer.delivery.uploadedAt != nil)
                milestone("3D reconstruction", complete: transfer.delivery.stage == .downloading || model.savedModel != nil)
                milestone("3D and AR available", complete: model.savedModel != nil)
            }.font(.callout)
            if transfer.delivery.stage == .uploading && transfer.total > 0 {
                ProgressView(value: Double(transfer.completed), total: Double(transfer.total))
                Text(Double(transfer.completed) / Double(transfer.total), format: .percent.precision(.fractionLength(0)))
                    .font(.headline.monospacedDigit())
            }
            if let checked = transfer.delivery.checkedAt {
                HStack { Text("Last server check"); Text(checked, format: .dateTime.hour().minute()) }
                    .font(.caption).foregroundStyle(.secondary)
            }
            if let code = transfer.delivery.failureCode {
                Text(code).font(.caption.monospaced()).textSelection(.enabled)
            }
            if let video = model.savedVideo {
                Button("Watch saved video", systemImage: "play.circle") { model.previewURL = video }
                if let segments = record.videoPaths, segments.count > 1 {
                    Menu("Saved video segments") {
                        ForEach(Array(segments.enumerated()), id: \.offset) { index, path in
                            Button("Video \(index + 1)") { model.previewURL = CaptureFiles.root(record).appendingPathComponent(path) }
                        }
                    }
                }
                if model.imageCount == 0 && record.mode == "video" {
                    Button("Retry preparing this video") { model.prepareSavedVideo { if $0 { sendIfPaired() } } }
                        .disabled(model.busy || transfer.busy)
                }
            }
            if let url = model.savedModel {
                Button("Open my dish in 3D / AR", systemImage: "arkit") { model.previewURL = url }
                    .buttonStyle(.borderedProminent)
                Text("In the viewer, choose AR to place the dish on your table. Check its scale before publishing.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }.padding(18).frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.blue.opacity(0.06), in: RoundedRectangle(cornerRadius: 22))
    }
    private func milestone(_ title: LocalizedStringKey, complete: Bool) -> some View {
        Label(title, systemImage: complete ? "checkmark.circle.fill" : "circle")
            .foregroundStyle(complete ? Color.green : Color.secondary)
    }
    private func sendIfPaired() {
        if let record = model.record, transfer.snapshot != nil { transfer.upload(record) }
        else { transfer.status = "Link your dish below to send the scan and start reconstruction." }
    }
    private var connection: some View {
        VStack(alignment: .leading, spacing: 12) {
            if transfer.snapshot != nil {
                if model.imageCount > 0 && model.savedModel == nil {
                    Button(transfer.delivery.uploadedAt != nil || transfer.snapshot?.scan.state == "finalized" ? "Check my 3D model" : "Send and create my 3D dish", systemImage: "icloud.and.arrow.up") {
                        sendIfPaired()
                    }.buttonStyle(.borderedProminent).disabled(model.busy || transfer.busy)
                }
                Text("Your PC receives the scan automatically. Keep DishPlay running there until the model is ready.")
                    .font(.caption).foregroundStyle(.secondary)
            } else {
                Label("Link your dish", systemImage: "link").font(.headline)
                Text("Open your dish on DishPlay and create an iPhone code. Enter it here to choose where the scan will be sent.")
                    .font(.callout).foregroundStyle(.secondary)
                if model.imageCount > 0 { Text("Your scan stays saved here. Link the dish, check its name, then send it.").font(.callout.weight(.medium)) }
                TextField("Private code from the dish page", text: $transfer.code)
                    .textFieldStyle(.roundedBorder).textInputAutocapitalization(.characters).autocorrectionDisabled()
                Button("Link this dish") {
                    let record = model.record ?? model.prepareAutomatic()
                    guard let record else { return }
                    transfer.select(record)
                    transfer.pair(record, onPaired: { id in model.markRemote(id) })
                }.buttonStyle(.bordered).disabled(model.busy || transfer.busy)
            }
            Link("Open DishPlay", destination: URL(string: "https://dishplay3d.vercel.app/dashboard")!)
        }.padding(18).background(Color.secondary.opacity(0.05), in: RoundedRectangle(cornerRadius: 18))
    }
}
