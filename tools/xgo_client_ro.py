import importlib.machinery
import importlib.util
import os

ROOT = os.environ.get("ROBOT_ROOT", os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
SRC = os.path.join(ROOT, "scripts", "dev_xgo-client.py")

if not os.path.isfile(SRC):
    raise ImportError(f"dev_xgo-client.py not found at {SRC}")

loader = importlib.machinery.SourceFileLoader("dev_xgo_client_mod", SRC)
spec = importlib.util.spec_from_loader(loader.name, loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)

# Udostępnij tę samą klasę, której oczekuje splash:
XGOClientRO = mod.XGOClientRO
