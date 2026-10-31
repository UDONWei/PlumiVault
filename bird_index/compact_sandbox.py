"""Linux/amd64 Landlock gate. No permissive fallback; standalone synthetic probe.

ABI >= 6 supplies truncate, TCP rules and signal/abstract-UNIX scoping.
Read access is not restricted here. Existing Docker read-only mounts still apply.
"""
import argparse
import ctypes
import errno
import json
import os
from pathlib import Path
import platform
import socket
import sqlite3
import subprocess
import sys
import tempfile

WRITE = sum(1 << bit for bit in (1, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14))
FILE_WRITE = (1 << 1) | (1 << 14)
BIND, CONNECT = 1, 2
READ = (1 << 2) | (1 << 3)
# Native x86_64, Linux 6.18 syscall table. No pathname metadata mutation is
# needed by these services. Caddy alone needs fchmod on its newly opened keys.
METADATA_CALLS = (90, 91, 92, 93, 94, 132, 188, 189, 190, 197, 198, 199,
                  235, 260, 261, 268, 280, 452, 463, 466, 469)


class SockFilter(ctypes.Structure):
    _fields_ = [('code', ctypes.c_ushort), ('jt', ctypes.c_ubyte),
                ('jf', ctypes.c_ubyte), ('k', ctypes.c_uint32)]


class SockProgram(ctypes.Structure):
    _fields_ = [('length', ctypes.c_ushort), ('filter', ctypes.POINTER(SockFilter))]


def metadata_filter(allow_fchmod=False):
    """BPF: reject alternate ABIs, metadata writes and nontrivial ioctls.

    fchmod is safe ONLY for the gateway, which cannot open photos for reading
    or writing under its separate Landlock read allowlist. O_PATH cannot be
    used with fchmod; fchmodat/at2 are always denied.
    """
    allow, deny, kill = 0x7fff0000, 0x00050000 | errno.EPERM, 0x80000000
    rows = [(0x20, 0, 0, 4), (0x15, 1, 0, 0xc000003e), (0x06, 0, 0, kill),
            (0x20, 0, 0, 0), (0x35, 0, 1, 0x40000000), (0x06, 0, 0, kill),
            (0x35, 0, 1, 470), (0x06, 0, 0, 0x50000 | errno.ENOSYS)]
    # Also exclude io_uring and ptrace/process-fd access instead of permitting
    # another route around this deliberately small CPU-only syscall policy.
    for number in (*METADATA_CALLS, 101, 310, 311, 425, 426, 427, 438):
        if number == 91 and allow_fchmod:continue
        rows += [(0x15, 0, 1, number), (0x06, 0, 0, deny)]
    # ioctl arg1 (low 32 bits). Only terminal queries and fd mode flags.
    rows += [(0x15, 1, 0, 16), (0x06, 0, 0, allow), (0x20, 0, 0, 24)]
    for request in (0x5401, 0x5413, 0x541b, 0x5421, 0x5450, 0x5451):
        rows += [(0x15, 0, 1, request), (0x06, 0, 0, allow)]
    rows += [(0x06, 0, 0, deny)]
    return rows


def restrict_metadata(lib, allow_fchmod=False):
    rows = metadata_filter(allow_fchmod)
    code = (SockFilter * len(rows))(*(SockFilter(*r) for r in rows))
    program = SockProgram(len(rows), code)
    if lib.prctl(22, 2, ctypes.byref(program), 0, 0):
        raise OSError(ctypes.get_errno(), 'Metadata seccomp filter failed')


class Ruleset(ctypes.Structure):
    _fields_ = [('fs', ctypes.c_uint64), ('net', ctypes.c_uint64), ('scoped', ctypes.c_uint64)]


class PathRule(ctypes.Structure):
    _pack_ = 1
    _fields_ = [('access', ctypes.c_uint64), ('fd', ctypes.c_int32)]


class PortRule(ctypes.Structure):
    _fields_ = [('access', ctypes.c_uint64), ('port', ctypes.c_uint64)]


def libc():
    if sys.platform != 'linux' or platform.machine() not in ('x86_64', 'AMD64'):
        raise RuntimeError('Compact mode requires Linux/amd64 with Landlock ABI >= 6')
    lib = ctypes.CDLL(None, use_errno=True);lib.syscall.restype = ctypes.c_long
    return lib


def checked(lib, number, *args):
    result = lib.syscall(ctypes.c_long(number), *args)
    if result < 0:
        code = ctypes.get_errno();raise OSError(code, os.strerror(code))
    return result


def abi_version():return checked(libc(), 444, ctypes.c_void_p(), ctypes.c_size_t(0), ctypes.c_uint(1))


def restrict(writable, bind_ports=(), connect_ports=(), *, readable=None, allow_fchmod=False):
    if allow_fchmod and readable is None:raise ValueError('fchmod requires a photo-free read allowlist')
    lib = libc();abi = abi_version()
    if abi < 6:raise RuntimeError('Landlock ABI >= 6 required; refusing unprotected compact mode')
    attr = Ruleset(WRITE | (READ if readable is not None else 0), BIND | CONNECT, 3)
    fd = checked(lib, 444, ctypes.byref(attr), ctypes.c_size_t(ctypes.sizeof(attr)), ctypes.c_uint(0))
    try:
        for value in writable:
            path = Path(value).resolve(strict=True)
            # A broad writable root would destroy the original-photo boundary.
            if str(path) in ('/', '/library', '/photos', '/config', '/models', '/app'):
                raise ValueError('Refusing broad writable path: '+str(path))
            pfd = os.open(path, os.O_PATH | os.O_CLOEXEC)
            try:
                rule = PathRule(WRITE if path.is_dir() else FILE_WRITE, pfd)
                checked(lib, 445, ctypes.c_int(fd), ctypes.c_int(1), ctypes.byref(rule), ctypes.c_uint(0))
            finally:os.close(pfd)
        for value in (() if readable is None else [*writable, *readable]):
            path = Path(value).resolve(strict=True)
            if str(path) in ('/', '/library', '/photos', '/data'):
                raise ValueError('Refusing gateway photo read access')
            pfd = os.open(path, os.O_PATH | os.O_CLOEXEC)
            try:
                rule = PathRule(READ if path.is_dir() else 1 << 2, pfd)
                checked(lib, 445, ctypes.c_int(fd), ctypes.c_int(1), ctypes.byref(rule), ctypes.c_uint(0))
            finally:os.close(pfd)
        for access, ports in ((BIND, bind_ports), (CONNECT, connect_ports)):
            for port in ports:
                if type(port) is not int or not 1 <= port <= 65535:raise ValueError('Invalid sandbox port')
                rule = PortRule(access, port)
                checked(lib, 445, ctypes.c_int(fd), ctypes.c_int(2), ctypes.byref(rule), ctypes.c_uint(0))
        if lib.prctl(38, 1, 0, 0, 0):raise OSError(ctypes.get_errno(), 'no_new_privs failed')
        checked(lib, 446, ctypes.c_int(fd), ctypes.c_uint(0))
        restrict_metadata(lib, allow_fchmod)
    finally:os.close(fd)
    return abi


def probe():
    """All attempted writes target disposable /tmp fixtures, never a photo mount."""
    abi = abi_version()
    if abi < 6:raise RuntimeError('Landlock ABI too old: '+str(abi))
    with tempfile.TemporaryDirectory(prefix='plumivault-landlock-', dir='/tmp') as temp:
        base = Path(temp);allowed = base/'data';protected = base/'protected'
        allowed.mkdir();protected.mkdir();original = protected/'synthetic.txt';original.write_bytes(b'fixture')
        (allowed/'alias').symlink_to(protected, target_is_directory=True)
        sys.stdout.flush();pid = os.fork()
        if pid == 0:
            try:
                restrict([allowed, '/dev/null'])
                (allowed/'ok').write_bytes(b'ok')
                with sqlite3.connect(allowed/'fixture.sqlite3') as db:
                    db.execute('PRAGMA journal_mode=WAL')
                    db.execute('CREATE TABLE fixture(value)');db.execute('INSERT INTO fixture VALUES(1)');db.commit()
                    with sqlite3.connect(allowed/'backup.sqlite3') as backup:db.backup(backup)
                assert original.read_bytes() == b'fixture'
                def forbidden(fn):
                    try:fn()
                    except OSError as exc:
                        if exc.errno in (errno.EACCES, errno.EPERM, errno.EXDEV):return
                        raise
                    raise AssertionError('Synthetic denied operation unexpectedly succeeded')
                forbidden(lambda: original.write_bytes(b'bad'))
                forbidden(lambda: os.truncate(original, 0))
                forbidden(lambda: original.unlink())
                forbidden(lambda: original.rename(protected/'moved'))
                forbidden(lambda: (protected/'new').mkdir())
                forbidden(lambda: (allowed/'alias/synthetic.txt').write_bytes(b'bad'))
                forbidden(lambda: os.chmod(original, 0o600))
                forbidden(lambda: os.utime(original, (1, 1)))
                forbidden(lambda: os.setxattr(original, 'user.plumivault', b'bad'))
                with original.open('rb') as source:forbidden(lambda: os.fchmod(source.fileno(), 0o600))
                with socket.socket() as sock:forbidden(lambda: sock.connect(('127.0.0.1', 9)))
                child = os.fork()
                if child == 0:
                    try:forbidden(lambda: original.write_bytes(b'bad'));os._exit(0)
                    except Exception:os._exit(1)
                assert os.waitpid(child, 0)[1] == 0
                code = "import os,sys; p=sys.argv[1]\ntry: os.chmod(p,0o600)\nexcept PermissionError: sys.exit(0)\nsys.exit(1)"
                assert subprocess.run([sys.executable, '-B', '-c', code, str(original)], check=False).returncode == 0
                print(json.dumps({'LandlockABI': abi, 'synthetic_write_isolation': 'passed', 'metadata_seccomp': 'passed', 'sqlite_wal_backup': 'passed', 'exec_inheritance': 'passed', 'photo_access': False}), flush=True)
                os._exit(0)
            except Exception as exc:
                print('Landlock probe failed: '+str(exc), flush=True);os._exit(1)
        _, status = os.waitpid(pid, 0)
        if status:raise RuntimeError('Synthetic sandbox probe failed; do not merge containers')
        if original.read_bytes() != b'fixture':raise RuntimeError('Synthetic source changed')
        # Gateway may chmod keys but must not open a photo through any alias.
        sys.stdout.flush();pid = os.fork()
        if pid == 0:
            try:
                restrict([allowed, '/dev/null'], readable=[allowed], allow_fchmod=True)
                with (allowed/'key').open('wb') as key:os.fchmod(key.fileno(), 0o600)
                for target in (original, allowed/'alias/synthetic.txt'):
                    try:target.read_bytes()
                    except PermissionError:pass
                    else:raise AssertionError('Gateway read protected fixture')
                os._exit(0)
            except Exception as exc:
                print('Gateway sandbox probe failed: '+str(exc), flush=True);os._exit(1)
        if os.waitpid(pid, 0)[1]:raise RuntimeError('Gateway synthetic sandbox probe failed')
        # Organizer must retain same-filesystem rename/restore under its roots.
        sys.stdout.flush();pid = os.fork()
        if pid == 0:
            try:
                restrict([allowed, protected, '/dev/null'])
                original.rename(allowed/'moved');(allowed/'moved').rename(original)
                os._exit(0)
            except Exception as exc:
                print('Organizer sandbox probe failed: '+str(exc), flush=True);os._exit(1)
        if os.waitpid(pid, 0)[1]:raise RuntimeError('Organizer synthetic sandbox probe failed')
        print('Synthetic gateway key access and organizer rename/restore: passed', flush=True)
    return abi


if __name__ == '__main__':
    parser = argparse.ArgumentParser();parser.add_argument('--probe', action='store_true');args = parser.parse_args()
    if args.probe:probe()
    else:print(json.dumps({'LandlockABI': abi_version()}))
