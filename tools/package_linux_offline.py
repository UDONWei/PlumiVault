"""Create and recheck a supplemental NAS archive without user configuration/data."""
import argparse
import hashlib
import io
import json
import tarfile
from pathlib import Path

from verify_offline_dependencies import verify


def digest(stream):
    result = hashlib.sha256()
    for block in iter(lambda: stream.read(1048576), b''):
        result.update(block)
    return result.hexdigest()


def package(output):
    root = Path(__file__).resolve().parents[1]
    payload = root / 'offline-build'
    dependency_check = verify(payload)
    manifest = json.loads((payload / 'manifest.json').read_text(encoding='utf-8'))
    names = [
        'Dockerfile.offline', 'Dockerfile.offline.dockerignore',
        'compose.offline.yaml', 'deploy/start-nas-offline.sh',
        'deploy/with-docker-sudo.sh', 'tools/verify_offline_dependencies.py',
        'tools/prepare_linux_dependencies.py', 'tools/package_linux_offline.py',
        'tests/test_offline.py', 'docs/NAS_OFFLINE_BUILD.md',
        'offline-build/manifest.json', 'offline-build/wheel-audit.json',
        'offline-build/wheel-plan.json',
    ]
    names += ['offline-build/' + row['path'] for row in manifest['files']]
    if len(names) != len(set(names)):
        raise ValueError('Duplicate archive path')
    records = []
    for name in sorted(names):
        path = root / name
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root):
            raise ValueError('Unsafe input path: ' + name)
        with path.open('rb') as stream:
            records.append({'path': name, 'bytes': path.stat().st_size,
                            'sha256': digest(stream)})
    report = {
        'kind': 'offline-build-supplement-v1',
        'target': 'linux/amd64 CPython 3.12.14',
        'contains_photos_or_user_configuration': False,
        'nas_build_verified': False,
        'dependency_check': dependency_check,
        'files': records,
    }
    raw_manifest = (json.dumps(report, indent=2, ensure_ascii=False) + '\n').encode('utf-8')
    output = Path(output).resolve()
    checksum = output.with_name(output.name + '.sha256')
    if output.exists() or checksum.exists():
        raise FileExistsError('Refusing to replace existing delivery')
    with tarfile.open(output, 'x', format=tarfile.PAX_FORMAT) as archive:
        for row in records:
            info = archive.gettarinfo(str(root / row['path']), arcname=row['path'])
            info.mode = 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ''
            with (root / row['path']).open('rb') as stream:
                archive.addfile(info, stream)
        info = tarfile.TarInfo('OFFLINE_BUNDLE_MANIFEST.json')
        info.size = len(raw_manifest)
        info.mode = 0o644
        archive.addfile(info, io.BytesIO(raw_manifest))
    expected = {row['path']: row for row in records}
    with tarfile.open(output, 'r') as archive:
        if archive.getnames() != [row['path'] for row in records] + ['OFFLINE_BUNDLE_MANIFEST.json']:
            raise ValueError('Unexpected archive contents')
        for member in archive.getmembers():
            if not member.isfile():
                raise ValueError('Non-file in archive')
            with archive.extractfile(member) as stream:
                if member.name == 'OFFLINE_BUNDLE_MANIFEST.json':
                    assert stream.read() == raw_manifest
                elif digest(stream) != expected[member.name]['sha256']:
                    raise ValueError('Archive checksum mismatch: ' + member.name)
    with output.open('rb') as stream:
        sha256 = digest(stream)
    checksum.write_text(sha256 + '  ' + output.name + '\n', encoding='ascii')
    return {'archive': str(output), 'bytes': output.stat().st_size,
            'sha256': sha256, 'verified_files': len(records) + 1,
            'nas_build_verified': False, 'scan_started': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(package(args.output), ensure_ascii=False, indent=2))
