import unittest
from unittest.mock import Mock
from app.ocr.chat_retrieval import OCRChatRetrievalService
from app.ocr.qdrant_adapter import OCRQdrantAdapter
from app.ocr.embedding import BGEEmbeddingAdapter
from qdrant_client import QdrantClient, models
from types import SimpleNamespace

class UploadSearchTests(unittest.TestCase):
    def test_metadata_query_allows_only_completed_indexed_owner_documents(self):
        documents=Mock();documents.find.return_value=[{'_id':'a'*64}]
        adapter=Mock();adapter.retrieve_documents.return_value=[{'text':'Amount: 750'}]
        service=OCRChatRetrievalService(documents_collection=documents,adapter_factory=lambda:adapter)
        self.assertEqual(service.retrieve_all_evidence('What was paid?','owner'),[{'text':'Amount: 750'}])
        query=documents.find.call_args.args[0]
        self.assertEqual(query['owner_user_id'],'owner');self.assertEqual(query['index_status'],'indexed')
        self.assertEqual(query['ocr_status']['$in'],['completed','not_required'])
        adapter.retrieve_documents.assert_called_once_with('What was paid?',['a'*64],'owner')

    def test_real_qdrant_filters_owner_and_indexed_ids_and_keeps_table_labels(self):
        client=QdrantClient(':memory:')
        config=SimpleNamespace(OCR_COLLECTION='ocr_documents',COLLECTION='statements',EMBED_MODEL='BAAI/bge-m3',EMBED_DIM=1024)
        embedding=BGEEmbeddingAdapter(embed_batch=lambda texts:[[1.0]+[0.0]*1023 for _ in texts])
        adapter=OCRQdrantAdapter(client=client,embedder=embedding,index_module=SimpleNamespace(config=config),qdrant_models=models)
        adapter.provision_collection()
        for owner,doc,amount in [('owner','a'*64,'750'),('owner','b'*64,'100'),('other','c'*64,'999')]:
            adapter.upsert_document({'document_id':doc,'filename':'expenses.png','pages':[{'page_number':1,'text':'reviewed','blocks':[{'type':'table','rows':[['Item','Amount'],['Travel',amount]]}]}]},owner_user_id=owner)
        chunks=adapter.retrieve_documents('What was paid?',['a'*64,'c'*64],'owner')
        self.assertEqual(len(chunks),1)
        self.assertIn('Amount: 750',chunks[0]['text'])
        self.assertEqual(chunks[0]['metadata']['metadata']['document_id'],'a'*64)
        client.close()

    def test_reconstructed_statement_paragraph_reaches_vector_retrieval_without_gutter(self):
        from app.ocr.layout import layout_from_words,blocks_text
        client=QdrantClient(':memory:')
        config=SimpleNamespace(OCR_COLLECTION='ocr_documents',COLLECTION='statements',EMBED_MODEL='BAAI/bge-m3',EMBED_DIM=1024)
        batches=[]
        def embed(texts):
            batches.extend(texts);return [[1.0]+[0.0]*1023 for _ in texts]
        adapter=OCRQdrantAdapter(client=client,embedder=BGEEmbeddingAdapter(embed_batch=embed),index_module=SimpleNamespace(config=config),qdrant_models=models)
        adapter.provision_collection()
        rows=[['Line No.','STATEMENT'],['1','The business began in 2005.'],['2','It operates in Haa.'],['3','The owner confirmed this account.']]
        blocks=layout_from_words([], [((0,0,900,400),rows,{'column_widths':[70,830]})])
        doc='d'*64
        adapter.upsert_document({'document_id':doc,'filename':'statement.pdf','pages':[{'page_number':1,'text':blocks_text(blocks),'blocks':blocks}]},owner_user_id='owner')
        documents=Mock();documents.find.return_value=[{'_id':doc}]
        service=OCRChatRetrievalService(documents_collection=documents,adapter_factory=lambda:adapter)
        chunks=service.retrieve_all_evidence('When did the business begin?','owner')
        self.assertEqual(len(chunks),1)
        self.assertIn('The business began in 2005. It operates in Haa.',chunks[0]['text'])
        self.assertNotIn('STATEMENT',chunks[0]['text']);self.assertNotIn(' | ',chunks[0]['text'])
        self.assertEqual(chunks[0]['metadata']['metadata']['page_number'],1)
        self.assertIn('The business began in 2005.',batches[0])
        client.close()
