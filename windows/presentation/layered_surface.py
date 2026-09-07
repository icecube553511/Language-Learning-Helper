"""Pointer-safe Win32 presentation of premultiplied RGBA effect frames."""

import ctypes
import ctypes.wintypes as wintypes
from functools import lru_cache

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


class _Win32Api:
    def __init__(self):
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        self.create_dc = gdi32.CreateCompatibleDC
        self.create_dc.argtypes, self.create_dc.restype = [wintypes.HDC], wintypes.HDC
        self.create_bitmap = gdi32.CreateDIBSection
        self.create_bitmap.argtypes = [wintypes.HDC, ctypes.POINTER(_BitmapInfoHeader),
                                       wintypes.UINT, ctypes.POINTER(ctypes.c_void_p),
                                       wintypes.HANDLE, wintypes.DWORD]
        self.create_bitmap.restype = wintypes.HBITMAP
        self.select_object = gdi32.SelectObject
        self.select_object.argtypes = [wintypes.HDC, wintypes.HANDLE]
        self.select_object.restype = wintypes.HANDLE
        self.delete_object = gdi32.DeleteObject
        self.delete_object.argtypes, self.delete_object.restype = [wintypes.HANDLE], wintypes.BOOL
        self.delete_dc = gdi32.DeleteDC
        self.delete_dc.argtypes, self.delete_dc.restype = [wintypes.HDC], wintypes.BOOL
        self.update_layer = user32.UpdateLayeredWindow
        self.update_layer.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT),
                                      ctypes.POINTER(wintypes.SIZE), wintypes.HDC,
                                      ctypes.POINTER(wintypes.POINT), wintypes.COLORREF,
                                      ctypes.POINTER(_BlendFunction), wintypes.DWORD]
        self.update_layer.restype = wintypes.BOOL


@lru_cache(maxsize=1)
def _win32_api() -> _Win32Api:
    return _Win32Api()


class LayeredSurface:
    """Reusable native backing store; the owning UI layer must call close()."""

    def __init__(self, *, _api=None):
        self._api = _api
        self._dc = None
        self._bitmap = None
        self._original = None
        self._pixels = ctypes.c_void_p()
        self._capacity = (0, 0)
        self._closed = False

    def _ensure_buffer(self, width: int, height: int) -> None:
        width = ((width + 63) // 64) * 64
        height = ((height + 63) // 64) * 64
        # A retained wide stride can dominate uploads after a wide-to-tall flight.
        repack = self._capacity[0] >= width * 2
        if not repack and width <= self._capacity[0] and height <= self._capacity[1]:
            return
        # Keep spare rows and columns so a moving trail does not reallocate each frame.
        if not repack:
            width = max(self._capacity[0], width)
            height = max(self._capacity[1], height)
        api = self._api
        new_dc = self._dc is None
        dc = api.create_dc(None) if new_dc else self._dc
        if not dc:
            raise OSError("CreateCompatibleDC failed for reward layer")
        bitmap = None
        try:
            info = _BitmapInfoHeader(ctypes.sizeof(_BitmapInfoHeader), width, -height,
                                     1, 32, 0, width * height * 4, 0, 0, 0, 0)
            pixels = ctypes.c_void_p()
            bitmap = api.create_bitmap(dc, ctypes.byref(info), 0, ctypes.byref(pixels), None, 0)
            if not bitmap or not pixels.value:
                raise OSError("CreateDIBSection failed for reward layer")
            original = api.select_object(dc, bitmap)
            if not original or original == ctypes.c_void_p(-1).value:
                raise OSError("SelectObject failed for reward layer")
        except Exception:
            if bitmap:
                api.delete_object(bitmap)
            if new_dc:
                api.delete_dc(dc)
            raise
        old_bitmap = self._bitmap
        self._dc, self._bitmap, self._pixels = dc, bitmap, pixels
        self._capacity = (width, height)
        if new_dc:
            self._original = original
        if old_bitmap:
            api.delete_object(old_bitmap)

    def present(self, hwnd: int, frame: Image.Image, x: int, y: int) -> None:
        """Upload premultiplied pixels, preserving the HWND's owner and input behavior."""
        if self._closed:
            raise RuntimeError("Reward layered surface is closed")
        width, height = frame.size
        if width < 1 or height < 1:
            raise ValueError("Reward layered frame must have nonzero dimensions")
        if self._api is None:
            self._api = _win32_api()
        self._ensure_buffer(width, height)
        data = frame.convert("RGBa").tobytes("raw", "BGRa", self._capacity[0] * 4, 1)
        ctypes.memmove(self._pixels, data, len(data))
        destination, size = wintypes.POINT(x, y), wintypes.SIZE(width, height)
        source, blend = wintypes.POINT(0, 0), _BlendFunction(0, 0, 255, 1)
        if not self._api.update_layer(hwnd, None, ctypes.byref(destination), ctypes.byref(size), self._dc,
                                      ctypes.byref(source), 0, ctypes.byref(blend), 2):
            raise OSError("UpdateLayeredWindow failed for reward layer")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._dc:
            self._api.select_object(self._dc, self._original)
            self._api.delete_object(self._bitmap)
            self._api.delete_dc(self._dc)
        self._dc = self._bitmap = self._original = None
        self._pixels = ctypes.c_void_p()
        self._capacity = (0, 0)


def present_alpha_frame(hwnd: int, frame: Image.Image, x: int, y: int) -> None:
    """One-shot compatibility helper; animation owners should reuse LayeredSurface."""
    surface = LayeredSurface()
    try:
        surface.present(hwnd, frame, x, y)
    finally:
        surface.close()
