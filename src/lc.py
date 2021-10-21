import os
import ctypes

if os.name == "nt":
    from _ctypes import FreeLibrary as _dlclose
elif os.name == "posix":
    from _ctypes import dlclose as _dlclose


def make_counter(function=None, encoding=None):
    global count
    encoding = encoding or getattr(make_counter, 'encoding', None)
    function = function or getattr(make_counter, 'function', None)
    make_counter.encoding = encoding
    make_counter.function = function

    if function is None or encoding is None:
        return

    count = lambda path: function(bytes(path, encoding=encoding))


def set_encoding(encoding):
    make_counter(encoding=encoding)


def load_shared_object(so):
    global module
    try:
        module = ctypes.cdll.LoadLibrary(so)

        c_count = module.lines_count
        c_count.argtypes = (ctypes.POINTER(ctypes.c_char),)
        c_count.restype = ctypes.c_int
        make_counter(function=c_count)
    except:
        module = None
        def c_count(path):
            with open(path, 'rb') as file:
                return file.read().count(b'\n')
        make_counter(function=c_count)


def unload_shared_object():
    if module:
        try:
            _dlclose(module._handle)
        except Exception as e:
            raise IOError("Could not unload shared object library.")
