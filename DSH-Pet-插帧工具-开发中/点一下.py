# -*- coding: utf-8 -*-
"""模拟鼠标点一下（给插帧工具的界面截图用）。
用法：python3 点一下.py <x> <y> [按钮号]

⚠️ 坑：XWarpPointer 的 dest_w 传 0(None) 时，dest_x/dest_y 会被当成
   「相对当前位置的偏移」，不是绝对坐标 —— 点了半天没反应就是这个原因。
   必须传 root 窗口，坐标才是屏幕绝对坐标。
"""
import ctypes
import sys
import time

x, y = int(sys.argv[1]), int(sys.argv[2])
键 = int(sys.argv[3]) if len(sys.argv) > 3 else 1

xlib = ctypes.CDLL("libX11.so.6")
xtst = ctypes.CDLL("libXtst.so.6")
xlib.XOpenDisplay.restype = ctypes.c_void_p
xlib.XDefaultRootWindow.restype = ctypes.c_ulong
xlib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
xlib.XWarpPointer.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong,
                              ctypes.c_int, ctypes.c_int, ctypes.c_uint,
                              ctypes.c_uint, ctypes.c_int, ctypes.c_int]
xlib.XFlush.argtypes = [ctypes.c_void_p]
xlib.XCloseDisplay.argtypes = [ctypes.c_void_p]

dpy = xlib.XOpenDisplay(None)
if not dpy:
    raise SystemExit("连不上 X")
root = xlib.XDefaultRootWindow(dpy)

xlib.XWarpPointer(dpy, 0, root, 0, 0, 0, 0, x, y)
xlib.XFlush(dpy)
time.sleep(0.25)
xtst.XTestFakeButtonEvent(ctypes.c_void_p(dpy), 键, True, 0)
xlib.XFlush(dpy)
time.sleep(0.08)
xtst.XTestFakeButtonEvent(ctypes.c_void_p(dpy), 键, False, 0)
xlib.XFlush(dpy)
time.sleep(0.35)
xlib.XCloseDisplay(dpy)
print(f"  ✓ 点了一下 ({x}, {y}) 按钮{键}")
