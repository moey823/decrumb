# SPDX-License-Identifier: AGPL-3.0-only
"""Small OS boundary shared by the worker and content-free diagnostics."""
import errno
import os
from pathlib import Path
import subprocess
import sys
import time


def lock_file(file, blocking=False):
    if sys.platform != 'win32':
        import fcntl
        fcntl.flock(file, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        return
    import msvcrt
    # Windows permits locking a range beyond EOF. All participants lock byte 0;
    # closing the file releases the lock, including after an abrupt process exit.
    while True:
        file.seek(0)
        try:
            msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            return
        except OSError as error:
            if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise
            if not blocking:
                raise BlockingIOError() from None
            time.sleep(0.05)


def private_mode(path_or_fd, mode=0o600):
    # NTFS privacy comes from the protected, inheritable runtime DACL created
    # before storing anything sensitive. chmod on Windows only sets read-only.
    if sys.platform != 'win32':
        os.chmod(path_or_fd, mode)


def helper_command(helper, *args):
    path = Path(helper)
    if sys.platform == 'win32' and path.suffix.lower() == '.py':
        return [sys.executable, '-B', str(path), *args]
    return [str(path), *args]


def child_options():
    return {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}


def process_alive(pid):
    if pid <= 0:
        return False
    if sys.platform == 'win32':
        import pywintypes
        import win32api
        import win32event
        try:
            handle = win32api.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        except pywintypes.error as error:
            if error.winerror in (5, 87):  # inaccessible/reused PID or no such process
                return False
            raise
        try:
            return win32event.WaitForSingleObject(handle, 0) == win32event.WAIT_TIMEOUT
        finally:
            handle.Close()
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
