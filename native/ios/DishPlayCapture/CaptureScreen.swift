import PhotosUI
import QuickLook
import SwiftUI
import UIKit

struct CaptureScreen: View {
    @ObservedObject var model: CaptureModel
    @StateObject private var transfer = CaptureTransfer()
    @State private var scan: GuidedScan?
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
                        Text("One guided scan. Automatic capture. Your 3D model, calculated on your PC.")
                            .font(.body).foregroundStyle(.secondary)
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
                        Label("Scan your dish", systemImage: "viewfinder")
                            .font(.headline).frame(maxWidth: .infinity).padding(.vertical, 12)
                    }.buttonStyle(.borderedProminent).disabled(model.busy || transfer.busy)
                    PhotosPicker(selection: $selectedPhotos, maxSelectionCount: 24, matching: .images) {
                        Label("Use existing photos", systemImage: "photo.on.rectangle")
                            .frame(maxWidth: .infinity)
                    }.buttonStyle(.bordered).disabled(model.busy || transfer.busy)
                    if model.phase == .preparing { ProgressView("Preparing selected photos…") }
                    if model.phase == .failed { Text(LocalizedStringKey(model.message)).foregroundStyle(.red) }
                    if model.imageCount > 0 {
                        Label("Your scan is saved", systemImage: "checkmark.circle.fill").foregroundStyle(.green)
                        if let url = model.savedModel {
                            Button("Explore my 3D dish", systemImage: "cube.transparent") { model.previewURL = url }
                                .buttonStyle(.borderedProminent)
                        }
                    }
                    connection
                    if !transfer.status.isEmpty {
                        Text(LocalizedStringKey(transfer.status)).font(.callout)
                            .padding(16).frame(maxWidth: .infinity, alignment: .leading)
                            .background(Color.blue.opacity(0.07), in: RoundedRectangle(cornerRadius: 16))
                            .accessibilityIdentifier("capture-status")
                    }
                    if transfer.busy {
                        if transfer.total > 0 && transfer.completed < transfer.total {
                            ProgressView("Sending your scan…", value: Double(transfer.completed), total: Double(transfer.total))
                        } else { ProgressView() }
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
                                            Text(record.dishReference.isEmpty ? "Untitled dish" : record.dishReference)
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
                    Text("The live preview shows observations. The final model is reconstructed from your photos and should be checked before publication.")
                        .font(.footnote).foregroundStyle(.secondary)
                }.padding(22).frame(maxWidth: 650).frame(maxWidth: .infinity)
            }
            .navigationTitle("DishPlay Capture").navigationBarTitleDisplayMode(.inline)
            .fullScreenCover(item: $scan) { active in
                GuidedScanScreen(scan: active, onContinue: {
                    model.refreshAutomatic()
                    sendIfPaired()
                }).interactiveDismissDisabled()
            }
            .sheet(item: $model.exportFile) { file in ExportPicker(url: file.url, onFinish: { model.exportFile = nil }) }
            .quickLookPreview($model.previewURL)
            .onAppear { transfer.select(model.record); transfer.onModel = model.receiveModel }
            .onChange(of: model.record?.id) { _, _ in transfer.select(model.record) }
            .onChange(of: selectedPhotos) { _, items in
                guard !items.isEmpty else { return }
                model.importPhotos(items) { selectedPhotos = []; sendIfPaired() }
            }
            .onChange(of: scenePhase) { _, value in
                if value != .active { transfer.pause(); model.pauseForInterruption() }
            }
            .onOpenURL { transfer.receive($0) }
            .confirmationDialog("Change this capture’s association?", isPresented: $showForget) {
                Button("Remove local association", role: .destructive) {
                    if let record = model.record { transfer.forget(record); model.markRemote(nil) }
                }
            } message: { Text("Saved photos remain available. Link a new dish before sending another scan.") }
        }.tint(.blue)
    }
    private func sendIfPaired() {
        if let record = model.record, transfer.snapshot != nil { transfer.upload(record) }
        else { transfer.status = "Link your dish below to send the scan and start reconstruction." }
    }
    private var connection: some View {
        VStack(alignment: .leading, spacing: 12) {
            if transfer.snapshot != nil {
                if model.imageCount > 0 {
                    Button(transfer.snapshot?.scan.state == "finalized" ? "Check my 3D model" : "Create my 3D model", systemImage: "icloud.and.arrow.up") {
                        sendIfPaired()
                    }.buttonStyle(.borderedProminent).disabled(model.busy || transfer.busy)
                }
                Text("Your PC receives the scan automatically. Keep DishPlay running there until the model is ready.")
                    .font(.caption).foregroundStyle(.secondary)
            } else {
                Label("Link your dish", systemImage: "link").font(.headline)
                Text("Open your dish on DishPlay and create an iPhone code. Enter it here to choose where the scan will be sent.")
                    .font(.callout).foregroundStyle(.secondary)
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
