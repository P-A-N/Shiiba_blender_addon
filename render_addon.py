bl_info = {
    "name": "Rendering and export camera info",
    "author": "horristic",
    "version": (1, 0, 0),
    "blender": (4, 4, 0),
    "location": "View3D > Sidebar > Camera Info",
    "description": "Display current camera position, rotation, and FOV",
    "category": "3D View",
}

import bpy
import math
import json
import os
from bpy.types import Panel, Operator, PropertyGroup
from bpy.props import StringProperty
from mathutils import Matrix


# ====== Property Group ======
class CameraExportSettings(PropertyGroup):
    output_prefix: StringProperty(
        name="File Prefix",
        description="Prefix for output files (e.g., 'render_' will create render_0001.png)",
        default="render_"
    )

    output_directory: StringProperty(
        name="Output Directory",
        description="Directory to save rendered images and camera data",
        default="//",
        subtype='DIR_PATH'
    )


# ====== UI Panel ======
class CAMERA_PT_InfoPanel(Panel):
    """Creates a Panel in the 3D Viewport sidebar showing camera information"""
    bl_label = "Camera Info"
    bl_idname = "CAMERA_PT_info_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Camera Info'

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
        settings_box.prop(settings, "output_directory")
        settings_box.prop(settings, "output_prefix")

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

        # Get output directory and prefix
        output_dir = bpy.path.abspath(settings.output_directory)
        prefix = settings.output_prefix
        frame_number = scene.frame_current

        # Create filename: prefix + frame number (4 digits) + .png
        filename = f"{prefix}{frame_number:04d}.png"
        output_path = os.path.join(output_dir, filename)

        # Create directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)

        # Set the render output path
        original_filepath = scene.render.filepath
        scene.render.filepath = output_path

        # Render the image with UI
        bpy.ops.render.render('INVOKE_DEFAULT', write_still=True)

        # Restore original filepath
        scene.render.filepath = original_filepath

        # Create JSON filename
        json_filename = f"{prefix}{frame_number:04d}.json"
        json_path = os.path.join(output_dir, json_filename)

        # Export camera data
        cam_data = camera.data

        # Get camera position (Blender coordinates)
        pos_blender = camera.location

        # Convert position from Blender (Z-up) to Three.js (Y-up)
        # Blender: (X, Y, Z) -> Three.js: (X, Z, -Y)
        pos_threejs = {
            "x": float(pos_blender.x),
            "y": float(pos_blender.z),
            "z": float(-pos_blender.y)
        }

        # Get camera rotation as quaternion
        if camera.rotation_mode == 'QUATERNION':
            quat_blender = camera.rotation_quaternion.copy()
        elif camera.rotation_mode == 'AXIS_ANGLE':
            quat_blender = camera.rotation_axis_angle.to_quaternion()
        else:
            quat_blender = camera.rotation_euler.to_quaternion()

        # Convert quaternion from Blender to Three.js coordinate system
        # Create rotation matrix for coordinate system conversion
        # Blender (X, Y, Z) -> Three.js (X, Z, -Y)
        conv_matrix = Matrix((
            (1,  0,  0),
            (0,  0, -1),
            (0,  1,  0)
        ))

        # Convert quaternion
        quat_matrix = quat_blender.to_matrix()
        converted_matrix = conv_matrix @ quat_matrix @ conv_matrix.transposed()
        quat_threejs = converted_matrix.to_quaternion()

        rot_threejs = {
            "x": float(quat_threejs.x),
            "y": float(quat_threejs.y),
            "z": float(quat_threejs.z),
            "w": float(quat_threejs.w)
        }

        # Calculate vertical FOV for Three.js
        aspect_ratio = scene.render.resolution_x / scene.render.resolution_y

        if cam_data.lens_unit == 'MILLIMETERS':
            # Determine which FOV we're calculating from sensor fit
            if cam_data.sensor_fit == 'VERTICAL':
                # Already vertical FOV
                sensor_size = cam_data.sensor_height
                fov_rad = 2 * math.atan(sensor_size / (2 * cam_data.lens))
                fov_vertical = math.degrees(fov_rad)
            elif cam_data.sensor_fit == 'HORIZONTAL':
                # Horizontal FOV, need to convert to vertical
                sensor_size = cam_data.sensor_width
                fov_h_rad = 2 * math.atan(sensor_size / (2 * cam_data.lens))
                # Convert horizontal FOV to vertical FOV
                fov_v_rad = 2 * math.atan(math.tan(fov_h_rad / 2) / aspect_ratio)
                fov_vertical = math.degrees(fov_v_rad)
            else:  # AUTO
                # Depends on aspect ratio
                if aspect_ratio > (cam_data.sensor_width / cam_data.sensor_height):
                    # Use horizontal sensor, convert to vertical
                    sensor_size = cam_data.sensor_width
                    fov_h_rad = 2 * math.atan(sensor_size / (2 * cam_data.lens))
                    fov_v_rad = 2 * math.atan(math.tan(fov_h_rad / 2) / aspect_ratio)
                    fov_vertical = math.degrees(fov_v_rad)
                else:
                    # Use vertical sensor
                    sensor_size = cam_data.sensor_height
                    fov_rad = 2 * math.atan(sensor_size / (2 * cam_data.lens))
                    fov_vertical = math.degrees(fov_rad)
        else:
            # FOV mode - camera.angle could be horizontal or vertical
            fov_rad = cam_data.angle
            if cam_data.sensor_fit == 'HORIZONTAL':
                # Convert to vertical
                fov_v_rad = 2 * math.atan(math.tan(fov_rad / 2) / aspect_ratio)
                fov_vertical = math.degrees(fov_v_rad)
            else:
                # Already vertical or auto (use vertical)
                fov_vertical = math.degrees(fov_rad)

        # Export lights data
        lights_data = []
        for obj in scene.objects:
            if obj.type == 'LIGHT':
                light_data_obj = obj.data

                # Get light position
                light_pos_blender = obj.location
                light_pos_threejs = {
                    "x": float(light_pos_blender.x),
                    "y": float(light_pos_blender.z),
                    "z": float(-light_pos_blender.y)
                }

                # Get light rotation as quaternion
                if obj.rotation_mode == 'QUATERNION':
                    light_quat_blender = obj.rotation_quaternion.copy()
                elif obj.rotation_mode == 'AXIS_ANGLE':
                    light_quat_blender = obj.rotation_axis_angle.to_quaternion()
                else:
                    light_quat_blender = obj.rotation_euler.to_quaternion()

                # Convert quaternion to Three.js coordinate system
                light_quat_matrix = light_quat_blender.to_matrix()
                light_converted_matrix = conv_matrix @ light_quat_matrix @ conv_matrix.transposed()
                light_quat_threejs = light_converted_matrix.to_quaternion()

                light_rot_threejs = {
                    "x": float(light_quat_threejs.x),
                    "y": float(light_quat_threejs.y),
                    "z": float(light_quat_threejs.z),
                    "w": float(light_quat_threejs.w)
                }

                # Get light properties
                light_info = {
                    "name": obj.name,
                    "type": light_data_obj.type,  # POINT, SUN, SPOT, AREA
                    "position": light_pos_threejs,
                    "rotation": light_rot_threejs,
                    "power": float(light_data_obj.energy),
                    "color": {
                        "r": float(light_data_obj.color[0]),
                        "g": float(light_data_obj.color[1]),
                        "b": float(light_data_obj.color[2])
                    }
                }

                # Add type-specific properties
                if light_data_obj.type == 'SPOT':
                    light_info["spot_size"] = float(light_data_obj.spot_size)
                    light_info["spot_blend"] = float(light_data_obj.spot_blend)
                elif light_data_obj.type == 'AREA':
                    light_info["size"] = float(light_data_obj.size)
                    if light_data_obj.shape == 'RECTANGLE':
                        light_info["size_y"] = float(light_data_obj.size_y)

                lights_data.append(light_info)

        # Create export data
        export_data = {
            "camera": {
                "position": pos_threejs,
                "rotation": rot_threejs,
                "fov": float(fov_vertical)
            },
            "lights": lights_data
        }

        # Write to JSON file
        try:
            with open(json_path, 'w') as f:
                json.dump(export_data, f, indent=2)
            self.report({'INFO'}, f"Camera data exported to {json_path}")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to write camera data: {str(e)}")
            return {'FINISHED'}  # Still return FINISHED since render was triggered


# ====== Registration ======
classes = (
    CameraExportSettings,
    CAMERA_OT_RenderAndExport,
    CAMERA_PT_InfoPanel,
)

def register():
    """Called when add-on is enabled"""
    print("=" * 50)
    print("Registering Camera Info Display Add-on")
    print("=" * 50)

    for cls in classes:
        bpy.utils.register_class(cls)

    # Register settings
    bpy.types.Scene.camera_export_settings = bpy.props.PointerProperty(type=CameraExportSettings)

    print("Camera Info Display registered successfully")
    print("   Access via: View3D > Sidebar > Camera Info tab")

def unregister():
    """Called when add-on is disabled"""
    print("Unregistering Camera Info Display Add-on")

    # Unregister settings
    del bpy.types.Scene.camera_export_settings

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    print("Camera Info Display unregistered")

if __name__ == "__main__":
    register()
