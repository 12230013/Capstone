"""PaddleOCR-VL 1.6 adapter for the existing document upload/review pipeline."""
from __future__ import annotations
import importlib
import math
import threading
from app.ocr.layout import blocks_text
from app.ocr.vl_layout import physical_metadata, table_block


class PaddleEngineUnavailableError(RuntimeError):
    """The VL runtime or model could not be initialized."""


class PaddleInferenceError(RuntimeError):
    """VL inference failed."""


class PaddleOutputSchemaError(RuntimeError):
    """VL output could not be interpreted."""


PADDLE_PIPELINE_VERSION = "v1.6"


class PaddleOCRVLEngine:
    PADDLE_PIPELINE_VERSION = 'v1.6'
    _models = {}
    _initialization_lock = threading.Lock()

    def __init__(self, layout_model_dir=None, vl_model_dir=None, device=None, backend=None, server_url=None, api_model=None):
        from app.ocr import config
        from app.ocr.hardware import select_hardware
        selected = select_hardware(backend or config.PADDLE_VL_BACKEND,
            device or config.PADDLE_DEVICE, cpu_threads=config.OCR_CPU_THREADS)
        self.hardware = selected.as_dict()
        self.backend = selected.backend
        self.device = selected.device
        self.server_url = server_url or config.PADDLE_VL_SERVER_URL
        self.api_model = api_model or config.PADDLE_VL_API_MODEL
        # Reuse the already downloaded official VL 1.6 weights locally.
        cached = config.BACKEND_ROOT / "data/ocr-vl-cache/official_models/PaddleOCR-VL-1.6"
        if self.backend == "mlx-vlm-server" and self.api_model == "PaddlePaddle/PaddleOCR-VL-1.6" and cached.is_dir():
            self.api_model = str(cached)
        self.layout_model_dir = layout_model_dir
        self.vl_model_dir = vl_model_dir
        self._engine = None

    def initialize(self):
        key = (self.layout_model_dir, self.vl_model_dir, self.device, self.backend, self.server_url, self.api_model)
        with self._initialization_lock:
            if key in self._models:
                self._engine = self._models[key]
                return
            try:
                paddleocr = importlib.import_module('paddleocr')
                options = dict(pipeline_version='v1.6', device=self.device,
                    use_doc_orientation_classify=False, use_doc_unwarping=False,
                    use_queues=False, enable_mkldnn=False, use_ocr_for_image_block=True,
                    cpu_threads=self.hardware['cpu_threads'])
                if self.backend == 'mlx-vlm-server':
                    from app.ocr.mlx_service import ensure_mlx_service
                    ensure_mlx_service(self.server_url)
                    options.update(vl_rec_backend=self.backend,
                        vl_rec_server_url=self.server_url,
                        vl_rec_api_model_name=self.api_model,
                        vl_rec_max_concurrency=1)
                if self.layout_model_dir:
                    options['layout_detection_model_dir'] = self.layout_model_dir
                if self.vl_model_dir:
                    options['vl_rec_model_dir'] = self.vl_model_dir
                self._engine = paddleocr.PaddleOCRVL(**options)
                self._models[key] = self._engine
            except Exception as exc:
                raise PaddleEngineUnavailableError(
                    'PaddleOCR-VL 1.6 could not initialize. Use .venv-new-ocr and '
                    'install backend/requirements.txt; check backend/OCR_RUNTIME.md.'
                ) from exc

    def predict_page(self, image_path, source_page_number, correlation_id=None,
                     image_width=None, image_height=None, table_regions=()):
        if self._engine is None:
            raise PaddleInferenceError('PaddleOCR-VL 1.6 is not initialized.')
        try:
            results = list(self._engine.predict(image_path))
        except Exception as exc:
            raise PaddleInferenceError('PaddleOCR-VL 1.6 page inference failed.') from exc
        if len(results) != 1:
            raise PaddleOutputSchemaError('VL returned an unexpected page count.')
        try:
            payload = getattr(results[0], 'json', results[0])
            if callable(payload): payload = payload()
            if not isinstance(payload, dict): raise ValueError('Invalid VL result.')
            payload = payload.get('res', payload)
            parsed = payload.get('parsing_res_list')
            if not isinstance(parsed, list): raise ValueError('Missing VL layout blocks.')
            layout_values = []
            for box in (payload.get('layout_det_res') or {}).get('boxes', []):
                value = box.get('score')
                if isinstance(value, bool): continue
                try: value = float(value)
                except (TypeError, ValueError): continue
                if math.isfinite(value) and 0 <= value <= 1:
                    layout_values.append(value * 100)
            blocks = []
            for item in parsed:
                if not isinstance(item, dict): raise ValueError('Invalid VL block.')
                content = item.get('block_content', '')
                if not isinstance(content, str): raise ValueError('Invalid VL text.')
                if not content.strip(): continue
                if item.get('block_label') == 'table' and '<table' in content.lower():
                    blocks.append(table_block(content, physical_metadata(item.get('block_bbox'), table_regions)))
                else:
                    blocks.append({'type':'text', 'text':content.strip()})
            text = blocks_text(blocks)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise PaddleOutputSchemaError('VL structured output could not be interpreted.') from exc
        return dict(text=text, blocks=blocks, page_number=source_page_number,
                    correlation_id=correlation_id, image_width=image_width,
                    image_height=image_height, engine='paddleocr_vl',
                    layout_confidence=round(sum(layout_values)/len(layout_values),1) if layout_values else None,
                    layout_confidence_values=layout_values, hardware=self.hardware)
