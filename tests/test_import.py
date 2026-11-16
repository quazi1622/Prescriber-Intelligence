"""Smoke tests for Excel selection, schema validation and DuckDB import."""
import csv
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import duckdb
from openpyxl import Workbook
from app import core


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.old_data=core.DATA
        core.DATA=self.root
        self.db=duckdb.connect(":memory:")
        self.headers=list(core.SOURCE_HEADERS)

    def tearDown(self):
        self.db.close()
        core.DATA=self.old_data
        self.tmp.cleanup()

    def workbook(self,sheet="Sheet1",count=3,shuffle=False,missing_code=False):
        path=self.root/"sample.xlsx"
        w=Workbook(write_only=True)
        w.create_sheet("Summary").append(["Not Rx data"])
        s=w.create_sheet(sheet)
        order=list(range(24))
        if shuffle:order=list(reversed(order))
        s.append([self.headers[i] for i in order])
        for i in range(count):
            data=["2025-05-01","2025-05-01","CHAMBER",str(i//2),"SFE-0001",
                'Dr "Quote", Name\nNew line',"MBBS","GP","Address, district",
                "A101","A100","A1","C101","C100","C1",
                "TAB","Product 1","10 mg","BRAND","P1","BEXIMCO","BPL","TG","Generic"]
            if missing_code and i==count-1:data[4]=""
            s.append([data[j] for j in order])
        w.save(path)
        return path

    def test_select_sheet_and_validate_roundtrip(self):
        path=self.workbook(sheet="TRD MAY'25",count=12,shuffle=True)
        self.assertEqual(core.available_sheets(path),["Summary","TRD MAY'25"])
        with self.assertRaisesRegex(ValueError,"Worksheet 'Sheet1' not found"):
            core.import_rx(self.db,path,sheet_name="Sheet1")
        n=core.import_rx(self.db,path,sheet_name="TRD MAY'25",memory_gb=4)
        self.assertEqual(n,12)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM rx").fetchone()[0],12)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM prescribers").fetchone()[0],2)
        self.assertEqual(self.db.execute("SELECT dr_name FROM rx LIMIT 1").fetchone()[0], 'Dr "Quote", Name\nNew line')

    def test_reject_malformed_headers_without_overwriting(self):
        good=self.workbook(sheet="Sheet1")
        core.import_rx(self.db,good,sheet_name="Sheet1")
        w=Workbook()
        s=w.active;s.title="Broken"
        s.append(["Wrong","Headers"])
        s.append(["1","2"])
        broken=self.root/"broken.xlsx";w.save(broken)
        with self.assertRaisesRegex(ValueError,"Missing required Excel headers"):
            core.import_rx(self.db,broken,sheet_name="Broken")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM rx").fetchone()[0],3)

    def test_reject_missing_doctor_code_without_overwriting(self):
        good=self.workbook(sheet="Sheet1")
        core.import_rx(self.db,good,sheet_name="Sheet1")
        bad=self.workbook(sheet="Sheet1",missing_code=True)
        with self.assertRaisesRegex(ValueError,"Missing Dr Code"):
            core.import_rx(self.db,bad,sheet_name="Sheet1")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM rx").fetchone()[0],3)


if __name__=="__main__":
    unittest.main()
