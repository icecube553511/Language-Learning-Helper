"""Pointer-safe Win32 presentation of premultiplied RGBA effect frames."""

import ctypes
import ctypes.wintypes as wintypes

from PIL import Image


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD), ("width", wintypes.LONG),
        ("height", wintypes.LONG), ("planes", wintypes.WORD),
        ("bit_count", wintypes.WORD), ("compression", wintypes.DWORD),
        ("image_size", wintypes.DWORD), ("x_pixels_per_meter", wintypes.LONG),
        ("y_pixels_per_meter", wintypes.LONG), ("colors_used", wintypes.DWORD),
        ("colors_important", wintypes.DWORD),
    ]


class _BlendFunction(ctypes.Structure):
    _fields_ = [("operation", ctypes.c_ubyte), ("flags", ctypes.c_ubyte),
                ("constant_alpha", ctypes.c_ubyte), ("alpha_format", ctypes.c_ubyte)]


def present_alpha_frame(hwnd: int, frame: Image.Image, x: int, y: int) -> None:
    """Update a layered HWND without capturing or assuming its background color."""
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    create_dc = gdi32.CreateCompatibleDC
    create_dc.argtypes, create_dc.restype = [wintypes.HDC], wintypes.HDC
    create_bitmap = gdi32.CreateDIBSection
    create_bitmap.argtypes = [wintypes.HDC, ctypes.POINTER(_BitmapInfoHeader),
                             wintypes.UINT, ctypes.POINTER(ctypes.c_void_p),
                             wintypes.HANDLE, wintypes.DWORD]
    create_bitmap.restype = wintypes.HBITMAP
    select_object = gdi32.SelectObject
    select_object.argtypes, select_object.restype = [wintypes.HDC, wintypes.HANDLE], wintypes.HANDLE
    delete_object = gdi32.DeleteObject
    delete_object.argtypes, delete_object.restype = [wintypes.HANDLE], wintypes.BOOL
    delete_dc = gdi32.DeleteDC
    delete_dc.argtypes, delete_dc.restype = [wintypes.HDC], wintypes.BOOL
    update_layer = user32.UpdateLayeredWindow
    update_layer.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT),
                            ctypes.POINTER(wintypes.SIZE), wintypes.HDC,
                            ctypes.POINTER(wintypes.POINT), wintypes.COLORREF,
                            ctypes.POINTER(_BlendFunction), wintypes.DWORD]
    update_layer.restype = wintypes.BOOL
    width, height = frame.size
    info = _BitmapInfoHeader(ctypes.sizeof(_BitmapInfoHeader), width, -height,
                             1, 32, 0, width * height * 4, 0, 0, 0, 0)
    destination, size = wintypes.POINT(x, y), wintypes.SIZE(width, height)
    source, blend = wintypes.POINT(0, 0), _BlendFunction(0, 0, 255, 1)
    pixels = ctypes.c_void_p()
    dc = create_dc(None)
    if not dc:
        raise OSError("CreateCompatibleDC failed for reward layer")
    bitmap, original = None, None
    try:
        bitmap = create_bitmap(dc, ctypes.byref(info), 0, ctypes.byref(pixels), None, 0)
        if not bitmap or not pixels.value:
            raise OSError("CreateDIBSection failed for reward layer")
        original = select_object(dc, bitmap)
        data = frame.convert("RGBa").tobytes("raw", "BGRa")
        ctypes.memmove(pixels, data, len(data))
        if not update_layer(hwnd, None, ctypes.byref(destination), ctypes.byref(size), dc,
                            ctypes.byref(source), 0, ctypes.byref(blend), 2):
            raise OSError("UpdateLayeredWindow failed for reward layer")
    finally:
        if original:
            select_object(dc, original)
        if bitmap:
            delete_object(bitmap)
        delete_dc(dc)
