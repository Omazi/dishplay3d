# Presentation and guided browser capture

## Design basis

The redesign retains DishPlay's warm white, graphite, restrained blue and existing licensed food photography. Large editorial type, deliberate spacing, image scale changes and short transitions respond to the requested Apple-like presentation without reproducing Apple's product artwork or page layout. Reference inspection: current DishPlay home/capture pages and the supplied dossier, page 3 (AR Code Object Capture sequence). The original 51.9-second video and target phone model were requested for a closer motion/device comparison.

The homepage explains capture, editing/publication and the customer menu through keyboard-accessible tabs. Demo price changes are explicitly local examples, and the displayed QR opens the actual demo menu. Capture links open the real capture page. Reduced-motion preferences disable animations; the server-rendered page remains readable without JavaScript. No WebGL engine or 3D viewer is loaded for this presentation.

## Browser capture behaviour

- Three selectable passes describe the sides (~30°), relief (~45°) and top (~65–80°). The angle is an instruction, not a measured phone pose. The plate remains still.
- The user confirms a completed circle; selected pass and confirmations persist per local series. Imported photos have no assigned pass. Camera photo metadata records the user-selected pass, not its spatial accuracy.
- Live analysis samples a 160×120 image every 500 ms. Central luminance/clipping, Laplacian variance and mean pixel differences provide advisory exposure, detail and stability feedback. Texture/noise/lighting changes can mislead these heuristics. They are not calibrated focus, overlap or object detectors.
- Assisted capture is opt-in. It waits for two stable samples, no quality warnings, a changed image compared with the previous retained frame, and at least 2.2 seconds between shots. Manual capture remains available. A changed image is not proof of a new viewing angle.
- Pausing, hiding the page, changing a pass/series, finalization, export or capture error stops assisted capture. Camera permission is requested only by the camera button. Import does not require camera permission.
- Captured originals retain advisory metrics and their version. Import analysis is sequential and optional: failure of advisory analysis does not discard a valid original. The ZIP still contains unchanged original bytes and explicit null poses/intrinsics.
- Paginated thumbnails expose every retained photo. Flagged photos have a review list; deletion remains explicit. Existing resumable upload and immutable finalization are preserved.

## Limits and verification

The guide is not the native spatial cube or live point cloud from the reference. Native Object Capture/ARCore work remains separate and needs physical-device acceptance. No fake coverage percentage, camera pose, point cloud or food model is generated. Reconstruction availability is unchanged.

Unit tests cover image-check edge cases. Browser tests exercise synthetic camera frames, blocked low-light auto capture, repeated-frame avoidance, a changed frame, pause, guide persistence, reduced motion and keyboard-operated product steps. Synthetic input validates control flow only, never a real food scan. Existing original-export, language-switch, linked transfer/finalization and restaurant/customer tests remain in CI.

The production build was measured at **767 MiB** sampled aggregate task RSS. Full end-to-end checks run on GitHub Actions rather than combining a database/server and browser on the 8 GB laptop.
