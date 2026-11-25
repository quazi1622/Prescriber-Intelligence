"""Offline Qt widget tests: search is never silently applied as an Rx filter."""
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"app"))
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from main import SearchableCombo

class SearchableFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def test_case_insensitive_substring_completion_and_committed_selection(self):
        combo=SearchableCombo()
        combo.addItems(["All","Azithrocin","Azithromax","Zimax"])
        combo.commit_programmatic_selection()
        self.assertEqual(combo.committed_text(),"All")
        self.assertEqual(combo.completer().filterMode(),Qt.MatchContains)
        self.assertEqual(combo.completer().caseSensitivity(),Qt.CaseInsensitive)
        combo.setEditText("ITHRO")
        # Partial text only searches; it must not become SQL query/filter state.
        self.assertEqual(combo.committed_text(),"All")
        combo.completer().setCompletionPrefix("ITHRO")
        self.assertEqual(combo.completer().completionModel().rowCount(),2)
        combo._completion_selected("Azithrocin")
        self.assertEqual(combo.committed_text(),"Azithrocin")
        combo.setEditText("not a value")
        self.assertEqual(combo.committed_text(),"Azithrocin")
        combo.close()

    def test_dropdown_and_search_button_preserved(self):
        combo=SearchableCombo()
        combo.addItems(["All","A1","A2","A10"])
        combo.commit_programmatic_selection()
        button=combo.search_button()
        self.assertEqual(button.toolTip().startswith("Search available"),True)
        self.assertEqual(combo.count(),4)
        combo.setCurrentIndex(2)
        combo.commit_programmatic_selection()
        self.assertEqual(combo.committed_text(),"A2")
        combo.close()

if __name__=="__main__":
    unittest.main()
