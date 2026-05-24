import ctypes
from dataclasses import dataclass
import struct
import os
import sys
from typing import Dict, Tuple

"""
Component Extractor for VST3 Plugins
--------------------------------
This script is designed to extract component information from VST3 plugins across both Windows and macOS.
"""

# Windows uses __stdcall for COM and VST APIs. macOS uses cdecl.
if sys.platform == 'win32':
    FUNCTYPE = ctypes.WINFUNCTYPE
else:
    FUNCTYPE = ctypes.CFUNCTYPE


def resolve_plugin_binary(plugin_path: str) -> str:
    """
    Resolves the actual executable binary path. 
    Crucial for handling macOS bundles and modern Windows VST3 folders.
    """
    if not os.path.isdir(plugin_path):
        return plugin_path  # It is a direct file (e.g., standard .dll)

    basename = os.path.splitext(os.path.basename(plugin_path))[0]

    if sys.platform == 'darwin':
        # macOS bundle structure: Plugin.vst3/Contents/MacOS/Plugin
        mac_bin = os.path.join(plugin_path, "Contents", "MacOS", basename)
        if os.path.exists(mac_bin):
            return mac_bin
    elif sys.platform == 'win32':
        # Windows VST3 folder structure: Plugin.vst3/Contents/x86_64-win/Plugin.vst3
        win_bin = os.path.join(plugin_path, "Contents",
                               "x86_64-win", f"{basename}.vst3")
        if os.path.exists(win_bin):
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


class ComponentExtractorError(Exception):
    pass


@dataclass
class VST3Component:
    name: str
    category: str
    guid_fields: Tuple[int, int, int, int]


def get_vst3_components(plugin_path: str) -> Dict[str, VST3Component]:
    binary_path = resolve_plugin_binary(plugin_path)

    try:
        lib = ctypes.CDLL(binary_path)
    except Exception as e:
        raise ComponentExtractorError(f"Failed to load binary: {e}")

    if not hasattr(lib, 'GetPluginFactory'):
        raise ComponentExtractorError(
            "Invalid VST3: 'GetPluginFactory' entry point not found.")

    lib.GetPluginFactory.restype = ctypes.c_void_p
    factory_ptr = lib.GetPluginFactory()

    if not factory_ptr:
        raise ComponentExtractorError(
            "GetPluginFactory returned a null pointer.")

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
