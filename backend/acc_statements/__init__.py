from .statement_parser import StatementParser

def get_parser():
    return StatementParser()

__all__ = [
    "StatementParser",
    "get_parser",
]
