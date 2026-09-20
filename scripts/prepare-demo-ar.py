"""Run with pinned Blender 4.5.13. Illustrative tabletop dimensions, not measured food."""
import json
import sys
import struct
from pathlib import Path
import bpy
from mathutils import Vector, Matrix

source, output = map(Path, sys.argv[sys.argv.index('--') + 1:])
output.mkdir(parents=True, exist_ok=True)
(output / 'ar-validation.json').unlink(missing_ok=True)
report = []
assert bpy.app.version == (4, 5, 13)

def clear():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    bpy.data.orphans_purge(do_recursive=True)

def bounds():
    points = [obj.matrix_world @ Vector(corner) for obj in bpy.context.scene.objects if obj.type == 'MESH' for corner in obj.bound_box]
    return Vector(tuple(min(p[i] for p in points) for i in range(3))), Vector(tuple(max(p[i] for p in points) for i in range(3)))

def inspect():
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    assert meshes and sum(len(obj.data.polygons) for obj in meshes) > 0
    assert all(obj.data.uv_layers for obj in meshes)
    assert any(node.type == 'TEX_IMAGE' and node.image and node.image.size[0] > 0 for mat in bpy.data.materials if mat.use_nodes for node in mat.node_tree.nodes)
    low, high = bounds()
    return {'dimensions_m': list(high-low), 'minimum_m': list(low), 'faces': sum(len(obj.data.polygons) for obj in meshes)}

for name, width in [('burger', 0.16), ('pasta', 0.26), ('salad', 0.24)]:
    clear()
    bpy.ops.import_scene.gltf(filepath=str(source / (name+'-illustration.glb')))
    low, high = bounds()
    factor = width / max(high.x-low.x, high.y-low.y)  # Blender is Z-up.
    center = Vector(((low.x+high.x)/2, (low.y+high.y)/2, low.z))
    transform = Matrix.Scale(factor, 4) @ Matrix.Translation(-center)
    for obj in bpy.context.scene.objects:
        if obj.parent is None: obj.matrix_world = transform @ obj.matrix_world
    bpy.context.view_layer.update()
    bpy.context.scene.unit_settings.system = 'METRIC'
    bpy.context.scene.unit_settings.scale_length = 1
    # Add a root transform directly: preserve the original compressed textures,
    # materials, geometry and attribution instead of re-encoding the GLB.
    glb = output / (name+'-illustration.glb')
    usdz = output / (name+'-illustration.usdz')
    original = (source / (name+'-illustration.glb')).read_bytes()
    json_length = struct.unpack_from('<I', original, 12)[0]
    document = json.loads(original[20:20+json_length])
    for scene in document['scenes']:
        node = {'name':'Illustrative tabletop scale', 'children':scene.get('nodes',[]),
                'matrix':[factor,0,0,0, 0,factor,0,0, 0,0,factor,0,
                          -center.x*factor,-center.z*factor,center.y*factor,1],
                'extras':{'illustrativeWidthMeters':width,'measuredFoodScale':False}}
        scene['nodes'] = [len(document['nodes'])]
        document['nodes'].append(node)
    encoded = json.dumps(document,separators=(',',':')).encode()
    encoded += b' ' * (-len(encoded)%4)
    remainder = original[20+json_length:]
    glb.write_bytes(struct.pack('<4sII',b'glTF',2,20+len(encoded)+len(remainder)) + struct.pack('<I4s',len(encoded),b'JSON') + encoded + remainder)
    # gltfpack quantizes UVs and restores them through KHR_texture_transform.
    # Bake those transforms into per-face UV loops for USD, whose export otherwise
    # loses the Mapping node (valid textures then sample only a corner of the atlas).
    transforms = {}
    for material in bpy.data.materials:
        if not material.use_nodes: continue
        mappings = [n for n in material.node_tree.nodes if n.type=='MAPPING']
        if not mappings: continue
        values = [(tuple(n.inputs['Location'].default_value),tuple(n.inputs['Scale'].default_value)) for n in mappings]
        assert all(value==values[0] for value in values), 'Different texture transforms need separate UV sets'
        assert all(tuple(n.inputs['Rotation'].default_value)==(0,0,0) for n in mappings)
        transforms[material.name]=values[0]
    for obj in bpy.context.scene.objects:
        if obj.type!='MESH': continue
        uv = obj.data.uv_layers.active.data
        for face in obj.data.polygons:
            material = obj.material_slots[face.material_index].material
            if material.name not in transforms: continue
            location, scale = transforms[material.name]
            for i in face.loop_indices:
                old = uv[i].uv.copy()
                uv[i].uv = (old.x*scale[0]+location[0],old.y*scale[1]+location[1])
    for material in bpy.data.materials:
        if not material.use_nodes: continue
        for node in list(material.node_tree.nodes):
            if node.type!='MAPPING': continue
            source_socket = node.inputs['Vector'].links[0].from_socket
            for link in list(node.outputs['Vector'].links):
                material.node_tree.links.new(source_socket,link.to_socket)
            material.node_tree.nodes.remove(node)
    # USD Preview Surface does not translate Blender's unlit emission graph.
    # Retain each material's original image/UVs using a matte surface for Quick Look.
    for material in bpy.data.materials:
        if not material.use_nodes or any(n.type=='BSDF_PRINCIPLED' for n in material.node_tree.nodes): continue
        images = {n.image for n in material.node_tree.nodes if n.type=='TEX_IMAGE' and n.image}
        assert len(images)==1, 'Unlit material needs an unambiguous original base-color texture'
        nodes = material.node_tree.nodes
        texture = next(n for n in nodes if n.type=='TEX_IMAGE' and n.image)
        surface = nodes.new('ShaderNodeBsdfPrincipled')
        surface.inputs['Roughness'].default_value=1
        surface.inputs['Specular IOR Level'].default_value=0
        target = next(n for n in nodes if n.type=='OUTPUT_MATERIAL')
        material.node_tree.links.new(texture.outputs['Color'],surface.inputs['Base Color'])
        material.node_tree.links.new(surface.outputs['BSDF'],target.inputs['Surface'])
    bpy.ops.wm.usd_export(filepath=str(usdz), export_animation=False, export_uvmaps=True,
        export_normals=True, export_materials=True, export_textures=True,
        export_textures_mode='NEW', relative_paths=True, generate_preview_surface=True,
        convert_orientation=True, export_global_forward_selection='NEGATIVE_Z', export_global_up_selection='Y')
    item={'dish':name, 'illustrative_width_m':width}
    for fmt, asset in [('glb',glb),('usdz',usdz)]:
        clear()
        if fmt=='glb': bpy.ops.import_scene.gltf(filepath=str(asset))
        else: bpy.ops.wm.usd_import(filepath=str(asset))
        item[fmt]=inspect()
        if fmt=='usdz':
            uvs = [loop.uv.x for obj in bpy.context.scene.objects if obj.type=='MESH' for loop in obj.data.uv_layers.active.data]
            assert max(uvs) > 0.5, 'USD UVs must include the decoded texture transform'
            item[fmt]['uv_transform_baked'] = True
        dimensions=item[fmt]['dimensions_m']
        assert abs(max(dimensions[:2])-width) < 0.002, (name,fmt,dimensions)
        assert abs(item[fmt]['minimum_m'][2]) < 0.002
    report.append(item)
(output/'ar-validation.json').write_text(json.dumps(report,indent=2)+'\n')
print('Three textured GLB/USDZ pairs exported and reimported at illustrative tabletop dimensions')
