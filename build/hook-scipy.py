# PyInstaller hook for scipy
# scipy has a large number of native .pyd extensions.
# Explicit collection prevents DLL resolution failures in
# scenarios where scipy is imported alongside onnxruntime.
from PyInstaller.utils.hooks import collect_submodules, collect_dynamic_libs

hiddenimports = collect_submodules("scipy")
binaries = collect_dynamic_libs("scipy")
