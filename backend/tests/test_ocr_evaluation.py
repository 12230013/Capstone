import random
import unittest
from app.ocr.evaluation import _distance, evaluate_text

class EvaluationTests(unittest.TestCase):
    def test_character_and_word_edits(self):
        result = evaluate_text('cat sat', 'cat bat')
        self.assertEqual(result['character_errors'], 1)
        self.assertEqual(result['cer_percent'], 14.29)
        self.assertEqual(result['wer_percent'], 50)

    def test_normalization_retains_case_and_punctuation(self):
        self.assertTrue(evaluate_text('  Hello\n world! ', 'Hello world!')['exact_match'])
        self.assertFalse(evaluate_text('hello world', 'Hello world!')['exact_match'])

    def test_empty_prediction_and_insertions(self):
        self.assertEqual(evaluate_text('', 'text')['cer_percent'], 100)
        self.assertGreater(evaluate_text('many extra words', 'a')['wer_percent'], 100)
        with self.assertRaises(ValueError): evaluate_text('text', '  ')
        with self.assertRaises(ValueError): evaluate_text('x' * 20001, 'text')

    def test_bit_distance_matches_dynamic_programming(self):
        rng = random.Random(42)
        for _ in range(100):
            a, b = [''.join(rng.choices('abc ', k=rng.randrange(25))) for _ in range(2)]
            row = list(range(len(a)+1))
            for j, right in enumerate(b, 1):
                updated = [j]
                for i, left in enumerate(a, 1):
                    updated.append(min(updated[-1]+1, row[i]+1, row[i-1]+(left != right)))
                row = updated
            self.assertEqual(_distance(a,b), row[-1])

    def test_page_size_is_fast_and_exact(self):
        self.assertEqual(_distance('a'*20000, 'a'*19999+'b'), 1)
