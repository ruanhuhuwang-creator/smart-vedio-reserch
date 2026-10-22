"""Prepare explicit resources and license/source notices; no user-data directory traversal."""
import argparse
from importlib import metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.request import urlretrieve
import tarfile
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent.parent


def source_archive(target):
    with ZipFile(target, 'w', ZIP_DEFLATED, compresslevel=6) as archive:
        for folder in ('backend', 'packaging', 'tests', 'frontend/src', 'frontend/public', 'frontend/e2e'):
            for file in (ROOT / folder).rglob('*'):
                if file.is_file() and '__pycache__' not in file.parts and file.suffix not in ('.pyc',):
                    archive.write(file, 'SmartVision-source/' + file.relative_to(ROOT).as_posix())
        for pattern in ('README.md', '*VALIDATION.md', 'requirements.txt', 'pytest.ini', '.gitignore',
                        'frontend/*.json', 'frontend/*.ts', 'frontend/.env.example', 'frontend/index.html',
                        'frontend/README.md', 'frontend/run.ps1'):
            for file in ROOT.glob(pattern):
                if file.is_file():
                    archive.write(file, 'SmartVision-source/' + file.relative_to(ROOT).as_posix())
        # Exact unmodified AGPL Python/YAML sources accompany this distribution.
        for package in ('ultralytics', 'ultralytics_thop'):
            try:
                distribution = metadata.distribution(package.replace('_', '-'))
            except metadata.PackageNotFoundError:
                continue
            for item in distribution.files or []:
                file = Path(distribution.locate_file(item))
                if file.is_file() and file.suffix in ('.py', '.yaml', '.yml', '.txt') and '__pycache__' not in file.parts:
                    archive.write(file, 'third-party-source/' + str(item).replace('\\', '/'))
        license_file = Path(metadata.distribution('ultralytics').locate_file('ultralytics-'
            + metadata.version('ultralytics') + '.dist-info/licenses/LICENSE'))
        archive.write(license_file, 'AGPL-3.0.txt')
        archive.write(ROOT / 'packaging' / 'DISTRIBUTION_LICENSE.md', 'DISTRIBUTION_LICENSE.md')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', type=Path, required=True)
    parser.add_argument('--ffprobe', type=Path, required=True)
    args = parser.parse_args()
    stage = args.stage.resolve()
    stage.mkdir(parents=True, exist_ok=True)
    (stage / 'bin').mkdir(exist_ok=True)
    licenses = stage / 'licenses'
    licenses.mkdir(exist_ok=True)
    shutil.copy2(args.ffprobe, stage / 'bin' / 'ffprobe.exe')
    for filename in ('LICENSE', 'README.txt'):
        candidate = args.ffprobe.parent.parent / filename
        if not candidate.is_file():
            raise RuntimeError(f'FFprobe 许可/构建信息缺失: {candidate}')
        shutil.copy2(candidate, licenses / ('FFprobe-' + filename))
    manifest = []
    for distribution in sorted(metadata.distributions(), key=lambda d: d.metadata['Name'].lower()):
        name = distribution.metadata['Name']
        info = {'name': name, 'version': distribution.version,
                'license': distribution.metadata.get('License-Expression') or distribution.metadata.get('License', ''),
                'home': distribution.metadata.get('Home-page', ''),
                'project_urls': distribution.metadata.get_all('Project-URL') or []}
        manifest.append(info)
        for entry in distribution.files or []:
            path = Path(str(entry))
            if any(part.lower().startswith(('license', 'copying', 'notice', 'copyright')) for part in path.parts):
                source = Path(distribution.locate_file(entry))
                if source.is_file() and source.stat().st_size < 20 * 1024 * 1024:
                    target = licenses / name / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    base = Path(sys.base_prefix)
    for file in [base / 'LICENSE.txt', base / 'tcl' / 'tcl8.6' / 'license.terms', base / 'tcl' / 'tk8.6' / 'license.terms']:
        if file.is_file():
            destination = licenses / 'Python-Tcl-Tk' / file.parent.name / file.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, destination)
    (licenses / 'DEPENDENCIES.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    (licenses / 'FFprobe-version.txt').write_text(subprocess.check_output([str(args.ffprobe), '-version'], text=True), encoding='utf-8')
    # Keep a complete upstream FFmpeg source archive alongside its exact build reference.
    cache = ROOT / 'data' / 'outputs' / 'packaging-downloads'
    cache.mkdir(parents=True, exist_ok=True)
    source = cache / 'ffmpeg-8.0.1.tar.xz'
    if not source.is_file():
        temporary = source.with_suffix('.partial')
        urlretrieve('https://ffmpeg.org/releases/ffmpeg-8.0.1.tar.xz', temporary)
        temporary.replace(source)
    shutil.copy2(source, licenses / source.name)
    # Swagger also remains usable without Internet in the packaged /docs page.
    swagger = cache / 'swagger-ui-dist-5.34.0.tgz'
    if not swagger.is_file():
        partial = swagger.with_suffix('.partial')
        urlretrieve('https://registry.npmjs.org/swagger-ui-dist/-/swagger-ui-dist-5.34.0.tgz', partial)
        partial.replace(swagger)
    with tarfile.open(swagger, 'r:gz') as archive:
        for source_name, target_name in [('swagger-ui-bundle.js', 'swagger-ui-bundle.js'),
                                         ('swagger-ui.css', 'swagger-ui.css'), ('favicon-32x32.png', 'swagger-favicon.png')]:
            (ROOT / 'frontend' / 'dist' / 'assets' / target_name).write_bytes(archive.extractfile('package/' + source_name).read())
        (licenses / 'Swagger-UI-LICENSE').write_bytes(archive.extractfile('package/LICENSE').read())
    for file in (ROOT / 'frontend' / 'node_modules').glob('@vue/*/LICENSE'):
        target = licenses / 'Vue' / file.parent.name / file.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, target)
    shutil.copy2(ROOT / 'frontend' / 'node_modules' / 'vue' / 'LICENSE', licenses / 'Vue-LICENSE')
    source_archive(ROOT / 'frontend' / 'dist' / 'source-code.zip')
    shutil.copy2(ROOT / 'packaging' / 'DISTRIBUTION_LICENSE.md', licenses / 'DISTRIBUTION_LICENSE.md')
    print(f'Resources and license records prepared: {stage}')


if __name__ == '__main__':
    main()
