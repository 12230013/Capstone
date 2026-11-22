import unittest
from app.ocr.editor_document import editor_blocks
from app.ocr.layout import blocks_text

def paragraph(text): return {'type':'paragraph','content':[{'type':'text','text':text}]}
def cell(text,**attrs): return {'type':'tableCell','attrs':attrs,'content':[paragraph(text)]}

class EditorDocumentTests(unittest.TestCase):
    def test_mixed_document_serializes_text_table_and_form(self):
        document={'type':'doc','content':[paragraph('Reviewed paragraph.'),{'type':'table','content':[{'type':'tableRow','content':[cell('Item'),cell('Amount')]},{'type':'tableRow','content':[cell('Travel'),cell('850')]}]},{'type':'table','attrs':{'layoutKind':'form'},'content':[{'type':'tableRow','content':[cell('Name'),cell('Karma')]}]}]}
        blocks=editor_blocks(document)
        self.assertEqual([b['type'] for b in blocks],['text','table','form'])
        self.assertIn('Travel | 850',blocks_text(blocks))
        self.assertIn('Name: Karma',blocks_text(blocks))

    def test_merged_cells_preserve_rectangular_storage(self):
        doc={'type':'doc','content':[{'type':'table','content':[{'type':'tableRow','content':[cell('Header',colspan=2)]},{'type':'tableRow','content':[cell('A'),cell('B')]}]}]}
        self.assertEqual(editor_blocks(doc)[0]['rows'],[['Header',''],['A','B']])

    def test_rejects_unrecognized_nodes_and_excessive_nesting(self):
        with self.assertRaises(ValueError):editor_blocks({'type':'doc','content':[{'type':'script','text':'bad'}]})
        nested=paragraph('x')
        for _ in range(35):nested={'type':'blockquote','content':[nested]}
        with self.assertRaises(ValueError):editor_blocks({'type':'doc','content':[nested]})
