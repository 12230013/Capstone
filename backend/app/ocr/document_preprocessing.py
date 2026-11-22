"""Conservative, in-memory image preprocessing for OCR input."""

from typing import Any

import cv2
import numpy as np
from PIL import Image

from app.ocr.config import (
    OCR_CONTRAST_ENABLED,
    OCR_DESKEW_ENABLED,
    OCR_DENOISE_ENABLED,
    OCR_PREPROCESSING_ENABLED,
    OCR_THRESHOLD_ENABLED,
    OCR_THRESHOLD_METHOD,
)

MAX_DESKEW_ANGLE_DEGREES = 7.0
MIN_DESKEW_ANGLE_DEGREES = 0.2


class ImagePreprocessingError(ValueError):
    """Raised when an image cannot be safely preprocessed."""


def preprocessing_settings() -> dict[str, Any]:
    """Return the effective preprocessing configuration for result metadata."""
    return {
        "enabled": OCR_PREPROCESSING_ENABLED,
        "grayscale": OCR_PREPROCESSING_ENABLED,
        "denoise": OCR_PREPROCESSING_ENABLED and OCR_DENOISE_ENABLED,
        "contrast": OCR_PREPROCESSING_ENABLED and OCR_CONTRAST_ENABLED,
        "threshold": OCR_PREPROCESSING_ENABLED and OCR_THRESHOLD_ENABLED,
        "threshold_method": OCR_THRESHOLD_METHOD,
        "deskew": OCR_PREPROCESSING_ENABLED and OCR_DESKEW_ENABLED,
    }


def to_grayscale(image: np.ndarray) -> np.ndarray:
    """Convert an RGB, BGR, or grayscale image to an 8-bit grayscale array."""
    if not isinstance(image, np.ndarray) or image.size == 0:
        raise ImagePreprocessingError("A non-empty image array is required.")
    if image.ndim == 2:
        if image.dtype != np.uint8:
            return cv2.normalize(image, None, 0, 255, cv2.NORM_MINMAX).astype(
                np.uint8
            )
        return image.copy()
    if image.ndim == 3 and image.shape[2] == 1:
        return to_grayscale(image[:, :, 0])
    if image.ndim == 3 and image.shape[2] == 3:
        return cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    if image.ndim == 3 and image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_RGBA2GRAY)
    raise ImagePreprocessingError("The image must have 1, 3, or 4 channels.")


def denoise_image(grayscale: np.ndarray) -> np.ndarray:
    """Remove isolated pixel noise with a conservative 3-by-3 median filter."""
    _validate_grayscale(grayscale)
    return cv2.medianBlur(grayscale, 3)


def enhance_contrast(grayscale: np.ndarray) -> np.ndarray:
    """Apply local contrast enhancement with conservative CLAHE settings."""
    _validate_grayscale(grayscale)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(grayscale)


def threshold_image(
    grayscale: np.ndarray,
    method: str = OCR_THRESHOLD_METHOD,
) -> np.ndarray:
    """Binarize an image using adaptive Gaussian or global Otsu thresholding."""
    _validate_grayscale(grayscale)
    method = method.strip().lower()
    if method == "binary":
        return cv2.threshold(
            grayscale,
            0,
            255,
            cv2.THRESH_BINARY | cv2.THRESH_OTSU,
        )[1]
    if method == "adaptive":
        return cv2.adaptiveThreshold(
            grayscale,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            10,
        )
    raise ImagePreprocessingError(
        "OCR_THRESHOLD_METHOD must be 'adaptive' or 'binary'."
    )


def estimate_skew_angle(grayscale: np.ndarray) -> float | None:
    """Estimate text-line skew; return None when there is not enough evidence."""
    _validate_grayscale(grayscale)
    binary = cv2.threshold(
        grayscale,
        0,
        255,
        cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU,
    )[1]
    coordinates = cv2.findNonZero(binary)
    if coordinates is None or len(coordinates) < 50:
        return None

    rectangle = cv2.minAreaRect(coordinates)
    angle = rectangle[-1]
    width, height = rectangle[1]
    if width < height:
        angle = 90 - angle
    else:
        angle = -angle

    if (
        MIN_DESKEW_ANGLE_DEGREES <= abs(angle) <= MAX_DESKEW_ANGLE_DEGREES
    ):
        return float(angle)
    return None


def deskew_image(grayscale: np.ndarray) -> tuple[np.ndarray, float | None]:
    """Correct only small, confidently measurable skew angles."""
    _validate_grayscale(grayscale)
    angle = estimate_skew_angle(grayscale)
    if angle is None:
        return grayscale.copy(), None

    height, width = grayscale.shape
    center = (width / 2.0, height / 2.0)
    transform = cv2.getRotationMatrix2D(center, angle, 1.0)
    corrected = cv2.warpAffine(
        grayscale,
        transform,
        (width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=255,
    )
    return corrected, angle


def _validate_grayscale(image: np.ndarray) -> None:
    if (
        not isinstance(image, np.ndarray)
        or image.size == 0
        or image.ndim != 2
        or image.dtype != np.uint8
    ):
        raise ImagePreprocessingError(
            "A non-empty 8-bit grayscale image is required."
        )


def preprocess_image(image: Image.Image) -> tuple[Image.Image, dict[str, Any]]:
    """Preprocess an OCR image without changing the caller's source image."""
    if not isinstance(image, Image.Image) or image.width < 1 or image.height < 1:
        raise ImagePreprocessingError("A valid PIL image is required.")

    settings = preprocessing_settings()
    details: dict[str, Any] = {
        **settings,
        "deskew_applied": False,
        "deskew_angle_degrees": None,
    }
    if not settings["enabled"]:
        return image, details

    try:
        rgb = np.asarray(image.convert("RGB"))
        processed = to_grayscale(rgb)
        if settings["denoise"]:
            processed = denoise_image(processed)
        if settings["contrast"]:
            processed = enhance_contrast(processed)
        if settings["deskew"]:
            processed, angle = deskew_image(processed)
            details["deskew_applied"] = angle is not None
            details["deskew_angle_degrees"] = (
                round(angle, 3) if angle is not None else None
            )
        if settings["threshold"]:
            processed = threshold_image(processed, settings["threshold_method"])
        return Image.fromarray(processed), details
    except ImagePreprocessingError:
        raise
    except cv2.error as exc:
        raise ImagePreprocessingError(
            "OpenCV could not preprocess the image."
        ) from exc
