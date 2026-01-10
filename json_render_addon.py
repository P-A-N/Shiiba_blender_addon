bl_info = {
    "name": "JSON Camera Render",
    "author": "horristic",
    "version": (1, 0, 0),
    "blender": (4, 4, 0),
    "location": "View3D > Sidebar > JSON Render",
    "description": "Render images by reading camera/light data from JSON files",
    "category": "3D View",
}

import bpy
import json
import os
from bpy.types import Panel, Operator, PropertyGroup
from bpy.props import StringProperty, BoolProperty, IntProperty
from mathutils import Vector, Quaternion


# ====== Property Group ======
class JSONRenderSettings(PropertyGroup):
    json_file: StringProperty(
        name="JSON File",
        description="JSON file containing camera/light data",
        default="",
        subtype='FILE_PATH'
    )

    output_directory: StringProperty(
        name="Output Directory",
        description="Directory where rendered images will be saved",
        default="//rendered/",
        subtype='DIR_PATH'
    )

    # Batch rendering properties
    image_directory: StringProperty(
        name="Image Directory",
        description="Directory containing rendered images (to find matching JSON files)",
        default="",
        subtype='DIR_PATH'
    )

    is_batch_rendering: BoolProperty(
        name="Batch Rendering Active",
        description="Internal flag to track if batch render is active",
        default=False
    )

    batch_render_count: IntProperty(
        name="Batch Render Count",
        description="Number of renders completed in current batch",
        default=0,
        min=0
    )

    batch_render_total: IntProperty(
        name="Batch Render Total",
        description="Total number of JSON files to render",
        default=0,
        min=0
    )


# ====== Helper Functions ======
def get_json_files_from_images(image_dir):
    """Get JSON files by scanning PNG files in image directory.

    - Only scans files directly in image_dir (ignores subdirectories)
    - Converts XXXXX.png to XXXXX.json
    - JSON files are in the parent directory of image_dir
    """
    image_path = bpy.path.abspath(image_dir)
    if not os.path.isdir(image_path):
        return []

    # Get parent directory where JSON files are located
    parent_dir = os.path.dirname(image_path.rstrip(os.sep))

    json_files = []
    for item in os.listdir(image_path):
        item_path = os.path.join(image_path, item)
        # Only process files (not directories) that are PNG
        if os.path.isfile(item_path) and item.lower().endswith('.png'):
            # Convert image name to JSON name
            base_name = os.path.splitext(item)[0]
            json_filename = f"{base_name}.json"
            json_path = os.path.join(parent_dir, json_filename)

            # Only add if JSON file exists
            if os.path.exists(json_path):
                json_files.append(json_path)

    return sorted(json_files)


def apply_json_to_scene(context, json_path):
    """Apply camera and light data from JSON file to the current scene"""
    try:
        with open(json_path, 'r') as f:
            data = json.load(f)
    except Exception as e:
        return False, f"Error reading JSON: {str(e)}"

    scene = context.scene
    camera = scene.camera

    if camera is None:
        return False, "No active camera in scene"

    # Set frame from JSON
    if "frame" in data:
        scene.frame_set(data["frame"])

    # Apply camera position
    if "position" in data:
        pos = data["position"]
        camera.location = Vector((pos["x"], pos["y"], pos["z"]))

    # Apply camera rotation (quaternion)
    if "rotation" in data:
        rot = data["rotation"]
        camera.rotation_mode = 'QUATERNION'
        camera.rotation_quaternion = Quaternion((rot["w"], rot["x"], rot["y"], rot["z"]))

    # Apply camera FOV
    if "fov" in data:
        camera.data.angle = data["fov"]

    # Update existing lights
    if "lights" in data:
        for light_data in data["lights"]:
            light_name = light_data.get("name", "")
            if not light_name:
                continue

            # Find existing light by name
            light_obj = scene.objects.get(light_name)
            if light_obj is None or light_obj.type != 'LIGHT':
                print(f"[JSON Render] Light not found: {light_name}")
                continue

            # Apply light position
            if "position" in light_data:
                pos = light_data["position"]
                light_obj.location = Vector((pos["x"], pos["y"], pos["z"]))

            # Apply light rotation (quaternion)
            if "rotation" in light_data:
                rot = light_data["rotation"]
                light_obj.rotation_mode = 'QUATERNION'
                light_obj.rotation_quaternion = Quaternion((rot["w"], rot["x"], rot["y"], rot["z"]))

            # Apply light energy
            if "energy" in light_data:
                light_obj.data.energy = light_data["energy"]

            # Apply light color
            if "color" in light_data:
                light_obj.data.color = light_data["color"]

            # Apply spot-specific properties
            if light_obj.data.type == 'SPOT':
                if "spot_size" in light_data:
                    light_obj.data.spot_size = light_data["spot_size"]
                if "spot_blend" in light_data:
                    light_obj.data.spot_blend = light_data["spot_blend"]

    return True, "JSON applied successfully"


# ====== UI Panel ======
class JSONRENDER_PT_MainPanel(Panel):
    """Panel for JSON Camera Render addon"""
    bl_label = "JSON Camera Render"
    bl_idname = "JSONRENDER_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'JSON Render'

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        settings = scene.json_render_settings

        # Check for active camera
        if scene.camera is None:
            box = layout.box()
            box.label(text="No active camera", icon='ERROR')
            return

        # JSON file selector
        box = layout.box()
        box.label(text="Input:", icon='FILE')
        box.prop(settings, "json_file", text="")

        # Show selected file name
        if settings.json_file:
            filename = os.path.basename(bpy.path.abspath(settings.json_file))
            box.label(text=f"Selected: {filename}")

        # Output directory
        layout.separator()
        out_box = layout.box()
        out_box.label(text="Output:", icon='FILEBROWSER')
        out_box.prop(settings, "output_directory", text="")

        # Action buttons
        layout.separator()
        action_box = layout.box()
        action_box.label(text="Actions:", icon='PLAY')

        # Apply button
        row = action_box.row()
        row.scale_y = 1.3
        row.operator("json_render.apply_json", text="Apply", icon='IMPORT')

        # Render button
        row = action_box.row()
        row.scale_y = 1.5
        row.operator("json_render.render", text="Render", icon='RENDER_STILL')

        # Batch Render section
        layout.separator()
        batch_box = layout.box()
        batch_box.label(text="Batch Render:", icon='RENDER_ANIMATION')

        # Image directory selector
        batch_box.prop(settings, "image_directory", text="Image Dir")

        # Show JSON file count
        json_files = get_json_files_from_images(settings.image_directory)
        batch_box.label(text=f"Found {len(json_files)} JSON file(s)", icon='FILE')

        # Batch render controls
        if settings.is_batch_rendering:
            # Show progress
            batch_box.label(text=f"Progress: {settings.batch_render_count}/{settings.batch_render_total}")

            row = batch_box.row()
            row.scale_y = 1.5
            row.alert = True
            row.operator("json_render.stop_batch", text="STOP Batch Render", icon='CANCEL')
        else:
            if len(json_files) > 0:
                row = batch_box.row()
                row.scale_y = 1.5
                row.operator("json_render.batch_render", text=f"Start Batch Render ({len(json_files)})", icon='RENDER_ANIMATION')
            else:
                batch_box.label(text="Set image directory to find JSON files", icon='INFO')

            # Show last batch count
            if settings.batch_render_count > 0:
                batch_box.label(text=f"Last batch: {settings.batch_render_count} renders", icon='INFO')


# ====== Operators ======
class JSONRENDER_OT_SelectJSON(Operator):
    """Select a JSON file to apply"""
    bl_idname = "json_render.select_json"
    bl_label = "Select JSON File"
    bl_description = "Select a JSON file containing camera/light data"

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.json", options={'HIDDEN'})

    def execute(self, context):
        settings = context.scene.json_render_settings
        settings.json_file = self.filepath
        self.report({'INFO'}, f"Selected: {os.path.basename(self.filepath)}")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class JSONRENDER_OT_ApplyJSON(Operator):
    """Apply camera and light data from JSON file to scene"""
    bl_idname = "json_render.apply_json"
    bl_label = "Apply JSON"
    bl_description = "Apply frame, camera position/rotation/FOV, and light positions from JSON"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = context.scene.json_render_settings

        if not settings.json_file:
            self.report({'ERROR'}, "No JSON file selected")
            return {'CANCELLED'}

        json_path = bpy.path.abspath(settings.json_file)
        if not os.path.exists(json_path):
            self.report({'ERROR'}, f"File not found: {json_path}")
            return {'CANCELLED'}

        success, message = apply_json_to_scene(context, json_path)

        if success:
            self.report({'INFO'}, message)
            return {'FINISHED'}
        else:
            self.report({'ERROR'}, message)
            return {'CANCELLED'}


class JSONRENDER_OT_Render(Operator):
    """Render the current scene to output directory"""
    bl_idname = "json_render.render"
    bl_label = "Render"
    bl_description = "Render the current scene and save to output directory"

    def execute(self, context):
        settings = context.scene.json_render_settings
        scene = context.scene

        if scene.camera is None:
            self.report({'ERROR'}, "No active camera in scene")
            return {'CANCELLED'}

        # Prepare output path
        output_dir = bpy.path.abspath(settings.output_directory)
        os.makedirs(output_dir, exist_ok=True)

        # Generate output filename from JSON filename or use default
        if settings.json_file:
            json_filename = os.path.basename(bpy.path.abspath(settings.json_file))
            base_name = os.path.splitext(json_filename)[0]
        else:
            base_name = f"render_{scene.frame_current:05d}"

        output_path = os.path.join(output_dir, f"{base_name}.png")

        # Check if file exists and find next available index
        if os.path.exists(output_path):
            index = 1
            while os.path.exists(os.path.join(output_dir, f"{base_name}_{index}.png")):
                index += 1
            output_path = os.path.join(output_dir, f"{base_name}_{index}.png")

        # Set render output path
        scene.render.filepath = output_path

        # Render with INVOKE_DEFAULT to show progress window
        bpy.ops.render.render('INVOKE_DEFAULT', write_still=True)

        self.report({'INFO'}, f"Rendering to: {output_path}")
        return {'FINISHED'}


class JSONRENDER_OT_BatchRender(Operator):
    """Batch render all JSON files found from image directory"""
    bl_idname = "json_render.batch_render"
    bl_label = "Batch Render"
    bl_description = "Render images for all JSON files found from image directory"

    _timer = None
    _json_files = []
    _current_index = 0
    _waiting_for_render = False

    def modal(self, context, event):
        settings = context.scene.json_render_settings

        # Check for stop
        if not settings.is_batch_rendering:
            self.report({'INFO'}, f"Batch render stopped - completed {settings.batch_render_count} renders")
            return self.finish(context)

        if event.type == 'ESC':
            self.report({'INFO'}, f"Batch render cancelled - completed {settings.batch_render_count} renders")
            settings.is_batch_rendering = False
            return self.finish(context)

        if event.type == 'TIMER':
            # If waiting for render, check if complete
            if self._waiting_for_render:
                return {'PASS_THROUGH'}

            # Check if we have more files to process
            if self._current_index >= len(self._json_files):
                self.report({'INFO'}, f"Batch render complete - {settings.batch_render_count} renders")
                settings.is_batch_rendering = False
                return self.finish(context)

            # Process next file
            self.render_next(context)

        return {'PASS_THROUGH'}

    def render_next(self, context):
        """Apply JSON and start render for current file"""
        settings = context.scene.json_render_settings
        scene = context.scene

        json_path = self._json_files[self._current_index]
        print(f"[Batch Render] Processing {self._current_index + 1}/{len(self._json_files)}: {os.path.basename(json_path)}")

        # Apply JSON data
        success, message = apply_json_to_scene(context, json_path)
        if not success:
            print(f"[Batch Render] Error applying JSON: {message}")
            self._current_index += 1
            return

        # Prepare output path
        output_dir = bpy.path.abspath(settings.output_directory)
        os.makedirs(output_dir, exist_ok=True)

        base_name = os.path.splitext(os.path.basename(json_path))[0]
        output_path = os.path.join(output_dir, f"{base_name}.png")

        # Set render output path
        scene.render.filepath = output_path

        # Mark as waiting and register completion handler
        self._waiting_for_render = True
        bpy.app.handlers.render_complete.append(self.render_complete_handler)
        bpy.app.handlers.render_cancel.append(self.render_cancel_handler)

        # Start render
        bpy.ops.render.render('INVOKE_DEFAULT', write_still=True)

    def render_complete_handler(self, scene, depsgraph=None):
        """Called when render completes"""
        # Remove handlers
        if self.render_complete_handler in bpy.app.handlers.render_complete:
            bpy.app.handlers.render_complete.remove(self.render_complete_handler)
        if self.render_cancel_handler in bpy.app.handlers.render_cancel:
            bpy.app.handlers.render_cancel.remove(self.render_cancel_handler)

        # Schedule next render
        def deferred_next():
            settings = bpy.context.scene.json_render_settings
            self._current_index += 1
            settings.batch_render_count = self._current_index
            self._waiting_for_render = False
            return None

        bpy.app.timers.register(deferred_next, first_interval=0.5)

    def render_cancel_handler(self, scene, depsgraph=None):
        """Called when render is cancelled"""
        # Remove handlers
        if self.render_complete_handler in bpy.app.handlers.render_complete:
            bpy.app.handlers.render_complete.remove(self.render_complete_handler)
        if self.render_cancel_handler in bpy.app.handlers.render_cancel:
            bpy.app.handlers.render_cancel.remove(self.render_cancel_handler)

        # Stop batch
        def deferred_stop():
            settings = bpy.context.scene.json_render_settings
            settings.is_batch_rendering = False
            self._waiting_for_render = False
            return None

        bpy.app.timers.register(deferred_stop, first_interval=0.1)

    def finish(self, context):
        """Clean up and finish"""
        settings = context.scene.json_render_settings
        settings.is_batch_rendering = False

        # Remove handlers if still registered
        try:
            if self.render_complete_handler in bpy.app.handlers.render_complete:
                bpy.app.handlers.render_complete.remove(self.render_complete_handler)
            if self.render_cancel_handler in bpy.app.handlers.render_cancel:
                bpy.app.handlers.render_cancel.remove(self.render_cancel_handler)
        except:
            pass

        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None

        # Force UI update
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()

        return {'FINISHED'}

    def execute(self, context):
        settings = context.scene.json_render_settings

        if context.scene.camera is None:
            self.report({'ERROR'}, "No active camera in scene")
            return {'CANCELLED'}

        # Get JSON files from image directory
        self._json_files = get_json_files_from_images(settings.image_directory)

        if not self._json_files:
            self.report({'ERROR'}, "No JSON files found from image directory")
            return {'CANCELLED'}

        # Initialize state
        self._current_index = 0
        self._waiting_for_render = False
        settings.is_batch_rendering = True
        settings.batch_render_count = 0
        settings.batch_render_total = len(self._json_files)

        # Set up timer
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.5, window=context.window)
        wm.modal_handler_add(self)

        self.report({'INFO'}, f"Starting batch render of {len(self._json_files)} files")
        return {'RUNNING_MODAL'}


class JSONRENDER_OT_StopBatch(Operator):
    """Stop the batch rendering process"""
    bl_idname = "json_render.stop_batch"
    bl_label = "Stop Batch Render"
    bl_description = "Stop the active batch rendering"

    def execute(self, context):
        settings = context.scene.json_render_settings
        settings.is_batch_rendering = False
        self.report({'INFO'}, "Batch render stop requested")
        return {'FINISHED'}


# ====== Registration ======
classes = (
    JSONRenderSettings,
    JSONRENDER_OT_SelectJSON,
    JSONRENDER_OT_ApplyJSON,
    JSONRENDER_OT_Render,
    JSONRENDER_OT_BatchRender,
    JSONRENDER_OT_StopBatch,
    JSONRENDER_PT_MainPanel,
)


def register():
    print("=" * 50)
    print("Registering JSON Camera Render Add-on")
    print("=" * 50)

    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.json_render_settings = bpy.props.PointerProperty(type=JSONRenderSettings)

    print("JSON Camera Render registered successfully")
    print("   Access via: View3D > Sidebar > JSON Render tab")


def unregister():
    print("Unregistering JSON Camera Render Add-on")

    del bpy.types.Scene.json_render_settings

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    print("JSON Camera Render unregistered")


if __name__ == "__main__":
    register()
