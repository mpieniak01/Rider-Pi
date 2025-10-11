import importlib.util, sys, ast, os
path = sys.argv[1]
spec = importlib.util.spec_from_file_location(os.path.basename(path).replace('.py',''), path)
if spec is None or spec.loader is None:
    sys.exit(1)
with open(path, 'rb') as f:
    ast.parse(f.read(), filename=path)
sys.exit(0)
