"""Offline test of ue_preview.py: runs the generated Unreal scripts against a fake `unreal` module and a stub editor server."""
import sys, os, json, threading, types, runpy, py_compile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tempfile
import ue_preview as UP
from http.server import BaseHTTPRequestHandler, HTTPServer
rows=[dict(tag=t,loc=[83.0,i,96.6],rot=[-28.9,-178.0,-4.0],scale=[0.21,0.22,0.21],priority=0) for i,t in enumerate(["SidePlateRight","FrontPlate","SidePlateLeft"])]
got=[]
class H(BaseHTTPRequestHandler):
    def do_POST(s):
        got.append((s.headers["X-MGP-Token"], json.loads(s.rfile.read(int(s.headers["Content-Length"])))))
        s.send_response(200); s.end_headers(); s.wfile.write(b"{}")
    def log_message(*a): pass
srv=HTTPServer(("127.0.0.1",0),H); threading.Thread(target=srv.serve_forever,daemon=True).start()
out=tempfile.mkdtemp()
paths=UP.write_scripts(out,"http://127.0.0.1:%d"%srv.server_port,"tok123","/Game/x/projector108_002",rows)
for p in paths: py_compile.compile(p, doraise=True)
# fake unreal
u=types.ModuleType("unreal"); actors=[]
class V:
    def __init__(s,*a,**k): s.x,s.y,s.z=(list(a)+[0,0,0])[:3]
class R:
    def __init__(s,roll=0,pitch=0,yaw=0): s.roll,s.pitch,s.yaw=roll,pitch,yaw
class Comp:
    def __init__(s): s.p={}
    def set_editor_property(s,k,v): s.p[k]=v
    def get_editor_property(s,k): return s.p[k]
    def does_socket_exist(s,n): return True
    def set_skeletal_mesh(s,m): s.mesh=m
    def set_decal_material(s,m): s.mat=m
class Actor:
    def __init__(s): s.tags=[]; s.root_component=Comp(); s.decal=s.root_component; s.skeletal_mesh_component=Comp(); actors.append(s)
    def set_actor_label(s,l): s.label=l
    def get_actor_label(s): return s.label
    def set_folder_path(s,p): pass
    def attach_to_actor(s,*a): s.att=a
    def destroy_actor(s): actors.remove(s)
class SkeletalMesh: pass
class Any:
    def __getattr__(s,n): return Any()
    def __call__(s,*a,**k): return Any()
u.Vector=V; u.Rotator=R; u.SkeletalMesh=SkeletalMesh; u.SkeletalMeshActor=Actor; u.DecalActor=Actor
u.log_warning=print
u.get_editor_subsystem=lambda c:types.SimpleNamespace(get_all_level_actors=lambda:list(actors),spawn_actor_from_class=lambda cls,*a:cls())
u.EditorActorSubsystem=None
u.EditorUtilityLibrary=types.SimpleNamespace(get_selected_assets=lambda:[SkeletalMesh()])
for n in ["AttachmentRule","AssetToolsHelpers","MaterialEditingLibrary","MaterialDomain","DecalBlendMode","MaterialExpressionTextureSampleParameter2D","MaterialProperty","Material","MaterialFactoryNew","MaterialInstanceConstant","MaterialInstanceConstantFactoryNew","AssetImportTask"]: setattr(u,n,Any())
u.load_asset=lambda p: None if "MGP" in p else "tex"
sys.modules["unreal"]=u
runpy.run_path(paths[0])
runpy.run_path(paths[0])   # second load must replace, not duplicate
assert [x.label for x in actors]==["MGP_Bike","MGP_SidePlateRight","MGP_FrontPlate","MGP_SidePlateLeft"], actors
dec=[x for x in actors if "MGP_PROJ" in x.tags][0]; dec.root_component.p["relative_location"]=V(1,2,3)
runpy.run_path(paths[1])
assert len(got)==3 and got[0][0]=="tok123" and got[0][1]["loc"]==[1,2,3] and got[1][1]["rot"]==[-28.9,-178.0,-4.0], got
# kept calibration
txt=open(paths[0]).read().replace("DECAL_SIZE = (128.0, 256.0, 256.0)","DECAL_SIZE = (10.0, 40.0, 40.0)").replace('NUMBER_PNG = r""','NUMBER_PNG = r"C:\\nums\\46.png"')
open(paths[0],"w").write(txt)
UP.write_scripts(out,"http://x","t","/Game/x/p",rows)
kept=[l.split("   #")[0] for l in open(paths[0]) if l.startswith(("DECAL_SIZE","NUMBER_PNG"))]
assert kept==['DECAL_SIZE = (10.0, 40.0, 40.0)','NUMBER_PNG = r"C:\\nums\\46.png"'], kept
print("ue_preview ok")
