# PaddleOCR-VL 1.6 runtime on main

The default OCR engine is the actual `PaddleOCRVL(pipeline_version="v1.6")` pipeline. Upload, review, original-file storage, MongoDB, BGE-M3 embeddings and Qdrant remain the same. Digital PDFs still extract their embedded text directly. Scanned pages retain grayscale cleanup, denoising, contrast enhancement, thresholding and conservative angle correction. Physical table geometry is measured before cleanup. Image-region OCR includes screenshots; blank pages do not discard other pages' results.

## This Mac / Apple Silicon

From the project root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
python3 -m venv .venv-mlx-ocr
.venv-mlx-ocr/bin/python -m pip install -r backend/requirements-mlx-ocr.txt
./backend/start-backend.sh
```

Alternatively activate `.venv`, enter `backend`, and use the normal Uvicorn command on port 8001. The existing frontend command remains `npm run dev` from `frontend`.

With `PADDLE_DEVICE=auto` and `PADDLE_VL_BACKEND=auto`, Apple Silicon uses Metal GPU recognition through a loopback-only MLX service on port 8111. The sidecar starts automatically when needed, reuses downloaded VL 1.6 weights and stays warm across backend reloads. Layout detection uses CPU with the available CPU thread count; `OCR_CPU_THREADS` can override it. GPU/CPU utilization varies by page and available memory. The Apple Neural Engine is not used by this runtime. `cpu` in the layout device field does not mean recognition is using CPU.

The service is deliberately limited to one simultaneous recognition sequence on this 16 GB M5 to avoid excessive unified-memory allocation. Layout detection and GPU recognition are separate stages; forcing 100% utilization or filling RAM is not an optimization goal.

## Windows NVIDIA GPU

Use a supported NVIDIA GPU and the appropriate driver/CUDA Paddle wheel. Do not install CPU and GPU Paddle distributions together. The example below uses the CUDA 12.6 channel; choose another official channel if required by the machine:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements-windows-gpu.txt
.\backend\start-backend.ps1
```

For an existing environment containing CPU Paddle, uninstall `paddlepaddle` before installing the GPU requirements. Common requirements exclude CPU Paddle on Windows to avoid silently replacing the CUDA build.

Auto selection uses `gpu:0` for both native VL recognition and layout when the Paddle runtime reports an available CUDA GPU. If `nvidia-smi` detects NVIDIA hardware but the installed Paddle runtime cannot use it, startup reports a clear installation/driver error rather than silently using CPU. Systems without a compatible NVIDIA CUDA runtime can explicitly install `backend/requirements-windows-cpu.txt`; AMD/Intel Windows GPU acceleration is not provided by this Paddle runtime. Windows selection is unit-tested; actual Windows GPU inference needs validation on that machine.

Official installation reference: https://github.com/PaddlePaddle/docs/blob/develop/docs/install/pip/windows-pip.md

## Configuration and information

```dotenv
OCR_ENGINE=paddleocr_vl
OCR_MODEL_ID=PaddleOCR-VL-1.6
PADDLE_DEVICE=auto
PADDLE_VL_BACKEND=auto
PADDLE_VL_SERVER_URL=http://127.0.0.1:8111/
```

Explicit `PADDLE_VL_BACKEND=native` / `PADDLE_DEVICE=cpu` allows CPU testing. Configuration is in the existing local `.env`; no experimental branch profile overrides it. Downloaded weights and service logs remain under ignored `backend/data/ocr-vl-cache/`.

Extraction information displays the actual model and selected recognition/layout devices. VL's numeric **layout detection confidence** is the mean valid detected-region score (0–100) and is shown per page and per document. It is neither text-recognition confidence nor measured OCR accuracy; the pipeline does not expose that score. Recognition confidence stays null rather than being fabricated or replaced by region confidence. CER/WER evaluation against a correct reference remains available.

VL confidence limitation: https://github.com/PaddlePaddle/PaddleOCR/issues/16899

Existing reviewed/indexed extractions are preserved. Use **Re-extract original** and then review/confirm to replace one. Outdated unreviewed duplicates from another model re-extract automatically. Indexing still requires review confirmation.
