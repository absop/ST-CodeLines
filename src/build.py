#!/usr/bin/python3


import sys
import os


def build_shared_object():
    platform = {
        'darwin': 'osx',
        'linux' : 'linux',
        'win32' : 'windows'
    }.get(sys.platform, None)

    if platform is None:
        return

    os.makedirs('../so', exist_ok=True)
    so = f'"../so/lc.{platform}.so"'
    cmd = f'gcc -fPIC -shared -O2 -s -DBUILD_SHARED_OBJECT lc.c -o {so}'

    print(f'begin build')
    print(cmd)
    try:
        os.system(cmd)
        print('build success')
    except:
        print('build failed')


if __name__ == '__main__':
    build_shared_object()
