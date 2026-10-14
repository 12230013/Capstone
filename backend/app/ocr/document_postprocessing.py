"""Unified text post-processing module for RAG pipeline ingestion."""

import re
from html.parser import HTMLParser


class HTMLTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = []
        self.current_table = []
        self.current_row = []
        self.current_cell = []
        self.in_table = False
        self.in_row = False
        self.in_cell = False

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self.in_table = True
            self.current_table = []
        elif tag == 'tr' and self.in_table:
            self.in_row = True
            self.current_row = []
        elif tag in ('td', 'th') and self.in_row:
            self.in_cell = True
            self.current_cell = []

    def handle_endtag(self, tag):
        if tag == 'table':
            self.in_table = False
            if self.current_table:
                self.tables.append(self.current_table)
        elif tag == 'tr' and self.in_table:
            self.in_row = False
            if self.current_row:
                self.current_table.append(self.current_row)
        elif tag in ('td', 'th') and self.in_row:
            self.in_cell = False
            cell_text = "".join(self.current_cell).strip()
            self.current_row.append(cell_text)

    def handle_data(self, data):
        if self.in_cell:
            self.current_cell.append(data)


def clean_text_for_rag(text: str) -> str:
    """
    Cleans and normalizes text from either PyMuPDF or PaddleOCR-VL 
    to optimize it for vector embeddings and RAG retrieval.
    """
    if not text:
        return ""

    # 1. Handle HTML tables if present (common from VLM OCR output)
    if "<table" in text:
        text = re.sub(r'<div[^>]*>.*?<img[^>]*>.*?</div>', '', text, flags=re.DOTALL)
        text = re.sub(r'<img[^>]*>', '', text)

        parser = HTMLTableParser()
        parser.feed(text)

        parts = re.split(r'<table.*?>.*?</table>', text, flags=re.DOTALL)
        rendered_blocks = []

        for table in parser.tables:
            if not table or len(table) < 2:
                continue
            headers = table[0]
            rows = table[1:]
            for row in rows:
                pairs = [f"{h}: {val}" for h, val in zip(headers, row) if val and val != "0.00"]
                if pairs:
                    rendered_blocks.append(" | ".join(pairs))

        text = parts[0].strip() if parts else ""
        if rendered_blocks:
            text += "\n\n" + "\n".join(rendered_blocks)

    # 2. General cleanup for PyMuPDF & plain text artifacts
    # Strip remaining HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    
    # Fix hyphenated words broken across line wraps (e.g., "docu-\nment" -> "document")
    text = re.sub(r'(\w+)-\s*\n\s*(\w+)', r'\1\2', text)
    
    # Collapse multiple consecutive spaces/tabs
    text = re.sub(r'[ \t]+', ' ', text)
    
    # Normalize excessive newlines
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()