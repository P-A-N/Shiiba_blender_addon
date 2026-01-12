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
import random
import re
from bpy.types import Panel, Operator, PropertyGroup
from bpy.props import StringProperty, BoolProperty, IntProperty, FloatProperty
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

    # JSON directory batch rendering
    json_directory: StringProperty(
        name="JSON Directory",
        description="Directory containing JSON files to batch render",
        default="",
        subtype='DIR_PATH'
    )

    # PLY downsample settings
    downsample_ratio: FloatProperty(
        name="Downsample Ratio",
        description="Ratio of points to keep (0.1 = 10%)",
        default=0.1,
        min=0.01,
        max=1.0
    )


# ====== Helper Functions ======
def downsample_ply(original_ply_path, output_ply_path, ratio):
    """Downsample original PLY file by randomly sampling vertices"""
    try:
        with open(original_ply_path, 'rb') as f:
            header_lines = []
            vertex_count = 0

            while True:
                line = f.readline().decode('ascii').strip()
                header_lines.append(line)

                if line.startswith('element vertex'):
                    vertex_count = int(line.split()[-1])

                if line == 'end_header':
                    header_end_pos = f.tell()
                    break

            if vertex_count == 0:
                return False, "No vertices found in PLY file"

            keep_count = max(1, int(vertex_count * ratio))

            if ratio >= 1.0 or keep_count >= vertex_count:
                f.seek(header_end_pos)
                vertex_data = f.read()
                write_ply(output_ply_path, header_lines, vertex_count, vertex_data)
                return True, f"PLY copied (100% of {vertex_count} points)"

            selected_indices = sorted(random.sample(range(vertex_count), keep_count))

            # Calculate bytes per vertex from file size
            f.seek(0, 2)  # Seek to end
            file_size = f.tell()
            vertex_data_size = file_size - header_end_pos
            bytes_per_vertex = vertex_data_size // vertex_count

            sampled_vertices = bytearray()
            for idx in selected_indices:
                f.seek(header_end_pos + idx * bytes_per_vertex)
                sampled_vertices.extend(f.read(bytes_per_vertex))

            write_ply(output_ply_path, header_lines, keep_count, bytes(sampled_vertices))
            return True, f"PLY downsampled: {vertex_count} -> {keep_count} points ({ratio*100:.1f}%)"

    except FileNotFoundError:
        return False, f"Original PLY not found: {original_ply_path}"
    except Exception as e:
        return False, f"Error downsampling PLY: {str(e)}"


def write_ply(output_path, header_lines, vertex_count, vertex_data):
    """Write PLY file with updated vertex count"""
    with open(output_path, 'wb') as f:
        for line in header_lines:
            if line.startswith('element vertex'):
                f.write(f'element vertex {vertex_count}\n'.encode('ascii'))
            elif line == 'end_header':
                f.write(b'end_header\n')
            else:
                f.write(f'{line}\n'.encode('ascii'))
        f.write(vertex_data)


def find_ply_for_frame(ply_directory, frame_number):
    """Find PLY file matching the given frame number"""
    try:
        ply_files = [f for f in os.listdir(ply_directory) if f.lower().endswith('.ply')]
        for filename in ply_files:
            numbers = re.findall(r'\d+', filename)
            if numbers:
                file_frame = int(numbers[-1])
                if file_frame == frame_number:
                    return os.path.join(ply_directory, filename)
        return None
    except Exception:
        return None


def get_json_files_from_directory(json_dir):
    """Get all JSON files directly in the specified directory.

    - Only scans files directly in json_dir (ignores subdirectories)
    - Returns list of absolute paths to JSON files
    """
    json_path = bpy.path.abspath(json_dir)
    if not os.path.isdir(json_path):
        return []

    json_files = []
    for item in os.listdir(json_path):
        item_path = os.path.join(json_path, item)
        # Only process files (not directories) that are JSON
        if os.path.isfile(item_path) and item.lower().endswith('.json'):
            json_files.append(item_path)

    return sorted(json_files)


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

        # JSON Directory Batch Render section
        layout.separator()
        json_dir_box = layout.box()
        json_dir_box.label(text="JSON Directory Batch:", icon='FILE_FOLDER')

        # JSON directory selector
        json_dir_box.prop(settings, "json_directory", text="JSON Dir")

        # Show JSON file count
        json_dir_files = get_json_files_from_directory(settings.json_directory)
        json_dir_box.label(text=f"Found {len(json_dir_files)} JSON file(s)", icon='FILE')

        # JSON directory batch render controls
        if settings.is_batch_rendering:
            json_dir_box.label(text="Batch render in progress...", icon='TIME')
        else:
            if len(json_dir_files) > 0:
                row = json_dir_box.row()
                row.scale_y = 1.5
                row.operator("json_render.batch_render_directory", text=f"Render JSON Dir ({len(json_dir_files)})", icon='RENDER_ANIMATION')
            else:
                json_dir_box.label(text="Set JSON directory to find files", icon='INFO')

        # Generate Downsampled PLY section
        layout.separator()
        ply_box = layout.box()
        ply_box.label(text="Generate Downsampled PLY:", icon='MESH_DATA')

        # Downsample ratio
        ply_box.prop(settings, "downsample_ratio", text="Ratio", slider=True)

        # Check if PLY Timeline addon is available
        if hasattr(scene, 'ply_timeline_settings'):
            ply_settings = scene.ply_timeline_settings
            ply_dir = bpy.path.abspath(ply_settings.ply_directory)

            if ply_dir and os.path.isdir(ply_dir):
                ply_box.label(text=f"Source: {os.path.basename(ply_dir.rstrip(os.sep))}", icon='FILE_FOLDER')

                json_dir = bpy.path.abspath(settings.json_directory)
                if json_dir and os.path.isdir(json_dir) and len(json_dir_files) > 0:
                    row = ply_box.row()
                    row.scale_y = 1.5
                    row.operator("json_render.generate_downsampled_ply", text=f"Generate PLYs ({len(json_dir_files)})", icon='EXPORT')
                else:
                    ply_box.label(text="Set JSON Directory above", icon='INFO')
            else:
                ply_box.label(text="Set PLY dir in PLY Timeline addon", icon='INFO')
        else:
            ply_box.label(text="PLY Timeline addon not active", icon='INFO')


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


class JSONRENDER_OT_BatchRenderDirectory(Operator):
    """Batch render all JSON files in the specified directory"""
    bl_idname = "json_render.batch_render_directory"
    bl_label = "Batch Render JSON Directory"
    bl_description = "Render images for all JSON files in the specified directory"

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
        print(f"[Batch Render Dir] Processing {self._current_index + 1}/{len(self._json_files)}: {os.path.basename(json_path)}")

        # Apply JSON data
        success, message = apply_json_to_scene(context, json_path)
        if not success:
            print(f"[Batch Render Dir] Error applying JSON: {message}")
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

        # Get JSON files from JSON directory
        self._json_files = get_json_files_from_directory(settings.json_directory)

        if not self._json_files:
            self.report({'ERROR'}, "No JSON files found in directory")
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

        self.report({'INFO'}, f"Starting batch render of {len(self._json_files)} JSON files from directory")
        return {'RUNNING_MODAL'}


class JSONRENDER_OT_GenerateDownsampledPLY(Operator):
    """Generate downsampled PLY files for all JSON files in JSON Directory"""
    bl_idname = "json_render.generate_downsampled_ply"
    bl_label = "Generate Downsampled PLYs"
    bl_description = "Create downsampled PLY files based on JSON files"

    def execute(self, context):
        scene = context.scene
        settings = scene.json_render_settings

        # Get PLY directory from PLY Timeline addon
        if not hasattr(scene, 'ply_timeline_settings'):
            self.report({'ERROR'}, "PLY Timeline addon not active")
            return {'CANCELLED'}

        ply_settings = scene.ply_timeline_settings
        ply_directory = bpy.path.abspath(ply_settings.ply_directory)

        if not ply_directory or not os.path.isdir(ply_directory):
            self.report({'ERROR'}, "PLY directory not set in PLY Timeline addon")
            return {'CANCELLED'}

        # Get JSON directory
        json_dir = bpy.path.abspath(settings.json_directory)
        if not json_dir or not os.path.isdir(json_dir):
            self.report({'ERROR'}, "JSON directory not set")
            return {'CANCELLED'}

        # Get all JSON files
        json_files = get_json_files_from_directory(settings.json_directory)
        if not json_files:
            self.report({'ERROR'}, "No JSON files found")
            return {'CANCELLED'}

        ratio = settings.downsample_ratio
        success_count = 0
        fail_count = 0

        for json_path in json_files:
            # Read JSON to get frame number
            try:
                with open(json_path, 'r') as f:
                    data = json.load(f)
                frame_number = data.get("frame")
                if frame_number is None:
                    print(f"[PLY Gen] No frame in JSON: {os.path.basename(json_path)}")
                    fail_count += 1
                    continue
            except Exception as e:
                print(f"[PLY Gen] Error reading JSON: {e}")
                fail_count += 1
                continue

            # Find PLY file for this frame
            original_ply_path = find_ply_for_frame(ply_directory, frame_number)
            if not original_ply_path:
                print(f"[PLY Gen] No PLY for frame {frame_number}")
                fail_count += 1
                continue

            # Output path - same directory as JSON, same base name as JSON
            json_base_name = os.path.splitext(os.path.basename(json_path))[0]
            output_ply_path = os.path.join(json_dir, f"{json_base_name}.ply")

            # Perform downsampling
            success, message = downsample_ply(original_ply_path, output_ply_path, ratio)

            if success:
                print(f"[PLY Gen] {message}")
                success_count += 1
            else:
                print(f"[PLY Gen] Failed: {message}")
                fail_count += 1

        if success_count > 0:
            self.report({'INFO'}, f"Generated {success_count} PLY file(s), {fail_count} failed")
            return {'FINISHED'}
        else:
            self.report({'ERROR'}, f"All {fail_count} PLY generation(s) failed")
            return {'CANCELLED'}


# ====== Registration ======
classes = (
    JSONRenderSettings,
    JSONRENDER_OT_SelectJSON,
    JSONRENDER_OT_ApplyJSON,
    JSONRENDER_OT_Render,
    JSONRENDER_OT_GenerateDownsampledPLY,
    JSONRENDER_OT_BatchRender,
    JSONRENDER_OT_StopBatch,
    JSONRENDER_OT_BatchRenderDirectory,
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
