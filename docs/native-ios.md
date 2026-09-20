# iOS capture app

> **Updated automatic scan / PC workflow:** see [automatic-scan.md](automatic-scan.md). The earlier implementation notes below describe the original opt-in/manual workflow; the new app uses ARKit automatic capture, automatic queue submission and private result downloads. Physical food reconstruction acceptance is still required.

Source: `native/ios`. Deployment target: iOS/iPadOS 17.0 or later. This minimal app uses Apple's actual Object Capture and photogrammetry APIs; it is separate from the restaurant web login.

## Build and install

**Version 0.1.0 (build 1.1) is ready for internal TestFlight testing.** The [signed release workflow passed](https://github.com/Omazi/dishplay3d/actions/runs/35523589363) for source `91baec4` on 2026-09-20 using Xcode 26.3 and the iOS 26.2 SDK. Apple completed processing without errors or warnings and reported `VALID` / `READY_FOR_BETA_TESTING`. The build is assigned to the internal group **DishPlay - Tests iPhone**, with French and English test notes. Follow [the installation steps](testflight.md#sur-liphone) to add your own account and install it.

All compilation and signing ran on hosted Macs with one Xcode build job. The Linux laptop has no Xcode or Apple SDK. Installation, camera behavior and reconstruction on a physical device remain unverified. The separate `iOS unsigned build` workflow still provides compilation evidence; its unsigned artifact cannot be installed directly on an iPhone.

On a Mac with a current stable Xcode and [XcodeGen 2.46.0+](https://github.com/yonaskolb/XcodeGen/releases/tag/2.46.0):

```bash
cd native/ios
xcodegen generate --spec project.yml
xcodebuild -project DishPlayCapture.xcodeproj -scheme DishPlayCapture \
  -configuration Debug -destination 'generic/platform=iOS' \
  -derivedDataPath build -jobs 1 CODE_SIGNING_ALLOWED=NO build
open DishPlayCapture.xcodeproj
```

For installation, select your own development team in Signing & Capabilities, choose a unique bundle identifier if necessary, connect the test iPhone/iPad, select it as the run destination and build/run. No team, certificate, provisioning profile or paid subscription is embedded. Camera and reconstruction capabilities still need runtime checks on the actual device.

## TestFlight distribution

The manual [iOS TestFlight workflow](../.github/workflows/testflight.yml) verifies an unsigned Release archive, then signs with the configured distribution identity and exports/uploads an IPA. It uses a hosted Mac, one Xcode build job and temporary keychain storage. The repository's `testflight` environment is configured for the `main` branch; credentials are stored as encrypted GitHub secrets. See [the TestFlight setup guide](testflight.md) for release evidence, installation and future account setup.

## Implemented flow

- Ask for camera permission only after a capture button. If denied, offer Settings and keep saved captures.
- Check `ObjectCaptureSession.isSupported` **before constructing a session**. On supported hardware, show genuine `ObjectCaptureView` spatial volume controls and `ObjectCapturePointCloudView` observations.
- Wait for SDK states. `startDetecting()` returning `false` leaves detection unstarted and displays recovery guidance. Native controls support volume reset, capture, pause/resume, another pass at a different height, finishing, and cancellation. Food is never flipped.
- Display actual SDK photo counts, feedback and scan-pass completion. No random points, invented poses or timer-driven coverage exist. SDK tracking and reconstruction quality remain hardware acceptance items.
- Wait for `.completed` before tearing down the capture session or offering reconstruction. Leaving the app pauses capture; the user chooses Resume. A failed/interrupted spatial session gets a new capture folder instead of combining independent coordinate frames.
- Unsupported Object Capture devices can use `UIImagePickerController` for a sequence of ordinary photos. This path deliberately has no spatial anchor, depth, intrinsics or point-cloud claim. JPEGs are encoded from the captured image; it is not a sensor RAW capture mode.
- Check `PhotogrammetrySession.isSupported` separately. An explicit action requests a real `.reduced` USDZ from saved images, shows only SDK progress, and handles completion/cancellation/errors. Each reconstruction attempt writes a new output directory; a failure never overwrites the last saved model.
- Inspect the actual model through Quick Look. A generated model is marked for human review; metric scale and food fidelity are not certified automatically. **No GLB export is claimed by this app.** Convert and validate GLB separately.
- Store captures in Documents/Captures with originals, checkpoints and metadata. Reopen saved captures, export a ZIP containing actual photos with SHA-256 hashes, and export the generated USDZ through the Files picker as a copy. No automatic cleanup deletes originals.

## Account and worker boundary

The optional dish reference remains a local label. The separate **Pair with website** section now claims a private, single-use code created for a saved dish in the restaurant website. Capture first, then generate the ten-minute code. Confirm the returned restaurant and dish before sending. The native capability only permits that capture’s status, image upload and finalization; it cannot access the restaurant account or publish its menu.

Credentials and pending claim retries live in the device-only Keychain, never in Documents or exported ZIPs. Uploads use one orientation-corrected JPEG working copy at a time (1920 px long edge, at most 3 MiB), cached in Application Support by original SHA-256. Originals, HEIC/depth/checkpoints and the local USDZ are retained unchanged. The server returns received hashes; resuming skips identical bytes. Backgrounding pauses transfer; reopen the saved series and resume. See [the pairing protocol and operator flow](native-pairing.md).

Capture guidance now uses three non-flipping passes. The SDK’s `userCompletedScanPass` event pauses at each completed pass; the next button resets the native dial for the new height. Suggested 30°/45°/65–80° angles are coaching, not measured coverage. Manual early finishing remains possible. Native UI guidance is available in French and English.

Object Capture can save HEIC images and associated depth/checkpoint data. The standalone Python worker currently accepts JPEG/PNG; retain the original native folder, and create an explicitly converted JPEG working set before using that worker. On compatible devices, local Apple reconstruction uses the original images directly. Do not rename HEIC files to `.jpg`.

The fallback path does not implement an ARKit anchored volume. This is a real photo-capture fallback, not native AR parity. Photo-library/video import, automatic USDZ/GLB upload, reconstruction checkpoints across app termination, native ARKit fallback, image-quality scoring, automatic crop/scale calibration, public publishing, and automated physical-camera tests remain outstanding.

## Physical acceptance required

Use one supported Object Capture device and an unsupported iPhone if available. Record device, OS and capture mode. Test permission refusal/recovery, native volume placement, handle adjustment, one stationary dish at multiple heights, genuine observed points, pause/resume, background interruption, cancellation, disk-full handling, saved-file export, reconstruction failure and preservation of the previous model. Validate the resulting USDZ in Quick Look and compare a measured plate dimension. Repeat the complete publication/QR flow using the web app and an Android phone. A simulator or unsigned build cannot satisfy these checks.

## API references

- [ObjectCaptureSession](https://developer.apple.com/documentation/realitykit/objectcapturesession), including its support check and asynchronous state updates.
- [startDetecting()](<https://developer.apple.com/documentation/realitykit/objectcapturesession/startdetecting()>) and [finish()](<https://developer.apple.com/documentation/realitykit/objectcapturesession/finish()>) state preconditions.
- [ObjectCaptureView](https://developer.apple.com/documentation/realitykit/objectcaptureview) and [ObjectCapturePointCloudView](https://developer.apple.com/documentation/realitykit/objectcapturepointcloudview).
- [Meet Object Capture for iOS](https://developer.apple.com/videos/play/wwdc2023/10191/) explains the capture lifecycle, non-flipping passes and reduced-detail on-device reconstruction.
- [PhotogrammetrySession](https://developer.apple.com/documentation/realitykit/photogrammetrysession) and [modelFile request](<https://developer.apple.com/documentation/realitykit/photogrammetrysession/request/modelfile(url:detail:geometry:)>).
- [File coordination for uploading](https://developer.apple.com/documentation/foundation/nsfilecoordinator/readingoptions/foruploading) creates a ZIP snapshot of a directory; [document export as a copy](<https://developer.apple.com/documentation/uikit/uidocumentpickerviewcontroller/init(forexporting:ascopy:)>) preserves the original.
