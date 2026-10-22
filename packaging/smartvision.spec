# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

root = Path(SPECPATH).parent
stage = Path(os.environ['SMARTVISION_BUILD_STAGE'])
datas = [
    (str(root / 'frontend' / 'dist'), 'frontend/dist'),
    (str(root / 'models' / 'yolo26n.pt'), 'models'),
    (str(root / 'backend' / 'database' / 'schema.sql'), 'backend/database'),
    (str(root / 'backend' / 'database' / 'migration_v2.sql'), 'backend/database'),
    (str(stage / 'licenses'), 'licenses'),
]
datas += collect_data_files('ultralytics', includes=['cfg/**/*.yaml'])
for name in ('ultralytics', 'torch', 'torchvision', 'numpy', 'opencv-python', 'fastapi', 'uvicorn'):
    datas += copy_metadata(name)
hidden = collect_submodules('ultralytics.nn') + [
    'ultralytics.models', 'ultralytics.models.yolo', 'ultralytics.models.yolo.detect.predict',
    'uvicorn.logging', 'uvicorn.loops.asyncio', 'uvicorn.protocols.http.h11_impl', 'uvicorn.lifespan.on',
    'torchvision', 'multipart',
]
a = Analysis([str(root / 'packaging' / 'launcher.py')], pathex=[str(root), str(root / 'packaging')],
    binaries=[(str(stage / 'bin' / 'ffprobe.exe'), 'bin')], datas=datas, hiddenimports=hidden,
    hookspath=[], hooksconfig={'matplotlib': {'backends': ['Agg']}}, runtime_hooks=[],
    excludes=['pytest', 'IPython', 'notebook', 'tensorboard', 'tensorflow', 'jax', 'onnx', 'onnxruntime',
              'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'ultralytics_platform', 'pip', 'setuptools'],
    noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='SmartVision',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=os.getenv('SMARTVISION_CONSOLE_BUILD') == '1', disable_windowed_traceback=False,
    uac_admin=False, contents_directory='_internal')
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='SmartVision')
