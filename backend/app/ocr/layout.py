"""Editable layout blocks built from PDF tables and OCR word geometry.

Detection is deliberately conservative; uncertain regions remain editable text.
"""
import re
from statistics import median

LAYOUT_VERSION = 6


def blocks_text(blocks):
    sections = []
    for block in blocks:
        if block['type'] == 'text':
            sections.append(block.get('text', ''))
        elif block['type'] == 'form':
            sections.append('\n'.join(f"{f['label']}: {f['value']}" for f in block['fields']))
        else:
            rows = block['rows']
            # Repeat column names on data rows so retrieval retains cell meaning.
            if rows and block.get('has_header') is False:
                sections.extend(' | '.join(row) for row in rows)
            elif rows:
                sections.append(' | '.join(rows[0]))
                for row in rows[1:]:
                    sections.append(' | '.join(f"{rows[0][i] or f'Column {i+1}'}: {v}" for i, v in enumerate(row)))
    return '\n\n'.join(s for s in sections if s.strip())


def _rows(words):
    groups = []
    for word in sorted(words, key=lambda w: ((w[1]+w[3])/2, w[0])):
        cy = (word[1]+word[3])/2
        group = next((g for g in reversed(groups[-3:]) if abs(g[0]-cy) <= max(3, (word[3]-word[1])*.55)), None)
        if group is None:
            groups.append([cy, [word]])
        else:
            group[1].append(word)
    return [sorted(g[1], key=lambda w:w[0]) for g in groups]


def _has_header(rows):
    names = {'item','amount','date','name','description','credit','debit','balance','sl no','sl.no','tran date','time stamp','statement','line no','account no','narration','tran desc'}
    return bool(rows) and sum(re.sub(r'[_\s]+',' ',cell.strip().lower()).rstrip('.') in names for cell in rows[0]) >= 2


def _statement_paragraphs(rows, metadata):
    """A narrow sequential line-number margin is stationery, not a data column."""
    if not rows or max(map(len,rows),default=0)<2 or len(rows)<2:return None
    first=re.sub(r'[^a-z]','',rows[0][0].lower())
    header=first in {'lineno','linenumber','line','no'} and 'statement' in ' '.join(rows[0][1:]).lower()
    def margin_numbers(value):
        # OCR can combine several ruled rows into one cell. Accept a group of
        # gutter numbers, but never consume words or amounts as line numbers.
        value = value.strip()
        if not value:
            return []
        if not re.fullmatch(r"\d{1,3}(?:[\s.,:;()\-]+\d{1,3})*[.)]?", value):
            return None
        return [int(n) for n in re.findall(r"\d+", value)]

    if not header and margin_numbers(rows[0][0]) is None:
        return None
    body=rows[1:] if header else rows
    parsed = [margin_numbers(r[0]) for r in body]
    numbers = [n for group in parsed if group for n in group]
    widths=metadata.get('column_widths') or []
    narrow=len(widths)>=2 and widths[0]/max(1,sum(widths))<.2
    # Ignore an isolated OCR outlier when its neighbours still form the gutter
    # sequence (e.g. 31, 32, 88, 34, 35).
    sequence = []
    for i, number in enumerate(numbers):
        if (sequence and i + 1 < len(numbers)
                and not 0 < number - sequence[-1] <= 5
                and 0 < numbers[i + 1] - sequence[-1] <= 5):
            continue
        sequence.append(number)
    steps = [b - a for a, b in zip(sequence, sequence[1:])]
    # A few missed/misread numbers must not turn the remainder of a statement
    # into a table. Require strong sequential evidence across the gutter.
    sequential = len(sequence) >= 3 and sum(0 < step <= 5 for step in steps) >= max(2, len(steps) * .7)
    margin_like = sum(group is not None for group in parsed) >= len(parsed) * .75
    prose=[' '.join(r[1:]).strip() for r in body if ' '.join(r[1:]).strip()]
    if not header and not (narrow and sequential and margin_like and prose and sum(len(v.split()) for v in prose)/len(prose)>=3):return None
    paragraphs=[];pending=[]
    if header:
        remainder=re.sub(r'\bSTATEMENT\b','',' '.join(rows[0][1:]),flags=re.IGNORECASE).strip()
        if remainder:pending.append(remainder)
    for row in body:
        value=' '.join(row[1:]).strip()
        if value:pending.append(re.sub(r'\s+',' ',value))
        elif pending:paragraphs.append(' '.join(pending));pending=[]
    if pending:paragraphs.append(' '.join(pending))
    return '\n\n'.join(paragraphs) or None


def layout_from_words(words, tables=()):
    """Use verified cell grids only; aligned prose and labels remain text."""
    remaining = list(words)
    positioned = []
    for entry in tables:
        bbox, rows = entry[:2]
        if not rows or max(map(len,rows),default=0)<2:continue
        width=max(map(len,rows))
        rows=[[str(v or '') for v in row]+['']*(width-len(row)) for row in rows]
        metadata=entry[2] if len(entry)>2 else {}
        narrative=_statement_paragraphs(rows,metadata)
        block={'type':'text','text':narrative,'source_layout':'numbered_statement'} if narrative is not None else {'type':'table','rows':rows,'has_header':_has_header(rows),**metadata}
        positioned.append((bbox[1],block))
        remaining=[w for w in remaining if not (bbox[0]<=(w[0]+w[2])/2<=bbox[2] and bbox[1]<=(w[1]+w[3])/2<=bbox[3])]
    line_height=median(max(1,w[3]-w[1]) for w in remaining) if remaining else 12
    for row in _rows(remaining):
        positioned.append((min(w[1] for w in row),{'type':'text','text':' '.join(w[4] for w in row)}))
    merged=[]
    for y,block in sorted(positioned,key=lambda item:item[0]):
        if block['type']=='text' and merged and merged[-1][1]['type']=='text':
            previous_y,previous=merged[-1]
            previous['text']+=('\n\n' if y-previous_y>line_height*2.2 else ' ')+block['text']
            merged[-1]=(y,previous)
        else:merged.append((y,block))
    return [b for _,b in merged]


def pdf_blocks(page):
    """Native PDF vector rules and text: no OCR or whitespace table guessing."""
    tables=[]
    try:
        for table in page.find_tables(strategy='lines_strict').tables:
            rows=table.extract()
            xs=sorted(set(round(c[i],1) for c in table.cells if c for i in (0,2)))
            ys=sorted(set(round(c[i],1) for c in table.cells if c for i in (1,3)))
            spans=[[] for _ in rows]
            for cell in table.cells:
                if not cell:continue
                c0,c1=[min(range(len(xs)),key=lambda i:abs(xs[i]-x)) for x in (cell[0],cell[2])]
                r0,r1=[min(range(len(ys)),key=lambda i:abs(ys[i]-y)) for y in (cell[1],cell[3])]
                if r0<len(spans):spans[r0].append({'column':c0,'colspan':c1-c0,'rowspan':r1-r0})
            metadata={'column_widths':[b-a for a,b in zip(xs,xs[1:])],'cell_spans':spans}
            tables.append((table.bbox,rows,metadata))
    except (AttributeError,ValueError,RuntimeError):pass
    words=[tuple(w[:5]) for w in page.get_text('words',sort=True)]
    widgets=list(page.widgets() or [])
    for widget in widgets:
        rect=widget.rect
        words=[w for w in words if not (rect.x0<=(w[0]+w[2])/2<=rect.x1 and rect.y0<=(w[1]+w[3])/2<=rect.y1)]
    blocks=layout_from_words(words,tables)
    if widgets:blocks.append({'type':'form','fields':[{'label':str(w.field_label or w.field_name or 'Field'),'value':str(w.field_value or '')} for w in widgets]})
    return blocks


def ocr_blocks(output, image, regions=None, cell_reader=None):
    """Assign text to physical cells, re-reading cropped cells when available."""
    polygons=output.get('rec_polys')
    if polygons is None:polygons=output.get('dt_polys')
    texts=output.get('rec_texts',[])
    if polygons is None or len(polygons)!=len(texts):return []
    words=[]
    scores=output.get("rec_scores",[])
    word_scores={}
    for wi,(polygon,text) in enumerate(zip(polygons,texts)):
        if text.strip():
            xs,ys=[float(p[0]) for p in polygon],[float(p[1]) for p in polygon]
            word=(min(xs),min(ys),max(xs),max(ys),text)
            words.append(word)
            word_scores[word]=float(scores[wi])*100 if wi<len(scores) else 0
    own_aligned = None
    if regions is None:
        from app.ocr.table_geometry import ruled_cells
        aligned,regions=ruled_cells(image)
        if aligned is not image:
            import numpy as np
            matrix=np.asarray(aligned.info['ocr_layout_transform'])
            transformed=[]
            transformed_scores={}
            for x0,y0,x1,y1,value in words:
                points=np.asarray([[x0,y0,1],[x1,y0,1],[x1,y1,1],[x0,y1,1]]) @ matrix.T
                updated=(float(points[:,0].min()),float(points[:,1].min()),float(points[:,0].max()),float(points[:,1].max()),value)
                transformed.append(updated)
                transformed_scores[updated]=word_scores[(x0,y0,x1,y1,value)]
            words=transformed;word_scores=transformed_scores;image=aligned;own_aligned=aligned
    import numpy as np
    tables=[]
    for region in regions:
        rows=[['']*(len(region['xs'])-1) for _ in range(len(region['ys'])-1)]
        cells=region['cells']
        assigned=[[] for _ in cells]
        for word in words:
            overlaps=[]
            for cell in cells:
                x0,y0,x1,y1=cell['bbox']
                overlaps.append(max(0,min(x1,word[2])-max(x0,word[0]))*max(0,min(y1,word[3])-max(y0,word[1])))
            best=max(range(len(cells)),key=lambda i:overlaps[i])
            area=max(1,(word[2]-word[0])*(word[3]-word[1]))
            if overlaps[best]/area>=.5:assigned[best].append(word)
        values=[' '.join(' '.join(w[4] for w in line) for line in _rows(ws)) for ws in assigned]
        if cell_reader:
            crops=[];indices=[]
            for i,cell in enumerate(cells):
                x0,y0,x1,y1=map(round,cell['bbox'])
                crop=image.crop((x0+3,y0+3,max(x0+4,x1-3),max(y0+4,y1-3))).convert('RGB')
                gray=np.asarray(crop.convert('L'))
                # Skip genuinely blank cells, not cells the page detector missed.
                if gray.size and (gray<min(200,float(np.median(gray))-20)).mean()>.001:
                    if crop.height<60:crop=crop.resize((crop.width*2,crop.height*2))
                    crops.append(crop);indices.append(i)
                else:crop.close()
            if crops:
                try:
                    readings=cell_reader(crops)
                    if len(readings)!=len(crops):raise ValueError('Cell OCR returned an unexpected result count.')
                    for i,reading in zip(indices,readings):
                        value=reading.get('text','') if isinstance(reading,dict) else reading
                        confidence=reading.get('confidence') if isinstance(reading,dict) else None
                        x0,y0,x1,y1=cells[i]['bbox']
                        contained=bool(assigned[i]) and all(w[0]>=x0-5 and w[1]>=y0-5 and w[2]<=x1+5 and w[3]<=y1+5 for w in assigned[i])
                        primary_confidence=sum(word_scores.get(w,0) for w in assigned[i])/max(1,len(assigned[i]))
                        prefer_primary=contained and values[i] and (
                            not value.strip() or
                            (confidence is not None and primary_confidence>confidence+5) or
                            (primary_confidence>=70 and len(value.replace(' ',''))<len(values[i].replace(' ',''))*.65)
                        )
                        if not prefer_primary:values[i]=value
                finally:
                    for crop in crops:crop.close()
        spans=[[] for _ in rows]
        for cell,value in zip(cells,values):
            r,c=cell['row'],cell['column'];rows[r][c]=value
            spans[r].append({'column':c,'colspan':cell['colspan'],'rowspan':cell['rowspan']})
        tables.append((region['bbox'],rows,{'cell_spans':spans,'column_widths':[b-a for a,b in zip(region['xs'],region['xs'][1:])]}))
    blocks=layout_from_words(words,tables)
    if own_aligned is not None:own_aligned.close()
    return blocks


def structured_chunks(blocks, size=1200):
    """Keep each table row with its labels; bound oversized text for embedding."""
    pieces = []
    for block in blocks:
        text = blocks_text([block])
        # Newlines carry row/field boundaries, including repeated column labels.
        for line in text.splitlines():
            for start in range(0, len(line), size):
                pieces.append(line[start:start+size])
    chunks = []
    current = ""
    for piece in pieces:
        if current and len(current)+len(piece)+1 > size:
            chunks.append(current); current = ""
        current = (current+"\n"+piece).strip()
    if current: chunks.append(current)
    return [{"chunk_id":i+1,"text":text} for i,text in enumerate(chunks)]
