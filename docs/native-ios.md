# iOS capture app

Source: `native/ios`. iOS/iPadOS 17 or later. DishPlay Capture is the website's companion for creating captures; the restaurant account and public menu remain on the website.

## Current capture flow

Version 0.3 makes **Film your dish** the primary action. It uses a rear-camera video recording, with **Record** and **Stop and use video** fixed at the bottom of the screen. Starting does not depend on Object Capture compatibility, ARKit tracking, foreground recognition or table detection. Instructions and errors are available in French and English.

Keep the dish still and well lit, walk slowly around the plate for about 20–40 seconds, finish slightly higher, and stop. Recording has no audio input and stops at 60 seconds or 180 MiB. Camera permission is requested when opening capture; denial offers Settings and leaves video/photo import available.

The original video is saved in Documents/Captures. AVAssetImageGenerator sequentially prepares at most 24 upright JPEGs, 1600 px on their longest edge. Basic sharpness, exposure and near-duplicate checks require at least eight usable views. These checks do not measure angular coverage or guarantee a reconstructable dish. The saved original can be replayed, exported in the capture ZIP, or used to retry interrupted preparation. Failed extraction does not expose partial images to upload.

**Use an existing video** uses file-based PhotosPicker transfer, limited to 250 MiB and 5–90 seconds; it does not read the entire movie into memory. Photo import is also available. Only JPEGs are uploaded, not the video. Existing capture records remain readable.

The previous ARKit/Vision scanner is available under **Advanced spatial scan**. It uses detected table/foreground positions, accepted camera angles and actual observed points. Its recognition gates can be unsuitable for some scenes; video mode bypasses those gates. Apple on-device USDZ reconstruction remains an optional advanced action only when `PhotogrammetrySession.isSupported`. PC reconstruction is the default. See [the complete flow and limits](automatic-scan.md).

## Pairing and reconstruction

Create a private code on a saved dish's website capture page and link it in the app. When the dish is already linked, successful video preparation starts image upload and reconstruction automatically. Otherwise, the capture remains local until linked and sent. Pairing credentials stay in the device-only Keychain and never enter exported ZIP files.

Photo upload is serial, checksummed and resumable. Backgrounding pauses transfer; return to the saved capture to resume. The PC consumes the durable reconstruction queue while awake and connected, under its existing one-CPU / 1.5 GiB hard RAM limit. Jobs wait when the PC is offline or memory is insufficient. The app verifies USDZ size and SHA-256 before opening the result in Quick Look. The website also provides the textured GLB. Publishing remains a separate review action.

## Build, tests and TestFlight

The [TestFlight guide](testflight.md) records the currently distributed build and installation steps. The manual [release workflow](../.github/workflows/testflight.yml) runs tests and an unsigned archive, then signs, validates and uploads the IPA. Existing signing material is reused; temporary secrets and the runner's signing keychain are removed after the job.

All compilation runs on hosted Macs with one Xcode build job, not on the 8 GB Linux laptop. The video suite encodes and decodes real MOV files and checks orientation, bounded frame count, rejection of static/dark/short movies, source preservation, staging cleanup and protection against overwriting existing photos. Spatial coverage tests remain in place. Neither suite exercises a physical camera.

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

On a real iPhone, test camera permission refusal/recovery, preview orientation, start/stop, a small screen with large text, leaving the app during recording, disk-full handling, movie import, original playback, retry, pairing, transfer interruption and result download. Capture a real dish, reconstruct it, and inspect surface fidelity and scale before publishing. A successful archive and reference reconstruction do not establish food quality or an easy physical capture experience.

## API references

- [AVCaptureMovieFileOutput](https://developer.apple.com/documentation/AVFoundation/AVCaptureMovieFileOutput).
- [AVAssetImageGenerator](https://developer.apple.com/documentation/avfoundation/avassetimagegenerator).
- [FileRepresentation](https://developer.apple.com/documentation/coretransferable/filerepresentation).
- [Photographs for Object Capture](https://developer.apple.com/documentation/realitykit/capturing-photographs-for-realitykit-object-capture/).
