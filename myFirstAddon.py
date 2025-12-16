import bpy

bl_info = {
    "name":"サンプルアドオン：星形メッシュの作成",
    "author":"horristic",
    "version": (1, 0, 0),
    "blender": (4,4, 0),
    "location":"３Dビューポート > サイドバー",
    "description":"平面の星形メッシュを作成するアドオン",
    "warning":"",
    "support":"COMMUNITY"   ,
    "doc_url":"",
    "tracker_url":"",
    "category":"Sample"
}

class SAMPLE_OT_CreateStarPolygon (bpy.types. Operator):
    bl_idname = "sample.create_star_polygon"
    bl_label = "星型メッシュを作成"
    bl_description = "星型メッシュを作成します"
    def execute (self, context) :
        print("オペレータを実行しました。")
        return {'FINISHED' }
    
classes = [
SAMPLE_OT_CreateStarPolygon,
]



def register ():
    for cls in classes:
        bpy.utils.register_class(cls)
    print(f"アドオン「{bl_info['name']}」が有効化されました。")

def unregister():
    for cls in classes:
        bpy.utils.unregister_class(cls)
    print(f"アドオン「{bl_info['name']}」が無効化されました。") 