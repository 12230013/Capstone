"""Validate the review editor's JSON and derive authoritative searchable blocks."""
ALLOWED = {'doc','paragraph','heading','text','hardBreak','pageBreak','bulletList','orderedList','listItem','table','tableRow','tableCell','tableHeader','blockquote','horizontalRule','codeBlock'}


def editor_blocks(document):
    count = 0
    def validate(node, depth=0):
        nonlocal count
        count += 1
        if count > 20000 or depth > 30 or not isinstance(node, dict) or node.get('type') not in ALLOWED:
            raise ValueError('The review document contains invalid or excessive content.')
        if not isinstance(node.get('text',''),str) or len(node.get('text','')) > 1000000:
            raise ValueError('Invalid review text.')
        children = node.get('content',[])
        if not isinstance(children,list): raise ValueError('Invalid review content.')
        for child in children: validate(child,depth+1)
    validate(document)
    if document.get('type') != 'doc': raise ValueError('A review page must be a document.')
    def text(node):
        if node['type']=='text': return node.get('text','')
        if node['type']=='hardBreak': return '\n'
        separator = '\n' if node['type'] in {'tableCell','tableHeader','bulletList','orderedList','listItem','blockquote'} else ''
        return separator.join(text(n) for n in node.get('content',[]))
    blocks=[]
    for node in document.get('content',[]):
        if node['type'] == 'pageBreak':
            continue
        if node['type'] != 'table':
            blocks.append({'type':'text','text':text(node)});continue
        rows=[]
        spans={}
        cell_spans=[]
        for ri,row in enumerate(node.get('content',[])):
            if row['type']!='tableRow': raise ValueError('Invalid table row.')
            values=[];ci=0;row_spans=[]
            for cell in row.get('content',[]):
                if cell['type'] not in {'tableCell','tableHeader'}: raise ValueError('Invalid table cell.')
                while (ri,ci) in spans: values.append('');ci+=1
                attrs=cell.get('attrs') or {}
                colspan,rowspan=attrs.get('colspan',1),attrs.get('rowspan',1)
                if not all(type(v) is int and 1<=v<=100 for v in (colspan,rowspan)): raise ValueError('Invalid cell spans.')
                row_spans.append({"column":ci,"colspan":colspan,"rowspan":rowspan})
                values.extend([text(cell)]+['']*(colspan-1))
                for rr in range(ri+1,ri+rowspan):
                    for cc in range(ci,ci+colspan): spans[rr,cc]=True
                ci+=colspan
            rows.append(values)
            cell_spans.append(row_spans)
        width=max(map(len,rows),default=0)
        if not rows or not width or width>100 or len(rows)>1000: raise ValueError('Invalid table size.')
        rows=[r+['']*(width-len(r)) for r in rows]
        if (node.get('attrs') or {}).get('layoutKind')=='form' and width==2:
            blocks.append({'type':'form','fields':[{'label':r[0],'value':r[1]} for r in rows]})
        else: blocks.append({'type':'table','rows':rows,'cell_spans':cell_spans,'has_header':bool(node.get('content') and any(c['type']=='tableHeader' for c in node['content'][0].get('content',[])))})
    return blocks
