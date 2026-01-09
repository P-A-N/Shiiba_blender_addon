bl_info = {
    "name": "PLY Timeline Loader",
    "author": "Shiiba NFT Unity",
    "version": (1, 0, 0),
    "blender": (4, 4, 0),
    "location": "View3D > Sidebar > PLY Timeline",
    "description": "Load PLY file sequences in timeline with on-demand loading",
    "category": "Animation",
}

import bpy
import numpy as np
import os
import glob
import re
from bpy.app.handlers import persistent
from bpy.props import StringProperty, IntProperty, BoolProperty, EnumProperty
from bpy.types import Panel, Operator, PropertyGroup
from collections import OrderedDict


# ====== PLY Loader Class ======
class PLYLoader:
    """Handles loading and parsing PLY binary files"""

    @staticmethod
    def load_ply_binary(ply_path):
        """
        Load PLY file with position, color, and motion vectors.
        Returns: (numpy structured array, metadata dict) or (None, None) if failed
        """
        if not os.path.exists(ply_path):
            print(f"PLY file not found: {ply_path}")
            return None, None

        try:
            metadata = {}

            # Read header and parse metadata
            with open(ply_path, 'rb') as f:
                line = b''
                while line.strip() != b'end_header':
                    line = f.readline()

                    # Parse comment lines for metadata
                    if line.startswith(b'comment'):
                        comment = line.decode('utf-8').strip()

                        # Parse torso_7_global_position
                        if 'torso_7_global_position:' in comment:
                            parts = comment.split('torso_7_global_position:')[1].strip().split()
                            if len(parts) == 3:
                                try:
                                    metadata['torso_position'] = (
                                        float(parts[0]),
                                        float(parts[1]),
                                        float(parts[2])
                                    )
                                except ValueError:
                                    pass

                        # Parse PointCloudFrame
                        elif 'PointCloudFrame:' in comment:
                            parts = comment.split('PointCloudFrame:')[1].strip()
                            try:
                                metadata['pointcloud_frame'] = int(parts)
                            except ValueError:
                                pass

                        # Parse BvhFrame
                        elif 'BvhFrame:' in comment:
                            parts = comment.split('BvhFrame:')[1].strip()
                            try:
                                metadata['bvh_frame'] = int(parts)
                            except ValueError:
                                pass

                header_end = f.tell()

            # Binary data structure
            dt = np.dtype([
                ('x', '<f4'), ('y', '<f4'), ('z', '<f4'),
                ('red', 'u1'), ('green', 'u1'), ('blue', 'u1'),
                ('vx', '<f4'), ('vy', '<f4'), ('vz', '<f4')
            ])

            # Load data
            with open(ply_path, 'rb') as f:
                f.seek(header_end)
                data = np.fromfile(f, dtype=dt)

            return data, metadata

        except Exception as e:
            print(f"Error loading PLY: {e}")
            return None, None


# ====== Frame Handler with Caching ======
class PLYFrameHandler:
    """Handles frame changes and loads PLY files on-demand"""

    def __init__(self, frame_map, obj, mesh, camera_target=None, cache_size=10):
        self.frame_map = frame_map  # {frame_num: filepath}
        self.obj = obj
        self.mesh = mesh
        self.camera_target = camera_target  # Camera target object for torso position
        self.cache = OrderedDict()  # LRU cache
        self.cache_size = cache_size
        self.current_loaded_frame = None

    def is_valid(self):
        """Check if the referenced Blender objects are still valid"""
        try:
            # Attempt to access a property to verify the object still exists
            _ = self.obj.name
            _ = self.mesh.name
            return True
        except ReferenceError:
            return False

    def __call__(self, scene, depsgraph=None):
        """Called automatically when timeline frame changes"""
        current_frame = scene.frame_current
        print(f"[PLY Handler] Frame changed to: {current_frame}")

        # Check if objects are still valid
        if not self.is_valid():
            print("[PLY Handler] Object reference is no longer valid, removing handler")
            if self in bpy.app.handlers.frame_change_post:
                bpy.app.handlers.frame_change_post.remove(self)
            return

        # Skip if already loaded
        if current_frame == self.current_loaded_frame:
            print(f"[PLY Handler] Frame {current_frame} already loaded, skipping")
            return

        # Check if PLY exists for this frame
        if current_frame not in self.frame_map:
            print(f"[PLY Handler] No PLY file for frame {current_frame}, hiding object")
            self.obj.hide_viewport = True
            self.obj.hide_render = True
            return

        # Check cache first
        if current_frame in self.cache:
            print(f"[PLY Handler] Loading frame {current_frame} from cache")
            ply_data, metadata = self.cache[current_frame]
            # Move to end (most recently used)
            self.cache.move_to_end(current_frame)
        else:
            # Load from file
            ply_path = self.frame_map[current_frame]
            print(f"[PLY Handler] Loading frame {current_frame} from file: {ply_path}")
            ply_data, metadata = PLYLoader.load_ply_binary(ply_path)

            if ply_data is None:
                self.obj.hide_viewport = True
                return

            # Add to cache (both data and metadata)
            self.cache[current_frame] = (ply_data, metadata)

            # Evict oldest if cache full
            if len(self.cache) > self.cache_size:
                oldest = self.cache.popitem(last=False)
                print(f"Cache evicted frame {oldest[0]}")

        # Update mesh
        self.update_mesh(ply_data)

        # Update camera target position if available
        print(f"[PLY Handler] Camera target: {self.camera_target}, Metadata: {metadata}")

        if self.camera_target and metadata and 'torso_position' in metadata:
            # Unity coordinates: (x, y, z)
            x, y, z = metadata['torso_position']

            # Apply Unity to Blender transformation:
            # 1. Rotate 90° around X-axis: (x, y, z) -> (x, -z, y)
            # 2. Scale by 20
            blender_x = x * 20
            blender_y = -z * 20
            blender_z = y * 20

            self.camera_target.location = (blender_x, blender_y, blender_z)
            print(f"[PLY Handler] Updated camera target: Unity{metadata['torso_position']} -> Blender({blender_x:.3f}, {blender_y:.3f}, {blender_z:.3f})")
        else:
            if not self.camera_target:
                print("[PLY Handler] No camera target object")
            elif not metadata:
                print("[PLY Handler] No metadata found")
            elif 'torso_position' not in metadata:
                print(f"[PLY Handler] torso_position not in metadata. Available keys: {list(metadata.keys())}")

        self.obj.hide_viewport = False
        self.obj.hide_render = False
        self.current_loaded_frame = current_frame

    def update_mesh(self, data):
        """Update mesh with new PLY data"""
        n = len(data)

        # Clear and rebuild geometry
        self.mesh.clear_geometry()

        # Apply Unity to Blender coordinate transformation:
        # Unity (x, y, z) -> Blender (x * 20, -z * 20, y * 20)
        positions = np.stack([
            data['x'] * 20,
            -data['z'] * 20,
            data['y'] * 20
        ], axis=1)
        self.mesh.from_pydata(positions.tolist(), [], [])
        self.mesh.update()

        # Update color attribute
        if "color" not in self.mesh.attributes:
            color_attr = self.mesh.attributes.new(name="color", type='FLOAT_COLOR', domain='POINT')
        else:
            color_attr = self.mesh.attributes["color"]

        colors = np.stack([
            data['red'] / 255.0,
            data['green'] / 255.0,
            data['blue'] / 255.0,
            np.ones(n)
        ], axis=1).astype(np.float32)
        color_attr.data.foreach_set("color", colors.ravel())

        # Update velocity attributes with Unity to Blender transformation (rotation only, no scale)
        # Unity (vx, vy, vz) -> Blender (vx, -vz, vy)
        velocity_transformed = [
            ('vx', data['vx']),
            ('vy', -data['vz']),
            ('vz', data['vy'])
        ]
        for name, arr in velocity_transformed:
            if name not in self.mesh.attributes:
                attr = self.mesh.attributes.new(name=name, type='FLOAT', domain='POINT')
            else:
                attr = self.mesh.attributes[name]
            attr.data.foreach_set("value", arr.astype(np.float32))


# ====== Global Handler Storage ======
_global_handler = None


# ====== Property Group (Settings) ======
class PLYTimelineSettings(PropertyGroup):
    ply_directory: StringProperty(
        name="PLY Directory",
        description="Directory containing PLY file sequence",
        default="/Volumes/horristicSSD2T/Dropbox/projects/shiiba/mesh_exported/assets/Totori/PLY_Filtered_Motion",
        subtype='DIR_PATH'
    )

    object_name: StringProperty(
        name="Object Name",
        description="Name for the point cloud object",
        default="PointCloud_Timeline"
    )

    cache_size: IntProperty(
        name="Cache Size",
        description="Number of frames to keep in memory",
        default=10,
        min=1,
        max=100
    )

    is_active: BoolProperty(
        name="Timeline Active",
        description="Is PLY timeline currently active",
        default=False
    )

    use_geometry_nodes: BoolProperty(
        name="Apply Geometry Nodes",
        description="Automatically apply a Geometry Nodes modifier",
        default=False
    )

    create_camera_target: BoolProperty(
        name="Create Camera Target",
        description="Create an empty object at torso position for camera tracking",
        default=True
    )

    camera_target_name: StringProperty(
        name="Camera Target Name",
        description="Name for the camera target object",
        default="PLY_CameraTarget"
    )

    def get_node_groups(self, context):
        """Enum callback to get available Geometry Nodes groups"""
        items = []
        for i, ng in enumerate(bpy.data.node_groups):
            if ng.type == 'GEOMETRY':
                items.append((ng.name, ng.name, f"Apply {ng.name}"))
        if not items:
            items.append(('NONE', 'No Geometry Nodes Available', 'Import a node group first'))
        return items

    geometry_nodes_group: EnumProperty(
        name="Node Group",
        description="Geometry Nodes group to apply",
        items=get_node_groups
    )


# ====== Operators ======
class PLY_OT_SetupTimeline(Operator):
    """Setup PLY timeline with frame change handler"""
    bl_idname = "ply.setup_timeline"
    bl_label = "Setup PLY Timeline"
    bl_description = "Discover PLY files and setup timeline playback"

    def execute(self, context):
        global _global_handler

        settings = context.scene.ply_timeline_settings

        print("=" * 50)
        print("[PLY Setup] Starting PLY Timeline setup...")
        print("=" * 50)

        # Discover all PLY files in directory
        search_pattern = os.path.join(settings.ply_directory, "*.ply")
        print(f"[PLY Setup] Searching for: {search_pattern}")
        ply_files = glob.glob(search_pattern)
        print(f"[PLY Setup] Found {len(ply_files)} PLY files")

        if not ply_files:
            self.report({'ERROR'}, f"No PLY files found in: {settings.ply_directory}")
            return {'CANCELLED'}

        # Build frame map - extract numbers from filenames
        import re
        frame_map = {}
        for filepath in ply_files:
            filename = os.path.basename(filepath)
            # Find all numbers in filename
            numbers = re.findall(r'\d+', filename)
            if numbers:
                # Use the last number found (usually the frame number)
                frame_num = int(numbers[-1])
                frame_map[frame_num] = filepath
                print(f"[PLY Setup] {filename} -> frame {frame_num}")
            else:
                self.report({'WARNING'}, f"No frame number found in: {filename}")
                continue

        if not frame_map:
            self.report({'ERROR'}, "No PLY files with frame numbers found")
            return {'CANCELLED'}

        # Get or create object
        if settings.object_name in bpy.data.objects:
            obj = bpy.data.objects[settings.object_name]
            mesh = obj.data
        else:
            mesh = bpy.data.meshes.new(f"{settings.object_name}_Mesh")
            obj = bpy.data.objects.new(settings.object_name, mesh)
            context.scene.collection.objects.link(obj)

        # Create or get camera target
        camera_target = None
        if settings.create_camera_target:
            if settings.camera_target_name in bpy.data.objects:
                camera_target = bpy.data.objects[settings.camera_target_name]
            else:
                camera_target = bpy.data.objects.new(settings.camera_target_name, None)
                camera_target.empty_display_type = 'SPHERE'
                camera_target.empty_display_size = 0.2
                context.scene.collection.objects.link(camera_target)
                print(f"[PLY Setup] Created camera target: {settings.camera_target_name}")

        # Apply Geometry Nodes if enabled
        if settings.use_geometry_nodes and settings.geometry_nodes_group != 'NONE':
            node_group_name = settings.geometry_nodes_group
            if node_group_name in bpy.data.node_groups:
                # Check if modifier already exists
                mod_name = "PLY_GeometryNodes"
                if mod_name not in obj.modifiers:
                    mod = obj.modifiers.new(name=mod_name, type='NODES')
                else:
                    mod = obj.modifiers[mod_name]

                mod.node_group = bpy.data.node_groups[node_group_name]
                self.report({'INFO'}, f"Applied Geometry Nodes: {node_group_name}")
            else:
                self.report({'WARNING'}, f"Node group '{node_group_name}' not found")

        # Set timeline range
        frames = sorted(frame_map.keys())
        context.scene.frame_start = frames[0]
        context.scene.frame_end = frames[-1]

        # Remove old handler if exists
        if _global_handler is not None:
            if _global_handler in bpy.app.handlers.frame_change_post:
                bpy.app.handlers.frame_change_post.remove(_global_handler)

        # Create and register new handler
        _global_handler = PLYFrameHandler(frame_map, obj, mesh, camera_target, settings.cache_size)
        bpy.app.handlers.frame_change_post.append(_global_handler)
        print(f"[PLY Setup] Handler registered! Total handlers: {len(bpy.app.handlers.frame_change_post)}")

        # Load initial frame
        print(f"[PLY Setup] Loading initial frame: {context.scene.frame_current}")
        _global_handler(context.scene)

        settings.is_active = True

        print(f"[PLY Setup] Setup complete! {len(frame_map)} frames ({frames[0]}-{frames[-1]})")
        print("=" * 50)
        self.report({'INFO'}, f"PLY Timeline setup complete! {len(frame_map)} frames ({frames[0]}-{frames[-1]})")

        return {'FINISHED'}


class PLY_OT_StopTimeline(Operator):
    """Stop PLY timeline and remove handler"""
    bl_idname = "ply.stop_timeline"
    bl_label = "Stop PLY Timeline"
    bl_description = "Remove frame change handler and stop timeline"

    def execute(self, context):
        global _global_handler

        print("=" * 50)
        print("[PLY Stop] Stopping PLY Timeline...")
        print("=" * 50)

        if _global_handler is not None:
            print(f"[PLY Stop] Handler exists: {_global_handler}")
            if _global_handler in bpy.app.handlers.frame_change_post:
                bpy.app.handlers.frame_change_post.remove(_global_handler)
                _global_handler = None
                context.scene.ply_timeline_settings.is_active = False
                print("[PLY Stop] Handler removed, timeline stopped")
                self.report({'INFO'}, "PLY Timeline stopped")
            else:
                print("[PLY Stop] Handler not found in frame_change_post")
                self.report({'WARNING'}, "Handler not found")
        else:
            print("[PLY Stop] No active handler, resetting state anyway")
            # Reset the state even if handler is missing
            context.scene.ply_timeline_settings.is_active = False
            self.report({'WARNING'}, "No active handler - state reset")

        print("=" * 50)
        return {'FINISHED'}


class PLY_OT_ClearCache(Operator):
    """Clear the PLY frame cache"""
    bl_idname = "ply.clear_cache"
    bl_label = "Clear Cache"
    bl_description = "Clear cached PLY frames to free memory"

    def execute(self, context):
        global _global_handler

        if _global_handler is not None and hasattr(_global_handler, 'cache'):
            cache_size = len(_global_handler.cache)
            _global_handler.cache.clear()
            self.report({'INFO'}, f"Cleared {cache_size} cached frames")
        else:
            self.report({'WARNING'}, "No active cache")

        return {'FINISHED'}


# ====== UI Panel ======
class PLY_PT_TimelinePanel(Panel):
    """Creates a Panel in the 3D Viewport sidebar"""
    bl_label = "PLY Timeline Loader"
    bl_idname = "PLY_PT_timeline_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'PLY Timeline'

    def draw(self, context):
        layout = self.layout
        settings = context.scene.ply_timeline_settings

        # Settings section
        box = layout.box()
        box.label(text="Settings:", icon='SETTINGS')
        box.prop(settings, "ply_directory")
        box.prop(settings, "object_name")
        box.prop(settings, "cache_size")

        # Geometry Nodes section
        layout.separator()
        gn_box = layout.box()
        gn_box.label(text="Geometry Nodes:", icon='GEOMETRY_NODES')
        gn_box.prop(settings, "use_geometry_nodes")
        if settings.use_geometry_nodes:
            gn_box.prop(settings, "geometry_nodes_group")

        # Camera Target section
        layout.separator()
        cam_box = layout.box()
        cam_box.label(text="Camera Target:", icon='EMPTY_AXIS')
        cam_box.prop(settings, "create_camera_target")
        if settings.create_camera_target:
            cam_box.prop(settings, "camera_target_name")

        # Status section
        layout.separator()
        status_box = layout.box()
        if settings.is_active:
            status_box.label(text="Status: Active", icon='CHECKMARK')
            if _global_handler and hasattr(_global_handler, 'cache'):
                status_box.label(text=f"Cached frames: {len(_global_handler.cache)}")
                status_box.label(text=f"Current frame: {_global_handler.current_loaded_frame or 'None'}")
        else:
            status_box.label(text="Status: Inactive", icon='X')

        # Control buttons
        layout.separator()
        row = layout.row(align=True)
        row.scale_y = 1.5

        if settings.is_active:
            row.operator("ply.stop_timeline", icon='PAUSE')
            layout.operator("ply.clear_cache", icon='TRASH')
        else:
            row.operator("ply.setup_timeline", icon='PLAY')

        # Info section
        layout.separator()
        info_box = layout.box()
        info_box.label(text="Timeline Controls:", icon='INFO')
        info_box.label(text="• Scrub timeline to load frames")
        info_box.label(text="• Frames cached for fast playback")
        info_box.label(text="• Object auto-hides if no PLY")


# ====== Persistent Handler (survives file loads) ======
@persistent
def load_post_handler(dummy):
    """Called after loading a new file - clears handler state"""
    global _global_handler
    # Don't auto-setup, let user manually setup
    # This prevents unexpected behavior when opening files
    if bpy.context.scene.ply_timeline_settings.is_active:
        bpy.context.scene.ply_timeline_settings.is_active = False


# ====== Registration ======
classes = (
    PLYTimelineSettings,
    PLY_OT_SetupTimeline,
    PLY_OT_StopTimeline,
    PLY_OT_ClearCache,
    PLY_PT_TimelinePanel,
)

def register():
    """Called when add-on is enabled"""
    print("=" * 50)
    print("Registering PLY Timeline Loader Add-on")
    print("=" * 50)

    for cls in classes:
        bpy.utils.register_class(cls)

    # Add settings to scene
    bpy.types.Scene.ply_timeline_settings = bpy.props.PointerProperty(type=PLYTimelineSettings)

    # Register load handler
    if load_post_handler not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(load_post_handler)

    print("✅ PLY Timeline Loader registered successfully")
    print("   Access via: View3D > Sidebar > PLY Timeline tab")

def unregister():
    """Called when add-on is disabled"""
    global _global_handler

    print("Unregistering PLY Timeline Loader Add-on")

    # Remove frame handler if active
    if _global_handler is not None:
        if _global_handler in bpy.app.handlers.frame_change_post:
            bpy.app.handlers.frame_change_post.remove(_global_handler)
        _global_handler = None

    # Remove load handler
    if load_post_handler in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(load_post_handler)

    # Remove settings
    del bpy.types.Scene.ply_timeline_settings

    # Unregister classes
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    print("✅ PLY Timeline Loader unregistered")

if __name__ == "__main__":
    register()
