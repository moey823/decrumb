# SPDX-License-Identifier: AGPL-3.0-only
"""Windows account storage and process containment. Imported lazily off Windows."""
import os
from pathlib import Path
import stat
import uuid

_job = None


def current_sid():
    import win32api
    import win32security
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32security.TOKEN_QUERY)
    try:
        return win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    finally:
        token.Close()


def check_private_directory(root):
    import win32security
    reject_links(root)
    descriptor = win32security.GetNamedSecurityInfo(str(root), win32security.SE_FILE_OBJECT,
                                                    win32security.DACL_SECURITY_INFORMATION)
    if not descriptor.GetSecurityDescriptorControl()[0] & 0x1000:  # SE_DACL_PROTECTED
        raise OSError('The runtime directory needs private permissions. Run setup.')
    acl = descriptor.GetSecurityDescriptorDacl()
    allowed = {str(current_sid()), str(win32security.CreateWellKnownSid(win32security.WinLocalSystemSid, None))}
    if acl is None or acl.GetAceCount() != 2:
        raise OSError('The runtime directory needs private permissions. Run setup.')
    for index in range(acl.GetAceCount()):
        (kind, flags), mask, owner = acl.GetAce(index)
        if kind != 0 or flags & 3 != 3 or mask != 0x1F01FF or str(owner) not in allowed:
            raise OSError('The runtime directory needs private permissions. Run setup.')


def reject_links(path):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        if item.exists() or item.is_symlink():
            info = item.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise OSError('Runtime paths must not contain links or junctions.')


def secure_directory(root):
    """Protect the directory before writing secrets, including existing children."""
    import win32security
    reject_links(root)
    root.mkdir(parents=True, exist_ok=True)
    paths = [root]
    for parent, directories, files in os.walk(root, followlinks=False):
        for name in directories + files:
            child = Path(parent) / name
            reject_links(child)
            paths.append(child)
    sid = current_sid()
    system = win32security.CreateWellKnownSid(win32security.WinLocalSystemSid, None)
    for path in paths:
        acl = win32security.ACL()
        inheritance = 3 if path.is_dir() else 0  # OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE
        for owner in (sid, system):
            acl.AddAccessAllowedAceEx(win32security.ACL_REVISION, inheritance, 0x1F01FF, owner)
        win32security.SetNamedSecurityInfo(
            str(path), win32security.SE_FILE_OBJECT,
            win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
            None, None, acl, None)


def contain_children():
    """Hold a non-inheritable kill-on-close job until this bridge process exits.

    Called BEFORE spawning Java. Even forced termination of the bridge therefore
    closes its sole job handle and stops the entire Java process tree.
    """
    global _job
    if _job is not None:
        return
    import win32api
    import win32job
    # pywin32 requires a string name. A fresh local name prevents accidentally
    # attaching to another installation's job; the default handle is private.
    job = win32job.CreateJobObject(None, 'Local\\Decrumb-' + uuid.uuid4().hex)
    try:
        limits = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
        limits['BasicLimitInformation']['LimitFlags'] = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, limits)
        win32job.AssignProcessToJobObject(job, win32api.GetCurrentProcess())
    except Exception:
        job.Close()
        raise
    _job = job
