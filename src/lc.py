import os
import ctypes

if os.name == "nt":
    from _ctypes import FreeLibrary as _dlclose
elif os.name == "posix":
    from _ctypes import dlclose as _dlclose


def count(path):
    return c_count(bytes(path, encoding=path_encoding))


def set_encoding(encoding):
    global path_encoding
    path_encoding = encoding


def load_shared_object(so):
    global module, c_count
    module = ctypes.cdll.LoadLibrary(so)

    c_count = module.lines_count
    c_count.argtypes = (ctypes.POINTER(ctypes.c_char),)
    c_count.restype = ctypes.c_int


def unload_shared_object():
    try:
        _dlclose(module._handle)
    except Exception as e:
        raise IOError("Could not unload shared object library.")
