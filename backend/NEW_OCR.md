# new_ocr: PaddleOCR-VL 1.6

This branch uses the same frontend, authentication, review editor, MongoDB/GridFS, BGE-M3 embeddings, and Qdrant collections as the working application. The OCR adapter uses the actual `PaddleOCRVL(pipeline_version="v1.6")` pipeline. Digital PDFs still use native text extraction. VL HTML tables are converted into the existing editable table blocks, including merged cells; numbered statement tables are reconstructed as paragraphs.

The branch's `backend/ocr-profile.env` overrides only the OCR engine/model/device after loading the existing `backend/.env`. The shared `.env` and the original `.venv` are unchanged. Downloaded VL weights are cached under ignored `backend/data/ocr-vl-cache/`. Recognition confidence is unavailable for VL; the UI shows **Unavailable** rather than treating a layout detection score as text accuracy. Reference-based CER/WER evaluation remains available.

Set up the separate environment from the repository root:

```bash
python3 -m venv .venv-new-ocr
.venv-new-ocr/bin/python -m pip install -r backend/requirements-new-ocr.txt
```

Stop the previous backend process, then start this branch with:

```bash
./backend/start-new-ocr.sh
```

Or activate `.venv-new-ocr`, enter `backend`, and run the usual Uvicorn command on port 8001. Keep the frontend running as before. The model is loaded lazily on the first scanned upload and reused within the process. CPU document parsing can be slower than PP-OCRv5 Mobile.

Existing reviewed/indexed results are preserved. Choose **Re-extract original** to replace their extraction with VL output, then review and index again. Unreviewed duplicate uploads from another OCR model are re-extracted automatically. Because database and storage locations are shared, confirmed saves on this branch update the same document records and index as main. Model smoke checks should use temporary output files when a comparison must not change saved content.

If this branch is started from the original `.venv` (PaddleOCR 3.5), startup fails with an explicit message pointing to `start-new-ocr.sh` instead of accepting uploads that cannot be extracted. Use the launcher or activate `.venv-new-ocr` before running Uvicorn.
