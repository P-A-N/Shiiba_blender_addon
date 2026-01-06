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
from bpy.types import Panel, Operator, PropertyGroup
from bpy.props import StringProperty
from mathutils import Matrix


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

        self.report({'INFO'}, f"Render complete: {self.output_path}")


# ====== Registration ======
classes = (
    CameraExportSettings,
    CAMERA_OT_RenderAndExport,
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
