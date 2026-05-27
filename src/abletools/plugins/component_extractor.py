import ctypes
from dataclasses import dataclass
from pathlib import Path
import struct
import sys
from typing import Dict, Tuple

"""
Component Extractor for VST3 Plugins
--------------------------------
This script is designed to extract component information from VST3 plugins across both Windows and macOS.
"""

type Uid = Tuple[int, int, int, int]

# Windows uses __stdcall for COM and VST APIs. macOS uses cdecl.
if sys.platform == 'win32':
    FUNCTYPE = ctypes.WINFUNCTYPE
else:
    FUNCTYPE = ctypes.CFUNCTYPE


def _resolve_plugin_binary(plugin_path: Path) -> Path:
    """
    Resolves the actual executable binary path. 
    Crucial for handling macOS bundles and modern Windows VST3 folders.
    """
    if not plugin_path.is_dir():
        return plugin_path  # It is a direct file (e.g., standard .dll)

    basename = plugin_path.stem

    if sys.platform == 'darwin':
        # macOS bundle structure: <plugin>.vst3/Contents/MacOS/<plugin>
        mac_bin = plugin_path / "Contents" / "MacOS" / basename
        if mac_bin.exists():
            return mac_bin
    elif sys.platform == 'win32':
        # Windows VST3 folder structure: <plugin>.vst3/Contents/x86_64-win/<plugin>.vst3
        win_bin = plugin_path / "Contents" / "x86_64-win" / f"{basename}.vst3"
        if win_bin.exists():
            return win_bin

    return plugin_path


class PClassInfo(ctypes.Structure):
    _fields_ = [
        # This has to be a ubyte and not a char so that we don't stop reading when we come across \0
        ("cid", ctypes.c_ubyte * 16),
        ("cardinality", ctypes.c_int32),
        ("category", ctypes.c_char * 32),
        ("name", ctypes.c_char * 64)
    ]


class ComponentExtractionError(Exception):
    pass


@dataclass
class VST3Component:
    name: str
    category: str
    # The 4 32-bit signed integers composing the plugin's GUID in big-endian format
    guid_fields: Uid


def get_vst3_components(plugin_path: Path) -> Dict[str, VST3Component]:
    binary_path = _resolve_plugin_binary(plugin_path)

    try:
        lib = ctypes.CDLL(binary_path)
    except Exception as e:
        raise ComponentExtractionError(
            f"Failed to load binary '{binary_path}'. Error: {e}")

    if not hasattr(lib, 'GetPluginFactory'):
        raise ComponentExtractionError(
            "Invalid VST3: 'GetPluginFactory' entry point not found.")

    lib.GetPluginFactory.restype = ctypes.c_void_p
    factory_ptr = lib.GetPluginFactory()

    if not factory_ptr:
        raise ComponentExtractionError(
            "Entry point 'GetPluginFactory' returned a null pointer.")

    # Cast to a pointer of void pointers to access the VTable
    vtable_ptr = ctypes.cast(factory_ptr, ctypes.POINTER(ctypes.c_void_p))[0]
    vtable = ctypes.cast(vtable_ptr, ctypes.POINTER(ctypes.c_void_p))

    # Map the countClasses and getClassInfo functions from the VTable
    countClasses_func = FUNCTYPE(ctypes.c_int32, ctypes.c_void_p)(vtable[4])
    getClassInfo_func = FUNCTYPE(
        ctypes.c_int32, ctypes.c_void_p, ctypes.c_int32, ctypes.POINTER(PClassInfo))(vtable[5])

    num_classes = countClasses_func(factory_ptr)
    plugin_components: Dict[str, VST3Component] = {}

    for i in range(num_classes):
        info = PClassInfo()
        # 0 corresponds to kResultOk
        if getClassInfo_func(factory_ptr, i, ctypes.pointer(info)) == 0:
            name = info.name.decode('utf-8', errors='ignore').strip('\x00')
            category = info.category.decode(
                'utf-8', errors='ignore').strip('\x00')
            # Live expects this to be in big-endian format
            guid_fields = struct.unpack(">4i", info.cid)
            plugin_components[category] = VST3Component(
                name=name,
                category=category,
                guid_fields=guid_fields
            )

    return plugin_components
