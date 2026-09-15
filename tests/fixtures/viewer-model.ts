// Synthetic triangle for testing glTF loading only. Never a food reconstruction or production asset.
export function technicalViewerFixture(): Buffer {
  const positions = Buffer.alloc(36);
  [-1, -1, 0, 1, -1, 0, 0, 1, 0].forEach((n, i) => positions.writeFloatLE(n, i * 4));
  const gltf = {
    asset: { version: '2.0', generator: 'DishPlay technical test fixture — not reconstructed' },
    scene: 0,
    scenes: [{ nodes: [0] }],
    nodes: [{ mesh: 0 }],
    meshes: [{ primitives: [{ attributes: { POSITION: 0 }, material: 0 }] }],
    materials: [
      {
        doubleSided: true,
        pbrMetallicRoughness: {
          baseColorFactor: [0.1, 0.3, 0.8, 1],
          metallicFactor: 0,
          roughnessFactor: 1,
        },
      },
    ],
    buffers: [{ byteLength: positions.length }],
    bufferViews: [{ buffer: 0, byteOffset: 0, byteLength: positions.length, target: 34962 }],
    accessors: [
      {
        bufferView: 0,
        componentType: 5126,
        count: 3,
        type: 'VEC3',
        min: [-1, -1, 0],
        max: [1, 1, 0],
      },
    ],
  };
  const raw = Buffer.from(JSON.stringify(gltf));
  const json = Buffer.alloc(Math.ceil(raw.length / 4) * 4, 0x20);
  raw.copy(json);
  const glb = Buffer.alloc(12 + 8 + json.length + 8 + positions.length);
  glb.write('glTF');
  glb.writeUInt32LE(2, 4);
  glb.writeUInt32LE(glb.length, 8);
  glb.writeUInt32LE(json.length, 12);
  glb.write('JSON', 16);
  json.copy(glb, 20);
  const binStart = 20 + json.length;
  glb.writeUInt32LE(positions.length, binStart);
  glb.write('BIN\0', binStart + 4);
  positions.copy(glb, binStart + 8);
  return glb;
}
