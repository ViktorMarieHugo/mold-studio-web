from __future__ import annotations

from pathlib import Path
import unittest

from streamlit.testing.v1 import AppTest


APP_FILE = Path(__file__).resolve().parents[1] / "3D_mold_studio.py"


class StreamlitAppTests(unittest.TestCase):
    def test_initial_screen_renders_without_exception(self) -> None:
        app = AppTest.from_file(str(APP_FILE), default_timeout=10).run()

        self.assertFalse(app.exception)
        self.assertEqual(app.title[0].value, "Irivek3Dstudio")
        self.assertEqual(len(app.file_uploader), 1)
        self.assertEqual(len(app.slider), 2)
        self.assertEqual(len(app.segmented_control), 0)
        self.assertEqual(len(app.button), 1)

        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertEqual(
            app.error[0].value,
            "Сначала загрузите мастер-модель STL или 3MF.",
        )


if __name__ == "__main__":
    unittest.main()
