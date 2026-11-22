import unittest
from unittest.mock import Mock, patch
from PIL import Image, ImageDraw
from app.ocr import document_ocr

class PaddlePreprocessingTests(unittest.TestCase):
    def test_cleanup_does_not_replace_original_table_geometry(self):
        source=Image.new('RGB',(1600,450),'white');draw=ImageDraw.Draw(source)
        for x in [50+i*105 for i in range(15)]: draw.line((x,70,x,175),fill='black',width=2)
        for y in (70,105,140,175): draw.line((50,y,1520,y),fill='black',width=2)
        filtered=Image.new('RGB',source.size,'white')
        engine=Mock();engine.predict.return_value=[{'rec_texts':['Test'], 'rec_scores':[.9]}]
        with patch.object(document_ocr,'PADDLEOCR_PREPROCESSING_ENABLED',True), patch.object(document_ocr,'preprocess_image',return_value=(filtered,{'enabled':True})) as cleanup, patch.object(document_ocr,'ocr_blocks',return_value=[]) as blocks:
            _,confidence,_,metadata=document_ocr._preprocess_and_classic_paddle_page(source,engine,1,'test')
        regions=blocks.call_args.kwargs['regions']
        self.assertEqual(len(regions),1)
        self.assertEqual(len(regions[0]['xs'])-1,14)
        self.assertEqual(len(regions[0]['ys'])-1,3)
        self.assertFalse(cleanup.call_args.kwargs['allow_deskew'])
        self.assertEqual(metadata['table_geometry_source'],'original_image')
        self.assertEqual(confidence,90)
        self.assertEqual(source.getpixel((50,70)),(0,0,0))
        source.close()

    def test_cleanup_failure_falls_back_to_original(self):
        source=Image.new('RGB',(300,100),'white')
        engine=Mock();engine.predict.return_value=[{'rec_texts':['Test'], 'rec_scores':[.9]}]
        with patch.object(document_ocr,'PADDLEOCR_PREPROCESSING_ENABLED',True), patch.object(document_ocr,'preprocess_image',side_effect=document_ocr.ImagePreprocessingError('failed')), patch.object(document_ocr,'ocr_blocks',return_value=[]):
            _,_,_,metadata=document_ocr._preprocess_and_classic_paddle_page(source,engine,1,'test')
        self.assertEqual(metadata['selection'],'original_rgb_fallback')
        source.close()
