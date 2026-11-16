"""Local import of the ACD RSE–ZSI workbook. No personnel data is published with app."""
import re
from pathlib import Path
from openpyxl import load_workbook

ROUTING_SHEET="RSE Email Routing"
ZSI_SHEET="ZSI Directory"
EMAIL_RE=re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")

def _str(value):
    return str(value).strip() if value is not None else ""

def _records(ws):
    iterator=ws.iter_rows(values_only=True)
    headings=[_str(v) for v in next(iterator)]
    if len(headings)!=len(set(headings)):
        raise ValueError(f"Duplicate column headers in {ws.title}")
    for row_no,values in enumerate(iterator,start=2):
        if not any(_str(v) for v in values):continue
        yield row_no,dict(zip(headings,values))

def _need(ws,required):
    headers=[_str(cell.value) for cell in next(ws.iter_rows(max_row=1))]
    missing=set(required)-set(headers)
    if missing:raise ValueError(f"Sheet {ws.title!r} missing headers: {sorted(missing)}")

def import_hierarchy(db,filename):
    """Validate all 51 ACD regions, parent-zone relationships and addresses atomically.

    Retains existing ASE CC lists keyed by ACD region, since the routing workbook
    intentionally contains only the RSE and parent ZSI directory.
    Returns summary and exception regions.
    """
    filename=Path(filename)
    if not filename.is_file():raise FileNotFoundError(filename)
    wb=load_workbook(filename,read_only=True,data_only=True)
    try:
        if ROUTING_SHEET not in wb.sheetnames or ZSI_SHEET not in wb.sheetnames:
            raise ValueError(f"Expected sheets: {ROUTING_SHEET!r}, {ZSI_SHEET!r}")
        route=wb[ROUTING_SHEET]
        zs=wb[ZSI_SHEET]
        _need(route,["Division","Zone","Region Code","Region Name","RSE Name","ZSI Name","To (RSE)","CC (Parent ZSI)","Status"])
        _need(zs,["Division","Designation","Zone","ZSI Name","ZSI Email","Status"])
        zones={}
        for rowno,row in _records(zs):
            if _str(row.get("Division"))!="ACD":continue
            zone=_str(row["Zone"])
            if not zone or zone in zones:raise ValueError(f"Missing or duplicate zone at ZSI Directory row {rowno}")
            zones[zone]={"name":_str(row["ZSI Name"]),"email":_str(row["ZSI Email"]),"status":_str(row["Status"])}
        if len(zones)!=16:raise ValueError(f"Expected 16 ACD ZSI zones, got {len(zones)}")
        existing={region:ases for region,ases in db.execute(
            "SELECT region,ase_emails FROM recipients WHERE division='ACD'").fetchall()}
        seen=set()
        payload=[]
        issues=[]
        for rowno,row in _records(route):
            if _str(row.get("Division"))!="ACD":continue
            region=_str(row["Region Code"])
            zone=_str(row["Zone"])
            if not region or region in seen:
                raise ValueError(f"Missing or duplicate ACD region at routing row {rowno}: {region!r}")
            seen.add(region)
            if zone not in zones:raise ValueError(f"Unknown parent zone {zone!r} for region {region}")
            parent=zones[zone]
            rse=_str(row["RSE Name"])
            to=_str(row["To (RSE)"])
            zsi=_str(row["ZSI Name"])
            cc=_str(row["CC (Parent ZSI)"])
            declared=_str(row["Status"])
            problems=[]
            if zsi!=parent["name"]:problems.append("ZSI name disagrees with parent zone directory")
            if cc!=parent["email"]:problems.append("ZSI email disagrees with parent zone directory")
            if not EMAIL_RE.fullmatch(to):problems.append("Missing/invalid RSE email")
            if not EMAIL_RE.fullmatch(cc):problems.append("Missing/invalid parent ZSI email")
            if parent["status"]!="Active":problems.append("Parent ZSI is not active")
            if declared!="Ready":problems.append(declared or "Routing not ready")
            status="Ready" if not problems else "BLOCKED: "+"; ".join(dict.fromkeys(problems))
            if problems:issues.append({"region":region,"zone":zone,"reason":status})
            payload.append(("ACD",region,zone,rse,to,existing.get(region,"") or "",zsi,cc,status))
        if len(payload)!=51:raise ValueError(f"Expected 51 ACD regional entries, got {len(payload)}")
        db.execute("BEGIN TRANSACTION")
        try:
            db.execute("DELETE FROM recipients WHERE division='ACD'")
            db.executemany("INSERT INTO recipients VALUES (?,?,?,?,?,?,?,?,?)",payload)
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
        return {"regions":len(payload),"ready":len(payload)-len(issues),"blocked":len(issues),"issues":issues,"ase_lists_preserved":sum(bool(p[5]) for p in payload)}
    finally:
        wb.close()
