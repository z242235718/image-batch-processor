# PyInstaller hook for rembg
# rembg dynamically loads model sessions and has dependencies on
# skimage, pymatting, pooch, and other submodules.
# copy_metadata is needed for packages that use importlib.metadata.version()
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, copy_metadata

hiddenimports = collect_submodules("rembg")
datas = collect_data_files("rembg") + copy_metadata("rembg") + copy_metadata("pymatting")
