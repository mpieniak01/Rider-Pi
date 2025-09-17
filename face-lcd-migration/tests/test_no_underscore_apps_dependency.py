import os
import pytest

def test_no_underscore_apps_dependency():
    # List of files to check for _apps imports
    files_to_check = [
        'apps/ui/face/driver/__init__.py',
        'apps/ui/face/panel_cfg.py',
        'apps/ui/face/face_io.py',
        'services/api_core/face_api.py',
        'tools/newface_lcd_direct.py',
        'tools/face_cli.py'
    ]
    
    for file_path in files_to_check:
        with open(file_path, 'r') as file:
            content = file.read()
            assert '_apps' not in content, f"Found '_apps' import in {file_path}"