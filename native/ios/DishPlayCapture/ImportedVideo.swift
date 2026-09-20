import CoreTransferable
import Foundation
import UniformTypeIdentifiers

struct ImportedVideo: Transferable {
    let url: URL

    static var transferRepresentation: some TransferRepresentation {
        FileRepresentation(importedContentType: .movie) { received in
            try VideoFrameExtractor.validateSize(received.file)
            let suffix = received.file.pathExtension.isEmpty ? "mov" : received.file.pathExtension
            let copy = FileManager.default.temporaryDirectory.appendingPathComponent("DishPlay-" + UUID().uuidString + "." + suffix)
            try FileManager.default.copyItem(at: received.file, to: copy)
            return ImportedVideo(url: copy)
        }
    }
}
