"""Build and verify a complete ZIP64 archive without including user data."""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--folder', type=Path, required=True)
    parser.add_argument('--zip', type=Path, required=True)
    args = parser.parse_args()
    files = sorted(path for path in args.folder.rglob('*') if path.is_file())
    for file in files:
        if file.suffix.lower() in {'.sqlite3', '.mp4', '.avi', '.mov', '.api.lock'} or '.venv' in file.parts or 'node_modules' in file.parts:
            raise RuntimeError(f'禁止把用户数据/开发环境加入分发包：{file}')
    total = sum(file.stat().st_size for file in files)
    with ZipFile(args.zip, 'x', ZIP_DEFLATED, compresslevel=5, allowZip64=True) as archive:
        for file in files:
            archive.write(file, 'SmartVision/' + file.relative_to(args.folder).as_posix())
    with ZipFile(args.zip) as archive:
        failed = archive.testzip()
        if failed:
            raise RuntimeError('ZIP CRC 校验失败：' + failed)
    digest = hashlib.sha256()
    with args.zip.open('rb') as source:
        for block in iter(lambda: source.read(4 * 1024 * 1024), b''):
            digest.update(block)
    manifest = {'folder': str(args.folder.resolve()), 'zip': str(args.zip.resolve()), 'files': len(files),
                'folder_bytes': total, 'zip_bytes': args.zip.stat().st_size, 'zip_sha256': digest.hexdigest()}
    args.zip.with_suffix('.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    args.zip.with_suffix('.sha256').write_text(digest.hexdigest() + '  ' + args.zip.name + '\n', encoding='ascii')
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
