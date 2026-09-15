# Android capture application

## Current evidence

`native/android/` contains a Kotlin Android application with ARCore capture and a system-camera fallback. The source has been reviewed against the official APIs listed below. **Physical Android capture, anchoring accuracy, reconstruction quality, and Android-to-web publication have not been verified.** A passing remote build verifies compilation and Android lint; it does not verify a phone camera or AR tracking.

The separate **Android capture APK** GitHub Actions workflow compiles a debug APK without signing credentials. Check its result on the exact commit being installed. No Android SDK installation, emulator, or Gradle build was started on the 8 GB development laptop for this implementation.

## What the app implements

- Camera permission, runtime ARCore availability, and Google Play Services for AR installation checks. AR is optional in the manifest.
- A live camera texture from the current ARCore frame. Tap a tracked upward horizontal plane to create an actual anchor.
- A wireframe volume in the anchor's coordinate system. Width, depth, and height controls are bounded to **5–100 cm**. Its bottom sits on the selected plane. Dimensions and anchor replacement lock once the first calibrated frame is accepted; a new series resets them.
- Actual ARCore sparse feature points filtered to the volume, confidence at least `0.3`, at most 500 points per displayed frame. The blue points are measured tracking features, not image-colored surface points, depth fusion, a dense cloud, a mesh, or a coverage score.
- User-triggered camera images with actual intrinsics, physical camera poses, anchor poses, monotonic nanosecond timestamps, measured points, and dimensions. Capture fails visibly if the camera image is unavailable, tracking is paused, the anchor is absent, calibration dimensions differ, or an unexpected CPU crop would invalidate the intrinsics.
- One background writer. Original CPU YUV samples are normalized losslessly into NV21; a JPEG is also encoded for the existing web importer. Android image and point-cloud resources are released after use. The normalized YUV file is **not Bayer sensor RAW**.
- A new segment identifier after a lifecycle pause, tracking interruption, or anchor replacement. Never merge segment coordinates without a verified registration step.
- Private on-device series with preserved originals, per-file SHA-256 hashes, metadata sidecars, series selection, and streaming ZIP export through Android's share sheet. A maximum of 150 accepted images / 1 GiB per series and a free-space reserve bound storage. Export requires additional free disk space approximately equal to the current series.
- A full-size `ACTION_IMAGE_CAPTURE` fallback using a scoped FileProvider URI. Its original camera-app output and EXIF are preserved. Intrinsics and poses are explicitly absent. No unsupported-device spatial capabilities are simulated.

## Obtain and install the APK

Preferred for this laptop:

1. Open **Actions → Android capture APK** in the repository and select a successful run for the desired commit.
2. Download the `dishplay-android-debug` artifact and extract `app-debug.apk`.
3. Transfer that APK to the test Android phone and install it, or use `adb install -r app-debug.apk` from an existing Android Platform Tools installation.

The APK uses the runner's debug signing key and is intended for testing. Different remote runs may have different debug keys: Android can reject an upgrade with a signature mismatch. **Export the existing captures before uninstalling an older app.** App uninstallation or clearing its storage removes its private originals. A Play Store/release signing workflow is not included.

For an adequately provisioned development machine with an existing SDK and JDK 17:

```sh
cd native/android
./gradlew --no-daemon --max-workers=1 :app:assembleDebug :app:lintDebug
```

Pinned versions: Gradle `8.11.1`, Android Gradle Plugin `8.9.2`, Kotlin `2.1.20`, ARCore `1.56.0`, AndroidX Core `1.15.0`, compile/target SDK `35`, minimum SDK `24`. Gradle uses one worker, a 1 GiB Java heap, no daemon, and the Kotlin compiler in-process. These limits do not represent measured whole-system memory usage. Do not run this build beside the web build on the 8 GB laptop.

## Capture, export, and continue on the web

1. Place the real dish on a stable table in diffuse light. Keep the dish still.
2. Activate AR and grant camera permission. Move slowly until tracking starts; touch the table beneath the plate. Adjust the volume to the actual plate/food bounds before the first capture.
3. Capture overlapping views while moving around the dish at several heights. The displayed point count reports measured features inside the volume; it does not establish completeness.
4. Pause before leaving the app. A resumed sequence has a separate segment. If AR is unavailable, use **Photo simple** for actual camera photos without spatial metadata.
5. Use **Exporter ZIP**, save the archive somewhere durable, and verify that it opens. **Mes séries** retains earlier on-device sessions; creating a new one never deletes earlier captures.
6. Extract the ZIP. Open a dish's capture screen in the web dashboard and import the JPEGs. The web importer has its own limits (24 MP, 25 MiB per imported file, 100 MiB per series; supported JPEG/PNG/WebP). A system-camera image that exceeds those limits needs a smaller derived copy; retain the original archive.

There is no native login, single-use pairing code, native upload, or native reconstruction worker connection. Importing JPEGs through the web currently omits the native metadata from reconstruction. Keep the archive for later calibration/reprojection validation. The worker must recover poses from images until the supplied native poses have passed a reprojection test and axis/unit conversion checks.

## Archive contract

`manifest.json` contains session metadata and the list of accepted frame records. The archive also includes `session.json`, individual `*.frame.json` sidecars, images, and NV21 originals where present. Partial originals from an interrupted write are retained and included when exporting a series with accepted frames; do not treat unindexed files as validated frames.

ARCore frame records contain:

- `frameTimestampNs`, `imageTimestampNs`: decimal strings to preserve 64-bit nanoseconds across JSON readers.
- `cameraToWorld`, `anchorToWorld`, `cameraToAnchor`: column-major 4×4 transforms.
- Camera axes: ARCore/OpenGL, +X right, +Y up, −Z forward. Camera matrices use the **physical**, unrotated CPU-camera pose, not display-oriented rendering poses.
- `intrinsics`: `fx`, `fy`, `cx`, `cy`, image dimensions for the unrotated CPU image. Image pixels use +u right and +v down.
- `segmentId`: an independent tracking segment; `volumeMeters` uses meters with the bottom at the anchor plane.
- `sparsePoints`: observed world and anchor-local coordinates plus ARCore confidence; no invented points or poses.
- `original`: exact normalized NV21 pixel samples and hash; `photo`: JPEG derivative and hash. Color fidelity of Android's YUV-to-JPEG conversion remains a physical acceptance check.

## Required phone tests

- Permission denial, retry, missing ARCore, ARCore installation cancellation, no system camera app.
- A textured table and a real plate: correct texture rotation/cropping, stationary anchor, bounded volume, zero points correctly shown on poorly tracked food.
- Intrinsics/image dimension agreement; pixel reprojection of known points; measured plate dimensions versus exported meters.
- Tracking loss, background/foreground, portrait/landscape, process death during camera fallback, low storage, and camera-in-use failure.
- Multiple captures save distinct bytes and timestamps; images and point clouds release properly; local originals survive errors.
- ZIP extraction and SHA-256 verification, old-series reopening, fallback photo orientation, and web import/publication from a real capture.
- Actual peak memory, battery/thermal behavior, image quality and reconstruction on the intended Android. No dense-cloud parity claim is made.

## Official references

- [Enable optional AR and runtime checks](https://developers.google.com/ar/develop/java/enable-arcore)
- [ARCore Session and lifecycle](https://developers.google.com/ar/reference/java/com/google/ar/core/Session)
- [Plane hit tests and real anchors](https://developers.google.com/ar/develop/java/hit-test/developer-guide)
- [Frame images, measured points, and texture coordinate transforms](https://developers.google.com/ar/reference/java/com/google/ar/core/Frame)
- [Physical camera pose and image intrinsics](https://developers.google.com/ar/reference/java/com/google/ar/core/Camera)
- [Point-cloud layout and resource release](https://developers.google.com/ar/reference/java/com/google/ar/core/PointCloud)
- [System camera output and FileProvider](https://developer.android.com/media/camera/camera-deprecated/photobasics)
- [AGP 8.9 compatibility](https://developer.android.com/build/releases/agp-8-9-0-release-notes)

Versions were checked against the official Maven artifacts, and the committed Gradle wrapper was retrieved from the official release tag. Third-party notices are in `native/android/THIRD_PARTY_NOTICES.md`.
