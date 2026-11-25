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
            generic VARCHAR,rx_key VARCHAR,company VARCHAR)""")
        self.db.executemany("INSERT INTO rx_items VALUES (?,?,?,?,?,?,?,?,?,?,?)",[
            ("ACD","T1","T10","T11","D1","Dr Alpha","GP","Azithrocin","Azithromycin","1","Beximco Pharmaceuticals PLC"),
            ("ACD","T1","T10","T11","D1","Dr Alpha","GP","Az","Azithromycin","2","Aristopharma"),
            ("ACD","T1","T10","T11","D1","Dr Alpha","GP","Az","Azithromycin","3","Aristopharma"),
            ("ACD","T1","T10","T11","D2","Dr Beta","Pediatrics","Az","Azithromycin","4","Aristopharma"),
            ("ACD","T1","T10","T11","D2","Dr Beta","Pediatrics","Az","Azithromycin","5","Aristopharma")
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

    def test_beximco_and_competitor_generic_rx_shares(self):
        shares=product_analysis.generic_rx_shares(
            self.db,"ACD","Azithromycin",region="T1",brand="Azithrocin")
        self.assertEqual(shares["total_rx"],5)
        self.assertEqual(shares["beximco_share"],20.0)
        self.assertEqual(shares["competitor_share"],80.0)
        self.assertEqual(shares["brand_share"],20.0)
        self.assertEqual(shares["overlap_rx"],0)
        self.assertEqual(shares["unclassified_rx"],0)
        self.assertEqual(product_analysis.competitor_brand_shares(
            self.db,"ACD","Azithromycin","T1"),[("Az",4,80.0)])
        self.db.execute("""INSERT INTO rx_items VALUES
            ('ACD','T1','T10','T11','D1','Dr Alpha','GP','Az','Azithromycin','1','Aristopharma')""")
        overlap=product_analysis.generic_rx_shares(
            self.db,"ACD","Azithromycin",region="T1")
        self.assertEqual(overlap["overlap_rx"],1)
        self.assertEqual(overlap["beximco_share"],20.0)
        self.assertEqual(overlap["competitor_share"],100.0)
        self.db.execute("""INSERT INTO rx_items VALUES
            ('ACD','T1','T10','T11','D1','Dr Alpha','GP','Mystery','Azithromycin','1',NULL)""")
        unknown=product_analysis.generic_rx_shares(
            self.db,"ACD","Azithromycin",region="T1")
        self.assertEqual(unknown["unclassified_rx"],1)

    def test_three_share_metrics_and_regional_competitor_sort(self):
        # Doctor D1: 3/3 observed prescriptions are azithromycin;
        # Azithrocin presence 1/3, competitor presence 2/3.
        rows=product_analysis.prescriber_share_rankings(
            self.db,"ACD",10,region="T1",generic="Azithromycin",brand="Azithrocin")
        self.assertEqual([r[4] for r in rows],["D1","D2"])
        self.assertEqual(rows[0][7:10],(3,1,2))
        self.assertEqual(rows[0][10:13],(100.0,33.3,66.7))
        self.assertEqual(rows[1][7:10],(2,0,2))
        self.assertEqual(rows[1][10:13],(100.0,0.0,100.0))
        summary=product_analysis.generic_scope_summary(
            self.db,"ACD","Azithromycin","T1",brand="Azithrocin")
        self.assertEqual(summary["generic_share"],100.0)
        self.assertEqual(summary["brand_share"],20.0)
        self.assertEqual(summary["competitor_share"],80.0)
        regional=product_analysis.regional_competitor_shares(
            self.db,"ACD","Azithromycin",region="T1")
        self.assertEqual(regional,[("T1","Az",4,5,80.0)])

    def test_regional_competitors_do_not_inherit_territory_filter(self):
        self.db.execute("""INSERT INTO rx_items VALUES
           ('ACD','T1','T20','T21','D3','Dr Gamma','GP',
           'Zimax','Azithromycin','6','Square')""")
        regional=product_analysis.regional_competitor_shares(
            self.db,"ACD","Azithromycin",region="T1")
        self.assertEqual(regional[0],("T1","Az",4,6,66.7))
        self.assertEqual(regional[1],("T1","Zimax",1,6,16.7))
        local=product_analysis.prescriber_share_rankings(
            self.db,"ACD",10,region="T1",ase="T10",territory="T11",
            generic="Azithromycin",brand="Azithrocin")
        self.assertEqual(len(local),2)

    def test_mail_top_n_is_per_territory_not_region(self):
        # Three doctor codes in one region, distributed across two MPEs.
        self.db.execute("""INSERT INTO rx_items VALUES
            ('ACD','T1','T20','T21','D3','Dr Gamma','GP','Az',
             'Azithromycin','6','Aristopharma')""")
        one=html_report.build_region_report(
            self.db,"ACD","T1",top_n=1,brand="Azithrocin",
            generic="Azithromycin")
        self.assertEqual(one["top_n"],1)
        self.assertEqual(one["territory_top_rows"],2)
        self.assertIn("Top 1 prescribers in each territory",one["html"])
        self.assertIn("Regional competitor-wise Rx share",one["html"])
        self.assertIn("Aristopharma",one["html"])
        two=html_report.build_region_report(
            self.db,"ACD","T1",top_n=2,brand="Azithrocin",
            generic="Azithromycin")
        self.assertEqual(two["territory_top_rows"],3)
        self.assertEqual(two["top_n"],2)

    def test_opportunities_require_competitor_and_no_target(self):
        self.db.execute("""INSERT INTO rx_items VALUES
            ('ACD','T1','T10','T11','D3','Dr Other','GP','Unknown',
             'Azithromycin','6',NULL)""")
        report=html_report.build_region_report(
            self.db,"ACD","T1",top_n=2,brand="Azithrocin",
            generic="Azithromycin")
        self.assertEqual(report["opportunities_total"],1)
        self.assertEqual(report["opportunities_shown"],1)
        self.assertIn("Showing 1 of 1",report["html"])
        opportunity_html=report["html"].split("Competitor opportunity review",1)[1]
        opportunity_html=opportunity_html.split("Territory review",1)[0]
        self.assertIn("Dr Beta",opportunity_html)
        self.assertNotIn("Dr Other",opportunity_html)

    def test_mobile_html_breakpoint_and_unsent_metadata(self):
        out=core.generate_drafts(self.db,self.root/"mobile_drafts",top_n=1,
            brand="Azithrocin",generic="Azithromycin",sender="sender@example.com")
        self.assertEqual(out[0][1],"REVIEW")
        msg=BytesParser(policy=policy.default).parsebytes(
            (self.root/"mobile_drafts"/"ACD_T1_Top_1.eml").read_bytes())
        self.assertEqual(msg["From"],"sender@example.com")
        self.assertEqual(msg["X-Unsent"],"1")
        self.assertIsNotNone(msg["Date"])
        self.assertIsNotNone(msg["Message-ID"])
        self.assertEqual(list(msg.iter_attachments()),[])
        content=msg.get_body(preferencelist=("html",)).get_content()
        self.assertIn("@media only screen",content)
        self.assertIn("data-label",content)
        self.assertIn("font-family:Tahoma",content)
        self.assertIn("Top 1 prescribers in each territory",content)

    def test_formatted_html_email_without_csv_attachment(self):
        report=html_report.build_region_report(
            self.db,"ACD","T1",top_n=5,brand="Azithrocin",
            generic="Azithromycin",recipient_name="RSE Test")
        self.assertEqual(report["rx"],5)
        self.assertEqual(report["target_rx"],1)
        self.assertIn("20.0%",report["html"])
        self.assertIn("80.0%",report["html"])
        self.assertIn("font-family:Tahoma",report["html"])
        self.assertIn('width="640"',report["html"])
        self.assertIn("Generic Rx share",report["html"])
        self.assertIn("Azithrocin Rx share",report["html"])
        self.assertIn("Competitor Rx share",report["html"])
        self.assertIn("Apparent Prescription Preference",report["html"])
        self.assertIn("Top observed prescribers",report["html"])
        self.assertIn("Competitor opportunity review",report["html"])
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
