"""Reject stale PyInstaller bytecode before runtime acceptance or distribution."""
import argparse
import hashlib
import json
from pathlib import Path
import types

from PyInstaller.archive.readers import CArchiveReader

ROOT = Path(__file__).resolve().parents[1]


def signature(value):
    if isinstance(value, types.CodeType):
        return (value.co_code, value.co_names, tuple(signature(item) for item in value.co_consts))
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    archive = CArchiveReader(str(args.exe)).open_embedded_archive('PYZ.pyz')
    names = ['backend.services.tasks', 'backend.services.indexing', 'backend.database.repository',
             'backend.database.api_repository', 'backend.services.search', 'backend.services.videos',
             'backend.api.routes', 'backend.schemas.api', 'backend.core.timestamps', 'backend.core.analyzer']
    results = {}
    for name in names:
        actual = archive.extract(name)
        source = (ROOT / (name.replace('.', '/') + '.py')).read_text(encoding='utf-8')
        expected = compile(source, actual.co_filename, 'exec', dont_inherit=True)
        results[name] = signature(actual) == signature(expected)
    report = {'modules': results, 'exe_sha256': hashlib.sha256(args.exe.read_bytes()).hexdigest()}
    args.report.write_text(json.dumps(report, indent=2), encoding='utf-8')
    if not all(results.values()):
        raise RuntimeError('EXE 内嵌代码与源码不同；请使用新的 workpath 构建，避免复用过期 PYZ 缓存')
    print('Frozen source verification passed:', len(results), 'modules')


if __name__ == '__main__':
    main()
