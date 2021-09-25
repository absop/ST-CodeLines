import os
from contextlib import contextmanager


def try_or_zero(thunk):
    try:
       return thunk()
    except:
       return 0


@contextmanager
def cd(path):
    cwd = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(cwd)


def strsize(bytesize):
    k = 0
    while bytesize >> (k + 10):
        k += 10
    units = ("B", "KB", "MB", "GB")
    size_by_unit = round(bytesize / (1 << k), 2) if k else bytesize
    return str(size_by_unit) + units[k // 10]
