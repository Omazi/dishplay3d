# Illustrative photographs

The example restaurant and all its menu data are fictional. The photographs are real stock photographs; they are not this restaurant's dishes, captured scans, or evidence of reconstruction. No demonstration 3D asset is represented as a reconstructed dish.

Images downloaded from Unsplash's image CDN for the labelled example catalogue:

| File                       | Original image                                               |
| -------------------------- | ------------------------------------------------------------ |
| `public/images/burger.jpg` | https://images.unsplash.com/photo-1568901346375-23c9450c58cd |
| `public/images/pasta.jpg`  | https://images.unsplash.com/photo-1473093226795-af9932fe5856 |
| `public/images/salad.jpg`  | https://images.unsplash.com/photo-1512621776951-a57141f2eefd |

See https://unsplash.com/license. Replace these with your own dish photographs for an actual restaurant. Example names, prices and allergen lists do not describe the stock photographs reliably and must never be used as food advice.

## Interactive 3D demonstration

`public/models/avocado-demo.glb` is Microsoft's **Avocado** sample, released under
[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/legalcode).
[Original model and attribution](https://github.com/KhronosGroup/glTF-Sample-Assets/tree/main/Models/Avocado).
This is a labelled demonstration object, not a DishPlay reconstruction or a restaurant's dish.

The original GLB was downloaded from Khronos' `glTF-Sample-Assets` on 2026-09-20:
`Models/Avocado/glTF-Binary/Avocado.glb`.
Its geometry is unchanged. Embedded textures were resized from 2048px to 1024px
(base color, JPEG quality 90) and 512px (normal and roughness, PNG), using Sharp.
The self-contained GLB is **365,196 bytes**, down from 8,110,040 bytes. It needs no
external decoder or texture downloads. `public/images/avocado-3d.webp` is a render
of that same model made with the installed model-viewer, encoded as WebP.

SHA-256:

- Original GLB: `ccc9c3ce56423720b09399c2351537207cd5a65f859f9e6e2f30922762f3abd4`
- Optimized GLB: `c2e37f707937d463f6b486702b6620448ceb5336abe233c290fc032916880a4c`
- Poster: `0fd20cbbc7bfdc386d1e6c28c741588156a851aae916a662ad953cdfa6ee6328`

The homepage requests the engine and GLB only after an explicit click. Automatic
rotation pauses when the section leaves the viewport, the document is hidden, or
the visitor moves the camera; reduced-motion users start with rotation disabled.
Returning to the image removes the viewer and its observers/listeners. The shared
model cache is limited to one entry; the existing menu uses the same engine.
