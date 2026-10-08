import unittest
from types import SimpleNamespace

import numpy as np

from web.face.recognizer import FaceRecognizer


class FaceAmbiguityTests(unittest.TestCase):
    def recognizer(self, query, identities, threshold=0.5, margin=0.08):
        rec = FaceRecognizer.__new__(FaceRecognizer)
        rec.extractor = SimpleNamespace(
            extract=lambda _image: np.asarray(query, dtype=np.float32))
        rec.identities = [
            {"name": name, "prototype": np.asarray(vector, dtype=np.float32)}
            for name, vector in identities
        ]
        rec.similarity_threshold = threshold
        rec.ambiguity_margin = margin
        return rec

    def test_clear_winner_is_authorized(self):
        rec = self.recognizer([1, 0], [("A", [1, 0]), ("B", [0, 1])])
        result = rec.recognize(np.zeros((2, 2, 3), dtype=np.uint8))
        self.assertTrue(result.authorized)
        self.assertEqual(result.identity, "A")
        self.assertGreaterEqual(result.margin, 0.08)

    def test_close_runner_up_is_rejected_as_ambiguous(self):
        rec = self.recognizer(
            [1, 0], [("A", [1, 0]), ("B", [0.998, 0.063])], margin=0.08)
        result = rec.recognize(np.zeros((2, 2, 3), dtype=np.uint8))
        self.assertFalse(result.authorized)
        self.assertEqual(result.identity, "unknown")
        self.assertLess(result.margin, 0.08)

    def test_absolute_threshold_still_rejects_weak_match(self):
        rec = self.recognizer(
            [1, 0], [("A", [0.55, 0.835]), ("B", [0, 1])], threshold=0.62)
        result = rec.recognize(np.zeros((2, 2, 3), dtype=np.uint8))
        self.assertFalse(result.authorized)
        self.assertEqual(result.identity, "unknown")


if __name__ == "__main__":
    unittest.main()
