"""Audit the explicit public-source file list; never read runtime/photo directories.

Run before staging/publishing. This is a guardrail, not a replacement for review.
"""
import json
import re
import subprocess
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = 'PUBLICATION_FILES.json'
FORBIDDEN_PARTS = {'.git', '.env', 'config', 'app-data', 'data', 'models', 'offline',
                   'offline-build', 'work', 'outputs', 'backups', 'imports', 'node_modules'}
ALLOWED_SUFFIXES = {'.py', '.js', '.css', '.html', '.md', '.txt', '.json', '.yaml',
                    '.sh', '.ps1', '.example', '.dockerignore'}
SPECIAL_NAMES = {'.gitignore', '.gitattributes', '.dockerignore', 'Dockerfile',
                 'Dockerfile.offline', 'Dockerfile.compact', 'Caddyfile', 'compact.Caddyfile'}
PATTERNS = {
    'private_key': r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    'github_token': r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b',
    'windows_user_path': r'(?i)[A-Z]:[\\/]Users[\\/][^\s/\\]+',
    'private_ipv4': r'\b(?:192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+)\b',
    'bcrypt_hash': r'\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}',
}


def main():
    names = json.loads((ROOT / MANIFEST).read_text(encoding='utf-8'))['files']
    errors = []
    if len(names) != len(set(names)) or MANIFEST not in names:
        errors.append('Invalid or duplicate manifest entries')
    for name in names:
        relative = PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts or ':' in name or '\\' in name:
            errors.append('Unsafe manifest path: ' + name)
            continue
        path = ROOT / name
        if any(part in FORBIDDEN_PARTS or part.startswith('.venv') for part in relative.parts):
            errors.append('Private/runtime path: ' + name)
            continue
        if path.suffix not in ALLOWED_SUFFIXES and path.name not in SPECIAL_NAMES:
            errors.append('Unapproved file type: ' + name)
            continue
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(ROOT):
            errors.append('Missing or unsafe file: ' + name)
            continue
        try:
            content = path.read_text(encoding='utf-8')
        except UnicodeError:
            errors.append('Non-UTF8 file: ' + name)
            continue
        if '\0' in content:
            errors.append('Binary content: ' + name)
        for label, pattern in PATTERNS.items():
            for match in re.finditer(pattern, content):
                line = content.count('\n', 0, match.start()) + 1
                errors.append(f'{name}:{line}: {label}')  # Never print matched secrets.
    # Check staged/tracked names when Git is available. Untracked files must be
    # reviewed before adding; excluded runtime directories are never traversed.
    try:
        result = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT, capture_output=True, check=True)
        tracked = set(filter(None, result.stdout.decode('utf-8').split('\0')))
        errors += ['Tracked outside manifest: ' + name for name in sorted(tracked - set(names))]
    except (OSError, subprocess.CalledProcessError):
        print('Git index check unavailable; file-content audit still performed.')
    if errors:
        print('\n'.join(errors))
        raise SystemExit(1)
    print(f'Public source audit passed: {len(names)} approved UTF-8 files.')


if __name__ == '__main__':
    main()
