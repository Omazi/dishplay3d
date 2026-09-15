# Native capture acceptance boundary

This checkout provides browser photo capture usable on iOS Safari and Android Chrome over HTTPS. It does **not** contain installable Swift/RealityKit or Kotlin/ARCore applications. No native compilation, iPhone capture, Android capture or dense live point cloud has been verified.

The dossier's native apps remain required for the full product, and require a dedicated implementation:

1. iOS: check `ObjectCaptureSession.isSupported` and reconstruction support separately; connect native capture view and point-cloud view to actual session state. Fall back to browser photos where unsupported.
2. Android: runtime camera permission and ARCore availability; real anchors, bounded volume controls and tracked points. Depth only when the session reports support.
3. Preserve image intrinsics, timestamps, coordinate conventions and segment boundaries after tracking loss. Validate reprojection before using poses in reconstruction.
4. Pair to a dish through a short-lived single-use code; never put account secrets in the public QR.
5. Test the full lifecycle including interruption, recovery, finalization, exported originals and upload resumption on physical phones.

Do not describe a browser framing guide as a spatial anchor, or photo counts as scene coverage. Do not use arbitrary sample 3D objects as proof of food reconstruction.
