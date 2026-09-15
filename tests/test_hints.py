import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QCoreApplication
from PySide6.QtTest import QTest
from niridashboard.hints import HintAssignments, NumericSelector


class HintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_assignment_is_ordered_stable_and_does_not_renumber_on_removal(self):
        hints = HintAssignments()
        self.assertEqual(hints.update([20, 10, 30]), {20: 1, 10: 2, 30: 3})
        self.assertEqual(hints.update([30, 20, 10]), {20: 1, 10: 2, 30: 3})
        self.assertEqual(hints.update([20, 30]), {20: 1, 30: 2})
        self.assertEqual(hints.update([20, 30, 40]), {20: 1, 30: 2, 40: 3})

    def make_selector(self, assignments, timeout=80):
        selector = NumericSelector(timeout_ms=timeout)
        selector.update(assignments)
        selected = []
        selector.selected.connect(selected.append)
        self.addCleanup(selector.deleteLater)
        return selector, selected

    def test_single_digit_is_immediate_when_no_longer_prefix_exists(self):
        selector, selected = self.make_selector({11: 1, 12: 2, 13: 3})
        selector.press("2")
        self.assertEqual(selected, [12])
        self.assertEqual(selector.pending, "")

    def test_multi_digit_selection_supports_more_than_nine_windows(self):
        selector, selected = self.make_selector({wid: wid for wid in range(1, 13)})
        selector.press("1")
        self.assertEqual(selected, [])
        self.assertEqual(selector.pending, "1")
        selector.press("0")
        self.assertEqual(selected, [10])

    def test_ambiguous_exact_prefix_commits_after_timeout(self):
        selector, selected = self.make_selector({1: 1, 10: 10, 11: 11})
        selector.press("1")
        self.assertEqual(selected, [])
        QTest.qWait(110)
        self.assertEqual(selected, [1])

    def test_removed_window_cancels_pending_selection(self):
        selector, selected = self.make_selector({10: 10, 11: 11})
        selector.press("1")
        selector.update({})
        self.assertEqual(selector.pending, "")
        QTest.qWait(110)
        self.assertEqual(selected, [])

    def test_escape_cancels_pending_sequence_without_selection(self):
        selector, selected = self.make_selector({1: 1, 10: 10})
        selector.press("1")
        self.assertTrue(selector.cancel_pending())
        self.assertFalse(selector.cancel_pending())
        QTest.qWait(110)
        self.assertEqual(selected, [])


if __name__ == "__main__":
    unittest.main()
