import importlib, importlib.util, inspect, types, sys, pathlib, dataclasses, os
ROOT=pathlib.Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT/"_apps"), str(ROOT/"apps")):
    if p not in sys.path: sys.path.insert(0, p)

# Załaduj _apps/ui/face_renderers.py pod kanoniczną nazwą
if 'apps' not in sys.modules:
    m=types.ModuleType('apps'); m.__path__=[str(ROOT/'apps')]; sys.modules['apps']=m
if 'apps.ui' not in sys.modules:
    m=types.ModuleType('apps.ui'); m.__path__=[str(ROOT/'apps/ui'), str(ROOT/'_apps/ui')]; sys.modules['apps.ui']=m
spec=importlib.util.spec_from_file_location('apps.ui.face_renderers', str(ROOT/'_apps/ui/face_renderers.py'))
m=importlib.util.module_from_spec(spec); sys.modules['apps.ui.face_renderers']=m; spec.loader.exec_module(m)

print("FILE:", m.__file__)
FC=getattr(m,'FaceConfig',None)
cfg=FC() if (FC and dataclasses.is_dataclass(FC)) else None
if cfg:
    for k,v in dict(lcd_do_init=True, lcd_rotate=270).items():
        if hasattr(cfg,k): setattr(cfg,k,v)

LR=getattr(m,'LCDRenderer',None)
inst=LR(cfg) if (LR and cfg is not None) else (LR() if LR else None)
print("LCDRenderer:", type(inst).__name__)

def pub(obj):
    out=[]
    for n in dir(obj):
        if n.startswith("_"): continue
        fn=getattr(obj,n)
        if callable(fn):
            try: sig=str(inspect.signature(fn))
            except Exception: sig="(?)"
            out.append((n,sig))
    return sorted(out)

def dump(prefix, obj):
    if obj is None: 
        return
    print(f"\n[{prefix}] methods:")
    for n,s in pub(obj):
        print(f" - {n}{s}")

dump("inst", inst)
for name in ("renderer","lcd","device","driver","screen","panel","disp","display"):
    dump(name, getattr(inst,name,None))
