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
          trim(coalesce(company,'')) AS company,
          concat_ws('|',rx_date,source_type,rx_serial,acd_mpe,dr_code) AS rx_key
        FROM rx WHERE trim(coalesce(acd_mpe,''))<>'' AND trim(coalesce(dr_code,''))<>''
        UNION ALL
        SELECT 'CCD',ccd_rse,ccd_ase,ccd_mpe,dr_code,dr_name,specialty,
          trim(coalesce(brand,'')),trim(coalesce(generic,'')),
          trim(coalesce(company,'')),
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
           CASE WHEN ? AND r.total_rx>0 THEN round(100.0*m.selected_rx/r.total_rx,1) END AS app_pct,
           row_number() over(partition by m.region,m.ase,m.territory
             order by m.selected_rx DESC,m.dr_code) AS place
        FROM matching m JOIN reference r USING (division,region,ase,territory,dr_code)
      )
      SELECT region,ase,territory,place,dr_code,dr_name,specialty,
             selected_rx,item_rows,'' AS address,app_pct
      FROM ordered WHERE place<=?
      ORDER BY region,ase,territory,place"""
    return db.execute(sql,args+baseline_args+[bool(brand),max(1,min(20,int(top_n)))]).fetchall()

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


def manufacturer_bucket(value):
    """Categorize the actual Company Name field. Empty is not a competitor."""
    import re
    normalized=re.sub(r"[^a-z0-9]","",str(value or "").lower())
    if not normalized:
        return "Unclassified"
    if normalized.startswith("beximco"):
        return "Beximco"
    return "Competitor"


def generic_rx_shares(db,division,generic,region="",ase="",territory="",brand=""):
    """Distinct-prescription presence shares within a single generic.

    Manufacturer affiliation must come from the imported Company Name, not
    an inferred brand list. Brand-specific shares use the same denominator.
    Shares may overlap if a single Rx lists multiple manufacturers/brands.
    No generic: return None rather than presenting misleading cross-generic share.
    """
    if not generic:
        return None
    if not has_product_index(db):
        raise ValueError("Re-import the Rx workbook to enable manufacturer shares.")
    fields={r[1] for r in db.execute("PRAGMA table_info('rx_items')").fetchall()}
    if "company" not in fields:
        raise ValueError("Re-import the Rx workbook to add Company Name mapping.")
    parts=["division=?","generic=?"]
    args=[division,generic]
    for name,value in (("region",region),("ase",ase),("territory",territory)):
        if value:parts.append(name+"=?");args.append(value)
    predicate=" AND ".join(parts)
    # A company is never guessed from its brand name. A generic prescription
    # with both competitor and Beximco brand rows counts once in each bucket.
    # Brand share is counted by a distinct Rx membership flag.
    sql="""WITH src AS (
      SELECT rx_key,brand,
        CASE WHEN trim(coalesce(company,''))='' THEN 'Unclassified'
             WHEN regexp_replace(lower(company),'[^a-z0-9]','','g') LIKE 'beximco%'
               THEN 'Beximco'
             ELSE 'Competitor' END AS owner
      FROM rx_items WHERE """+predicate+"""
    ), per_rx AS (
      SELECT rx_key,
        max(CASE WHEN owner='Beximco' THEN 1 ELSE 0 END) AS bpl,
        max(CASE WHEN owner='Competitor' THEN 1 ELSE 0 END) AS competitor,
        max(CASE WHEN owner='Unclassified' THEN 1 ELSE 0 END) AS unclassified,
        max(CASE WHEN brand=? THEN 1 ELSE 0 END) AS selected_brand
      FROM src GROUP BY rx_key
    )
    SELECT count(*) AS total_rx,coalesce(sum(bpl),0),coalesce(sum(competitor),0),
      coalesce(sum(unclassified),0),coalesce(sum(CASE WHEN bpl=1 AND competitor=1 THEN 1 ELSE 0 END),0),
      coalesce(sum(selected_brand),0)
    FROM per_rx"""
    total,bex,competitor,unknown,overlap,selected=db.execute(sql,args+[brand or "\0"]).fetchone()
    total=int(total)
    def share(count):
        return round(100*int(count)/total,1) if total else None
    result={"division":division,"generic":generic,"brand":brand,
        "total_rx":total,"beximco_rx":int(bex),"competitor_rx":int(competitor),
        "unclassified_rx":int(unknown),"overlap_rx":int(overlap),
        "brand_rx":int(selected),"beximco_share":share(bex),
        "competitor_share":share(competitor),"unclassified_share":share(unknown),
        "brand_share":share(selected)}
    return result


def competitor_brand_shares(db,division,generic,region="",ase="",territory="",limit=20):
    """Top competing brands using generic denominator; manufacturer-classified."""
    base=generic_rx_shares(db,division,generic,region,ase,territory)
    if not base or not base["total_rx"]:return []
    where=["division=?","generic=?"]
    args=[division,generic]
    for column,value in (("region",region),("ase",ase),("territory",territory)):
        if value:where.append(column+"=?");args.append(value)
    sql="""SELECT brand,count(DISTINCT rx_key) AS n
        FROM rx_items WHERE """+" AND ".join(where)+"""
        AND trim(coalesce(brand,''))<>''
        AND trim(coalesce(company,''))<>''
        AND regexp_replace(lower(company),'[^a-z0-9]','','g') NOT LIKE 'beximco%'
        GROUP BY brand ORDER BY n DESC,brand LIMIT ?"""
    rows=db.execute(sql,args+[max(1,min(100,int(limit)))]).fetchall()
    return [(brand,int(n),round(100*n/base["total_rx"],1)) for brand,n in rows]


def prescriber_share_rankings(db,division="ACD",top_n=10,region="",ase="",territory="",generic="",brand=""):
    """Per-territory ranks based on generic Rx volume, then selected brand Rx.

    Generic Rx share = doctor generic distinct Rx / doctor's all distinct Rx.
    Selected Brand Rx share = doctor target brand Rx / doctor generic Rx.
    Competitor Rx share = doctor generic Rx featuring non-Beximco company /
                          doctor generic distinct Rx.
    No generic selection: do not manufacture meaningful share columns.
    """
    if not generic:
        return []
    if not has_product_index(db):
        raise ValueError("Re-import the Rx workbook to enable product shares.")
    base=["division=?"]
    args=[division]
    for k,v in (("region",region),("ase",ase),("territory",territory)):
        if v:base.append(k+"=?");args.append(v)
    wh=" AND ".join(base)
    sql="""WITH per_rx AS (
      SELECT region,ase,territory,dr_code,rx_key,
        max(dr_name) AS dr_name,max(specialty) AS specialty,
        max(CASE WHEN generic=? THEN 1 ELSE 0 END) AS has_generic,
        max(CASE WHEN generic=? AND brand=? THEN 1 ELSE 0 END) AS has_brand,
        max(CASE WHEN generic=? AND trim(coalesce(company,''))<>'' AND
          regexp_replace(lower(company),'[^a-z0-9]','','g') NOT LIKE 'beximco%'
          THEN 1 ELSE 0 END) AS has_competitor
      FROM rx_items WHERE """+wh+"""
      GROUP BY region,ase,territory,dr_code,rx_key
    ), doctor AS (
      SELECT region,ase,territory,dr_code,max(dr_name) dr_name,max(specialty) specialty,
        count(*) AS all_rx,sum(has_generic) AS generic_rx,
        sum(has_brand) AS brand_rx,sum(has_competitor) AS competitor_rx
      FROM per_rx GROUP BY 1,2,3,4 HAVING sum(has_generic)>0
    ), ordered AS (
      SELECT *,
        round(100.0*generic_rx/nullif(all_rx,0),1) AS generic_share,
        CASE WHEN ? THEN round(100.0*brand_rx/nullif(generic_rx,0),1) END AS brand_share,
        round(100.0*competitor_rx/nullif(generic_rx,0),1) AS competitor_share,
        row_number() over(partition by region,ase,territory
            order by generic_rx DESC, brand_rx DESC, competitor_rx DESC,dr_code) AS place
      FROM doctor
    )
    SELECT region,ase,territory,place,dr_code,dr_name,specialty,generic_rx,
      brand_rx,competitor_rx,generic_share,brand_share,competitor_share
    FROM ordered WHERE place<=?
    ORDER BY region,ase,territory,place"""
    bind=[generic,generic,brand or "\0",generic]+args+[bool(brand),max(1,min(20,int(top_n)))]
    return db.execute(sql,bind).fetchall()


def generic_scope_summary(db,division,generic,region="",ase="",territory="",brand=""):
    """Summaries across the chosen scope; shares have distinct Rx denominators."""
    if not generic:return None
    where=["division=?"];args=[division]
    for k,v in (("region",region),("ase",ase),("territory",territory)):
        if v:where.append(k+"=?");args.append(v)
    total=db.execute("SELECT count(DISTINCT rx_key) FROM rx_items WHERE "+
                     " AND ".join(where),args).fetchone()[0]
    detail=generic_rx_shares(db,division,generic,region,ase,territory,brand)
    detail["all_rx"]=int(total)
    detail["generic_share"]=round(100*detail["total_rx"]/total,1) if total else None
    return detail


def regional_competitor_shares(db,division,generic,region="",limit_per_region=25):
    """Competitor Rx ranking scoped by region ONLY, never ASE or territory.

    With 'All regions' selected, each returned row explicitly identifies its
    regional denominator, avoiding comparisons against national totals.
    """
    if not generic:return []
    if not has_product_index(db):return []
    fields={r[1] for r in db.execute("PRAGMA table_info('rx_items')").fetchall()}
    if "company" not in fields:raise ValueError("Re-import data to index Company Name")
    where=["division=?","generic=?"];args=[division,generic]
    if region:where.append("region=?");args.append(region)
    sql="""WITH scoped AS (
      SELECT region,brand,company,rx_key FROM rx_items WHERE """+" AND ".join(where)+"""
    ), totals AS (
      SELECT region,count(DISTINCT rx_key) generic_rx FROM scoped GROUP BY region
    ), competitor AS (
      SELECT region,brand,count(DISTINCT rx_key) brand_rx
      FROM scoped WHERE trim(coalesce(brand,''))<>'' AND
        trim(coalesce(company,''))<>'' AND
        regexp_replace(lower(company),'[^a-z0-9]','','g') NOT LIKE 'beximco%'
      GROUP BY region,brand
    ), ranked AS (
      SELECT c.region,c.brand,c.brand_rx,t.generic_rx,
        round(100.0*c.brand_rx/nullif(t.generic_rx,0),1) share,
        row_number() over(partition by c.region ORDER BY c.brand_rx DESC,c.brand) position
      FROM competitor c JOIN totals t ON c.region=t.region
    )
    SELECT region,brand,brand_rx,generic_rx,share
    FROM ranked WHERE position<=? ORDER BY region,brand_rx DESC,brand"""
    return db.execute(sql,args+[max(1,min(100,int(limit_per_region)))]).fetchall()
