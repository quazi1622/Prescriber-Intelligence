"""Outlook and mobile-friendly regional Rx report from local DuckDB facts.

Counts are distinct observed Rx identifiers and all manufacturer classification
uses the imported Company Name. No source data leaves the local application.
"""
from collections import Counter, defaultdict

try:
    from .outlook_layout import render_report
    from .product_analysis import (
        generic_rx_shares, prescriber_share_rankings, report_date_range
    )
except ImportError:
    from outlook_layout import render_report
    from product_analysis import (
        generic_rx_shares, prescriber_share_rankings, report_date_range
    )


def num(value):
    return f"{int(value):,}"


def pct(part, total):
    return f"{100 * part / total:.1f}%" if total else "—"


def _company_is_competitor(company):
    import re
    normalized = re.sub(r"[^a-z0-9]", "", str(company or "").lower())
    return bool(normalized and not normalized.startswith("beximco"))


def build_region_report(db, division, region, top_n=10, brand="", generic="",
                        recipient_name=""):
    """Render every territory's Top N, regional competitors and true opportunities."""
    n = max(1, min(20, int(top_n)))
    if not db.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name='rx_items'"
    ).fetchone()[0]:
        raise ValueError("Re-import Excel Rx data to create the Brand/Generic index.")

    clauses = ["division=?", "region=?"]
    params = [division, region]
    if generic:
        clauses.append("generic=?")
        params.append(generic)
    where = " AND ".join(clauses)

    region_row = db.execute(
        "SELECT count(DISTINCT rx_key), count(DISTINCT dr_code), "
        "count(DISTINCT territory) FROM rx_items WHERE " + where, params
    ).fetchone()
    total, prescriber_count, territory_count = map(int, region_row)
    if not total:
        return {"html": "", "text": "", "rx": 0, "prescribers": 0,
                "target_rx": 0, "scope": generic or "All generics",
                "territories": 0, "top_n": n}

    brand_rows = db.execute(
        "SELECT brand, count(DISTINCT rx_key) AS cnt FROM rx_items WHERE "
        + where
        + " AND trim(coalesce(brand,''))<>'' "
          "GROUP BY brand ORDER BY cnt DESC, brand",
        params
    ).fetchall()
    brand_counts = [(str(b), int(c)) for b,c in brand_rows]
    selected_rx = int(db.execute(
        "SELECT count(DISTINCT rx_key) FROM rx_items WHERE "
        + where + " AND brand=?", params + [brand]
    ).fetchone()[0]) if brand else 0

    # Source index is already division- and territory-scoped. The ranking
    # function restarts row_number within each RSE/ASE/MPE combination.
    if generic:
        ranked = prescriber_share_rankings(
            db, division, n, region=region, generic=generic, brand=brand
        )
    else:
        doctor_rows = db.execute(
            """WITH grouped AS (
                SELECT region,ase,territory,dr_code,max(dr_name) dr_name,
                  max(specialty) specialty,count(DISTINCT rx_key) rx
                FROM rx_items WHERE """ + where + """
                GROUP BY 1,2,3,4
             ), numbered AS (
                SELECT *,row_number() OVER (
                  PARTITION BY region,ase,territory
                  ORDER BY rx DESC,dr_code) place
                FROM grouped
             )
             SELECT region,ase,territory,place,dr_code,dr_name,specialty,
                    rx,0,0,NULL,NULL,NULL
             FROM numbered WHERE place<=?
             ORDER BY region,ase,territory,place""",
            params + [n]
        ).fetchall()

    # Business card: all territories receive their own Top N, never only
    # the regional top N. A compact regional preview is supplementary.
    territory_top = []
    for r in ranked:
        rse,ase,territory,rank,code,name,specialty,generic_rx,brand_rx,competitor_rx,*_ = r
        territory_top.append([
            f"{ase or '—'} / {territory or '—'}", str(rank),
            f"{name or 'Unnamed'} ({code}) · {specialty or '—'}",
            f"{num(generic_rx)} generic Rx / {num(brand_rx)} {brand or 'target'} Rx"
            if brand else f"{num(generic_rx)} observed Rx"
        ])
    regional_preview = sorted(
        ranked, key=lambda r: (-int(r[7]), -int(r[8]), str(r[4]))
    )[:n]
    top_rows = [
        [str(i), f"{r[5]} ({r[4]}) · {r[6]}",
         f"{r[1]} / {r[2]}",
         f"{num(r[7])} generic Rx · {num(r[8])} {brand} Rx"
         if brand else f"{num(r[7])} observed Rx"]
        for i,r in enumerate(regional_preview,1)
    ]

    # Aggregate territory totals independently of Top N selection.
    totals = db.execute(
        "SELECT ase,territory,count(DISTINCT rx_key) FROM rx_items WHERE "
        + where + " GROUP BY ase,territory ORDER BY ase,territory", params
    ).fetchall()
    targets = {}
    if brand:
        targets = {
            (a,t): int(c) for a,t,c in db.execute(
                "SELECT ase,territory,count(DISTINCT rx_key) "
                "FROM rx_items WHERE " + where
                + " AND brand=? GROUP BY ase,territory", params+[brand]
            ).fetchall()
        }
    # Show territory-specific leaders, never pretend region leaders
    # are the territory-specific top doctors.
    leader_names = defaultdict(list)
    for r in ranked:
        if len(leader_names[(r[1],r[2])]) < min(n,3):
            leader_names[(r[1],r[2])].append(str(r[5]))
    territory_rows = [
        [f"{a or '—'} / {t or '—'}",num(c),
         f"{num(targets.get((a,t),0))} / {pct(targets.get((a,t),0),c)}"
          if brand else "Not selected",
         "; ".join(leader_names.get((a,t),[])) or "—"]
        for a,t,c in totals
    ]

    # Manufacturer-specific competitor ranking is ALWAYS regional, and
    # does not inherit ASE or MPE filters from the desktop view.
    competitor_rows = []
    competitor_count = 0
    if generic:
        entries = db.execute(
            """SELECT brand,company,count(DISTINCT rx_key) AS cnt
               FROM rx_items WHERE """ + where + """
               AND trim(coalesce(brand,''))<>''
               AND trim(coalesce(company,''))<>''
               AND regexp_replace(lower(company),'[^a-z0-9]','','g') NOT LIKE 'beximco%'
               GROUP BY brand,company ORDER BY cnt DESC,brand,company""",
            params
        ).fetchall()
        competitor_rows = [
            [b,c,num(count),pct(count,total)]
            for b,c,count in entries[:20]
        ]
        competitor_count = len(entries)

    # Distinguish no target-brand Rx from confirmed competitor Rx.
    # Both criteria must be true for a competitor opportunity.
    opportunity_rows = []
    opportunity_count = 0
    if brand and generic:
        doctors = db.execute(
            """WITH scoped AS (
                SELECT ase,territory,dr_code,max(dr_name) AS dr_name,
                  count(DISTINCT rx_key) AS total_rx,
                  count(DISTINCT CASE WHEN brand=? THEN rx_key END) AS target_rx,
                  count(DISTINCT CASE WHEN trim(coalesce(company,''))<>'' AND
                    regexp_replace(lower(company),'[^a-z0-9]','','g') NOT LIKE 'beximco%'
                    THEN rx_key END) AS competitor_rx
                FROM rx_items WHERE """ + where + """
                GROUP BY ase,territory,dr_code
             )
             SELECT ase,territory,dr_code,dr_name,total_rx,competitor_rx
             FROM scoped WHERE target_rx=0 AND competitor_rx>0
             ORDER BY competitor_rx DESC,total_rx DESC,dr_code""",
            [brand]+params
        ).fetchall()
        opportunity_count = len(doctors)
        selected_doctors=doctors[:20]
        wanted={(a,t,code) for a,t,code,*_ in selected_doctors}
        brand_details=defaultdict(list)
        if wanted:
            detail_rows=db.execute(
                """SELECT ase,territory,dr_code,brand,
                   count(DISTINCT rx_key) cnt FROM rx_items
                   WHERE """+where+"""
                   AND trim(coalesce(company,''))<>''
                   AND regexp_replace(lower(company),'[^a-z0-9]','','g') NOT LIKE 'beximco%'
                   GROUP BY ase,territory,dr_code,brand
                   ORDER BY cnt DESC,brand""",params
            ).fetchall()
            for a,t,code,b,cnt in detail_rows:
                if (a,t,code) in wanted and len(brand_details[(a,t,code)])<4:
                    brand_details[(a,t,code)].append(f"{b} {cnt}")
        for a,t,code,name,rx,comp in selected_doctors:
            detail=", ".join(brand_details[(a,t,code)])
            opportunity_rows.append([
                f"{a or '—'} / {t or '—'}",str(name or code),
                detail or "Competitor manufacturer recorded",num(comp)
            ])

    shares = generic_rx_shares(
        db, division, generic, region=region, brand=brand
    ) if generic else None
    scope = f"{generic or 'All generics'} / {brand or 'All brands'}"
    if shares:
        all_rx=int(db.execute(
            "SELECT count(DISTINCT rx_key) FROM rx_items "
            "WHERE division=? AND region=?",
            [division,region]
        ).fetchone()[0])
        kpi_items=[
            (pct(total,all_rx),"Generic Rx share"),
            (pct(selected_rx,total),f"{brand or 'Target'} Rx share"),
            (pct(shares["competitor_rx"],total),"Competitor Rx share"),
            (num(total),"Generic Rx (denominator)")
        ]
        classification_note=(
            f"Company Name verified by imported data: "
            f"{shares['unclassified_rx']} Rx with missing company and "
            f"{shares['overlap_rx']} Rx containing both Beximco and competitor manufacturers. "
            f"Generic share denominator: {num(all_rx)} all-product Rx; "
            f"brand and competitor share denominator: {num(total)} generic Rx."
        )
    else:
        kpi_items=[("N/A","Generic Rx share"),("N/A","Target Rx share"),
                   ("N/A","Competitor Rx share"),(num(total),"Observed Rx")]
        classification_note="Select a specific generic for comparable Rx-share percentages."

    action_lines=[
        f"Review the {num(total)} observed generic Rx across {territory_count} territories with the respective ASEs.",
        f"Use the Top {n} list within each territory; rankings reset for each MPE.",
    ]
    if brand and generic:
        action_lines.append(
            f"{opportunity_count} doctors show competitor Rx but no observed "
            f"{brand} Rx; {min(20,opportunity_count)} are detailed below."
        )
    opportunity_note=(
        f"{opportunity_count} confirmed competitor-prescribing doctors have no "
        f"recorded {brand} Rx. Showing {min(20,opportunity_count)} of "
        f"{opportunity_count}; not all missing-brand doctors are classified as competitors."
    ) if brand and generic else ""

    method_note=(
        "Apparent Prescription Preference is an observed prescription-presence measure, "
        "not a physician's stated preference. Brand and company shares may overlap on "
        "prescriptions with multiple products. All percentages describe only the "
        "imported sample, not national market share."
    )
    period=report_date_range(db).replace(" 00:00:00","")
    intro=(
        f"This {period} report contains {num(total)} observed prescriptions "
        f"for {generic or 'all generics'} from {num(prescriber_count)} distinct "
        f"doctor codes across {num(territory_count)} territories in {region}. "
        f"The selected brand {brand} appears in {num(selected_rx)} prescriptions "
        f"({pct(selected_rx,total)} of the selected scope)."
        if brand else
        f"This {period} report contains {num(total)} observed prescriptions "
        f"from {num(prescriber_count)} prescribers in {num(territory_count)} territories."
    )
    html=render_report(
        division=division,period=period,region=region,
        generic=generic or "All generics",scope=scope,
        recipient=recipient_name or "Regional Sales Executive",
        intro=intro,kpi_items=kpi_items,summary_note=classification_note,
        action_lines=action_lines,top_rows=top_rows,
        territory_top_rows=territory_top,brand_rows=[
            [b,num(c),pct(c,total)] for b,c in brand_counts[:12]
        ],competitor_rows=competitor_rows,
        opportunity_rows=opportunity_rows,territory_rows=territory_rows,
        method_note=method_note,top_n=n,opportunity_note=opportunity_note,
        brand_note=(
            f"Showing the top {min(12,len(brand_counts))} of "
            f"{len(brand_counts)} observed brands."
        ),
        competitor_note=(
            f"Regional denominator: {num(total)} distinct generic Rx. "
            f"Showing the top {len(competitor_rows)} of "
            f"{competitor_count} competitor brand/manufacturer combinations."
        ) if generic else ""
    )
    text=(
        f"Regional Rx review: {region}\nPeriod: {period}\nScope: {scope}\n"
        f"Generic Rx: {num(total)}\nSelected brand Rx: {num(selected_rx)}\n"
        f"Top {n} prescribers per territory are provided in the HTML version.\n"
        f"Competitor opportunities: {opportunity_count}, "
        f"showing {min(20,opportunity_count)}.\n"
        "Draft for review only. No emails have been sent.\n"
    )
    return {"html":html,"text":text,"manufacturer_shares":shares,
            "rx":total,"prescribers":prescriber_count,"target_rx":selected_rx,
            "scope":scope,"territories":territory_count,"top_n":n,
            "opportunities_total":opportunity_count,
            "opportunities_shown":len(opportunity_rows),
            "territory_top_rows":len(territory_top)}
