"""Local DuckDB analytics. Confidential inputs are never sent to GitHub."""
import csv, io, re, sys
from pathlib import Path
from email.message import EmailMessage
import duckdb
from openpyxl import load_workbook

ROOT=Path(sys.executable).resolve().parent if getattr(sys,"frozen",False) else Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
DATA.mkdir(exist_ok=True)
DB=DATA/"prescriber.duckdb"
FIELDS=["entry_date","rx_date","source_type","rx_serial","dr_code","dr_name","degree","specialty","address","acd_mpe","acd_ase","acd_rse","ccd_mpe","ccd_ase","ccd_rse","dosage","product","strength","brand","product_code","company","bpl_division","therapy","generic"]
HEADERS=["RSE","ASE","Territory","Rank","Doctor Code","Prescriber","Specialty","Prescriptions","Product Rows","Address"]

def connect():
    db=duckdb.connect(str(DB))
    db.execute("SET memory_limit='1GB'")
    db.execute("CREATE TABLE IF NOT EXISTS recipients (division VARCHAR,region VARCHAR,zone VARCHAR,rse_name VARCHAR,rse_email VARCHAR,ase_emails VARCHAR,zsi_name VARCHAR,zsi_email VARCHAR,audit_status VARCHAR)")
    return db

def import_audit(db,path):
    with open(path,encoding="utf-8-sig",newline="") as f:
        records=list(csv.DictReader(f))
    db.execute("DELETE FROM recipients")
    payload=[("ACD",r.get("Region",""),r.get("Zone",""),r.get("RSE Name",""),r.get("To",""),r.get("ASE CC list",""),r.get("ZSI Name",""),r.get("ZSI CC",""),r.get("Status","")) for r in records]
    if payload:db.executemany("INSERT INTO recipients VALUES (?,?,?,?,?,?,?,?,?)",payload)
    return len(payload)

def import_rx(db,path,progress=None):
    path=Path(path)
    csvpath=DATA/"_staging_rx.csv"
    count=0
    try:
        wb=load_workbook(path,read_only=True,data_only=True)
        ws=wb.worksheets[0]
        with open(csvpath,"w",encoding="utf-8",newline="") as f:
            w=csv.writer(f)
            w.writerow(FIELDS)
            for i,row in enumerate(ws.iter_rows(values_only=True)):
                if i==0:continue
                values=["" if x is None else str(x) for x in row[:24]]
                if not any(values[:6]):continue
                w.writerow((values+[""]*24)[:24])
                count+=1
                if progress and count%20000==0:progress(count)
        wb.close()
        escaped=str(csvpath).replace("'","''")
        db.execute("CREATE OR REPLACE TABLE rx AS SELECT * FROM read_csv_auto('"+escaped+"',header=true,all_varchar=true)")
        db.execute("""CREATE OR REPLACE TABLE prescribers AS
        WITH expanded AS (
            SELECT 'ACD' division,acd_rse region,acd_ase ase,acd_mpe territory,dr_code,dr_name,specialty,address,
            concat_ws('|',rx_date,source_type,rx_serial,acd_mpe,dr_code) rx_key FROM rx WHERE trim(coalesce(acd_mpe,''))<>''
            UNION ALL
            SELECT 'CCD',ccd_rse,ccd_ase,ccd_mpe,dr_code,dr_name,specialty,address,
            concat_ws('|',rx_date,source_type,rx_serial,ccd_mpe,dr_code) FROM rx WHERE trim(coalesce(ccd_mpe,''))<>''
        )
        SELECT division,region,ase,territory,dr_code,max(dr_name) dr_name,max(specialty) specialty,max(address) address,
        count(DISTINCT rx_key) prescriptions,count(*) product_rows
        FROM expanded WHERE trim(coalesce(dr_code,''))<>'' GROUP BY 1,2,3,4,5""")
        return count
    finally:
        csvpath.unlink(missing_ok=True)

def has_rankings(db):
    return bool(db.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='prescribers'").fetchone()[0])

def choices(db,division,column,region="",ase=""):
    if not has_rankings(db):return []
    if column not in ("region","ase","territory"):raise ValueError("Invalid filter")
    parts=["division=?","trim(coalesce("+column+",''))<>''"]
    args=[division]
    if region and column!="region":parts.append("region=?");args.append(region)
    if ase and column=="territory":parts.append("ase=?");args.append(ase)
    return [r[0] for r in db.execute("SELECT DISTINCT "+column+" FROM prescribers WHERE "+" AND ".join(parts)+" ORDER BY 1",args).fetchall()]

def ranking(db,division="ACD",top_n=10,region="",ase="",territory=""):
    if not has_rankings(db):return []
    where=["division=?"]
    args=[division]
    for col,val in (("region",region),("ase",ase),("territory",territory)):
        if val:where.append(col+"=?");args.append(val)
    args.append(max(1,min(20,int(top_n))))
    sql="""WITH ranked AS (SELECT region,ase,territory,dr_code,dr_name,specialty,address,prescriptions,product_rows,
    row_number() OVER(PARTITION BY region,ase,territory ORDER BY prescriptions DESC,dr_code) AS rank
    FROM prescribers WHERE """+" AND ".join(where)+""")
    SELECT region,ase,territory,rank,dr_code,dr_name,specialty,prescriptions,product_rows,address
    FROM ranked WHERE rank<=? ORDER BY region,ase,territory,rank"""
    return db.execute(sql,args).fetchall()

def write_csv(rows,path):
    with open(path,"w",newline="",encoding="utf-8-sig") as f:
        w=csv.writer(f);w.writerow(HEADERS);w.writerows(rows)

def generate_drafts(db,outdir,top_n=10):
    outdir=Path(outdir);outdir.mkdir(parents=True,exist_ok=True)
    manifest=[]
    for region,zone,name,email,ases,zname,zemail,status in db.execute("SELECT region,zone,rse_name,rse_email,ase_emails,zsi_name,zsi_email,audit_status FROM recipients WHERE division='ACD' ORDER BY region").fetchall():
        rows=ranking(db,"ACD",top_n,region=region)
        valid=bool(email and re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",email) and rows)
        msg=EmailMessage()
        if valid:msg["To"]=email
        else:msg["X-Recipient-Review"]="BLOCKED: missing RSE address or Rx data"
        cc=list(dict.fromkeys(x.strip() for x in (ases or "").split(";")+[zemail or ""] if x.strip()))
        if cc:msg["Cc"]=", ".join(cc)
        msg["Subject"]=f"[DRAFT] ACD {region} — Top {top_n} prescribers by territory"
        msg.set_content("Dear "+(name or "Regional Sales Executive")+",\n\nAttached is the territory-level prescriber report for your region.\n\nPlease verify recipients, reporting period and ranking definitions before sending.\n\nThis is a draft and was not sent.\n")
        if rows:
            stream=io.StringIO();w=csv.writer(stream);w.writerow(HEADERS);w.writerows(rows)
            msg.add_attachment(stream.getvalue().encode("utf-8-sig"),maintype="text",subtype="csv",filename=f"ACD_{region}_Top_{top_n}.csv")
        filename=f"ACD_{region}_Top_{top_n}.eml"
        (outdir/filename).write_bytes(msg.as_bytes())
        manifest.append([region,"REVIEW" if valid else "BLOCKED",len(rows),filename])
    write_csv_manifest=outdir/"draft_manifest.csv"
    with open(write_csv_manifest,"w",encoding="utf-8-sig",newline="") as f:
        w=csv.writer(f);w.writerow(["Region","Status","Rows","File"]);w.writerows(manifest)
    return manifest
