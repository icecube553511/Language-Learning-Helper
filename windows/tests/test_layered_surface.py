from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import sys
import unittest
from pathlib import Path

from PIL import Image


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from presentation.layered_surface import LayeredSurface, _BitmapInfoHeader, _BlendFunction


class FakeNativeApi:
    """Reject invalid GDI lifetimes and keep real writable DIB memory for uploads."""

    def __init__(self):
        self.calls = []
        self.stock_bitmap = 0x100000001
        self.dc = 0x100000002
        self.selected = self.stock_bitmap
        self.bitmaps = {}
        self.next_bitmap = 0x100000010
        self.fail_dc = False
        self.fail_bitmap = False
        self.fail_pixels = False
        self.fail_select = False
        self.fail_update = False
        self.last_upload = None

    def create_dc(self, source):
        self.calls.append(("create_dc",))
        return None if self.fail_dc else self.dc

    def create_bitmap(self, dc, info_pointer, usage, pixels_pointer, section, offset):
        self.calls.append(("create_bitmap",))
        if self.fail_bitmap:
            return None
        info = ctypes.cast(info_pointer, ctypes.POINTER(_BitmapInfoHeader)).contents
        assert info.height < 0 and info.bit_count == 32
        pixels = ctypes.create_string_buffer(info.width * -info.height * 4)
        bitmap = self.next_bitmap
        self.next_bitmap += 1
        self.bitmaps[bitmap] = (pixels, info.width, -info.height)
        if not self.fail_pixels:
            ctypes.cast(pixels_pointer, ctypes.POINTER(ctypes.c_void_p))[0] = ctypes.addressof(pixels)
        return bitmap

    def select_object(self, dc, bitmap):
        self.calls.append(("select", bitmap))
        if self.fail_select:
            return ctypes.c_void_p(-1).value
        previous, self.selected = self.selected, bitmap
        return previous

    def delete_object(self, bitmap):
        assert bitmap != self.selected, "Cannot delete a selected bitmap"
        self.calls.append(("delete_bitmap", bitmap))
        del self.bitmaps[bitmap]
        return True

    def delete_dc(self, dc):
        assert self.selected == self.stock_bitmap, "Restore the DC's original bitmap first"
        self.calls.append(("delete_dc",))
        return True

    def update_layer(self, hwnd, target_dc, position_pointer, size_pointer, source_dc,
                     source_pointer, key, blend_pointer, flags):
        size = ctypes.cast(size_pointer, ctypes.POINTER(wintypes.SIZE)).contents
        position = ctypes.cast(position_pointer, ctypes.POINTER(wintypes.POINT)).contents
        blend = ctypes.cast(blend_pointer, ctypes.POINTER(_BlendFunction)).contents
        pixels, width, height = self.bitmaps[self.selected]
        assert size.cx <= width and size.cy <= height
        assert blend.constant_alpha == 255 and blend.alpha_format == 1 and flags == 2
        self.last_upload = {
            "hwnd": hwnd,
            "position": (position.x, position.y),
            "size": (size.cx, size.cy),
            "rows": [pixels.raw[row * width * 4:row * width * 4 + size.cx * 4]
                     for row in range(size.cy)],
        }
        return not self.fail_update


class LayeredSurfaceTests(unittest.TestCase):
    def test_reuses_dc_and_bitmap_for_changing_frames_inside_capacity(self):
        api = FakeNativeApi()
        surface = LayeredSurface(_api=api)
        for size in ((24, 30), (31, 45), (12, 10), (64, 64), (1, 1)):
            surface.present(0x200000001, Image.new("RGBA", size), -120, 40)
        self.assertEqual(api.calls.count(("create_dc",)), 1)
        self.assertEqual(api.calls.count(("create_bitmap",)), 1)
        self.assertEqual(api.last_upload["position"], (-120, 40))
        self.assertEqual(api.last_upload["size"], (1, 1))
        self.assertEqual(api.last_upload["hwnd"], 0x200000001)
        surface.close()
        self.assertFalse(api.bitmaps)

    def test_upload_premultiplies_alpha_and_respects_padded_stride(self):
        api = FakeNativeApi()
        surface = LayeredSurface(_api=api)
        frame = Image.new("RGBA", (2, 2), (240, 120, 60, 128))
        frame.putpixel((1, 1), (255, 80, 20, 0))
        surface.present(12, frame, 0, 0)
        self.assertEqual(api.last_upload["rows"], [bytes((30, 60, 120, 128)) * 2,
                                                  bytes((30, 60, 120, 128, 0, 0, 0, 0))])
        surface.present(12, Image.new("RGBA", (1, 2)), 0, 0)
        self.assertEqual(api.last_upload["rows"], [bytes(4), bytes(4)])
        surface.close()

    def test_growth_reuses_dc_and_replaces_bitmap_before_deleting_previous(self):
        api = FakeNativeApi()
        surface = LayeredSurface(_api=api)
        surface.present(12, Image.new("RGBA", (20, 20)), 0, 0)
        first_bitmap = api.selected
        surface.present(12, Image.new("RGBA", (65, 20)), 0, 0)
        self.assertNotEqual(first_bitmap, api.selected)
        self.assertEqual(api.calls.count(("create_dc",)), 1)
        self.assertEqual(api.calls.count(("create_bitmap",)), 2)
        self.assertNotIn(first_bitmap, api.bitmaps)
        surface.close()
        self.assertFalse(api.bitmaps)

    def test_initial_allocation_failures_release_partial_resources(self):
        for failure in ("fail_dc", "fail_bitmap", "fail_pixels", "fail_select"):
            with self.subTest(failure):
                api = FakeNativeApi()
                setattr(api, failure, True)
                surface = LayeredSurface(_api=api)
                with self.assertRaises(OSError):
                    surface.present(12, Image.new("RGBA", (20, 20)), 0, 0)
                self.assertFalse(api.bitmaps)
                self.assertEqual(api.calls.count(("delete_dc",)), 0 if failure == "fail_dc" else 1)
                setattr(api, failure, False)
                surface.present(12, Image.new("RGBA", (20, 20)), 0, 0)
                surface.close()
                self.assertFalse(api.bitmaps)

    def test_wide_to_tall_frames_repack_stride_and_reuse_nearby_sizes(self):
        api = FakeNativeApi()
        surface = LayeredSurface(_api=api)
        surface.present(12, Image.new("RGBA", (192, 20)), 0, 0)
        wide_bitmap = api.selected
        for size in ((28, 108), (30, 107), (29, 105), (28, 108), (64, 128)):
            surface.present(12, Image.new("RGBA", size), 0, 0)
            self.assertEqual(api.bitmaps[api.selected][1:], (64, 128))
        self.assertEqual(api.calls.count(("create_dc",)), 1)
        self.assertEqual(api.calls.count(("create_bitmap",)), 2)
        self.assertNotIn(wide_bitmap, api.bitmaps)
        surface.close()
        self.assertFalse(api.bitmaps)

    def test_moderately_narrower_frames_keep_existing_stride(self):
        api = FakeNativeApi()
        surface = LayeredSurface(_api=api)
        for width in (192, 129, 150, 180, 130):
            surface.present(12, Image.new("RGBA", (width, 20)), 0, 0)
        self.assertEqual(api.calls.count(("create_bitmap",)), 1)
        surface.close()

    def test_failed_repack_preserves_buffer_and_retries_next_frame(self):
        for failure in ("fail_bitmap", "fail_pixels", "fail_select"):
            with self.subTest(failure):
                api = FakeNativeApi()
                surface = LayeredSurface(_api=api)
                surface.present(12, Image.new("RGBA", (192, 20)), 0, 0)
                wide_bitmap = api.selected
                setattr(api, failure, True)
                with self.assertRaises(OSError):
                    surface.present(12, Image.new("RGBA", (28, 108)), 0, 0)
                self.assertEqual(api.selected, wide_bitmap)
                self.assertEqual(list(api.bitmaps), [wide_bitmap])
                setattr(api, failure, False)
                surface.present(12, Image.new("RGBA", (28, 108)), 0, 0)
                self.assertEqual(api.bitmaps[api.selected][1:], (64, 128))
                self.assertNotIn(wide_bitmap, api.bitmaps)
                surface.close()
                self.assertFalse(api.bitmaps)

    def test_failed_growth_preserves_last_usable_buffer(self):
        for failure in ("fail_bitmap", "fail_pixels", "fail_select"):
            with self.subTest(failure):
                api = FakeNativeApi()
                surface = LayeredSurface(_api=api)
                surface.present(12, Image.new("RGBA", (20, 20)), 0, 0)
                first_bitmap = api.selected
                setattr(api, failure, True)
                with self.assertRaises(OSError):
                    surface.present(12, Image.new("RGBA", (80, 20)), 0, 0)
                self.assertEqual(api.selected, first_bitmap)
                self.assertEqual(list(api.bitmaps), [first_bitmap])
                setattr(api, failure, False)
                surface.present(12, Image.new("RGBA", (20, 20)), 0, 0)
                surface.close()
                self.assertFalse(api.bitmaps)

    def test_failed_upload_can_retry_and_still_closes(self):
        api = FakeNativeApi()
        surface = LayeredSurface(_api=api)
        api.fail_update = True
        with self.assertRaisesRegex(OSError, "UpdateLayeredWindow"):
            surface.present(12, Image.new("RGBA", (20, 20)), 0, 0)
        api.fail_update = False
        surface.present(12, Image.new("RGBA", (20, 20)), 0, 0)
        self.assertEqual(api.calls.count(("create_bitmap",)), 1)
        surface.close()
        self.assertFalse(api.bitmaps)

    def test_close_is_idempotent_restores_original_and_prevents_new_allocations(self):
        api = FakeNativeApi()
        surface = LayeredSurface(_api=api)
        surface.present(12, Image.new("RGBA", (20, 20)), 0, 0)
        bitmap = api.selected
        surface.close()
        self.assertEqual(api.calls[-3:], [("select", api.stock_bitmap),
                                         ("delete_bitmap", bitmap), ("delete_dc",)])
        previous_calls = list(api.calls)
        surface.close()
        with self.assertRaisesRegex(RuntimeError, "closed"):
            surface.present(12, Image.new("RGBA", (20, 20)), 0, 0)
        self.assertEqual(api.calls, previous_calls)

    def test_empty_surface_close_and_empty_frame_do_not_allocate_native_resources(self):
        api = FakeNativeApi()
        surface = LayeredSurface(_api=api)
        with self.assertRaises(ValueError):
            surface.present(12, Image.new("RGBA", (0, 20)), 0, 0)
        surface.close()
        self.assertEqual(api.calls, [])


if __name__ == "__main__":
    unittest.main()
