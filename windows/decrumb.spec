# SPDX-License-Identifier: AGPL-3.0-only
# One directory, shared Python runtime, four small entry points. No onefile
# extraction of code into the private account directory on every command.
from pathlib import Path
root = Path(SPECPATH).parent
data = [(str(root / 'release.json'), '.'), (str(root / 'rules/defaults.json'), 'rules')]
cli = Analysis([str(root / 'windows.py')], pathex=[str(root)], datas=data)
helper = Analysis([str(root / 'windows_helper.py')], pathex=[str(root)], datas=data)
bridge = Analysis([str(root / 'windows_signal.py')], pathex=[str(root)])
cli_pyz = PYZ(cli.pure)
executables = [
    EXE(cli_pyz, cli.scripts, [], exclude_binaries=True, name='decrumb', console=True),
    EXE(cli_pyz, cli.scripts, [], exclude_binaries=True, name='decrumb-background', console=False),
    EXE(PYZ(helper.pure), helper.scripts, [], exclude_binaries=True, name='url-cleaner', console=True),
    EXE(PYZ(bridge.pure), bridge.scripts, [], exclude_binaries=True, name='decrumb-signal', console=True),
]
bundle = COLLECT(*executables, cli.binaries, cli.datas, helper.binaries, helper.datas,
                 bridge.binaries, bridge.datas, name='Decrumb')
