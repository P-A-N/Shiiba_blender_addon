bl_info = {
    "name": "Rendering and export camera info",
    "author": "horristic",
    "version": (1, 0, 0),
    "blender": (4, 4, 0),
    "location": "View3D > Sidebar > Render & Export",
    "description": "Display current camera position, rotation, and FOV",
    "category": "3D View",
}

import bpy
import math
import json
import os
import random
import struct
import re
import shutil
from bpy.types import Panel, Operator, PropertyGroup
from bpy.props import StringProperty, FloatProperty, BoolProperty, IntProperty
from mathutils import Matrix, Vector, Quaternion


# ====== Property Group ======
class CameraExportSettings(PropertyGroup):
    export_directory: StringProperty(
        name="Export Directory",
        description="Parent directory where work folders will be created",
        default="//",
        subtype='DIR_PATH'
    )

    work_name: StringProperty(
        name="Name of work",
        description="Name of the work - used as directory name and file prefix",
        default="render"
    )

    radius_near: FloatProperty(
        name="Radius Near",
        description="Minimum distance from target (meters)",
        default=0.5,
        min=0.01,
        max=100.0,
        soft_min=0.1,
        soft_max=10.0,
        unit='LENGTH'
    )

    radius_far: FloatProperty(
        name="Radius Far",
        description="Maximum distance from target (meters)",
        default=2.0,
        min=0.01,
        max=100.0,
        soft_min=0.1,
        soft_max=10.0,
        unit='LENGTH'
    )

    downsample_enabled: BoolProperty(
        name="Export Downsampled PLY",
        description="Export a downsampled version of the original PLY file with embedded camera/light data",
        default=False
    )

    downsample_ratio: FloatProperty(
        name="Downsample Ratio",
        description="Percentage of points to keep (e.g., 0.1 = 10%)",
        default=0.1,
        min=0.01,
        max=1.0,
        soft_min=0.01,
        soft_max=1.0,
        subtype='PERCENTAGE'
    )

    move_lights_with_camera: BoolProperty(
        name="Move Lights with Camera",
        description="When enabled, lights maintain their relative position and orientation to camera",
        default=True
    )

    target_offset_max: FloatProperty(
        name="Target Offset Max",
        description="Maximum random offset from target point (meters)",
        default=10.0,
        min=0.0,
        max=50.0,
        soft_min=0.0,
        soft_max=20.0,
        unit='LENGTH'
    )

    target_down_offset: FloatProperty(
        name="Target Down Offset",
        description="Vertical offset to look below target point (meters)",
        default=5.5,
        min=0.0,
        max=20.0,
        soft_min=0.0,
        soft_max=10.0,
        unit='LENGTH'
    )

    frame_min: IntProperty(
        name="Frame Min",
        description="Minimum frame number for random selection",
        default=1,
        min=0
   )

    frame_max: IntProperty(
        name="Frame Max",
        description="Maximum frame number for random selection",
        default=250,
        min=0
    )

    max_renders: IntProperty(
        name="Max Renders",
        description="Maximum number of renders (0 = unlimited)",
        default=0,
        min=0
    )

    is_loop_rendering: BoolProperty(
        name="Loop Rendering Active",
        description="Internal flag to track if loop render is active",
        default=False
    )

    loop_render_count: IntProperty(
        name="Loop Render Count",
        description="Number of renders completed in current loop",
        default=0,
        min=0
    )

    loop_waiting_for_render: BoolProperty(
        name="Waiting for Render",
        description="Internal flag to track if waiting for render to complete",
        default=False
    )

    loop_render_pending: BoolProperty(
        name="Render Pending",
        description="Internal flag to track if render should start on next modal tick",
        default=False
    )

    loop_render_start_time: FloatProperty(
        name="Render Start Time",
        description="Time when render was scheduled",
        default=0.0
    )

    theta_center: FloatProperty(
        name="Theta Center (degrees)",
        description="Center value for theta (azimuthal angle) in degrees",
        default=180.0,
        min=0.0,
        max=360.0,
        soft_min=0.0,
        soft_max=360.0
    )

    theta_std_dev: FloatProperty(
        name="Theta Std Dev (degrees)",
        description="Standard deviation for theta (azimuthal angle) in degrees",
        default=60.0,
        min=1.0,
        max=180.0,
        soft_min=10.0,
        soft_max=90.0
    )

    phi_center: FloatProperty(
        name="Phi Center (degrees)",
        description="Center value for phi (polar angle) in degrees. 0°=top, 90°=horizon, 180°=bottom",
        default=45.0,
        min=0.0,
        max=180.0,
        soft_min=0.0,
        soft_max=180.0
    )

    phi_std_dev: FloatProperty(
        name="Phi Std Dev (degrees)",
        description="Standard deviation for phi (polar angle) in degrees",
        default=20.0,
        min=1.0,
        max=90.0,
        soft_min=5.0,
        soft_max=60.0
    )

    distance_adjustment_start: FloatProperty(
        name="Distance Adjust Start (m)",
        description="Distance where phi angle adjustment starts",
        default=30.0,
        min=0.0,
        max=200.0,
        soft_min=10.0,
        soft_max=100.0,
        unit='LENGTH'
    )

    distance_adjustment_end: FloatProperty(
        name="Distance Adjust End (m)",
        description="Distance where phi angle adjustment reaches maximum",
        default=80.0,
        min=0.0,
        max=200.0,
        soft_min=20.0,
        soft_max=150.0,
        unit='LENGTH'
    )

    phi_reduction_max: FloatProperty(
        name="Max Phi Reduction (degrees)",
        description="Maximum phi angle reduction at far distances (makes camera look more down)",
        default=15.0,
        min=0.0,
        max=90.0,
        soft_min=0.0,
        soft_max=45.0
    )

    fov_min: FloatProperty(
        name="FOV Min (degrees)",
        description="Minimum field of view for random camera",
        default=20.0,
        min=1.0,
        max=179.0,
        soft_min=10.0,
        soft_max=120.0
    )

    fov_max: FloatProperty(
        name="FOV Max (degrees)",
        description="Maximum field of view for random camera",
        default=80.0,
        min=1.0,
        max=179.0,
        soft_min=10.0,
        soft_max=120.0
    )


# ====== UI Panel ======
class CAMERA_PT_InfoPanel(Panel):
    """Creates a Panel in the 3D Viewport sidebar showing camera information"""
    bl_label = "Render & Export"
    bl_idname = "CAMERA_PT_info_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Render & Export'

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # Get active camera
        camera = scene.camera

        if camera is None:
            box = layout.box()
            box.label(text="No active camera", icon='ERROR')
            box.label(text="Set a camera in scene properties")
            return

        if camera.type != 'CAMERA':
            box = layout.box()
            box.label(text="Active object is not a camera", icon='ERROR')
            return

        # Camera name section
        name_box = layout.box()
        name_box.label(text=f"Camera: {camera.name}", icon='CAMERA_DATA')

        # Position section
        layout.separator()
        pos_box = layout.box()
        pos_box.label(text="Position:", icon='EMPTY_ARROWS')

        pos = camera.location
        col = pos_box.column(align=True)
        row = col.row(align=True)
        row.label(text="X:")
        row.label(text=f"{pos.x:.4f}")
        row = col.row(align=True)
        row.label(text="Y:")
        row.label(text=f"{pos.y:.4f}")
        row = col.row(align=True)
        row.label(text="Z:")
        row.label(text=f"{pos.z:.4f}")

        # Rotation section (Euler angles in degrees)
        layout.separator()
        rot_box = layout.box()
        rot_box.label(text="Rotation:", icon='DRIVER_ROTATIONAL_DIFFERENCE')

        # Get rotation in degrees
        if camera.rotation_mode == 'QUATERNION':
            euler = camera.rotation_quaternion.to_euler()
        elif camera.rotation_mode == 'AXIS_ANGLE':
            euler = camera.rotation_axis_angle.to_euler()
        else:
            euler = camera.rotation_euler

        rot_deg_x = math.degrees(euler.x)
        rot_deg_y = math.degrees(euler.y)
        rot_deg_z = math.degrees(euler.z)

        col = rot_box.column(align=True)
        row = col.row(align=True)
        row.label(text="X:")
        row.label(text=f"{rot_deg_x:.2f}°")
        row = col.row(align=True)
        row.label(text="Y:")
        row.label(text=f"{rot_deg_y:.2f}°")
        row = col.row(align=True)
        row.label(text="Z:")
        row.label(text=f"{rot_deg_z:.2f}°")

        # FOV section
        layout.separator()
        fov_box = layout.box()
        fov_box.label(text="Field of View:", icon='OUTLINER_OB_CAMERA')

        cam_data = camera.data

        # Get FOV based on sensor fit
        if cam_data.lens_unit == 'MILLIMETERS':
            # Calculate FOV from focal length
            if cam_data.sensor_fit == 'VERTICAL':
                sensor_size = cam_data.sensor_height
            elif cam_data.sensor_fit == 'HORIZONTAL':
                sensor_size = cam_data.sensor_width
            else:  # AUTO
                if context.scene.render.resolution_x * cam_data.sensor_height > \
                   context.scene.render.resolution_y * cam_data.sensor_width:
                    sensor_size = cam_data.sensor_width
                else:
                    sensor_size = cam_data.sensor_height

            fov_rad = 2 * math.atan(sensor_size / (2 * cam_data.lens))
            fov_deg = math.degrees(fov_rad)

            col = fov_box.column(align=True)
            row = col.row(align=True)
            row.label(text="Focal Length:")
            row.label(text=f"{cam_data.lens:.2f} mm")
            row = col.row(align=True)
            row.label(text="FOV:")
            row.label(text=f"{fov_deg:.2f}°")
        else:  # FOV mode
            fov_rad = cam_data.angle
            fov_deg = math.degrees(fov_rad)

            col = fov_box.column(align=True)
            row = col.row(align=True)
            row.label(text="FOV:")
            row.label(text=f"{fov_deg:.2f}°")

        # Output settings
        layout.separator()
        settings_box = layout.box()
        settings_box.label(text="Output Settings:", icon='FILEBROWSER')
        settings = context.scene.camera_export_settings
        settings_box.prop(settings, "export_directory")
        settings_box.prop(settings, "work_name")

        # PLY Downsample settings
        layout.separator()
        ply_box = layout.box()
        ply_box.label(text="PLY Downsample:", icon='MESH_DATA')
        ply_box.prop(settings, "downsample_enabled")
        if settings.downsample_enabled:
            ply_box.prop(settings, "downsample_ratio", slider=True)

        # Random Camera settings
        layout.separator()
        random_box = layout.box()
        random_box.label(text="Random Camera:", icon='FILE_REFRESH')
        random_box.prop(settings, "radius_near")
        random_box.prop(settings, "radius_far")
        random_box.prop(settings, "target_offset_max")
        random_box.prop(settings, "target_down_offset")

        # Random FOV settings
        random_box.separator()
        random_box.label(text="Random FOV:", icon='OUTLINER_OB_CAMERA')
        row = random_box.row(align=True)
        row.prop(settings, "fov_min")
        row.prop(settings, "fov_max")

        # Gaussian distribution settings
        random_box.separator()
        random_box.label(text="Angle Distribution (Gaussian):", icon='DRIVER')
        random_box.prop(settings, "theta_center")
        random_box.prop(settings, "theta_std_dev")
        random_box.prop(settings, "phi_center")
        random_box.prop(settings, "phi_std_dev")

        # Distance-based angle adjustment
        random_box.separator()
        random_box.label(text="Distance-Based Adjustment:", icon='ARROW_LEFTRIGHT')
        random_box.prop(settings, "distance_adjustment_start")
        random_box.prop(settings, "distance_adjustment_end")
        random_box.prop(settings, "phi_reduction_max")

        # Light relationship controls
        random_box.separator()
        random_box.prop(settings, "move_lights_with_camera")
        random_box.operator("camera.save_light_relationship", text="Save Light Relationship", icon='LIGHT')

        # Show status if lights have saved relationships
        lights_with_data = sum(1 for obj in context.scene.objects
                              if obj.type == 'LIGHT' and "camera_offset_x" in obj)
        if lights_with_data > 0:
            status_row = random_box.row()
            status_row.label(text=f"Saved: {lights_with_data} light(s)", icon='CHECKMARK')

        random_box.separator()
        random_box.operator("camera.view_to_camera", text="Set View to Camera", icon='VIEW_CAMERA')
        random_box.operator("camera.random_position", text="Randomize Camera Position", icon='FILE_REFRESH')

        # Loop Render section
        layout.separator()
        loop_box = layout.box()
        loop_box.label(text="Loop Random Render:", icon='RENDER_ANIMATION')

        settings = context.scene.camera_export_settings

        # Frame range controls
        row = loop_box.row(align=True)
        row.prop(settings, "frame_min")
        row.prop(settings, "frame_max")

        # Random frame button
        loop_box.operator("camera.random_frame", text="Random Frame", icon='TIME')

        # Optional max renders
        loop_box.prop(settings, "max_renders")

        # Start/Stop buttons
        loop_box.separator()
        if settings.is_loop_rendering:
            # Show stop button when active
            row = loop_box.row()
            row.scale_y = 1.5
            row.alert = True
            row.operator("camera.stop_loop_render", text="STOP Loop Render", icon='CANCEL')

            # Show status with render count
            status_row = loop_box.row()
            status_row.label(text=f"Rendering... (Completed: {settings.loop_render_count})", icon='TIME')
        else:
            # Show start button when inactive
            row = loop_box.row()
            row.scale_y = 1.5
            row.operator("camera.loop_render", text="Start Loop Render", icon='RENDER_ANIMATION')

            # Show last count if any
            if settings.loop_render_count > 0:
                count_row = loop_box.row()
                count_row.label(text=f"Last session: {settings.loop_render_count} renders", icon='INFO')

        # Render button
        layout.separator()
        render_box = layout.box()
        render_box.scale_y = 1.5
        render_box.operator("camera.render_and_export", text="Render Image", icon='RENDER_STILL')


# ====== Helper Functions ======
def downsample_ply(original_ply_path, output_ply_path, ratio):
    """Downsample original PLY file"""
    try:
        # Read original PLY file
        with open(original_ply_path, 'rb') as f:
            # Parse header
            header_lines = []
            vertex_count = 0
            header_end_pos = 0

            while True:
                line = f.readline().decode('ascii').strip()
                header_lines.append(line)

                # Extract vertex count
                if line.startswith('element vertex'):
                    vertex_count = int(line.split()[-1])

                # Check for end of header
                if line == 'end_header':
                    header_end_pos = f.tell()
                    break

            if vertex_count == 0:
                return False, "No vertices found in PLY file"

            # Calculate keep count
            keep_count = max(1, int(vertex_count * ratio))

            # Handle 100% ratio - just copy file
            if ratio >= 1.0 or keep_count == vertex_count:
                # Read all vertex data
                vertex_data = f.read(vertex_count * 27)  # 27 bytes per vertex

                write_ply(output_ply_path, header_lines, vertex_count, vertex_data)
                return True, f"PLY copied (100% of {vertex_count} points)"

            # Random sampling
            selected_indices = sorted(random.sample(range(vertex_count), keep_count))

            # Read selected vertices
            sampled_vertices = bytearray()
            for idx in selected_indices:
                f.seek(header_end_pos + idx * 27)
                sampled_vertices.extend(f.read(27))

            # Write downsampled PLY
            write_ply(output_ply_path, header_lines, keep_count, bytes(sampled_vertices))

            return True, f"PLY downsampled: {vertex_count} → {keep_count} points ({ratio*100:.1f}%)"

    except FileNotFoundError:
        return False, f"Original PLY file not found: {original_ply_path}"
    except Exception as e:
        return False, f"Error downsampling PLY: {str(e)}"


def write_ply(output_path, header_lines, vertex_count, vertex_data):
    """Write PLY file with updated vertex count"""
    with open(output_path, 'wb') as f:
        # Write header with modifications
        for line in header_lines:
            # Update vertex count
            if line.startswith('element vertex'):
                f.write(f'element vertex {vertex_count}\n'.encode('ascii'))
            elif line == 'end_header':
                f.write(b'end_header\n')
            else:
                f.write(f'{line}\n'.encode('ascii'))

        # Write vertex data
        f.write(vertex_data)


def find_ply_for_frame(ply_directory, frame_number):
    """Find PLY file matching the given frame number using same logic as PLYLoader"""
    try:
        # Get all .ply files in directory
        ply_files = [f for f in os.listdir(ply_directory) if f.lower().endswith('.ply')]

        for filename in ply_files:
            # Extract frame number from filename (last numeric value)
            # This matches the logic from ply_timeline_addon.py
            numbers = re.findall(r'\d+', filename)
            if numbers:
                file_frame = int(numbers[-1])
                if file_frame == frame_number:
                    return os.path.join(ply_directory, filename)

        return None
    except Exception as e:
        return None


def round_floats(obj, precision=10):
    """Recursively round all float values in nested dicts/lists to specified precision"""
    if isinstance(obj, float):
        return round(obj, precision)
    elif isinstance(obj, dict):
        return {k: round_floats(v, precision) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [round_floats(item, precision) for item in obj]
    else:
        return obj


def export_render_data(context, output_path, json_path, blend_path, original_filepath):
    """Export camera data, lights data, PLY file, and blend file after render completes"""
    scene = context.scene
    camera = scene.camera

    # Restore original filepath
    scene.render.filepath = original_filepath

    # Export camera data
    cam_data = camera.data

    # Get camera position (Blender coordinates)
    pos_blender = camera.location

    # Get camera rotation as quaternion
    if camera.rotation_mode == 'QUATERNION':
        quaternion_blender = camera.rotation_quaternion.copy()
    elif camera.rotation_mode == 'AXIS_ANGLE':
        quaternion_blender = camera.rotation_axis_angle.to_quaternion()
    else:
        quaternion_blender = camera.rotation_euler.to_quaternion()

    # Export lights data
    lights_data = []
    for obj in scene.objects:
        if obj.type == 'LIGHT':
            light_data_obj = obj.data

            # Get light position (raw Blender coordinates)
            light_pos_blender = obj.location
            light_pos = {
                "x": float(light_pos_blender.x),
                "y": float(light_pos_blender.y),
                "z": float(light_pos_blender.z)
            }

            # Get light rotation as quaternion (raw Blender quaternion)
            if obj.rotation_mode == 'QUATERNION':
                light_quat_blender = obj.rotation_quaternion.copy()
            elif obj.rotation_mode == 'AXIS_ANGLE':
                light_quat_blender = obj.rotation_axis_angle.to_quaternion()
            else:
                light_quat_blender = obj.rotation_euler.to_quaternion()

            light_rot = {
                "x": float(light_quat_blender.x),
                "y": float(light_quat_blender.y),
                "z": float(light_quat_blender.z),
                "w": float(light_quat_blender.w)
            }

            # Get light properties
            light_info = {
                "name": obj.name,
                "type": light_data_obj.type,  # POINT, SUN, SPOT, AREA
                "position": light_pos,
                "rotation": light_rot,
                "energy": float(light_data_obj.energy),
                "color": [float(c) for c in light_data_obj.color]
            }

            # Add type-specific properties
            if light_data_obj.type == 'SPOT':
                light_info["spot_size"] = float(light_data_obj.spot_size)
                light_info["spot_blend"] = float(light_data_obj.spot_blend)

            lights_data.append(light_info)

    # Prepare JSON data
    camera_data = {
        "position": {
            "x": float(pos_blender.x),
            "y": float(pos_blender.y),
            "z": float(pos_blender.z)
        },
        "rotation": {
            "x": float(quaternion_blender.x),
            "y": float(quaternion_blender.y),
            "z": float(quaternion_blender.z),
            "w": float(quaternion_blender.w)
        },
        "fov": float(cam_data.angle),
        "frame": scene.frame_current,
        "lights": lights_data
    }

    # Round all float values to 10 decimal places to reduce file size
    camera_data = round_floats(camera_data, precision=10)

    # Write JSON file
    with open(json_path, 'w') as f:
        json.dump(camera_data, f, indent=2)

    # Save .blend file
    bpy.ops.wm.save_as_mainfile(filepath=blend_path, copy=True, compress=True)

    # Export PLY file with camera data if PLY Timeline addon is active
    settings = scene.camera_export_settings
    # Check if PLY settings exist (which means PLY addon is active)
    if hasattr(scene, 'ply_timeline_settings'):
        ply_settings = scene.ply_timeline_settings
        ply_directory = bpy.path.abspath(ply_settings.ply_directory)

        if ply_directory and os.path.isdir(ply_directory):
            frame_number = scene.frame_current

            # Find the PLY file for current frame
            original_ply_path = find_ply_for_frame(ply_directory, frame_number)

            if original_ply_path:
                # Output PLY path - save to same directory as JSON (root export directory)
                ply_filename = os.path.splitext(os.path.basename(json_path))[0] + '.ply'
                output_ply_path = os.path.join(os.path.dirname(json_path), ply_filename)

                # Downsample ratio from settings
                ratio = settings.downsample_ratio

                # Downsample and export
                success, message = downsample_ply(original_ply_path, output_ply_path, ratio)

                if success:
                    print(f"[Export] PLY exported: {output_ply_path}")
                else:
                    print(f"[Export] PLY export failed: {message}")
            else:
                print(f"[Export] PLY file not found for frame {frame_number}")
        else:
            print(f"[Export] PLY directory not valid: {ply_directory}")
    else:
        print("[Export] PLY Timeline addon not active")


# ====== Render State (persistent across operator lifetime) ======
_render_state = {
    'rendering': False,
    'cancelled': False,
}

def _render_complete_handler(scene, depsgraph):
    """Handler called when render completes"""
    _render_state['rendering'] = False
    # Remove self from handlers
    if _render_complete_handler in bpy.app.handlers.render_complete:
        bpy.app.handlers.render_complete.remove(_render_complete_handler)

def _render_cancel_handler(scene, depsgraph):
    """Handler called when render is cancelled"""
    _render_state['rendering'] = False
    _render_state['cancelled'] = True
    # Remove handlers
    if _render_cancel_handler in bpy.app.handlers.render_cancel:
        bpy.app.handlers.render_cancel.remove(_render_cancel_handler)
    if _render_complete_handler in bpy.app.handlers.render_complete:
        bpy.app.handlers.render_complete.remove(_render_complete_handler)


# ====== Operators ======
class CAMERA_OT_RenderAndExport(Operator):
    """Render image and export camera data for Three.js"""
    bl_idname = "camera.render_and_export"
    bl_label = "Render and Export"
    bl_description = "Render image and save camera data as JSON alongside the image"

    _timer = None

    def modal(self, context, event):
        if event.type == 'TIMER':
            # Check if rendering is complete using global state
            if not _render_state['rendering']:
                # Rendering finished, now export data
                if not _render_state['cancelled']:
                    self.export_data(context)
                self.cancel_timer(context)
                return {'FINISHED'}

        return {'PASS_THROUGH'}

    def cancel_timer(self, context):
        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None

    def execute(self, context):
        camera = context.scene.camera
        if camera is None:
            self.report({'ERROR'}, "No active camera")
            return {'CANCELLED'}

        if camera.type != 'CAMERA':
            self.report({'ERROR'}, "Active object is not a camera")
            return {'CANCELLED'}

        # Get settings
        scene = context.scene
        settings = scene.camera_export_settings

        # Get export directory and work name
        export_base_dir = bpy.path.abspath(settings.export_directory)
        work_name = settings.work_name
        frame_number = scene.frame_current

        # Create output directory: export_directory/work_name/
        output_dir = os.path.join(export_base_dir, work_name)
        # Create img subdirectory for PNG files
        img_dir = os.path.join(output_dir, "img")

        # Create directories if they don't exist
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(img_dir, exist_ok=True)

        # Find next available filename with index if file exists
        base_filename = f"{work_name}_{frame_number:05d}"
        filename = f"{base_filename}.png"
        json_filename = f"{base_filename}.json"
        blend_filename = f"{base_filename}.blend"

        output_path = os.path.join(img_dir, filename)
        json_path = os.path.join(output_dir, json_filename)
        blend_path = os.path.join(output_dir, blend_filename)

        # Check if files exist and find next available index
        index = 1
        while os.path.exists(output_path) or os.path.exists(json_path) or os.path.exists(blend_path):
            filename = f"{base_filename}_{index}.png"
            json_filename = f"{base_filename}_{index}.json"
            blend_filename = f"{base_filename}_{index}.blend"

            output_path = os.path.join(img_dir, filename)
            json_path = os.path.join(output_dir, json_filename)
            blend_path = os.path.join(output_dir, blend_filename)
            index += 1

        # Store paths for later use in export_data
        self.output_path = output_path
        self.json_path = json_path
        self.blend_path = blend_path
        self.original_filepath = scene.render.filepath

        # Set the render output path
        scene.render.filepath = output_path

        # Reset render state and register handlers
        _render_state['rendering'] = True
        _render_state['cancelled'] = False
        bpy.app.handlers.render_complete.append(_render_complete_handler)
        bpy.app.handlers.render_cancel.append(_render_cancel_handler)

        # Start rendering
        bpy.ops.render.render('INVOKE_DEFAULT', write_still=True)

        # Set up modal timer
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)

        return {'RUNNING_MODAL'}

    def export_data(self, context):
        """Export all data after render completes"""
        export_render_data(context, self.output_path, self.json_path,
                          self.blend_path, self.original_filepath)
        self.report({'INFO'}, f"Render complete: {self.output_path}")


class CAMERA_OT_SaveLightRelationship(Operator):
    """Save the current spatial relationship between camera and all lights"""
    bl_idname = "camera.save_light_relationship"
    bl_label = "Save Light Relationship"
    bl_description = "Save the relative position and rotation of all lights to the camera"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        camera = scene.camera

        if camera is None:
            self.report({'ERROR'}, "No active camera")
            return {'CANCELLED'}

        if camera.type != 'CAMERA':
            self.report({'ERROR'}, "Active object is not a camera")
            return {'CANCELLED'}

        # Ensure camera is in quaternion rotation mode for consistent calculations
        camera.rotation_mode = 'QUATERNION'

        # Get camera's transform
        camera_quat = camera.rotation_quaternion.copy()
        camera_pos = camera.location.copy()

        # Find all lights in the scene
        lights = [obj for obj in scene.objects if obj.type == 'LIGHT']

        if not lights:
            self.report({'WARNING'}, "No lights found in scene")
            return {'CANCELLED'}

        # Save relationship for each light
        saved_count = 0
        for light in lights:
            # Ensure light is in quaternion rotation mode
            light.rotation_mode = 'QUATERNION'

            # Calculate position offset in camera's local space
            # Transform world offset to camera local space
            world_offset = light.location - camera_pos
            camera_matrix = camera_quat.to_matrix()
            local_offset = camera_matrix.inverted() @ world_offset

            # Store position offset
            light["camera_offset_x"] = local_offset.x
            light["camera_offset_y"] = local_offset.y
            light["camera_offset_z"] = local_offset.z

            saved_count += 1

        self.report({'INFO'}, f"Saved light relationship for {saved_count} light(s)")
        return {'FINISHED'}


class CAMERA_OT_RandomPosition(Operator):
    """Position camera randomly around PLY_CameraTarget using polar coordinates"""
    bl_idname = "camera.random_position"
    bl_label = "Random Camera Position"
    bl_description = "Randomly position camera around PLY_CameraTarget (distance: 0.5-2m)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        camera = scene.camera

        if camera is None:
            self.report({'ERROR'}, "No active camera")
            return {'CANCELLED'}

        if camera.type != 'CAMERA':
            self.report({'ERROR'}, "Active object is not a camera")
            return {'CANCELLED'}

        # Find the target object
        target = scene.objects.get("PLY_CameraTarget")
        if target is None:
            self.report({'ERROR'}, "PLY_CameraTarget object not found in scene")
            return {'CANCELLED'}

        # Get target position
        target_pos = target.location

        # Get settings
        settings = scene.camera_export_settings
        radius_near = settings.radius_near
        radius_far = settings.radius_far

        # Validate radius values
        if radius_near >= radius_far:
            self.report({'ERROR'}, "Radius Near must be less than Radius Far")
            return {'CANCELLED'}

        # Generate random polar coordinates
        # Keep generating until we get a position above the floor
        max_attempts = 100
        attempt = 0
        camera_pos = None

        while attempt < max_attempts:
            # distance: radial distance (from radius_near to radius_far)
            distance = random.uniform(radius_near, radius_far)

            # theta: azimuthal angle (0 to 2π) - rotation around Z axis
            # Use Gaussian distribution with user-defined center and std dev
            theta_center_rad = math.radians(settings.theta_center)
            theta_std_dev_rad = math.radians(settings.theta_std_dev)
            theta = random.gauss(theta_center_rad, theta_std_dev_rad)
            # Wrap theta to [0, 2π] range
            theta = theta % (2 * math.pi)

            # phi: polar angle (0 to π) - angle from Z axis
            # Use Gaussian distribution with user-defined center and std dev
            phi_center_rad = math.radians(settings.phi_center)
            phi_std_dev_rad = math.radians(settings.phi_std_dev)

            # Adjust phi based on distance: farther = lower angle (more top-down)
            dist_start = settings.distance_adjustment_start
            dist_end = settings.distance_adjustment_end
            phi_reduction = settings.phi_reduction_max

            if distance > dist_start and dist_end > dist_start:
                # Linear interpolation from dist_start to dist_end
                # At dist_start: 0 degree reduction
                # At dist_end: phi_reduction degree reduction
                distance_factor = min((distance - dist_start) / (dist_end - dist_start), 1.0)
                phi_adjustment = math.radians(phi_reduction) * distance_factor
                phi_center_rad = phi_center_rad - phi_adjustment
                # Ensure phi_center_rad doesn't go below 0
                phi_center_rad = max(0, phi_center_rad)

            phi = random.gauss(phi_center_rad, phi_std_dev_rad)
            # Clamp phi to [0, π] range
            phi = max(0, min(math.pi, phi))

            # Convert polar to Cartesian coordinates
            x = distance * math.sin(phi) * math.cos(theta)
            y = distance * math.sin(phi) * math.sin(theta)
            z = distance * math.cos(phi)

            # Calculate final camera position
            camera_pos = Vector((
                target_pos.x + x,
                target_pos.y + y,
                target_pos.z + z
            ))

            # Check if camera is above floor (Z > 0)
            if camera_pos.z > 0:
                break

            attempt += 1

        if camera_pos is None or camera_pos.z <= 0:
            self.report({'ERROR'}, "Could not find valid camera position above floor after 100 attempts")
            return {'CANCELLED'}

        # Set camera position
        camera.location = camera_pos

        # Point camera at target using a more reliable method
        # Generate random offset for look-at point
        if settings.target_offset_max > 0:
            offset_distance = random.uniform(0, settings.target_offset_max)
            offset_theta = random.uniform(0, 2 * math.pi)
            offset_phi = random.uniform(0, math.pi)

            offset_x = offset_distance * math.sin(offset_phi) * math.cos(offset_theta)
            offset_y = offset_distance * math.sin(offset_phi) * math.sin(offset_theta)
            offset_z = offset_distance * math.cos(offset_phi)

            # Apply target down offset
            look_at_point = target_pos + Vector((offset_x, offset_y, offset_z - settings.target_down_offset))
        else:
            # Apply target down offset
            look_at_point = target_pos + Vector((0, 0, -settings.target_down_offset))

        # Calculate direction from camera to look-at point
        direction = look_at_point - camera.location

        # Use track_to constraint approach: camera looks down -Z axis
        rot_quat = direction.to_track_quat('Z', 'Y')

        # Apply rotation
        camera.rotation_mode = 'QUATERNION'
        camera.rotation_quaternion = rot_quat

        # Flip 180 degrees because camera looks down -Z
        flip = Quaternion((0, 1, 0), math.pi)
        camera.rotation_quaternion @= flip

        # Randomize camera FOV
        fov_min = settings.fov_min
        fov_max = settings.fov_max
        if fov_min < fov_max:
            fov_degrees = random.uniform(fov_min, fov_max)
            fov_radians = math.radians(fov_degrees)
            camera.data.angle = fov_radians

        # Move lights with camera if enabled
        if settings.move_lights_with_camera:
            # Get all lights with saved relationships
            lights = [obj for obj in scene.objects if obj.type == 'LIGHT']
            moved_lights = 0

            for light in lights:
                # Check if this is a backlight (name contains "Back")
                is_backlight = "back" in light.name.lower()

                if is_backlight:
                    # Backlight: place on opposite side of target from camera, 10m from target
                    # Calculate direction from camera to target
                    camera_to_target = target_pos - camera.location
                    camera_to_target_normalized = camera_to_target.normalized()

                    # Place backlight 10m beyond target (opposite side from camera)
                    backlight_distance = 10.0
                    light.location = target_pos + camera_to_target_normalized * backlight_distance

                    # Make backlight face the target
                    light_direction = target_pos - light.location
                    light.rotation_mode = 'QUATERNION'
                    light_rot_quat = light_direction.to_track_quat('-Z', 'Y')
                    light.rotation_quaternion = light_rot_quat

                    moved_lights += 1

                # Check if light has saved offset data (for non-backlights)
                elif ("camera_offset_x" in light and
                    "camera_offset_y" in light and
                    "camera_offset_z" in light):

                    # Retrieve stored offset
                    local_offset = Vector((
                        light["camera_offset_x"],
                        light["camera_offset_y"],
                        light["camera_offset_z"]
                    ))

                    # Transform offset to world space using camera's rotation
                    camera_matrix = camera.rotation_quaternion.to_matrix()
                    world_offset = camera_matrix @ local_offset

                    # Set light position
                    light.location = camera.location + world_offset

                    # Make light face the target
                    light_direction = target_pos - light.location
                    light.rotation_mode = 'QUATERNION'
                    light_rot_quat = light_direction.to_track_quat('-Z', 'Y')
                    light.rotation_quaternion = light_rot_quat

                    moved_lights += 1

            if moved_lights > 0:
                self.report({'INFO'}, f"Camera positioned at distance {distance:.2f}m (θ={math.degrees(theta):.1f}°, φ={math.degrees(phi):.1f}°) - {moved_lights} light(s) moved")
            else:
                self.report({'INFO'}, f"Camera positioned at distance {distance:.2f}m (θ={math.degrees(theta):.1f}°, φ={math.degrees(phi):.1f}°)")
        else:
            self.report({'INFO'}, f"Camera positioned at distance {distance:.2f}m (θ={math.degrees(theta):.1f}°, φ={math.degrees(phi):.1f}°)")

        return {'FINISHED'}


class CAMERA_OT_LoopRender(Operator):
    """Continuously render random frames with random camera positions until stopped"""
    bl_idname = "camera.loop_render"
    bl_label = "Loop Random Render"
    bl_description = "Randomly select frames and render with random camera positions until stopped"

    _timer = None
    _render_count = 0
    _should_stop = False
    _waiting_for_render = False
    _output_dir = None
    _render_complete_flag = False
    _rendering = False

    # Store paths for export after render
    output_path = None
    json_path = None
    blend_path = None
    original_filepath = None

    def modal(self, context, event):
        settings = context.scene.camera_export_settings

        # Handle ESC key to stop
        if event.type == 'ESC':
            self.report({'INFO'}, f"Loop render cancelled by ESC - completed {self._render_count} renders")
            return self.finish(context)

        # Check stop button
        if not settings.is_loop_rendering:
            self.report({'INFO'}, f"Loop render stopped - completed {self._render_count} renders")
            return self.finish(context)

        if event.type == 'TIMER':
            import time

            # Check if render is pending and delay has passed (1 second)
            if settings.loop_render_pending:
                if time.time() - settings.loop_render_start_time >= 1.0:
                    settings.loop_render_pending = False
                    print(f"[Loop Render] Starting render now (from modal with valid context)")
                    try:
                        context.view_layer.update()
                    except Exception as e:
                        print(f"[Loop Render] Pre-render view layer update warning: {e}")
                    bpy.ops.render.render('INVOKE_DEFAULT', write_still=True)
            # If not waiting, start next iteration
            # Use settings.loop_waiting_for_render instead of self._waiting_for_render
            # because the deferred timer callback cannot access self
            elif not settings.loop_waiting_for_render and not self._should_stop:
                print(f"[Loop Render] Starting next render (count: {settings.loop_render_count})")
                self.start_next_render(context)

        return {'PASS_THROUGH'}

    def render_complete_handler(self, scene, depsgraph=None):
        """Called when render completes"""
        print(f"[Loop Render] Render completion handler triggered")

        # Remove the handler first to prevent re-entry
        try:
            if self.render_complete_handler in bpy.app.handlers.render_complete:
                bpy.app.handlers.render_complete.remove(self.render_complete_handler)
        except Exception as e:
            print(f"[Loop Render] Error removing handler: {e}")

        # Defer export operations to after the render handler completes
        # This prevents "update requested during evaluation" errors
        # IMPORTANT: Use longer delay (0.5s) to ensure depsgraph is fully stable

        # Capture all needed data as local variables before the timer fires
        # The operator instance (self) may be deallocated by then
        output_path = self.output_path
        json_path = self.json_path
        blend_path = self.blend_path
        original_filepath = self.original_filepath

        def deferred_export():
            print(f"[Loop Render] Executing deferred export...")
            context = bpy.context

            # Ensure we're not in the middle of a depsgraph evaluation
            # by checking if any updates are pending
            try:
                # Force a complete view layer update first to flush pending operations
                context.view_layer.update()
            except Exception as e:
                print(f"[Loop Render] View layer update warning: {e}")

            # Export data using captured local variables
            export_render_data(context, output_path, json_path,
                              blend_path, original_filepath)
            print(f"[Loop Render] Export complete: {output_path}")

            # Update counters via scene settings (not via self)
            settings = context.scene.camera_export_settings
            settings.loop_render_count += 1

            # Check if should stop
            max_renders = settings.max_renders
            if max_renders > 0 and settings.loop_render_count >= max_renders:
                print(f"[Loop Render] Max renders reached, stopping")
                settings.is_loop_rendering = False

            # Signal that we're ready for next render
            settings.loop_waiting_for_render = False
            print(f"[Loop Render] Ready for next render")

            return None  # Don't repeat

        # Schedule export to happen after handler completes
        # Use longer delay (0.5s) to ensure depsgraph is fully stable before save
        bpy.app.timers.register(deferred_export, first_interval=0.5)

    def start_next_render(self, context):
        """Select random frame, randomize camera, and start render"""
        scene = context.scene
        settings = scene.camera_export_settings

        # Select random frame
        frame_min = settings.frame_min
        frame_max = settings.frame_max

        if frame_min >= frame_max:
            self.report({'ERROR'}, "Frame Min must be less than Frame Max")
            return self.finish(context)

        random_frame = random.randint(frame_min, frame_max)
        # frame_set() triggers depsgraph update internally
        scene.frame_set(random_frame)

        # Wait for depsgraph to stabilize after frame change
        try:
            context.view_layer.update()
        except Exception as e:
            print(f"[Loop Render] View layer update after frame_set warning: {e}")

        # Randomize camera position
        bpy.ops.camera.random_position()

        # Ensure depsgraph is stable after camera move
        try:
            context.view_layer.update()
        except Exception as e:
            print(f"[Loop Render] View layer update after camera move warning: {e}")

        # Prepare render paths (same logic as CAMERA_OT_RenderAndExport)
        export_base_dir = bpy.path.abspath(settings.export_directory)
        work_name = settings.work_name
        frame_number = scene.frame_current

        # Create output directory and img subdirectory
        output_dir = os.path.join(export_base_dir, work_name)
        img_dir = os.path.join(output_dir, "img")
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(img_dir, exist_ok=True)

        # Find next available filename with index
        base_filename = f"{work_name}_{frame_number:05d}"
        filename = f"{base_filename}.png"
        json_filename = f"{base_filename}.json"
        blend_filename = f"{base_filename}.blend"

        output_path = os.path.join(img_dir, filename)
        json_path = os.path.join(output_dir, json_filename)
        blend_path = os.path.join(output_dir, blend_filename)

        # Find next available index if files exist
        index = 1
        while os.path.exists(output_path) or os.path.exists(json_path) or os.path.exists(blend_path):
            filename = f"{base_filename}_{index}.png"
            json_filename = f"{base_filename}_{index}.json"
            blend_filename = f"{base_filename}_{index}.blend"

            output_path = os.path.join(img_dir, filename)
            json_path = os.path.join(output_dir, json_filename)
            blend_path = os.path.join(output_dir, blend_filename)
            index += 1

        # Store paths for later export
        self.output_path = output_path
        self.json_path = json_path
        self.blend_path = blend_path
        self.original_filepath = scene.render.filepath

        # Set render output path
        scene.render.filepath = output_path

        # Register render completion handler
        # First, remove any existing handler to avoid duplicates
        try:
            while self.render_complete_handler in bpy.app.handlers.render_complete:
                bpy.app.handlers.render_complete.remove(self.render_complete_handler)
        except:
            pass

        # Now add the handler
        bpy.app.handlers.render_complete.append(self.render_complete_handler)
        print(f"[Loop Render] Registered render completion handler")

        # Mark that we're waiting for render
        self._waiting_for_render = True
        settings.loop_waiting_for_render = True

        # Schedule render to start from modal loop (where we have valid context)
        # Using a timer here causes "Python context internal state bug" errors
        import time
        settings.loop_render_pending = True
        settings.loop_render_start_time = time.time()
        print(f"[Loop Render] Scheduled render to start (1s delay, via modal)")

    def export_data_after_render(self, context):
        """Export PLY, blend file, and JSON data after render completes"""
        # Call standalone export function
        export_render_data(context, self.output_path, self.json_path,
                          self.blend_path, self.original_filepath)
        print(f"[Loop Render] Export complete: {self.output_path}")

    def finish(self, context):
        """Clean up and finish"""
        settings = context.scene.camera_export_settings
        settings.is_loop_rendering = False
        settings.loop_waiting_for_render = False
        settings.loop_render_pending = False
        settings.loop_render_count = self._render_count

        # Remove render completion handler if still registered
        if self.render_complete_handler in bpy.app.handlers.render_complete:
            bpy.app.handlers.render_complete.remove(self.render_complete_handler)

        if self._timer:
            try:
                context.window_manager.event_timer_remove(self._timer)
            except:
                pass
            self._timer = None

        # Force UI update
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()

        return {'FINISHED'}

    def execute(self, context):
        # Validate inputs
        settings = context.scene.camera_export_settings

        if context.scene.camera is None:
            self.report({'ERROR'}, "No active camera")
            return {'CANCELLED'}

        if settings.frame_min >= settings.frame_max:
            self.report({'ERROR'}, "Frame Min must be less than Frame Max")
            return {'CANCELLED'}

        # Initialize state
        self._render_count = 0
        self._should_stop = False
        self._waiting_for_render = False
        settings.is_loop_rendering = True
        settings.loop_render_count = 0
        settings.loop_waiting_for_render = False
        settings.loop_render_pending = False

        # Set up timer to check every 0.1 second for responsive render scheduling
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)

        self.report({'INFO'}, "Loop render started")

        # Start first render
        self.start_next_render(context)

        return {'RUNNING_MODAL'}


class CAMERA_OT_StopLoopRender(Operator):
    """Stop the loop rendering process"""
    bl_idname = "camera.stop_loop_render"
    bl_label = "Stop Loop Render"
    bl_description = "Stop the active loop rendering"

    def execute(self, context):
        settings = context.scene.camera_export_settings
        settings.is_loop_rendering = False
        self.report({'INFO'}, "Loop render stop requested")
        return {'FINISHED'}


class CAMERA_OT_RandomFrame(Operator):
    """Set the current frame to a random value within the configured range"""
    bl_idname = "camera.random_frame"
    bl_label = "Random Frame"
    bl_description = "Jump to a random frame within Frame Min and Frame Max range"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        settings = scene.camera_export_settings

        frame_min = settings.frame_min
        frame_max = settings.frame_max

        if frame_min >= frame_max:
            self.report({'ERROR'}, "Frame Min must be less than Frame Max")
            return {'CANCELLED'}

        random_frame = random.randint(frame_min, frame_max)
        scene.frame_set(random_frame)

        self.report({'INFO'}, f"Frame set to {random_frame}")
        return {'FINISHED'}


class CAMERA_OT_ViewToCamera(Operator):
    """Set camera position and rotation to match the current 3D viewport view"""
    bl_idname = "camera.view_to_camera"
    bl_label = "View to Camera"
    bl_description = "Set the active camera's position and rotation to match the current 3D viewport"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        camera = scene.camera
        settings = scene.camera_export_settings

        if camera is None:
            self.report({'ERROR'}, "No active camera")
            return {'CANCELLED'}

        if camera.type != 'CAMERA':
            self.report({'ERROR'}, "Active object is not a camera")
            return {'CANCELLED'}

        # Find the 3D viewport
        area = None
        for a in context.screen.areas:
            if a.type == 'VIEW_3D':
                area = a
                break

        if area is None:
            self.report({'ERROR'}, "No 3D viewport found")
            return {'CANCELLED'}

        # Get the region_3d from the viewport
        region_3d = area.spaces.active.region_3d

        # Get the view matrix and extract position/rotation
        view_matrix = region_3d.view_matrix.inverted()

        # Set camera position
        camera.location = view_matrix.translation

        # Set camera rotation
        camera.rotation_mode = 'QUATERNION'
        camera.rotation_quaternion = view_matrix.to_quaternion()

        # Move lights with camera if enabled
        moved_lights = 0
        if settings.move_lights_with_camera:
            # Get target position for backlight calculation
            target = scene.objects.get("PLY_CameraTarget")
            target_pos = target.location if target else camera.location

            # Get all lights in the scene
            lights = [obj for obj in scene.objects if obj.type == 'LIGHT']

            for light in lights:
                # Check if this is a backlight (name contains "Back")
                is_backlight = "back" in light.name.lower()

                if is_backlight:
                    # Backlight: place on opposite side of target from camera, 10m from target
                    camera_to_target = target_pos - camera.location
                    camera_to_target_normalized = camera_to_target.normalized()

                    # Place backlight 10m beyond target (opposite side from camera)
                    backlight_distance = 10.0
                    light.location = target_pos + camera_to_target_normalized * backlight_distance

                    # Make backlight face the target
                    light_direction = target_pos - light.location
                    light.rotation_mode = 'QUATERNION'
                    light_rot_quat = light_direction.to_track_quat('-Z', 'Y')
                    light.rotation_quaternion = light_rot_quat

                    moved_lights += 1

                # Check if light has saved offset data (for non-backlights)
                elif ("camera_offset_x" in light and
                      "camera_offset_y" in light and
                      "camera_offset_z" in light):

                    # Retrieve stored offset
                    local_offset = Vector((
                        light["camera_offset_x"],
                        light["camera_offset_y"],
                        light["camera_offset_z"]
                    ))

                    # Transform offset to world space using camera's rotation
                    camera_matrix = camera.rotation_quaternion.to_matrix()
                    world_offset = camera_matrix @ local_offset

                    # Set light position
                    light.location = camera.location + world_offset

                    # Make light face the target
                    light_direction = target_pos - light.location
                    light.rotation_mode = 'QUATERNION'
                    light_rot_quat = light_direction.to_track_quat('-Z', 'Y')
                    light.rotation_quaternion = light_rot_quat

                    moved_lights += 1

        # Export JSON file (same logic as render button, but without rendering)
        export_base_dir = bpy.path.abspath(settings.export_directory)
        work_name = settings.work_name
        frame_number = scene.frame_current

        # Create output directory
        output_dir = os.path.join(export_base_dir, work_name)
        os.makedirs(output_dir, exist_ok=True)

        # Find next available filename with index if file exists
        base_filename = f"{work_name}_{frame_number:05d}"
        json_filename = f"{base_filename}.json"
        json_path = os.path.join(output_dir, json_filename)

        index = 1
        while os.path.exists(json_path):
            json_filename = f"{base_filename}_{index}.json"
            json_path = os.path.join(output_dir, json_filename)
            index += 1

        # Export camera and lights data to JSON
        cam_data = camera.data

        # Get camera rotation as quaternion
        quaternion_blender = camera.rotation_quaternion.copy()

        # Export lights data
        lights_data = []
        for obj in scene.objects:
            if obj.type == 'LIGHT':
                light_data_obj = obj.data

                # Get light position
                light_pos = {
                    "x": float(obj.location.x),
                    "y": float(obj.location.y),
                    "z": float(obj.location.z)
                }

                # Get light rotation as quaternion
                if obj.rotation_mode == 'QUATERNION':
                    light_quat = obj.rotation_quaternion.copy()
                elif obj.rotation_mode == 'AXIS_ANGLE':
                    light_quat = obj.rotation_axis_angle.to_quaternion()
                else:
                    light_quat = obj.rotation_euler.to_quaternion()

                light_rot = {
                    "x": float(light_quat.x),
                    "y": float(light_quat.y),
                    "z": float(light_quat.z),
                    "w": float(light_quat.w)
                }

                light_info = {
                    "name": obj.name,
                    "type": light_data_obj.type,
                    "position": light_pos,
                    "rotation": light_rot,
                    "energy": float(light_data_obj.energy),
                    "color": [float(c) for c in light_data_obj.color]
                }

                if light_data_obj.type == 'SPOT':
                    light_info["spot_size"] = float(light_data_obj.spot_size)
                    light_info["spot_blend"] = float(light_data_obj.spot_blend)

                lights_data.append(light_info)

        # Prepare JSON data
        camera_data = {
            "position": {
                "x": float(camera.location.x),
                "y": float(camera.location.y),
                "z": float(camera.location.z)
            },
            "rotation": {
                "x": float(quaternion_blender.x),
                "y": float(quaternion_blender.y),
                "z": float(quaternion_blender.z),
                "w": float(quaternion_blender.w)
            },
            "fov": float(cam_data.angle),
            "frame": frame_number,
            "lights": lights_data
        }

        # Round floats and write JSON
        camera_data = round_floats(camera_data, precision=10)
        with open(json_path, 'w') as f:
            json.dump(camera_data, f, indent=2)

        if moved_lights > 0:
            self.report({'INFO'}, f"Camera set to current view - {moved_lights} light(s) moved - JSON exported: {json_filename}")
        else:
            self.report({'INFO'}, f"Camera set to current view - JSON exported: {json_filename}")
        return {'FINISHED'}


# ====== Registration ======
classes = (
    CameraExportSettings,
    CAMERA_OT_RenderAndExport,
    CAMERA_OT_SaveLightRelationship,
    CAMERA_OT_RandomPosition,
    CAMERA_OT_LoopRender,
    CAMERA_OT_StopLoopRender,
    CAMERA_OT_RandomFrame,
    CAMERA_OT_ViewToCamera,
    CAMERA_PT_InfoPanel,
)

def register():
    """Called when add-on is enabled"""
    print("=" * 50)
    print("Registering Render & Export Add-on")
    print("=" * 50)

    # Clean up any stale render handlers from previous addon crashes/reloads
    try:
        # Clear all render_complete handlers that might be stale
        handlers_to_remove = []
        for handler in bpy.app.handlers.render_complete:
            handler_name = getattr(handler, '__name__', '')
            if 'render_complete_handler' in handler_name:
                handlers_to_remove.append(handler)

        for handler in handlers_to_remove:
            try:
                bpy.app.handlers.render_complete.remove(handler)
                print(f"   Cleaned up stale handler: {handler}")
            except:
                pass
    except Exception as e:
        print(f"   Note: Could not clean handlers: {e}")

    for cls in classes:
        bpy.utils.register_class(cls)

    # Register settings
    bpy.types.Scene.camera_export_settings = bpy.props.PointerProperty(type=CameraExportSettings)

    print("Render & Export registered successfully")
    print("   Access via: View3D > Sidebar > Render & Export tab")

def unregister():
    """Called when add-on is disabled"""
    print("Unregistering Render & Export Add-on")

    # Clean up any active handlers
    try:
        handlers_to_remove = []
        for handler in bpy.app.handlers.render_complete:
            handler_name = getattr(handler, '__name__', '')
            if 'render_complete_handler' in handler_name:
                handlers_to_remove.append(handler)

        for handler in handlers_to_remove:
            try:
                bpy.app.handlers.render_complete.remove(handler)
            except:
                pass
    except:
        pass

    # Unregister settings
    del bpy.types.Scene.camera_export_settings

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    print("Render & Export unregistered")

if __name__ == "__main__":
    register()
