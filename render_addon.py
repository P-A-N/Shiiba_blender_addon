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
from bpy.props import StringProperty, FloatProperty, BoolProperty
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
        random_box.operator("camera.random_position", text="Randomize Camera Position", icon='FILE_REFRESH')

        # Render button
        layout.separator()
        render_box = layout.box()
        render_box.scale_y = 1.5
        render_box.operator("camera.render_and_export", text="Render Image", icon='RENDER_STILL')


# ====== Operators ======
class CAMERA_OT_RenderAndExport(Operator):
    """Render image and export camera data for Three.js"""
    bl_idname = "camera.render_and_export"
    bl_label = "Render and Export"
    bl_description = "Render image and save camera data as JSON alongside the image"

    _timer = None
    _rendering = False

    def modal(self, context, event):
        if event.type == 'TIMER':
            # Check if rendering is complete
            if not self._rendering:
                # Rendering finished, now export data
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

        # Create directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)

        # Find next available filename with index if file exists
        base_filename = f"{work_name}_{frame_number:04d}"
        filename = f"{base_filename}.png"
        json_filename = f"{base_filename}.json"
        blend_filename = f"{base_filename}.blend"

        output_path = os.path.join(output_dir, filename)
        json_path = os.path.join(output_dir, json_filename)
        blend_path = os.path.join(output_dir, blend_filename)

        # Check if files exist and find next available index
        index = 1
        while os.path.exists(output_path) or os.path.exists(json_path) or os.path.exists(blend_path):
            filename = f"{base_filename}_{index}.png"
            json_filename = f"{base_filename}_{index}.json"
            blend_filename = f"{base_filename}_{index}.blend"

            output_path = os.path.join(output_dir, filename)
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

        # Register render handlers
        bpy.app.handlers.render_complete.append(self.render_complete_handler)
        bpy.app.handlers.render_cancel.append(self.render_cancel_handler)

        # Start rendering
        self._rendering = True
        bpy.ops.render.render('INVOKE_DEFAULT', write_still=True)

        # Set up modal timer
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)

        return {'RUNNING_MODAL'}

    def render_complete_handler(self, scene, depsgraph):
        # Mark rendering as complete
        self._rendering = False
        # Remove handler
        bpy.app.handlers.render_complete.remove(self.render_complete_handler)

    def render_cancel_handler(self, scene, depsgraph):
        # Mark rendering as cancelled
        self._rendering = False
        # Remove handlers
        if self.render_cancel_handler in bpy.app.handlers.render_cancel:
            bpy.app.handlers.render_cancel.remove(self.render_cancel_handler)
        if self.render_complete_handler in bpy.app.handlers.render_complete:
            bpy.app.handlers.render_complete.remove(self.render_complete_handler)

    def downsample_ply(self, original_ply_path, output_ply_path, ratio, camera_data_json):
        """Downsample original PLY file and embed camera/light data in header"""
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

                # Handle 100% ratio - just copy file with camera data added
                if ratio >= 1.0 or keep_count == vertex_count:
                    # Read all vertex data
                    vertex_data = f.read(vertex_count * 27)  # 27 bytes per vertex

                    # Write output with camera data
                    self._write_ply_with_camera_data(output_ply_path, header_lines,
                                                     vertex_count, vertex_data, camera_data_json)
                    return True, f"PLY copied with camera data (100% of {vertex_count} points)"

                # Random sampling
                selected_indices = sorted(random.sample(range(vertex_count), keep_count))

                # Read selected vertices
                sampled_vertices = bytearray()
                for idx in selected_indices:
                    f.seek(header_end_pos + idx * 27)
                    sampled_vertices.extend(f.read(27))

                # Write downsampled PLY
                self._write_ply_with_camera_data(output_ply_path, header_lines,
                                                 keep_count, bytes(sampled_vertices), camera_data_json)

                return True, f"PLY downsampled: {vertex_count} → {keep_count} points ({ratio*100:.1f}%)"

        except FileNotFoundError:
            return False, f"Original PLY file not found: {original_ply_path}"
        except Exception as e:
            return False, f"Error downsampling PLY: {str(e)}"

    def _write_ply_with_camera_data(self, output_path, header_lines, vertex_count, vertex_data, camera_data_json):
        """Write PLY file with updated vertex count and embedded camera data"""
        with open(output_path, 'wb') as f:
            # Write header with modifications
            for line in header_lines:
                # Update vertex count
                if line.startswith('element vertex'):
                    f.write(f'element vertex {vertex_count}\n'.encode('ascii'))
                # Insert camera data comment before end_header
                elif line == 'end_header':
                    f.write(f'comment camera_data: {camera_data_json}\n'.encode('ascii'))
                    f.write(b'end_header\n')
                else:
                    f.write(f'{line}\n'.encode('ascii'))

            # Write vertex data
            f.write(vertex_data)

    def _find_ply_for_frame(self, ply_directory, frame_number):
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

    def export_data(self, context):
        scene = context.scene
        camera = scene.camera

        # Restore original filepath
        scene.render.filepath = self.original_filepath

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
                    "power": float(light_data_obj.energy),
                    "color": {
                        "r": float(light_data_obj.color[0]),
                        "g": float(light_data_obj.color[1]),
                        "b": float(light_data_obj.color[2])
                    }
                }

                # Add type-specific properties
                if light_data_obj.type == 'POINT':
                    light_info["radius"] = float(light_data_obj.shadow_soft_size)
                elif light_data_obj.type == 'AREA':
                    light_info["size"] = float(light_data_obj.size)
                    if light_data_obj.shape == 'RECTANGLE':
                        light_info["size_y"] = float(light_data_obj.size_y)

                lights_data.append(light_info)

        # Create export data
        export_data = {
            "camera": {
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
                "fov": float(camera.data.angle)
            },
            "lights": lights_data
        }

        # Write to JSON file
        try:
            with open(self.json_path, 'w') as f:
                json.dump(export_data, f, indent=2)
            self.report({'INFO'}, f"Camera data exported to {self.json_path}")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to write camera data: {str(e)}")

        # Save blend file in the work directory (using the same indexed filename)
        try:
            bpy.ops.wm.save_as_mainfile(filepath=self.blend_path, copy=True)
            self.report({'INFO'}, f"Blend file saved to {self.blend_path}")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to save blend file: {str(e)}")

        # Export downsampled PLY with embedded camera data if enabled
        settings = scene.camera_export_settings
        if settings.downsample_enabled:
            # Check if PLY timeline addon is available
            if hasattr(scene, 'ply_timeline_settings'):
                ply_settings = scene.ply_timeline_settings
                ply_directory = bpy.path.abspath(ply_settings.ply_directory)

                if ply_directory and os.path.isdir(ply_directory):
                    # Find PLY file for current frame
                    current_frame = scene.frame_current
                    original_ply_path = self._find_ply_for_frame(ply_directory, current_frame)

                    if original_ply_path:
                        # Generate output PLY filename (same base as render output)
                        ply_base_filename = os.path.splitext(os.path.basename(self.output_path))[0]
                        output_ply_path = os.path.join(os.path.dirname(self.output_path), f"{ply_base_filename}.ply")

                        # Create compact JSON for embedding
                        camera_data_json = json.dumps(export_data, separators=(',', ':'))

                        # Downsample and export
                        success, message = self.downsample_ply(
                            original_ply_path,
                            output_ply_path,
                            settings.downsample_ratio,
                            camera_data_json
                        )

                        if success:
                            self.report({'INFO'}, f"PLY export: {message}")
                        else:
                            self.report({'WARNING'}, f"PLY export failed: {message}")
                    else:
                        self.report({'WARNING'}, f"No PLY file found for frame {current_frame}")
                else:
                    self.report({'WARNING'}, "PLY directory not set or invalid")
            else:
                self.report({'WARNING'}, "PLY timeline addon not active - cannot export PLY")

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
            # theta: azimuthal angle (0 to 2π) - rotation around Z axis
            theta = random.uniform(0, 2 * math.pi)
            # phi: polar angle (0 to π) - angle from Z axis
            phi = random.uniform(0, math.pi)
            # distance: radial distance (from radius_near to radius_far)
            distance = random.uniform(radius_near, radius_far)

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

            look_at_point = target_pos + Vector((offset_x, offset_y, offset_z))
        else:
            look_at_point = target_pos

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

        # Move lights with camera if enabled
        if settings.move_lights_with_camera:
            # Get all lights with saved relationships
            lights = [obj for obj in scene.objects if obj.type == 'LIGHT']
            moved_lights = 0

            for light in lights:
                # Check if light has saved offset data
                if ("camera_offset_x" in light and
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


# ====== Registration ======
classes = (
    CameraExportSettings,
    CAMERA_OT_RenderAndExport,
    CAMERA_OT_SaveLightRelationship,
    CAMERA_OT_RandomPosition,
    CAMERA_PT_InfoPanel,
)

def register():
    """Called when add-on is enabled"""
    print("=" * 50)
    print("Registering Render & Export Add-on")
    print("=" * 50)

    for cls in classes:
        bpy.utils.register_class(cls)

    # Register settings
    bpy.types.Scene.camera_export_settings = bpy.props.PointerProperty(type=CameraExportSettings)

    print("Render & Export registered successfully")
    print("   Access via: View3D > Sidebar > Render & Export tab")

def unregister():
    """Called when add-on is disabled"""
    print("Unregistering Render & Export Add-on")

    # Unregister settings
    del bpy.types.Scene.camera_export_settings

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    print("Render & Export unregistered")

if __name__ == "__main__":
    register()
