"""Translate VL HTML tables into the existing safe, editable review blocks."""
from html.parser import HTMLParser
from app.ocr.layout import _has_header, _statement_paragraphs


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.row = None
        self.cell = None
        self.has_header = False

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            if len(self.rows) >= 1000: raise ValueError('VL table has too many rows.')
            self.row = []
        elif tag in {'td', 'th'} and self.row is not None:
            attrs = dict(attrs)
            colspan, rowspan = int(attrs.get('colspan', 1)), int(attrs.get('rowspan', 1))
            if not 1 <= colspan <= 100 or not 1 <= rowspan <= 100: raise ValueError('Invalid VL cell span.')
            self.cell = {'parts': [], 'colspan': colspan, 'rowspan': rowspan}
            if not self.rows and tag == 'th': self.has_header = True
        elif tag in {'br', 'p'} and self.cell is not None:
            self.cell['parts'].append('\n')

    def handle_data(self, data):
        if self.cell is not None: self.cell['parts'].append(data)

    def handle_endtag(self, tag):
        if tag in {'td', 'th'} and self.cell is not None:
            self.cell['text'] = ' '.join(''.join(self.cell.pop('parts')).split())
            self.row.append(self.cell)
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def table_block(html, metadata=None):
    parser = _TableParser()
    parser.feed(html)
    rows, spans, occupied = [], [], set()
    for ri, cells in enumerate(parser.rows):
        row, row_spans, ci = [], [], 0
        for cell in cells:
            while (ri, ci) in occupied:
                row.append(''); ci += 1
            cs, rs = cell['colspan'], cell['rowspan']
            if ci + cs > 100: raise ValueError('VL table has too many columns.')
            row.extend([cell['text']] + [''] * (cs - 1))
            row_spans.append({'column': ci, 'colspan': cs, 'rowspan': rs})
            for rr in range(ri + 1, ri + rs):
                for cc in range(ci, ci + cs): occupied.add((rr, cc))
            ci += cs
        while (ri, ci) in occupied:
            row.append(''); ci += 1
        rows.append(row); spans.append(row_spans)
    width = max(map(len, rows), default=0)
    if not rows or not width: raise ValueError('VL table contains no cells.')
    rows = [r + [''] * (width-len(r)) for r in rows]
    metadata = metadata or {}
    narrative = _statement_paragraphs(rows, metadata)
    if narrative is not None:
        return {'type': 'text', 'text': narrative, 'source_layout': 'numbered_statement'}
    return {'type': 'table', 'rows': rows, 'cell_spans': spans,
            'has_header': parser.has_header or _has_header(rows), **metadata}


def physical_metadata(bbox, regions):
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4: return {}
    def overlap(region):
        a, b, c, d = region['bbox']
        intersection = max(0, min(c, bbox[2])-max(a, bbox[0])) * max(0, min(d, bbox[3])-max(b, bbox[1]))
        return intersection / max(1, (c-a)*(d-b))
    region = max(regions, key=overlap, default=None)
    if region is None or overlap(region) < .5: return {}
    return {'column_widths': [b-a for a,b in zip(region['xs'], region['xs'][1:])]}
