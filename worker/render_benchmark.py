"""Identical neutral inspection render; independent auto-framing is NOT geometric alignment."""
import sys
import bpy
from mathutils import Vector
source,target=sys.argv[sys.argv.index("--")+1:]
bpy.ops.object.select_all(action="SELECT");bpy.ops.object.delete(use_global=False)
bpy.ops.import_scene.gltf(filepath=source)
meshes=[o for o in bpy.context.scene.objects if o.type=="MESH"]
points=[o.matrix_world@Vector(corner) for o in meshes for corner in o.bound_box]
low=Vector([min(p[i] for p in points) for i in range(3)])
high=Vector([max(p[i] for p in points) for i in range(3)])
center=(low+high)/2;radius=max((high-low).length/2,.001)
bpy.ops.object.camera_add(location=center+Vector((1.4,-1.8,1.25))*radius)
camera=bpy.context.object;camera.rotation_euler=(center-camera.location).to_track_quat("-Z","Y").to_euler()
camera.data.clip_start=radius/1000;camera.data.clip_end=radius*100
camera.data.type="ORTHO";camera.data.ortho_scale=radius*2.5;bpy.context.scene.camera=camera
bpy.ops.object.light_add(type="AREA",location=center+Vector((1,-1,3))*radius)
bpy.context.object.data.energy=800*radius*radius;bpy.context.object.data.shape="DISK";bpy.context.object.data.size=radius*3
scene=bpy.context.scene;scene.render.engine="CYCLES";scene.cycles.device="CPU";scene.cycles.samples=12
scene.render.threads_mode="FIXED";scene.render.threads=1
scene.world.color=(.3,.3,.3);scene.render.resolution_x=512;scene.render.resolution_y=512;scene.render.resolution_percentage=100
scene.render.image_settings.file_format="PNG";scene.render.filepath=target
bpy.ops.render.render(write_still=True)
