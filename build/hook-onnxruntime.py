# PyInstaller hook for onnxruntime
# Explicitly collect all native DLLs and data files for onnxruntime.
# In --onedir mode, DLLs stay on disk next to .pyd files, matching
# the expected layout for native extension loading.
from PyInstaller.utils.hooks import collect_dynamic_libs, collect_data_files, collect_submodules

binaries = collect_dynamic_libs("onnxruntime")
datas = collect_data_files("onnxruntime")

hiddenimports = collect_submodules("onnxruntime")
