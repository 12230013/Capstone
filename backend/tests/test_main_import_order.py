import ast
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = BACKEND_ROOT / "app" / "main.py"


class MainImportOrderTests(unittest.TestCase):
    def test_ocr_configuration_initializes_before_ocr_router_import(self):
        main_tree = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))
        statements = main_tree.body

        config_import_index = next(
            index
            for index, statement in enumerate(statements)
            if isinstance(statement, ast.ImportFrom)
            and statement.module == "app.ocr"
            and any(
                alias.name == "config" and alias.asname == "ocr_config"
                for alias in statement.names
            )
        )
        initialization_index = next(
            index
            for index, statement in enumerate(statements)
            if isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Call)
            and isinstance(statement.value.func, ast.Attribute)
            and isinstance(statement.value.func.value, ast.Name)
            and statement.value.func.value.id == "ocr_config"
            and statement.value.func.attr == "initialize_config"
        )
        ocr_router_import_index = next(
            index
            for index, statement in enumerate(statements)
            if isinstance(statement, ast.ImportFrom)
            and statement.module == "app.api.routes.ocr_documents"
        )

        self.assertLess(config_import_index, initialization_index)
        self.assertLess(
            initialization_index,
            ocr_router_import_index,
            "OCR configuration must initialize before the OCR router import.",
        )


if __name__ == "__main__":
    unittest.main()
