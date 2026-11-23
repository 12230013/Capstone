import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from app.ocr import paddle_ocr, document_ocr
from app.ocr.vl_layout import table_block

class VLAdapterTests(unittest.TestCase):
    def setUp(self):
        paddle_ocr.PaddleOCRVLEngine._models.clear()

    def test_actual_vl_class_version_and_one_time_initialization(self):
        constructor=Mock(return_value=Mock())
        with patch.object(paddle_ocr.importlib,'import_module',return_value=SimpleNamespace(PaddleOCRVL=constructor)):
            first=paddle_ocr.PaddleOCRVLEngine(device='cpu');first.initialize()
            second=paddle_ocr.PaddleOCRVLEngine(device='cpu');second.initialize()
        constructor.assert_called_once()
        self.assertEqual(constructor.call_args.kwargs['pipeline_version'],'v1.6')
        self.assertTrue(constructor.call_args.kwargs['use_ocr_for_image_block'])
        self.assertIs(first._engine,second._engine)

    def test_factory_really_initializes_pipeline(self):
        engine=Mock()
        with patch.object(document_ocr,'create_paddle_engine',return_value=engine):
            self.assertIs(document_ocr._create_paddle_engine(),engine)
        engine.initialize.assert_called_once()

    def test_generator_json_output_keeps_reading_order_and_editable_table(self):
        engine=paddle_ocr.PaddleOCRVLEngine()
        engine._engine=Mock()
        engine._engine.predict.return_value=iter([SimpleNamespace(json={'res':{'parsing_res_list':[
            {'block_label':'text','block_content':'A paragraph before the table.'},
            {'block_label':'table','block_content':'<table><tr><th>Item</th><th>Amount</th></tr><tr><td>Travel</td><td>750</td></tr></table>'},
            {'block_label':'text','block_content':'A paragraph after the table.'},
        ]}})])
        result=engine.predict_page('image.png',3)
        self.assertEqual([b['type'] for b in result['blocks']],['text','table','text'])
        self.assertEqual(result['blocks'][1]['rows'][1],['Travel','750'])
        self.assertIn('Amount: 750',result['text'])
        self.assertEqual(result['page_number'],3)

    def test_table_spans_are_preserved_as_plain_editor_cells(self):
        block=table_block('<table><tr><th colspan="2">Costs</th></tr><tr><td rowspan="2">Travel</td><td>750</td></tr><tr><td>250</td></tr></table>')
        self.assertEqual(block['rows'],[['Costs',''],['Travel','750'],['','250']])
        self.assertEqual(block['cell_spans'][1][0]['rowspan'],2)
        self.assertEqual(block['cell_spans'][0][0]['colspan'],2)

    def test_numbered_ruled_statement_remains_paragraphs(self):
        html='<table><tr><td>12 13</td><td>The business started in Haa.</td></tr><tr><td>14</td><td>It continues to operate today.</td></tr></table>'
        block=table_block(html,{'column_widths':[60,840]})
        self.assertEqual(block['type'],'text')
        self.assertEqual(block['text'],'The business started in Haa. It continues to operate today.')

    def test_invalid_and_empty_outputs_fail_explicitly(self):
        engine=paddle_ocr.PaddleOCRVLEngine();engine._engine=Mock()
        for payload in ({'res':{}},{'res':{'parsing_res_list':'invalid'}}):
            engine._engine.predict.return_value=[SimpleNamespace(json=payload)]
            with self.assertRaises(paddle_ocr.PaddleOutputSchemaError):engine.predict_page('image.png',1)
        with self.assertRaises(ValueError):table_block('<table><tr><td colspan="10000">bad</td></tr></table>')

    def test_vl_table_output_chunks_keep_labels_for_existing_rag(self):
        from app.ocr.layout import structured_chunks
        from app.ocr.vl_layout import table_block
        block=table_block('<table><tr><th>Item</th><th>Amount</th></tr><tr><td>Travel</td><td>750</td></tr></table>')
        chunks=structured_chunks([block])
        self.assertIn('Amount: 750',chunks[0]['text'])
        # Review and retrieval keep using the same canonical block schema.
        self.assertEqual(block['type'],'table')
        self.assertEqual(block['rows'][0],['Item','Amount'])

    def test_mlx_routes_recognition_to_gpu_service_without_changing_layout_device(self):
        constructor=Mock(return_value=Mock())
        with patch('app.ocr.mlx_service.ensure_mlx_service') as service, patch.object(paddle_ocr.importlib,'import_module',return_value=SimpleNamespace(PaddleOCRVL=constructor)):
            engine=paddle_ocr.PaddleOCRVLEngine(backend='mlx-vlm-server',server_url='http://127.0.0.1:8111/',device='cpu')
            engine.initialize()
        service.assert_called_once_with('http://127.0.0.1:8111/')
        options=constructor.call_args.kwargs
        self.assertEqual(options['vl_rec_backend'],'mlx-vlm-server')
        self.assertEqual(options['vl_rec_max_concurrency'],1)
        self.assertEqual(options['device'],'cpu')
        self.assertTrue(options['vl_rec_api_model_name'].endswith('PaddleOCR-VL-1.6'))

    def test_valid_blank_page_does_not_discard_other_pages(self):
        engine=paddle_ocr.PaddleOCRVLEngine();engine._engine=Mock()
        engine._engine.predict.return_value=[SimpleNamespace(json={'res':{'parsing_res_list':[]}})]
        page=engine.predict_page('blank.png',12)
        self.assertEqual(page['text'],'')
        self.assertEqual(page['blocks'],[])
        self.assertEqual(page['page_number'],12)
