import sys
from pathlib import Path

# Ensure acc_statements folder is in sys.path so intra-package modules resolve reliably
_pkg_dir = str(Path(__file__).resolve().parent)
if _pkg_dir not in sys.path:
    sys.path.insert(0, _pkg_dir)

try:
    from acc_statements.statement_parser import StatementParser
except ImportError:
    from statement_parser import StatementParser

def get_parser():
    return StatementParser()

__all__ = [
    "StatementParser",
    "get_parser",
]
