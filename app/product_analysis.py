"""Brand and generic analytics on the locally imported Rx workbook."""
import duckdb

def has_product_index(db):
    return bool(db.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name='rx_items'"
    ).fetchone()[0])

def create_product_index(db):
    """Create searchable ACD/CCD product facts inside the import transaction."""
    db.execute("""CREATE OR REPLACE TABLE rx_items AS
        SELECT 'ACD' AS division,acd_rse AS region,acd_ase AS ase,
          acd_mpe AS territory,dr_code,dr_name,specialty,
          trim(coalesce(brand,'')) AS brand,trim(coalesce(generic,'')) AS generic,
          concat_ws('|',rx_date,source_type,rx_serial,acd_mpe,dr_code) AS rx_key
        FROM rx WHERE trim(coalesce(acd_mpe,''))<>'' AND trim(coalesce(dr_code,''))<>''
        UNION ALL
        SELECT 'CCD',ccd_rse,ccd_ase,ccd_mpe,dr_code,dr_name,specialty,
          trim(coalesce(brand,'')),trim(coalesce(generic,'')),
          concat_ws('|',rx_date,source_type,rx_serial,ccd_mpe,dr_code)
        FROM rx WHERE trim(coalesce(ccd_mpe,''))<>'' AND trim(coalesce(dr_code,''))<>''""")

def product_choices(db,division,kind,region="",ase="",territory="",brand="",generic=""):
    if not has_product_index(db):return []
    if kind not in ("brand","generic"):raise ValueError("Invalid product filter")
    where=["division=?",f"trim(coalesce({kind},''))<>''"]
    args=[division]
    for column,value in (("region",region),("ase",ase),("territory",territory)):
        if value:where.append(column+"=?");args.append(value)
    if kind=="brand" and generic:where.append("generic=?");args.append(generic)
    if kind=="generic" and brand:where.append("brand=?");args.append(brand)
    return [r[0] for r in db.execute(
        f"SELECT DISTINCT {kind} FROM rx_items WHERE "+" AND ".join(where)
        +f" ORDER BY {kind}",args).fetchall()]

def filtered_rankings(db,division="ACD",top_n=10,region="",ase="",territory="",brand="",generic=""):
    """Return ranked doctor prescriptions and apparent preference percentage.

    Denominator: all distinct observed Rx for a doctor within the same territory
    and selected generic (when provided); otherwise all observed Rx for that
    doctor/territory. Do not interpret this as true/causal preference.
    """
    if not has_product_index(db):
        raise ValueError("Re-import your Excel workbook to enable Brand/Generic filters.")
    where=["i.division=?"]
    args=[division]
    for col,value in (("region",region),("ase",ase),("territory",territory),
                      ("brand",brand),("generic",generic)):
        if value:where.append("i."+col+"=?");args.append(value)
    baseline=["division=?"]
    baseline_args=[division]
    if generic:baseline.append("generic=?");baseline_args.append(generic)
    sql="""WITH matching AS (
        SELECT i.division,i.region,i.ase,i.territory,i.dr_code,
          MAX(i.dr_name) AS dr_name,MAX(i.specialty) AS specialty,
          count(DISTINCT rx_key) AS selected_rx, count(*) AS item_rows
        FROM rx_items i WHERE """+" AND ".join(where)+"""
        GROUP BY 1,2,3,4,5
      ), reference AS (
        SELECT division,region,ase,territory,dr_code,count(DISTINCT rx_key) AS total_rx
        FROM rx_items WHERE """+" AND ".join(baseline)+"""
        GROUP BY 1,2,3,4,5
      ), ordered AS (
        SELECT m.region,m.ase,m.territory,m.dr_code,m.dr_name,m.specialty,
           m.selected_rx,m.item_rows,
           CASE WHEN r.total_rx>0 THEN round(100.0*m.selected_rx/r.total_rx,1) END AS app_pct,
           row_number() over(partition by m.region,m.ase,m.territory
             order by m.selected_rx DESC,m.dr_code) AS place
        FROM matching m JOIN reference r USING (division,region,ase,territory,dr_code)
      )
      SELECT region,ase,territory,place,dr_code,dr_name,specialty,
             selected_rx,item_rows,'' AS address,app_pct
      FROM ordered WHERE place<=?
      ORDER BY region,ase,territory,place"""
    return db.execute(sql,args+baseline_args+[max(1,min(20,int(top_n)))]).fetchall()

def breakdown(db,division,region,generic="",brand=""):
    """Generic-scope brand counts, counting each Rx once per brand."""
    if not has_product_index(db):raise ValueError("Rx item index not imported.")
    clauses=["division=?","region=?","trim(coalesce(brand,''))<>''"]
    args=[division,region]
    if generic:clauses.append("generic=?");args.append(generic)
    rows=db.execute(
        "SELECT brand,COUNT(DISTINCT rx_key) AS rx "
        "FROM rx_items WHERE "+" AND ".join(clauses)
        +" GROUP BY brand ORDER BY rx DESC,brand",args).fetchall()
    return [(str(k),int(v)) for k,v in rows]

def doctor_brand_details(db,division,region,generic="",brand=""):
    """All doctor/brand observations in the selected region and generic."""
    clauses=["division=?","region=?"]
    args=[division,region]
    if generic:clauses.append("generic=?");args.append(generic)
    sql="""SELECT ase,territory,dr_code,max(dr_name),max(specialty),brand,
      count(DISTINCT rx_key) AS rx FROM rx_items WHERE """+" AND ".join(clauses)+"""
      GROUP BY 1,2,3,6 ORDER BY ase,territory,dr_code,brand"""
    return db.execute(sql,args).fetchall()

def report_date_range(db):
    """Use observed date range; avoid claiming a national survey."""
    try:
        vals=db.execute("SELECT min(rx_date),max(rx_date) FROM rx WHERE rx_date IS NOT NULL AND rx_date<>''").fetchone()
        return " to ".join(str(x) for x in vals if x) or "Imported dataset"
    except Exception:return "Imported dataset"
