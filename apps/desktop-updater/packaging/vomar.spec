# Native PyInstaller build; GUI/CLI share one dynamically linked runtime directory.
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules
root=Path(SPECPATH).parents[2]
source=root/'apps/desktop-updater/src'
probe=Path(os.environ['VOMAR_PROBE_ROOT'])
notices=Path(os.environ['VOMAR_NOTICES_ROOT'])
data=[(str(source/'vomar_updater/resources/firmware-public.der'),'vomar_updater/resources'),(str(probe),'vomar_updater/resources/probe'),(str(notices),'notices')]
hidden=collect_submodules('bleak.backends')+['keyring.backends.SecretService','keyring.backends.macOS','keyring.backends.Windows']
common=dict(pathex=[str(source),str(root)],datas=data,hiddenimports=hidden,excludes=['PySide6.QtWebEngineCore','PySide6.QtWebEngineWidgets','PySide6.QtQml','tkinter','pytest'],noarchive=False)
gui=Analysis([str(root/'apps/desktop-updater/packaging/gui_entry.py')],**common)
cli=Analysis([str(root/'apps/desktop-updater/packaging/cli_entry.py')],**common)
gui_exe=EXE(PYZ(gui.pure),gui.scripts,[],exclude_binaries=True,name='Vomar',console=False,disable_windowed_traceback=False,target_arch=None)
cli_exe=EXE(PYZ(cli.pure),cli.scripts,[],exclude_binaries=True,name='vomar-cli',console=True,target_arch=None)
coll=COLLECT(gui_exe,cli_exe,gui.binaries,gui.datas,cli.binaries,cli.datas,name='Vomar')
if __import__('sys').platform=='darwin':
    app=BUNDLE(coll,name='Vomar.app',bundle_identifier='org.openvimar.updater.desktop',info_plist={'CFBundleDisplayName':'Vomar','LSMinimumSystemVersion':'14.4','NSBluetoothAlwaysUsageDescription':'Vomar uses Bluetooth to discover and update the selected dimmer after your review.','NSBluetoothPeripheralUsageDescription':'Vomar communicates with the selected dimmer recovery.','NSHighResolutionCapable':True})
