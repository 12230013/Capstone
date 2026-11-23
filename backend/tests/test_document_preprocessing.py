import unittest
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

from app.ocr import document_preprocessing as preprocessing


class DocumentPreprocessingTests(unittest.TestCase):
    @staticmethod
    def make_text_image():
        image = np.full((320, 900, 3), 255, dtype=np.uint8)
        cv2.putText(
            image,
            "SYNTHETIC STATEMENT 2026",
            (45, 100),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.4,
            (0, 0, 0),
            3,
            cv2.LINE_AA,
        )
        cv2.putText(
            image,
            "PAYMENT RECORD 12345",
            (45, 180),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.4,
            (0, 0, 0),
            3,
            cv2.LINE_AA,
        )
        return image

    def test_grayscale_conversion_handles_color_and_existing_grayscale(self):
        color = np.full((20, 30, 3), (20, 80, 160), dtype=np.uint8)
        grayscale = preprocessing.to_grayscale(color)
        self.assertEqual(grayscale.shape, (20, 30))
        self.assertEqual(grayscale.dtype, np.uint8)

        unchanged = preprocessing.to_grayscale(grayscale)
        np.testing.assert_array_equal(unchanged, grayscale)
        self.assertIsNot(unchanged, grayscale)

    def test_denoising_and_contrast_return_valid_grayscale_images(self):
        noisy = np.random.default_rng(12).integers(
            0,
            256,
            size=(80, 100),
            dtype=np.uint8,
        )
        denoised = preprocessing.denoise_image(noisy)
        enhanced = preprocessing.enhance_contrast(noisy)
        for output in (denoised, enhanced):
            self.assertEqual(output.shape, noisy.shape)
            self.assertEqual(output.dtype, np.uint8)

    def test_thresholding_supports_adaptive_and_binary_modes(self):
        grayscale = preprocessing.to_grayscale(self.make_text_image())
        for method in ("adaptive", "binary"):
            with self.subTest(method=method):
                thresholded = preprocessing.threshold_image(grayscale, method)
                self.assertEqual(thresholded.shape, grayscale.shape)
                self.assertEqual(set(np.unique(thresholded)), {0, 255})

    def test_deskew_corrects_a_small_synthetic_rotation(self):
        straight = self.make_text_image()
        height, width = straight.shape[:2]
        transform = cv2.getRotationMatrix2D((width / 2, height / 2), 4.0, 1.0)
        rotated = cv2.warpAffine(
            straight,
            transform,
            (width, height),
            borderValue=(255, 255, 255),
        )
        grayscale = preprocessing.to_grayscale(rotated)
        corrected, angle = preprocessing.deskew_image(grayscale)

        self.assertIsNotNone(angle)
        self.assertAlmostEqual(angle, 4.0, delta=1.5)
        self.assertIsNone(preprocessing.estimate_skew_angle(corrected))
        self.assertEqual(corrected.shape, grayscale.shape)

    def test_deskew_leaves_straight_document_unchanged(self):
        straight = preprocessing.to_grayscale(self.make_text_image())
        corrected, angle = preprocessing.deskew_image(straight)

        self.assertIsNone(angle)
        np.testing.assert_array_equal(corrected, straight)

    def test_invalid_input_returns_a_controlled_error(self):
        with self.assertRaises(preprocessing.ImagePreprocessingError):
            preprocessing.preprocess_image("not an image")
        with self.assertRaises(preprocessing.ImagePreprocessingError):
            preprocessing.to_grayscale(np.empty((0, 0), dtype=np.uint8))

    def test_disabled_preprocessing_passes_original_image_through(self):
        source = Image.fromarray(self.make_text_image(), mode="RGB")
        with patch.object(preprocessing, "OCR_PREPROCESSING_ENABLED", False):
            result, details = preprocessing.preprocess_image(source)

        self.assertIs(result, source)
        self.assertFalse(details["enabled"])
        self.assertFalse(details["deskew_applied"])

    def test_pipeline_preserves_source_pixels_and_reports_stages(self):
        source = Image.fromarray(self.make_text_image(), mode="RGB")
        original_pixels = np.asarray(source).copy()

        processed, details = preprocessing.preprocess_image(source)

        self.assertIsNot(processed, source)
        self.assertEqual(processed.mode, "L")
        self.assertTrue(details["enabled"])
        self.assertTrue(details["denoise"])
        self.assertTrue(details["contrast"])
        self.assertEqual(details["threshold_method"], "adaptive")
        np.testing.assert_array_equal(np.asarray(source), original_pixels)
        processed.close()
        source.close()

    def test_thresholding_rejects_unknown_method(self):
        with self.assertRaises(preprocessing.ImagePreprocessingError):
            preprocessing.threshold_image(
                np.zeros((20, 20), dtype=np.uint8),
                "unknown",
            )

    def test_layout_aligned_pages_skip_second_rotation(self):
        source = Image.fromarray(self.make_text_image())
        with patch.object(preprocessing, "deskew_image") as rotate:
            result, details = preprocessing.preprocess_image(source, allow_deskew=False)
        rotate.assert_not_called()
        self.assertFalse(details["deskew"])
        result.close()
        source.close()

    def test_faint_noisy_scan_is_preprocessed_without_changing_source(self):
        gray = preprocessing.to_grayscale(self.make_text_image())
        faint = (210 + gray.astype(np.float32) * (45 / 255)).astype(np.uint8)
        noise = np.random.default_rng(21).normal(0, 2, faint.shape)
        source = Image.fromarray(np.clip(faint + noise, 0, 255).astype(np.uint8)).convert("RGB")
        before = np.asarray(source).copy()
        result, details = preprocessing.preprocess_image(source)
        self.assertTrue(details["enabled"])
        self.assertGreater(np.ptp(np.asarray(result)), 0)
        np.testing.assert_array_equal(before, np.asarray(source))
        result.close()
        source.close()


if __name__ == "__main__":
    unittest.main()
