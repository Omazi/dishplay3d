# iOS capture app

Source: `native/ios`. iOS/iPadOS 17 or later. DishPlay Capture is the website's companion for creating captures; the restaurant account and public menu remain on the website.

## Current capture flow

Version 0.4 makes **Scan your dish** the primary action: one rising orbit, automatic useful-view selection, a real camera-position coverage ring, targeted missing-sector guidance, and a provisional lower 3D preview. Detection uses a central foreground instance and table raycasts. If it stalls, **Center scan here** offers explicit estimated placement after four seconds. Normal spatial tracking is still required.

The preview adapts to the phone: RGB masks/poses produce a colored silhouette estimate; scene depth provides observed points; supported scene reconstruction provides a clipped measured mesh. It never presents this approximation as the final model. Review allows rotation/zoom, continuation, missing-area capture and restart with originals archived. See [implementation, preview alternatives and limits](automatic-scan.md).

**Other capture methods** retains the working video recorder and video/photo import. Video uses **Record → Stop and use video** without waiting for recognition or spatial tracking. Original movies are preserved and bounded JPEG extraction stays sequential. This fallback is useful when tracking is unsuitable; it has no live spatial preview.

## Pairing and reconstruction

Create a private code on a saved dish's website capture page and link it in the app. When the dish is already linked, continuing a guided scan or successful video preparation starts image upload and reconstruction automatically. Otherwise, the capture remains local until linked and sent. Pairing credentials stay in the device-only Keychain and never enter exported ZIP files.

Photo upload is serial, checksummed and resumable. Backgrounding pauses transfer; return to the saved capture to resume. The PC consumes the durable reconstruction queue while awake and connected, under its existing one-CPU / 1.5 GiB hard RAM limit. Jobs wait when the PC is offline or memory is insufficient. The app verifies USDZ size and SHA-256 before opening the result in Quick Look. The website also provides the textured GLB. Publishing remains a separate review action.

## Build, tests and TestFlight

The [TestFlight guide](testflight.md) records the currently distributed build and installation steps. The manual [release workflow](../.github/workflows/testflight.yml) runs tests and an unsigned archive, then signs, validates and uploads the IPA. Existing signing material is reused; temporary secrets and the runner's signing keychain are removed after the job.

All compilation runs on hosted Macs with one Xcode build job, not on the 8 GB Linux laptop. The video suite encodes and decodes real MOV files and checks orientation, bounded frame count, rejection of static/dark/short movies, source preservation, staging cleanup and protection against overwriting existing photos. Coverage and synthetic camera-projection / silhouette-geometry tests validate the new progressive preview. These suites do not exercise a physical camera.

On a Mac with Xcode 26.3 and XcodeGen 2.46.0:

```bash
cd native/ios
xcodegen generate --spec project.yml
xcodebuild -project DishPlayCapture.xcodeproj -scheme DishPlayCapture \
  -configuration Release -destination 'generic/platform=iOS' \
  -derivedDataPath build -jobs 1 CODE_SIGNING_ALLOWED=NO build
```

The unsigned artifact cannot be installed directly on an iPhone; use TestFlight or a development-signed build.

## Physical acceptance

On a standard iPhone and a LiDAR-capable iPhone, test automatic anchoring, the manual fallback, RGB/depth preview alignment, both orbit directions, top-view hints, automatic completion, missing-area resume, restart preservation and review interaction. Also test camera permission refusal/recovery, preview orientation, start/stop, a small screen with large text, leaving the app during recording, disk-full handling, movie import, original playback, retry, pairing, transfer interruption and result download. Capture a real dish, reconstruct it, and inspect surface fidelity and scale before publishing. A successful archive and reference reconstruction do not establish food quality or an easy physical capture experience.

## API references

- [AVCaptureMovieFileOutput](https://developer.apple.com/documentation/AVFoundation/AVCaptureMovieFileOutput).
- [AVAssetImageGenerator](https://developer.apple.com/documentation/avfoundation/avassetimagegenerator).
- [FileRepresentation](https://developer.apple.com/documentation/coretransferable/filerepresentation).
- [Photographs for Object Capture](https://developer.apple.com/documentation/realitykit/capturing-photographs-for-realitykit-object-capture/).
