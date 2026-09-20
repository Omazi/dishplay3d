# Native capture acceptance boundary

This checkout includes browser capture, an iOS SwiftUI/RealityKit app and an Android Kotlin/ARCore app. Sources and cloud build workflows are provided; a successful compiler result does not establish physical capture quality.

- [iOS implementation and build](native-ios.md): actual Object Capture guidance, volume and point-cloud view where supported; ordinary camera fallback, preserved images, ZIP export, independently checked local USDZ reconstruction and Quick Look. ARKit spatial guidance on unsupported Object Capture devices is still absent.
- [Android implementation and build](native-android.md): runtime ARCore/camera checks, actual tracked points and anchored bounds, preserved image/pose/intrinsics records, export and ordinary camera fallback. Sparse tracking points are not a dense reconstruction.
- Web `/capture`: real HTTPS camera and photo import, IndexedDB originals, resumable checksummed upload, immutable finalization and optional worker status. No invented native poses. Video sampling is not implemented.

## Remaining integration and physical evidence

1. Sign/install the iOS app with an Apple development account; install the CI-generated Android APK on a compatible device.
2. Exercise the implemented iPhone [single-use pairing and resumable upload](native-pairing.md) on the signed physical app. The Android client has not yet adopted this protocol. Public menu QR codes contain no account credentials.
3. Verify pose conventions, image orientation, intrinsics and tracking segment boundaries by reprojection before using native poses in reconstruction. The CPU worker currently calibrates from images.
4. Exercise interruption, permission denial, finalization, original export and recovery on actual phones.
5. Capture a real dish, reconstruct it, inspect textured GLB/USDZ and metric scale, then publish and scan the same QR on both platforms.

No physical iPhone or Android was available during this build. A browser framing guide is not a spatial anchor, and photo counts do not measure geometric coverage. Synthetic geometry used by viewer tests is not evidence of food reconstruction.
