"""Local DuckDB analytics. Confidential inputs are never sent to GitHub."""
import csv, io, re, sys, shutil, uuid
from pathlib import Path
from email.message import EmailMessage
import duckdb
from openpyxl import load_workbook
from product_analysis import create_product_index, filtered_rankings
from html_report import build_region_report

ROOT=Path(sys.executable).resolve().parent if getattr(sys,"frozen",False) else Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
DATA.mkdir(exist_ok=True)
DB=DATA/"prescriber.duckdb"
FIELDS=["entry_date","rx_date","source_type","rx_serial","dr_code","dr_name","degree","specialty","address","acd_mpe","acd_ase","acd_rse","ccd_mpe","ccd_ase","ccd_rse","dosage","product","strength","brand","product_code","company","bpl_division","therapy","generic"]
HEADERS=["RSE","ASE","Territory","Rank","Doctor Code","Prescriber","Specialty","Prescriptions","Product Rows","Address"]

def connect(memory_gb=4):
    memory_gb=max(1,min(16,int(memory_gb)))
    db=duckdb.connect(str(DB))
    db.execute(f"SET memory_limit='{memory_gb}GB'")
    db.execute(f"SET temp_directory='{str(DATA / 'duckdb_tmp').replace(chr(39), chr(39)*2)}'")
    db.execute("CREATE TABLE IF NOT EXISTS recipients (division VARCHAR,region VARCHAR,zone VARCHAR,rse_name VARCHAR,rse_email VARCHAR,ase_emails VARCHAR,zsi_name VARCHAR,zsi_email VARCHAR,audit_status VARCHAR)")
    return db

def import_audit(db,path):
    with open(path,encoding="utf-8-sig",newline="") as f:
        records=list(csv.DictReader(f))
    db.execute("DELETE FROM recipients")
    payload=[("ACD",r.get("Region",""),r.get("Zone",""),r.get("RSE Name",""),r.get("To",""),r.get("ASE CC list",""),r.get("ZSI Name",""),r.get("ZSI CC",""),r.get("Status","")) for r in records]
    if payload:db.executemany("INSERT INTO recipients VALUES (?,?,?,?,?,?,?,?,?)",payload)
    return len(payload)

SOURCE_HEADERS=[
    "Entry Date","Prescription Date","Rx Source Type","Rx Sl No",
    "Dr Code","Dr Name/Institute Name","Doc Degree","Doc Specialty",
    "Detail Address","ACD MPE","ACD ASE","ACD RSE",
    "CCD. MPE Code","CCD.ASE Code","CCD. RSE Code",
    "Dosage Description","Product Name","Strength","Brand Name",
    "SFE Product Code","Company Name","Division BPL","TG_l(All)","Generic Name"
]

def available_sheets(path):
    wb=load_workbook(path,read_only=True,data_only=True)
    try:
        return list(wb.sheetnames)
    finally:
        wb.close()

def _normalized(value):
    return re.sub(r"[^a-z0-9]","",str(value or "").lower())

def _header_mapping(header):
    actual={}
    for index, name in enumerate(header):
        normalized=_normalized(name)
        if normalized:
            if normalized in actual:
                raise ValueError(f"Duplicate Excel header: {name!r}")
            actual[normalized]=index
    positions=[]
    missing=[]
    for source, canonical in zip(SOURCE_HEADERS,FIELDS):
        position=actual.get(_normalized(source),actual.get(_normalized(canonical)))
        if position is None:missing.append(source)
        else:positions.append(position)
    if missing:
        raise ValueError("Missing required Excel headers: "+", ".join(missing)
            +". Found: "+", ".join(str(h) for h in header))
    return positions

def import_rx(db,path,progress=None,sheet_name="Sheet1",memory_gb=4):
    """Stream validated XLSX rows, then atomically replace DuckDB tables."""
    path=Path(path)
    if not path.is_file():raise FileNotFoundError(path)
    wb=load_workbook(path,read_only=True,data_only=True)
    staging=DATA/("_staging_rx_"+uuid.uuid4().hex+".csv")
    count=0
    started=False
    try:
        if sheet_name not in wb.sheetnames:
            raise ValueError(f"Worksheet {sheet_name!r} not found. Available sheets: "
                             +", ".join(repr(n) for n in wb.sheetnames))
        ws=wb[sheet_name]
        rows=ws.iter_rows(values_only=True)
        header=next(rows,None)
        if header is None:raise ValueError("Selected worksheet is empty")
        indices=_header_mapping(header)
        if ws.max_row and ws.max_row>1_048_576:
            raise ValueError("Worksheet exceeds Excel's maximum row count")
        free=shutil.disk_usage(DATA).free
        if free < max(512*1024*1024, path.stat().st_size*3):
            raise OSError("Insufficient disk space for streaming import; free at least 512 MB")
        with open(staging,"w",encoding="utf-8",newline="") as f:
            writer=csv.writer(f,quoting=csv.QUOTE_MINIMAL)
            writer.writerow(FIELDS)
            for excel_row,row in enumerate(rows,start=2):
                values=["" if row[i] is None else str(row[i])
                        for i in indices]
                if not any(values):continue
                if not values[4].strip():
                    raise ValueError(f"Missing Dr Code on Excel row {excel_row}")
                writer.writerow(values)
                count+=1
                if progress and count%20000==0:progress(count)
        if count==0:raise ValueError("No prescription data rows in the selected worksheet")
        escaped=str(staging).replace("'","''")
        column_sql="{"+", ".join("'"+field+"': 'VARCHAR'" for field in FIELDS)+"}"
        db.execute(f"SET memory_limit='{max(1,min(16,int(memory_gb)))}GB'")
        db.execute("BEGIN TRANSACTION")
        started=True
        db.execute(
            "CREATE OR REPLACE TABLE rx AS SELECT * FROM read_csv('"+escaped
            +"', auto_detect=false, columns="+column_sql
            +", header=true, delim=',', quote='"+chr(34)+"', escape='"+chr(34)+"'"
            +", max_line_size=10000000)"
        )
        loaded=db.execute("SELECT COUNT(*) FROM rx").fetchone()[0]
        if loaded!=count:
            raise ValueError(f"Import mismatch: Excel {count:,} rows, DuckDB {loaded:,} rows")
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
        create_product_index(db)
        db.execute("COMMIT")
        started=False
        return count
    except BaseException:
        if started:
            db.execute("ROLLBACK")
        raise
    finally:
        wb.close()
        staging.unlink(missing_ok=True)

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

def generate_drafts(db,outdir,top_n=10,brand="",generic="",division="ACD"):
    """Create unsent email drafts with HTML body, no CSV attachment.

    Blocking rules never put recipients or prescriber data in invalid drafts.
    Recipient routing is currently validated for ACD only.
    """
    if division!="ACD":
        raise ValueError("CCD routing has not yet been validated; only ACD drafts are supported.")
    outdir=Path(outdir);outdir.mkdir(parents=True,exist_ok=True)
    manifest=[]
    for region,zone,name,email,ases,zname,zemail,status in db.execute(
        "SELECT region,zone,rse_name,rse_email,ase_emails,zsi_name,zsi_email,audit_status "
        "FROM recipients WHERE division='ACD' ORDER BY region").fetchall():
        def good(value):
            return bool(value and re.fullmatch(r"[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+",value))
        cc_candidates=[e.strip() for e in (ases or "").replace(",", ";").split(";") if e.strip()]
        cc_candidates.append(zemail or "")
        invalid_cc=[e for e in cc_candidates if e and not good(e)]
        unique_cc=list(dict.fromkeys(
            e for e in cc_candidates if good(e) and e.lower()!=(email or "").lower()))
        permitted=(status=="Ready" and good(email) and good(zemail) and not invalid_cc)
        report=None
        if permitted:
            report=build_region_report(db,"ACD",region,top_n,brand,generic,name)
            if report["rx"]==0:permitted=False
        msg=EmailMessage()
        msg["Subject"]=f"[DRAFT] ACD {region} — {brand or generic or 'Rx'} prescription review"
        if permitted:
            msg["To"]=email
            if unique_cc:msg["Cc"]=", ".join(unique_cc)
            msg.set_content(report["text"])
            msg.add_alternative(report["html"],subtype="html")
        else:
            msg["X-Recipient-Review"]="BLOCKED: recipient hierarchy or no matching Rx data"
            msg.set_content("BLOCKED DRAFT — Do not send.\n"
                            +"Region: "+str(region)+"\n"
                            +"Reason: "+str(status or "Missing routing")+"\n"
                            +"Matching prescription data may also be unavailable.\n")
        filename=f"ACD_{region}_Top_{max(1,min(20,int(top_n)))}.eml"
        (outdir/filename).write_bytes(msg.as_bytes())
        manifest.append([region,"REVIEW" if permitted else "BLOCKED",
                         report["rx"] if report else 0,filename,
                         "" if permitted else (status or "No matching Rx / invalid CC")])
    with open(outdir/"draft_manifest.csv","w",encoding="utf-8-sig",newline="") as f:
        w=csv.writer(f)
        w.writerow(["Region","Status","Scoped Rx count","File","Routing issue"])
        w.writerows(manifest)
    return manifest
