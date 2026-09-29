# -*- coding: utf-8 -*-
"""往当前焦点窗口发一个按键（默认回车）。

用法：python3 敲键.py [keysym]     keysym 默认 Return
注意：会先确保目标窗口在前台（调用方自己 wmctrl -a）。
"""
import ctypes
import sys
import time

名字 = sys.argv[1] if len(sys.argv) > 1 else "Return"

xlib = ctypes.CDLL("libX11.so.6")
xtst = ctypes.CDLL("libXtst.so.6")
xlib.XOpenDisplay.restype = ctypes.c_void_p
xlib.XStringToKeysym.restype = ctypes.c_ulong
xlib.XStringToKeysym.argtypes = [ctypes.c_char_p]
xlib.XKeysymToKeycode.restype = ctypes.c_ubyte
xlib.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
xlib.XFlush.argtypes = [ctypes.c_void_p]

dpy = xlib.XOpenDisplay(None)
if not dpy:
    raise SystemExit("连不上 X")
keysym = xlib.XStringToKeysym(名字.encode())
if keysym == 0:
    raise SystemExit(f"不认识的键名：{名字}")
keycode = xlib.XKeysymToKeycode(dpy, keysym)

xtst.XTestFakeKeyEvent(ctypes.c_void_p(dpy), keycode, True, 0)
xlib.XFlush(dpy)
time.sleep(0.06)
xtst.XTestFakeKeyEvent(ctypes.c_void_p(dpy), keycode, False, 0)
xlib.XFlush(dpy)
time.sleep(0.3)
print(f"  ✓ 敲了一下 {名字}（keycode {keycode}）")
