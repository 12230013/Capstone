import os
import subprocess
import sys
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]


class OCRConfigTests(unittest.TestCase):
    def run_config_script(self, script: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(BACKEND_ROOT)
        return subprocess.run(
            [sys.executable, "-c", script],
            cwd=BACKEND_ROOT,
            env=environment,
            capture_output=True,
            check=True,
            text=True,
        )

    def test_import_does_not_load_dotenv(self):
        completed = self.run_config_script(
            "import dotenv; "
            "from unittest.mock import Mock; "
            "dotenv.load_dotenv = Mock(); "
            "import app.ocr.config; "
            "assert dotenv.load_dotenv.call_count == 0"
        )
        self.assertEqual(completed.stdout, "")

    def test_explicit_initialization_loads_backend_env_path(self):
        completed = self.run_config_script(
            "import dotenv; "
            "from unittest.mock import Mock; "
            "dotenv.load_dotenv = Mock(); "
            "import app.ocr.config as config; "
            "config.initialize_config(); "
            "dotenv.load_dotenv.assert_called_once_with(config.BACKEND_ROOT / '.env')"
        )
        self.assertEqual(completed.stdout, "")

    def test_repeated_initialization_refreshes_settings_before_consumers_import(self):
        completed = self.run_config_script(
            "import os; "
            "import app.ocr.config as config; "
            "os.environ['OCR_RENDER_DPI'] = '317'; "
            "os.environ['PDF_DETECTION_MIN_PAGE_CHARS'] = '53'; "
            "config.initialize_config(); "
            "assert config.OCR_RENDER_DPI == 317; "
            "config.initialize_config(); "
            "os.environ['OCR_RENDER_DPI'] = '411'; "
            "config.initialize_config(); "
            "from app.ocr.document_detection import DetectionThresholds; "
            "assert config.OCR_RENDER_DPI == 317; "
            "assert DetectionThresholds().min_meaningful_chars_per_page == 53"
        )
        self.assertEqual(completed.stdout, "")


if __name__ == "__main__":
    unittest.main()
