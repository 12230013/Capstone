import unittest
import fitz
from PIL import Image, ImageDraw
from app.ocr.layout import layout_from_words, ocr_blocks, pdf_blocks, blocks_text

class LayoutTests(unittest.TestCase):
    def test_aligned_headings_and_colon_labels_are_not_invented_tables(self):
        words=[(10,10,100,20,'STATEMENT'),(300,10,460,20,'Department of Investigation'),(300,40,460,50,'Anti-Corruption Commission'),(10,80,150,90,'Name: Karma')]
        blocks=layout_from_words(words)
        self.assertTrue(all(b['type']=='text' for b in blocks))
        self.assertIn('Name: Karma',blocks_text(blocks))

    def test_ruled_scan_preserves_empty_cells(self):
        image=Image.new('RGB',(500,250),'white'); draw=ImageDraw.Draw(image)
        for x in (20,220,470): draw.line((x,20,x,220),fill='black',width=2)
        for y in (20,80,150,220): draw.line((20,y,470,y),fill='black',width=2)
        boxes=[[[30,35],[100,35],[100,55],[30,55]],[[230,35],[320,35],[320,55],[230,55]],[[30,95],[100,95],[100,115],[30,115]],[[230,165],[320,165],[320,185],[230,185]]]
        blocks=ocr_blocks({'rec_polys':boxes,'rec_texts':['Item','Amount','Travel','200']}, image)
        self.assertEqual(blocks[0]['rows'],[['Item','Amount'],['Travel',''],['','200']])

    def test_digital_pdf_table_and_caption(self):
        doc=fitz.open(); page=doc.new_page(width=500,height=300)
        page.insert_text((20,20),'Expense report')
        for x in (20,220,470): page.draw_line((x,40),(x,180))
        for y in (40,100,180): page.draw_line((20,y),(470,y))
        for x,y,t in [(30,70,'Item'),(230,70,'Amount'),(30,130,'Travel'),(230,130,'500')]: page.insert_text((x,y),t)
        blocks=pdf_blocks(page)
        table=next(b for b in blocks if b['type']=='table')
        self.assertEqual(table['rows'],[['Item','Amount'],['Travel','500']])
        self.assertIn('Expense report',blocks_text(blocks));doc.close()

    def test_long_table_is_chunked_with_column_labels(self):
        from app.ocr.layout import structured_chunks
        blocks=[{'type':'table','rows':[['Name','Amount']]+[[f'Person {i}','500'] for i in range(100)]}]
        chunks=structured_chunks(blocks)
        self.assertTrue(all(len(c['text'])<=1200 for c in chunks))
        self.assertIn('Amount: 500',chunks[-1]['text'])

    def test_pdf_widget_values_are_editable_form_fields(self):
        doc=fitz.open(); page=doc.new_page()
        widget=fitz.Widget();widget.field_name='Applicant';widget.field_type=fitz.PDF_WIDGET_TYPE_TEXT
        widget.field_value='Karma';widget.rect=fitz.Rect(30,30,240,60);page.add_widget(widget)
        blocks=pdf_blocks(page)
        self.assertEqual(blocks[-1]['fields'][0],{'label':'Applicant','value':'Karma'});doc.close()

    def test_ocr_lines_become_one_paragraph_and_large_gaps_separate_paragraphs(self):
        words=[(10,10,200,25,'Hope is the light'),(10,30,200,45,'that guides you.'),(10,90,200,105,'Another paragraph.')]
        blocks=layout_from_words(words)
        self.assertEqual(len(blocks),1)
        self.assertEqual(blocks[0]['text'],'Hope is the light that guides you.\n\nAnother paragraph.')

    def test_borderless_numbered_paragraph_is_not_a_table(self):
        words=[(10,10,25,20,'1'),(100,10,500,20,'I started my business.'),(10,40,25,50,'2'),(100,40,500,50,'It operates in Haa.'),(10,70,25,80,'3')]
        self.assertTrue(all(b['type']=='text' for b in layout_from_words(words)))

    def test_shaded_wide_table_uses_real_borders_not_character_strokes(self):
        from app.ocr.table_geometry import ruled_cells
        image=Image.new('RGB',(1600,450),'white');draw=ImageDraw.Draw(image)
        xs=[50+i*105 for i in range(15)];ys=[70,105,140,175]
        draw.rectangle((50,70,xs[-1],105),fill='#888888')
        for x in xs:draw.line((x,70,x,175),fill='black',width=2)
        for y in ys:draw.line((50,y,xs[-1],y),fill='black',width=2)
        for i in range(14):
            for r in range(3):draw.text((xs[i]+6,ys[r]+8),'CREDIT 1000',fill='black')
        _,regions=ruled_cells(image)
        self.assertEqual(len(regions),1)
        self.assertEqual(len(regions[0]['xs'])-1,14)
        self.assertEqual(len(regions[0]['ys'])-1,3)

    def test_cell_reader_prevents_cross_boundary_text_from_moving_values(self):
        image=Image.new('RGB',(500,250),'white');draw=ImageDraw.Draw(image)
        for x in (20,220,470):draw.line((x,20,x,220),fill='black',width=2)
        for y in (20,80,150,220):draw.line((20,y,470,y),fill='black',width=2)
        for x,y,t in [(30,35,'Name'),(230,35,'Karma'),(30,95,'CID'),(230,95,'12345'),(30,165,'Town'),(230,165,'Haa')]:draw.text((x,y),t,fill='black')
        boxes=[[[30,35],[400,35],[400,55],[30,55]]]
        blocks=ocr_blocks({'rec_polys':boxes,'rec_texts':['Name Karma']},image,cell_reader=lambda crops:['Name','Karma','CID','12345','Town','Haa'])
        self.assertEqual(blocks[0]['rows'],[['Name','Karma'],['CID','12345'],['Town','Haa']])

    def test_native_pdf_wide_table_retains_columns_and_merged_cells(self):
        doc=fitz.open();page=doc.new_page(width=1600,height=400)
        xs=[50+i*105 for i in range(15)]
        for x in xs:page.draw_line((x,70),(x,175))
        for y in (70,105,140,175):page.draw_line((50,y),(xs[-1],y))
        for i in range(14):
            for r in range(3):page.insert_text((xs[i]+5,90+35*r),f'C{i}R{r}',fontsize=9)
        tables=[b for b in pdf_blocks(page) if b['type']=='table']
        self.assertEqual(len(tables),1)
        self.assertEqual(len(tables[0]['rows'][0]),14)
        self.assertEqual(tables[0]['rows'][2][13],'C13R2')
        self.assertEqual(len(tables[0]['column_widths']),14)
        doc.close()

    def test_empty_cell_reread_does_not_erase_a_contained_page_reading(self):
        image=Image.new('RGB',(500,250),'white');draw=ImageDraw.Draw(image)
        for x in (20,220,470):draw.line((x,20,x,220),fill='black',width=2)
        for y in (20,80,150,220):draw.line((20,y,470,y),fill='black',width=2)
        draw.text((230,95),'10502000470',fill='black')
        output={'rec_polys':[[[230,95],[340,95],[340,115],[230,115]]],'rec_texts':['10502000470'],'rec_scores':[.95]}
        blocks=ocr_blocks(output,image,cell_reader=lambda crops:[{'text':'','confidence':None} for _ in crops])
        table=next(b for b in blocks if b['type']=='table')
        self.assertEqual(table['rows'][1][1],'10502000470')

    def test_handwritten_strokes_inside_lined_statement_do_not_become_columns(self):
        from app.ocr.table_geometry import ruled_cells
        image=Image.new('RGB',(1000,900),'white');draw=ImageDraw.Draw(image)
        for x in(40,130,960):draw.line((x,40,x,840),fill='black',width=2)
        for y in range(40,841,50):draw.line((40,y,960,y),fill='black',width=2)
        for row in range(16):
            y=50+row*50
            for x in range(160+(row%3)*5,900,45):draw.line((x,y,x,y+30),fill='black',width=2)
        _,regions=ruled_cells(image)
        self.assertEqual(len(regions),1)
        self.assertEqual(len(regions[0]['xs'])-1,2)

    def test_ruled_statement_is_paragraphs_without_line_number_margin(self):
        rows=[['Line No.','STATEMENT'],['1','I started my business in Haa.'],['2','It has operated since 2005.'],['3',''],['4','My family also owns a hotel.'],['5','This is a second paragraph.']]
        blocks=layout_from_words([], [((0,0,900,600),rows,{'column_widths':[70,830]})])
        self.assertEqual([b['type'] for b in blocks],['text'])
        self.assertEqual(blocks[0]['text'],'I started my business in Haa. It has operated since 2005.\n\nMy family also owns a hotel. This is a second paragraph.')

    def test_ruled_statement_continuation_is_prose_but_real_two_column_table_stays(self):
        rows=[[str(i),f'This sentence continues the statement on line {i}.'] for i in range(12,20)]
        blocks=layout_from_words([], [((0,0,900,600),rows,{'column_widths':[70,830]})])
        self.assertEqual(blocks[0]['type'],'text')
        self.assertNotIn('12 |',blocks_text(blocks))
        real=[['Item','Description']]+[[str(i),'A detailed product description with several words.'] for i in range(1,8)]
        self.assertEqual(layout_from_words([], [((0,0,900,600),real,{'column_widths':[70,830]})])[0]['type'],'table')

    def test_statement_body_fragments_are_joined_even_with_spurious_internal_columns(self):
        rows=[['Line No.','STATEMENT','',''],['1','A business','operates in','Haa.'],['2','The owner','began trading','in 2005.'],['3','This is','the same','statement.']]
        blocks=layout_from_words([], [((0,0,900,400),rows,{'column_widths':[70,100,300,430]})])
        self.assertEqual(blocks[0]['type'],'text')
        self.assertIn('A business operates in Haa. The owner began trading in 2005.',blocks[0]['text'])

    def test_grouped_gutter_numbers_do_not_turn_continuation_into_table(self):
        rows=[['12 13 14','The business started in 2005 and was previously in another name.'],['15','It began in the year'],['16','2023 in the name of my wife.'],['17',''],['18','The main source of timber was'],['19 20','a private registered supplier.'],['21','']]
        blocks=layout_from_words([], [((0,0,852,600),rows,{'column_widths':[80,772]})])
        self.assertEqual(blocks[0]['type'],'text')
        self.assertEqual(blocks[0]['text'],'The business started in 2005 and was previously in another name. It began in the year 2023 in the name of my wife.\n\nThe main source of timber was a private registered supplier.')

    def test_missing_and_one_incorrect_gutter_number_keep_numbered_prose(self):
        rows=[['31.','The witness explained the circumstances.'],['32','This sentence continues across ruled lines.'],['','The number here was not recognized.'],['88','This margin number was read incorrectly.'],['34','The account continues on this line.'],['35','The witness confirmed the account.'],['36','This is the final sentence.']]
        self.assertEqual(layout_from_words([], [((0,0,900,600),rows,{'column_widths':[60,840]})])[0]['type'],'text')

    def test_real_serial_number_table_with_multiple_data_columns_is_preserved(self):
        rows=[['No.','Item','Quantity','Amount'],['1','Timber','20','500'],['2','Boards','10','300'],['3','Nails','30','100']]
        self.assertEqual(layout_from_words([], [((0,0,900,400),rows,{'column_widths':[60,400,200,240]})])[0]['type'],'table')

    def test_short_statement_region_with_grouped_numbers_is_still_prose(self):
        for rows in ([['Line No.','STATEMENT'],['1','This short statement must remain prose.']], [['12 13','This sentence spans two ruled lines.'],['14','It continues on the next line.']]):
            self.assertEqual(layout_from_words([], [((0,0,900,200),rows,{'column_widths':[70,830]})])[0]['type'],'text')
