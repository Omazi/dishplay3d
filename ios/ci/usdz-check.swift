// Apple's own readers open a USDZ made by the calculator. Run on a Mac (the screen check does it):
//
//     swift ios/ci/usdz-check.swift <model.usdz> <picture.png>
//
// - Model I/O: what Apple's USD reader finds in the file (meshes, vertices, texture coordinates).
// - RealityKit, the engine behind iPhone's AR viewer: the size of the model in metres, its material and whether
//   the picture painted on it was found.
// - SceneKit: a picture of the model, to be looked at.
// Ends with a non-zero status when one of them finds no model, or no texture.
import AppKit
import Foundation
import Metal
import ModelIO
import RealityKit
import SceneKit

setvbuf(stdout, nil, _IOLBF, 0)
let arguments = CommandLine.arguments
guard arguments.count == 3 else {
    FileHandle.standardError.write(Data("usage: swift usdz-check.swift <model.usdz> <picture.png>\n".utf8))
    exit(2)
}
let modelURL = URL(fileURLWithPath: arguments[1])
let pictureURL = URL(fileURLWithPath: arguments[2])
var problems: [String] = []

// MARK: Model I/O

var meshCount = 0
var vertexCount = 0
var meshesWithTextureCoordinates = 0

func tally(_ object: MDLObject) {
    if let mesh = object as? MDLMesh {
        meshCount += 1
        vertexCount += mesh.vertexCount
        let attributes = mesh.vertexDescriptor.attributes.compactMap { $0 as? MDLVertexAttribute }
        if attributes.contains(where: { $0.name == MDLVertexAttributeTextureCoordinate && $0.format != .invalid }) {
            meshesWithTextureCoordinates += 1
        }
    }
    for child in object.children.objects { tally(child) }
}

let asset = MDLAsset(url: modelURL)
for index in 0..<asset.count { tally(asset.object(at: index)) }
print("Model I/O: \(meshCount) mesh(es), \(vertexCount) vertices, \(meshesWithTextureCoordinates) with texture coordinates")
if meshCount == 0 || vertexCount == 0 { problems.append("Model I/O found no mesh") }
if meshesWithTextureCoordinates == 0 { problems.append("Model I/O found no texture coordinates") }

// MARK: RealityKit

var partCount = 0
var materialCount = 0
var texturedMaterialCount = 0

func inspect(_ entity: Entity) {
    if let model = entity.components[ModelComponent.self] {
        partCount += 1
        for material in model.materials {
            materialCount += 1
            if let physical = material as? PhysicallyBasedMaterial, physical.baseColor.texture != nil {
                texturedMaterialCount += 1
            }
        }
    }
    for child in entity.children { inspect(child) }
}

do {
    let entity = try Entity.load(contentsOf: modelURL)
    inspect(entity)
    let size = entity.visualBounds(relativeTo: nil).extents
    let centimetres = [size.x, size.y, size.z].map { String(format: "%.1f", $0 * 100) }.joined(separator: " × ")
    print("RealityKit: \(partCount) part(s), \(materialCount) material(s), \(texturedMaterialCount) with a picture; size \(centimetres) cm")
    if partCount == 0 { problems.append("RealityKit found no model") }
    if texturedMaterialCount == 0 { problems.append("RealityKit found no picture on the model") }
} catch {
    problems.append("RealityKit could not open the file: \(error)")
}

// MARK: SceneKit

do {
    let scene = try SCNScene(url: modelURL, options: nil)
    let sphere = scene.rootNode.boundingSphere
    let radius = max(Double(sphere.radius), 0.001)
    let centre = sphere.center
    let viewpoint = SCNNode()
    let camera = SCNCamera()
    camera.zNear = radius * 0.05
    camera.zFar = radius * 40
    viewpoint.camera = camera
    viewpoint.position = SCNVector3(x: centre.x, y: centre.y + CGFloat(radius * 1.2), z: centre.z + CGFloat(radius * 2.2))
    viewpoint.look(at: centre)
    scene.rootNode.addChildNode(viewpoint)
    scene.background.contents = NSColor(srgbRed: 0.082, green: 0.086, blue: 0.075, alpha: 1)
    let renderer = SCNRenderer(device: MTLCreateSystemDefaultDevice(), options: nil)
    renderer.scene = scene
    renderer.pointOfView = viewpoint
    renderer.autoenablesDefaultLighting = true
    let image = renderer.snapshot(atTime: 0, with: CGSize(width: 900, height: 900), antialiasingMode: .multisampling4X)
    if let tiff = image.tiffRepresentation, let bitmap = NSBitmapImageRep(data: tiff),
       let png = bitmap.representation(using: .png, properties: [:]) {
        try png.write(to: pictureURL)
        print("SceneKit: picture written, radius of the scene \(String(format: "%.1f", radius * 100)) cm")
    } else {
        problems.append("SceneKit drew nothing that could be saved")
    }
} catch {
    problems.append("SceneKit could not open the file: \(error)")
}

if problems.isEmpty {
    print("USDZ accepted by Apple's readers")
} else {
    for problem in problems { print("PROBLEM: \(problem)") }
    exit(1)
}
