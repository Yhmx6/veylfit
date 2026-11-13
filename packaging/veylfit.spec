# Build from repository root with: python -m PyInstaller packaging/veylfit.spec
from pathlib import Path
from PyInstaller.utils.hooks import collect_all,copy_metadata
root=Path(SPECPATH).parent
src=root/'src'/'veylfit'
mp_data,mp_bins,mp_hidden=collect_all('mediapipe')
datas=mp_data+[(str(src/folder),folder) for folder in ('templates','face_assets','pose_assets','shape_assets')]
datas += [(str(root/'THIRD_PARTY_NOTICES.md'),'.'),(str(root/'licenses'),'licenses')]
for package in ('mediapipe','numpy','pillow','pyinstaller'):
    datas+=copy_metadata(package)
a=Analysis([str(src/'main.py')],pathex=[str(src)],binaries=mp_bins,datas=datas,
           hiddenimports=mp_hidden+['diagnostics','measurement_fit'],excludes=['IPython','notebook','pandas','scipy','pytest'],noarchive=False)
a.datas=[item for item in a.datas if 'matplotlib/mpl-data/sample_data/' not in item[0].replace('\\','/')]
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='Veylfit',console=False,debug=False,strip=False,upx=False)
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='Veylfit')
