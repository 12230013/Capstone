# new_ocr: PaddleOCR-VL 1.6

This branch uses the same frontend, authentication, review editor, MongoDB/GridFS, BGE-M3 embeddings, and Qdrant collections as the working application. The OCR adapter uses the actual `PaddleOCRVL(pipeline_version="v1.6")` pipeline. Digital PDFs still use native text extraction. VL HTML tables are converted into the existing editable table blocks, including merged cells; numbered statement tables are reconstructed as paragraphs.

The branch's `backend/ocr-profile.env` overrides only the OCR engine/model/device/inference-backend settings after loading the existing `backend/.env`. The shared `.env` and the original `.venv` are unchanged. Downloaded VL weights are cached under ignored `backend/data/ocr-vl-cache/`. Recognition confidence is unavailable for VL; the UI shows **Unavailable** rather than treating a layout detection score as text accuracy. Reference-based CER/WER evaluation remains available.

Set up the separate environment from the repository root:

```bash
python3 -m venv .venv-new-ocr
.venv-new-ocr/bin/python -m pip install -r backend/requirements-new-ocr.txt
```

Stop the previous backend process, then start this branch with:

```bash
./backend/start-new-ocr.sh
```

Or activate `.venv-new-ocr`, enter `backend`, and run the usual Uvicorn command on port 8001. Keep the frontend running as before. The model is loaded lazily on the first scanned upload and reused within the process. Layout runs on CPU; recognition uses the MLX GPU service described below.

Existing reviewed/indexed results are preserved. Choose **Re-extract original** to replace their extraction with VL output, then review and index again. Unreviewed duplicate uploads from another OCR model are re-extracted automatically. Because database and storage locations are shared, confirmed saves on this branch update the same document records and index as main. Model smoke checks should use temporary output files when a comparison must not change saved content.

If this branch is started from the original `.venv` (PaddleOCR 3.5), startup fails with an explicit message pointing to `start-new-ocr.sh` instead of accepting uploads that cannot be extracted. Use the launcher or activate `.venv-new-ocr` before running Uvicorn.

## Apple M5 GPU acceleration

Recognition now uses the local MLX-VLM service on the M5's Metal GPU. PaddleOCR's layout model still uses CPU, so `PADDLE_DEVICE=cpu` is intentional. `PADDLE_VL_BACKEND=mlx-vlm-server` and the loopback service URL in `ocr-profile.env` select GPU recognition. No changes to the frontend, MongoDB/GridFS, BGE-M3 or Qdrant are needed.

MLX runs in its own environment to avoid changing backend dependencies:

```bash
python3 -m venv .venv-mlx-ocr
.venv-mlx-ocr/bin/python -m pip install -r backend/requirements-mlx-ocr.txt
```

Start the backend as before (`./backend/start-new-ocr.sh`, or Uvicorn from `.venv-new-ocr`). The first scanned upload starts/reuses MLX automatically on `127.0.0.1:8111`, reusing the existing official VL 1.6 weights. One recognition sequence runs at a time to limit unified-memory use. The service stays warm across backend reloads; stop it when no extraction is active with `./backend/stop-mlx-ocr.sh`. `./backend/start-mlx-ocr.sh` is available for foreground service logs if needed; automatic startup reuses it when it is already healthy.

Service logs are in ignored `backend/data/ocr-vl-cache/mlx-server.log`. Saved extraction metadata records `vl_recognition_backend=mlx-vlm-server`. Recognition remains VL 1.6 and still requires review before indexing. MLX is not a separate OCR model and does not use the Apple Neural Engine.

Validation on the local M5: the 15-page sample completed via MLX in 154.6 seconds, with results retained for review and no automatic indexing. This is a measurement for that document, not a runtime guarantee for other files. Image-region OCR is enabled so phone screenshots are not skipped; valid blank pages no longer fail otherwise readable PDFs. The UI treats `manual_review` as a finished extraction state rather than polling indefinitely.
