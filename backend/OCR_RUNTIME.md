# PaddleOCR-VL 1.6 runtime on main

## Ubuntu deployment behind Nginx

OCR endpoints are disabled for remote requests by default. For the current
HTTP-only college VM, set the following in `backend/.env` and restart the backend:

```dotenv
OCR_DEPLOYMENT_ENABLED=true
APP_ENV=production
ENVIRONMENT=production
SESSION_COOKIE_SECURE=false
FRONTEND_ORIGINS=http://172.21.48.183
PADDLE_VL_BACKEND=native
PADDLE_DEVICE=cpu
```

`FRONTEND_ORIGINS` must exactly match the browser origin, including scheme and
port if present, and must not include a path or trailing slash. Since this VM is
served over HTTP, `SESSION_COOKIE_SECURE=false` is needed for the browser to
send the session cookie. This exposes session traffic to the network; switch to
HTTPS and `SESSION_COOKIE_SECURE=true` if TLS becomes available. Production
cookies remain Secure by default when this setting is omitted.
The deployment flag only lifts the loopback/development restriction for the
normal OCR workflow. Session authentication, mutation Origin and CSRF checks,
per-document ownership, upload type and size validation, review confirmation,
and the case-linked indexing restriction remain active. Reference-based OCR
evaluation remains loopback-only and is not exposed by this flag.

Nginx must proxy `/api/ocr/` to the FastAPI service, preserve browser cookies
and the `Origin` header, and allow request bodies up to the configured
`OCR_MAX_UPLOAD_BYTES` (25 MiB by default), for example with
`client_max_body_size 27m;`. The backend needs write access to its persistent
`backend/data/documents/` and `backend/data/ocr/` directories; MongoDB must be
reachable for session and document metadata. On a CPU-only VM, explicitly set
`PADDLE_DEVICE=cpu`; `PADDLE_VL_BACKEND=native` selects the regular Paddle
runtime rather than the Apple-only MLX service.

At startup, the app provisions the dedicated OCR collection if it is absent
and validates its schema if it already exists. Do not run the manual
`provision_collection()` command while the backend is open on the same local
Qdrant directory: local Qdrant storage permits only one process at a time.
Use one backend process with local file storage, or configure a Qdrant server
for concurrent workers. Existing collections and stored documents are not
recreated or deleted by this deployment setting.

If OCR endpoints still return 404 after enabling the flag and restarting,
check that Nginx forwards the `/api/ocr/` path to FastAPI. A CSRF or Origin
configuration problem returns 403, while a missing/expired session returns
401.

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
