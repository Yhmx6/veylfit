"""Verify the unmodified standard license and exact distributed notices."""
from pathlib import Path
import argparse
import hashlib

ROOT = Path(__file__).resolve().parents[1]
FILES = ('LICENSE', 'LICENSE.zh-CN.md', 'LICENSE-SCOPE.md', 'COMMERCIAL.md', 'THIRD_PARTY_NOTICES.md')
UPSTREAM_BLOB = '5ecc88cfc4b1cff608ed640efe913c9dd97935c3'

def verify(bundle=None):
    license_text = (ROOT / 'LICENSE').read_text('utf-8')
    marker = '# PolyForm Noncommercial License 1.0.0\n'
    body = license_text[license_text.index(marker):].encode('utf-8')
    assert hashlib.sha1(b'blob ' + str(len(body)).encode() + b'\0' + body).hexdigest() == UPSTREAM_BLOB
    assert license_text.startswith('Required Notice: Copyright (c) 2026 Yhmx6.')
    for name in FILES:
        text = (ROOT / name).read_text('utf-8')
        assert text and '尚未作为仓库正式授权发布' not in text and 'COMMERCIAL.proposed.md' not in text, name
        if bundle is not None:
            assert (Path(bundle) / name).read_bytes() == (ROOT / name).read_bytes(), name
    assert 'LicenseFile=..\\LICENSE' in (ROOT / 'packaging/installer.iss').read_text('utf-8')
    print('Official license body verified; distribution notices match.' if bundle else 'Official license body and source notices verified.')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--bundle', type=Path)
    verify(parser.parse_args().bundle)
