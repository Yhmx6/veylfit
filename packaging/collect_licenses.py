from pathlib import Path
import importlib.metadata as md
import shutil,sys,json,hashlib
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'licenses';out.mkdir(exist_ok=True)
for dist in md.distributions():
    name=dist.metadata['Name'];target=out/name;target.mkdir(exist_ok=True)
    for item in dist.files or []:
        if any(x in item.name.lower() for x in ('license','copying','notice')) and item.suffix.lower() not in ('.py','.pyc','.so','.pyd'):
            source=dist.locate_file(item)
            if source.is_file():
                dest=target/str(item).replace('/','_').replace('\\','_');shutil.copyfile(source,dest)
    if not any(target.iterdir()):target.rmdir()
for candidate in (Path(sys.base_prefix)/'LICENSE.txt',Path(sys.base_prefix)/'tcl/tcl8.6/license.terms',Path(sys.base_prefix)/'tcl/tk8.6/license.terms'):
    if candidate.is_file():shutil.copyfile(candidate,out/(candidate.parent.name+'-'+candidate.name))
p=ROOT/'src/veylfit'
assets={str(f.relative_to(p)).replace('\\','/'):dict(sha256=hashlib.sha256(f.read_bytes()).hexdigest(),bytes=f.stat().st_size)
        for folder in ('templates','face_assets','shape_assets','pose_assets') for f in (p/folder).iterdir() if f.is_file()}
(ROOT/'packaging/assets-manifest.json').write_text(json.dumps(assets,indent=2),'utf-8')
print('Collected distribution license texts and generic asset hashes.')
