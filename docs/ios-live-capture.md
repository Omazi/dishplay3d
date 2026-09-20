# iOS 0.5: live recording and durable scan receipts

## User flow

- **Film and scan my dish** opens the AR camera with the observed point/silhouette preview below it. The same AR camera feed is recorded, with a red recording indicator. There is no second camera session competing with ARKit.
- Keep the dish still, follow the orange arc and raise the phone gently. Green sectors represent accepted observations. When coverage is sufficient the app stops and saves the movie before enabling the send button.
- Review, fill missing areas, or send to the explicitly linked dish. If not linked, the scan remains saved; link a dish, verify its displayed name and tap **Send and create my 3D dish**.
- The selected scan shows saved/uploaded/reconstruction/3D+AR milestones. Only a confirmed server finalization sets the upload receipt. Per-file acknowledgments drive upload progress; interrupted transfers skip hashes already stored on the server.
- After server confirmation the PC works independently. Returning to the app or selecting a prior scan checks the server and retrieves its verified USDZ. The ready model has a direct **Open my dish in 3D / AR** button. Saved videos and the status of every scan remain accessible.
- **Video only (without live 3D)** remains a clearly labeled fallback under Other capture methods. It cannot infer a live spatial cloud from an ordinary recording.

## Persistence and resource limits

`delivery.json` is separate from `capture.json`, so camera metadata saves cannot erase server receipts. No capability or association code is exported. Existing capture records decode with optional video segment paths. Opening a saved scan performs read-only checks; it never uploads or starts another job without the send/check action. Queued reconstruction polling releases the UI between requests and stops in the background. An interrupted download retains the confirmed upload receipt.

The movie encoder admits one AR image at a time on a serial utility queue, copies it into its own at-most-three-buffer pool, encodes H.264 at up to 1280 pixels / 15fps / 2.5 Mbps, and skips frames under encoder backpressure. The original camera buffer is not retained by the hardware encoder. Camera analysis retains at most one additional ARFrame. A continuous segment is capped at 90 seconds, then the user can resume; earlier segments and restart originals are preserved. A short iOS background task finalizes the movie when leaving the app. The main capture remains its individually saved useful JPEG observations, even if recording fails.

PC reconstruction limits remain one CPU, 1536 MiB container memory, one job at a time and no extra swap. Compilation and real movie encode/decode tests run on hosted macOS, not on the user's 8 GB laptop.

## Validation and limits

Hosted tests cover durable receipts after interruption/corruption, real movie encoding/decoding and portrait orientation, monotonic timestamps, resolution cap, shutdown before the first frame, preserved existing movies, plus existing video extraction, orbit coverage, silhouette projection and signing checks. The full iOS release target must archive before a signed TestFlight upload.

Physical camera alignment, point density, thermal behavior and AR placement still require an iPhone run. The evolving display is an observed point cloud / silhouette estimate / depth surface, not the final textured photogrammetry result. Scene depth and mesh are used only on supported hardware; scale remains unverified until reviewed.

Apple references: [ARFrame camera image](https://developer.apple.com/documentation/arkit/arframe/capturedimage), [pixel buffer writer](https://developer.apple.com/documentation/avfoundation/avassetwriterinputpixelbufferadaptor), [writer completion](https://developer.apple.com/documentation/avfoundation/avassetwriter/finishwriting(completionhandler:)).
