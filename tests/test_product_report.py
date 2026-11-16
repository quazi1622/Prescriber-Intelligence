"""Synthetic tests for product filters, apparent preference, inline email HTML."""
import tempfile
import unittest
from pathlib import Path
from email import policy
from email.parser import BytesParser
import duckdb
from app import core, product_analysis, html_report

class ProductReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.db=duckdb.connect(":memory:")
        self.db.execute("""CREATE TABLE rx_items(
            division VARCHAR, region VARCHAR,ase VARCHAR,territory VARCHAR,
            dr_code VARCHAR,dr_name VARCHAR,specialty VARCHAR,brand VARCHAR,
            generic VARCHAR,rx_key VARCHAR)""")
        self.db.executemany("INSERT INTO rx_items VALUES (?,?,?,?,?,?,?,?,?,?)",[
            ("ACD","T1","T10","T11","D1","Dr Alpha","GP","Azithrocin","Azithromycin","1"),
            ("ACD","T1","T10","T11","D1","Dr Alpha","GP","Az","Azithromycin","2"),
            ("ACD","T1","T10","T11","D1","Dr Alpha","GP","Az","Azithromycin","3"),
            ("ACD","T1","T10","T11","D2","Dr Beta","Pediatrics","Az","Azithromycin","4"),
            ("ACD","T1","T10","T11","D2","Dr Beta","Pediatrics","Az","Azithromycin","5")
        ])
        self.db.execute("""CREATE TABLE prescribers AS
            SELECT division,region,ase,territory,dr_code,max(dr_name) dr_name,
            max(specialty) specialty,'' address,count(DISTINCT rx_key) prescriptions,
            count(*) product_rows
            FROM rx_items GROUP BY 1,2,3,4,5""")
        self.db.execute("""CREATE TABLE recipients (
            division VARCHAR,region VARCHAR,zone VARCHAR,rse_name VARCHAR,
            rse_email VARCHAR,ase_emails VARCHAR,zsi_name VARCHAR,
            zsi_email VARCHAR,audit_status VARCHAR)""")
        self.db.execute("""INSERT INTO recipients VALUES
            ('ACD','T1','Z1','RSE Test','rse@example.com','ase@example.com',
             'ZSI Test','zsi@example.com','Ready')""")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_filters_and_preference(self):
        self.assertEqual(product_analysis.product_choices(
            self.db,"ACD","generic"),["Azithromycin"])
        self.assertEqual(set(product_analysis.product_choices(
            self.db,"ACD","brand",generic="Azithromycin")),{"Az","Azithrocin"})
        rows=product_analysis.filtered_rankings(self.db,"ACD",top_n=20,
                        brand="Azithrocin",generic="Azithromycin")
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0][4],"D1")
        self.assertEqual(rows[0][7],1)
        self.assertAlmostEqual(rows[0][10],33.3)
        generic_only=product_analysis.filtered_rankings(
            self.db,"ACD",top_n=20,generic="Azithromycin")
        self.assertEqual(len(generic_only),2)
        self.assertIsNone(generic_only[0][10])

    def test_formatted_html_email_without_csv_attachment(self):
        report=html_report.build_region_report(
            self.db,"ACD","T1",top_n=5,brand="Azithrocin",
            generic="Azithromycin",recipient_name="RSE Test")
        self.assertEqual(report["rx"],5)
        self.assertEqual(report["target_rx"],1)
        self.assertIn("20.0%",report["html"])
        self.assertIn("Apparent Prescription Preference",report["html"])
        self.assertIn("Top 5 prescribers in every territory",report["html"])
        self.assertIn("Prescribers without observed Azithrocin Rx",report["html"])
        output=core.generate_drafts(
            self.db,self.root/"drafts",5,brand="Azithrocin",generic="Azithromycin")
        self.assertEqual(output[0][1],"REVIEW")
        email=BytesParser(policy=policy.default).parsebytes(
            (self.root/"drafts"/"ACD_T1_Top_5.eml").read_bytes())
        self.assertEqual(email["To"],"rse@example.com")
        self.assertIn("ase@example.com",email["Cc"])
        self.assertIn("zsi@example.com",email["Cc"])
        self.assertEqual(list(email.iter_attachments()),[])
        self.assertIn("text/html",[p.get_content_type() for p in email.walk()])

if __name__=="__main__":
    unittest.main()
