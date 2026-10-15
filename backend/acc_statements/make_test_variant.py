import re
import sys
from pathlib import Path

import config

# usage: python make_test_variant.py stmt_01 "12 March 2024" "14 March 2024"
src, find, replace = sys.argv[1], sys.argv[2], sys.argv[3]
text = (config.DATA_DIR / f"{src}.txt").read_text(encoding="utf-8")
if find not in text:
    sys.exit(f"'{find}' not found in {src}.txt")
text = text.replace(find, replace)
text = re.sub(r"(?im)^(Name:).*$", r"\1 TEST WITNESS (SYNTHETIC)", text)
text = re.sub(r"(?im)^(CID No\.?:).*$", r"\1 00000000000", text)
out = config.DATA_DIR / f"{src}_variant.txt"
out.write_text(text, encoding="utf-8")
print("written", out, "(synthetic test data, delete before any real use)")