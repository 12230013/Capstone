"""
Module: acc_statements.statement_parser
Extracts structured metadata and clean content from ACC witness and suspect statements.
"""
import re
from pathlib import Path
from typing import Dict, Any, List

class StatementParser:
    def __init__(self):
        self.header_fields = [
            "name",
            "cid",
            "gender",
            "dob",
            "village",
            "gewog",
            "dzongkhang",
            "phone_number",
            "occupation"
        ]

    def parse_statement_file(self, file_path: str) -> Dict[str, Any]:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Statement file not found: {file_path}")

        text = path.read_text(encoding="utf-8")
        return self.parse_text(text, filename=path.name)

    def parse_text(self, text: str, filename: str = "statement.txt") -> Dict[str, Any]:
        metadata: Dict[str, Any] = {
            "filename": filename,
            "statement_id": Path(filename).stem,
            "name": "Unknown",
            "cid": "Unknown",
            "gender": "Unknown",
            "dob": "Unknown",
            "village": "Unknown",
            "gewog": "Unknown",
            "dzongkhang": "Unknown",
            "phone_number": "Unknown",
            "occupation": "Unknown"
        }

        body_lines: List[str] = []
        is_in_body = False

        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                if not is_in_body and body_lines:
                    is_in_body = True
                continue

            # Look for header metadata
            header_match = re.match(r"^(Name|CID|Gender|DOB|Village|Gewog|Dzongkhang|Phone\s*Number|Occupation)\s*:\s*(.*)$", stripped, re.IGNORECASE)
            if header_match and not is_in_body:
                field_name = header_match.group(1).lower().replace(" ", "_")
                field_val = header_match.group(2).strip()
                metadata[field_name] = field_val
            else:
                is_in_body = True
                body_lines.append(stripped)

        full_body = "\n\n".join(body_lines)

        return {
            "metadata": metadata,
            "statement_id": metadata["statement_id"],
            "person_name": metadata.get("name", "Unknown"),
            "cid": metadata.get("cid", "Unknown"),
            "phone_number": metadata.get("phone_number", "Unknown"),
            "occupation": metadata.get("occupation", "Unknown"),
            "text": text,
            "body": full_body
        }
