"""Synthetic, privacy-safe tests for ACD hierarchy routing and CC safeguards."""
import tempfile
import unittest
from pathlib import Path
from email import policy
from email.parser import BytesParser

import duckdb
from openpyxl import Workbook
from app import routing, core

class HierarchyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)
        self.db=duckdb.connect(":memory:")
        self.db.execute("CREATE TABLE recipients (division VARCHAR,region VARCHAR,zone VARCHAR,rse_name VARCHAR,rse_email VARCHAR,ase_emails VARCHAR,zsi_name VARCHAR,zsi_email VARCHAR,audit_status VARCHAR)")
        self.db.execute("INSERT INTO recipients VALUES ('ACD','R01','Zone 1','Old','old@example.com','ase@example.com','Old','oldzsi@example.com','old')")
    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def create_workbook(self):
        wb=Workbook()
        route=wb.active
        route.title=routing.ROUTING_SHEET
        route.append(["Division","Zone","Region Code","Region Name","RSE Name","ZSI Name",
                      "To (RSE)","CC (Parent ZSI)","Status"])
        z=wb.create_sheet(routing.ZSI_SHEET)
        z.append(["Division","Designation","Zone","ZSI Name","ZSI Email","Status"])
        for i in range(1,17):
            z.append(["ACD","ZSI",f"Zone {i}",f"Parent {i}",
                      None if i==10 else f"parent{i}@example.com",
                      "Vacant" if i==10 else "Active"])
        for i in range(1,52):
            zone=10 if i in (8,9,10) else 1+(i%15)
            if i==51:zone=13
            rse=None if i==51 else f"rse{i}@example.com"
            cc=None if zone==10 else f"parent{zone}@example.com"
            status="Review — missing role/contact" if i==51 else ("Vacant ZSI — CC unavailable" if zone==10 else "Ready")
            route.append(["ACD",f"Zone {zone}",f"R{i:02}",f"Region {i}",f"RSE {i}",
                          f"Parent {zone}",rse,cc,status])
        p=self.path/"hierarchy.xlsx"
        wb.save(p)
        return p

    def test_import_51_and_flag_missing_parent_or_rse(self):
        result=routing.import_hierarchy(self.db,self.create_workbook())
        self.assertEqual(result["regions"],51)
        self.assertEqual(result["blocked"],4)
        self.assertEqual(result["ready"],47)
        preserved=self.db.execute("SELECT ase_emails FROM recipients WHERE region='R01'").fetchone()[0]
        self.assertEqual(preserved,"ase@example.com")

    def test_blocked_draft_has_no_live_recipient_or_attachment(self):
        routing.import_hierarchy(self.db,self.create_workbook())
        self.db.execute("""CREATE TABLE prescribers AS SELECT 'ACD' division,
             'R08' region, 'ASE1' ase, 'T1' territory, 'DR1' dr_code,
             'Doctor' dr_name, 'GP' specialty, 'Address' address,
             2 prescriptions, 2 product_rows""")
        items=core.generate_drafts(self.db,self.path/"drafts",top_n=2)
        self.assertEqual(len(items),51)
        message=BytesParser(policy=policy.default).parsebytes((self.path/"drafts"/"ACD_R08_Top_2.eml").read_bytes())
        self.assertIsNone(message.get("To"))
        self.assertIsNone(message.get("Cc"))
        self.assertFalse(message.iter_attachments().__next__() if False else list(message.iter_attachments()))

if __name__=="__main__":
    unittest.main()
