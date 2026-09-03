from __future__ import annotations

import unittest

from presentation.widgets import centered_window_position


class PopupGeometryTests(unittest.TestCase):
    def test_centers_on_owner_in_screen_coordinates(self):
        self.assertEqual(
            centered_window_position(
                400,
                200,
                owner_bounds=(300, 240, 800, 600),
                screen_width=1920,
                screen_height=1080,
            ),
            (500, 440),
        )

    def test_clamps_centered_popup_inside_screen_margin(self):
        self.assertEqual(
            centered_window_position(
                800,
                700,
                owner_bounds=(0, 0, 300, 200),
                screen_width=1024,
                screen_height=768,
                margin=8,
            ),
            (8, 8),
        )

    def test_centers_without_owner(self):
        self.assertEqual(
            centered_window_position(
                300,
                180,
                owner_bounds=None,
                screen_width=1280,
                screen_height=720,
            ),
            (490, 270),
        )


if __name__ == "__main__":
    unittest.main()
