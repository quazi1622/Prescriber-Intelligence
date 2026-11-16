"""Outlook-compatible inline HTML Rx reports. All numbers come from local DuckDB."""
from collections import defaultdict,Counter
from html import escape
from email.message import EmailMessage
import re

def safe(value):
    return escape(str(value if value is not None else ""),quote=True)

def num(value):
    return f"{int(value):,}"

def pct(part,total):
    return f"{100*part/total:.1f}%" if total else "—"

def row_cells(values,header=False,highlight=False):
    tag="th" if header else "td"
    base=("background:#104f69;color:#ffffff;font-weight:bold;" if header else
          "background:#def5e8;color:#165e43;font-weight:700;" if highlight else
          "background:#ffffff;color:#263343;")
    return "<tr>"+ "".join(
        f'<{tag} style="{base}border:1px solid #d2d8dc;padding:8px 7px;vertical-align:top;font-size:12px;">{safe(v)}</{tag}>'
        for v in values
    )+"</tr>"

def table(headers,records,highlight_col=None):
    parts=['<table role="presentation" cellspacing="0" cellpadding="0" width="100%" style="width:100%;border-collapse:collapse;font-family:Arial,sans-serif;">']
    parts.append(row_cells(headers,header=True))
    for row in records:
        if highlight_col is None:parts.append(row_cells(row))
        else:
            parts.append('<tr>')
            for i,val in enumerate(row):
                positive= i==highlight_col and str(val) not in ("0","0.0%","—","")
                style=("background:#d9f5e4;color:#16673a;font-weight:bold;" if positive
                      else "background:#ffe9ea;color:#9b2431;" if i==highlight_col
                      else "background:#ffffff;color:#263343;")
                parts.append(f'<td style="{style}border:1px solid #d2d8dc;padding:8px 7px;font-size:12px;">{safe(val)}</td>')
            parts.append('</tr>')
    return "".join(parts)+"</table>"

def section(title,color="#155670"):
    return f'<h2 style="font:700 18px Arial,sans-serif;color:{color};border-bottom:3px solid {color};padding-bottom:6px;margin:28px 0 12px;">{safe(title)}</h2>'

def build_region_report(db,division,region,top_n=10,brand="",generic="",recipient_name=""):
    """Report a selected generic's observed Rx, comparing the selected brand.

    If no generic is selected, use all observed Rx in the region; brand names
    may appear across generics, so report scope labels disclose this.
    Counts are distinct Rx identifiers, not product-line counts.
    """
    if not db.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='rx_items'").fetchone()[0]:
        raise ValueError("Re-import Excel Rx data to create the Brand/Generic index.")
    where=["division=?","region=?"]
    args=[division,region]
    if generic:where.append("generic=?");args.append(generic)
    clause=" AND ".join(where)
    # Each prescription is counted once at each observed brand; totals count
    # unique Rx. Brand totals can sum above 100% for multi-brand prescriptions.
    raw=db.execute("""SELECT ase,territory,dr_code,max(dr_name),max(specialty),brand,
          count(DISTINCT rx_key) FROM rx_items WHERE """+clause+
          " GROUP BY ase,territory,dr_code,brand",args).fetchall()
    baseline=db.execute("""SELECT count(DISTINCT rx_key),
          count(DISTINCT dr_code), count(DISTINCT territory)
          FROM rx_items WHERE """+clause,args).fetchone()
    total=int(baseline[0]);prescribers=int(baseline[1]);territories=int(baseline[2])
    # Key each doctor by territory to prevent accidental cross-territory merges.
    doctors={}
    brands=Counter()
    for ase,territory,code,name,specialty,b,rxc in raw:
        key=(str(ase or ""),str(territory or ""),str(code or ""))
        item=doctors.setdefault(key,{"name":name or "Unnamed prescriber",
            "specialty":specialty or "—","brand_rx":Counter()})
        item["brand_rx"][str(b or "Unspecified")]+=int(rxc)
    counts=db.execute("""SELECT ase,territory,dr_code,
          count(DISTINCT rx_key) AS total_rx
          FROM rx_items WHERE """+clause+
          " GROUP BY ase,territory,dr_code",args).fetchall()
    doctor_totals={(str(a or ""),str(t or ""),str(c or "")):int(n)
                   for a,t,c,n in counts}
    territory_counts=db.execute(
        "SELECT ase,territory,count(DISTINCT rx_key) FROM rx_items WHERE "
        +clause+" GROUP BY ase,territory",args).fetchall()
    territory_totals={(str(a or ""),str(t or "")):int(n)
                      for a,t,n in territory_counts}
    territory_target_totals={}
    if brand:
        counts=db.execute(
            "SELECT ase,territory,count(DISTINCT rx_key) FROM rx_items WHERE "
            +clause+" AND brand=? GROUP BY ase,territory",args+[brand]).fetchall()
        territory_target_totals={(str(a or ""),str(t or "")):int(n)
                                 for a,t,n in counts}
    # Actual target Rx count uses DISTINCT keys; never sum brand rows as total.
    if brand:
        count_sql="SELECT count(DISTINCT rx_key) FROM rx_items WHERE "+clause+" AND brand=?"
        target_rx=int(db.execute(count_sql,args+[brand]).fetchone()[0])
    else:target_rx=0
    brand_rows=db.execute("""SELECT brand,count(DISTINCT rx_key) AS n FROM rx_items
        WHERE """+clause+" AND trim(coalesce(brand,''))<>'' GROUP BY brand ORDER BY n DESC,brand",args).fetchall()
    for b,n in brand_rows:brands[str(b)]=int(n)
    rank_items=[]
    nonprescribers=[]
    territory_data=defaultdict(list)
    for (ase,terr,code),d in doctors.items():
        # Total by doctor must not sum brand-specific counts due to overlap.
        d_total=doctor_totals[(ase,terr,code)]
        selected=d["brand_rx"].get(brand,0) if brand else 0
        d["total"]=d_total;d["target"]=selected
        d["app"]=pct(selected,d_total) if brand else "—"
        detail=", ".join(f"{b} {c}" for b,c in d["brand_rx"].most_common(6))
        item={"ase":ase,"terr":terr,"code":code,"detail":detail,**d}
        rank_items.append(item)
        territory_data[(ase,terr)].append(item)
        if brand and selected==0 and d_total:nonprescribers.append(item)
    rank_items.sort(key=lambda d:(-d["total"],d["code"]))
    nonprescribers.sort(key=lambda d:(-d["total"],d["code"]))
    top_n=max(1,min(20,int(top_n)))
    main_rows=[[i+1,d["name"]+" ("+d["code"]+")",d["specialty"],
                f'{d["ase"]} / {d["terr"]}',d["total"],d["detail"],
                d["target"] if brand else "—",d["app"]]
                for i,d in enumerate(rank_items[:top_n])]
    brand_share=[[b,num(n),pct(n,total)] for b,n in brand_rows[:12]]
    territory_rows=[]
    for (ase,terr),items in sorted(territory_data.items()):
        items.sort(key=lambda d:(-d["total"],d["code"]))
        t_rx=territory_totals[(ase,terr)]
        b_rx=territory_target_totals.get((ase,terr),0) if brand else 0
        territory_rows.append([f"{ase} / {terr}",num(t_rx),num(len(items)),
                               num(b_rx) if brand else "—",
                               pct(b_rx,t_rx) if brand else "—",
                               "; ".join(d["name"] for d in items[:3])])
    non_rows=[[f'{d["ase"]} / {d["terr"]}',d["name"],d["specialty"],
               d["total"],d["detail"]] for d in nonprescribers[:80]]
    comparator=brand or "All observed brands"
    survey=generic or "All generics"
    scope=survey+" / "+comparator
    badge=lambda value,label,accent=False:(
       '<td width="25%" style="padding:6px;"><table role="presentation" width="100%" style="border:1px solid #d7dce0;background:'+
       ("#e0f6e7" if accent else "#f7f8fa")+
       ';"><tr><td style="text-align:center;padding:14px 4px;"><div style="font:bold 22px Arial;color:'+
       ("#13814d" if accent else "#263342")+';">'+safe(value)+
       '</div><div style="font:12px Arial;color:#485464;">'+safe(label)+'</div></td></tr></table></td>')
    kpi='<table role="presentation" width="100%"><tr>'+badge(num(total),"Observed Rx")+badge(num(prescribers),"Prescribers")+badge(num(territories),"MPE territories")+badge(pct(target_rx,total) if brand else "—","Target brand share",bool(brand))+'</tr></table>'
    introductory=("In the imported survey, this region recorded "
          +f"{num(total)} distinct prescriptions from {num(prescribers)} prescribers across {num(territories)} territories"
          +(f". {brand} appeared in {num(target_rx)} of those prescriptions ({pct(target_rx,total)})." if brand else ".")
          +" These are observed sample metrics, not national market shares.")
    actions=["Review the observed brand mix with the relevant ASEs and validate local context before planning follow-up.",
             "Use the ranked prescriber list and territory comparison to prioritize review of the sample data."]
    if nonprescribers:
        actions.append(f"{num(len(nonprescribers))} prescribers in this region had no recorded {brand} Rx within the selected reporting scope; investigate whether this reflects genuine opportunity or incomplete survey capture.")
    if not generic:
        actions.append("Select a Generic filter to obtain a like-for-like therapeutic-class brand comparison.")
    table_style=lambda title,headers,rows,highlight=None: section(title)+(table(headers,rows,highlight) if rows else '<p style="color:#607080;">No matching records.</p>')
    top=table_style(f"Top {top_n} observed prescribers",["Rank","Prescriber / Code","Specialty","ASE / MPE","Rx","Brands prescribed",comparator+" Rx","APP"],main_rows,6 if brand else None)
    mix=table_style("Observed Rx share by brand",["Brand","Distinct Rx","% of selected scope"],brand_share)
    zero=table_style(f"Prescribers without observed {brand} Rx",["ASE / MPE","Prescriber","Specialty","Selected-scope Rx","Brands observed"],non_rows) if brand else ""
    territories_section=table_style("Territory-by-territory review",["ASE / MPE","Rx","Prescribers",comparator+" Rx","APP","Leading observed prescribers"],territory_rows,3 if brand else None)
    body=f"""<!DOCTYPE html><html><body style="background:#f0f2f4;margin:0;padding:16px;font-family:Arial,sans-serif;color:#263342;">
<table role="presentation" cellspacing="0" cellpadding="0" width="100%" style="max-width:900px;margin:auto;background:#ffffff;border-collapse:collapse;">
<tr><td style="padding:0 0 22px;"><div style="background:#104f69;padding:22px 25px;color:white;">
<div style="font:12px Arial;letter-spacing:1px;color:#d8edf2;">PRESCRIBER INTELLIGENCE · {safe(division)} · {safe(scope)}</div>
<div style="font:bold 25px Arial;margin-top:7px;">{safe(region)} — Prescription Review</div></div></td></tr>
<tr><td style="padding:0 25px 30px;">
<p>Dear {safe(recipient_name or 'Regional Sales Executive')},</p>
<p>I hope this email finds you well.</p><p style="line-height:1.55;">{safe(introductory)}</p>
{kpi}
{section("Action points")}
<ol style="font:14px/1.6 Arial;color:#263342;">{"".join('<li style="margin-bottom:7px;">'+safe(x)+'</li>' for x in actions)}</ol>
{top}{mix}{zero}{territories_section}
<p style="font:12px/1.5 Arial;color:#657381;margin-top:30px;">
<b>Apparent Prescription Preference (APP)</b> = observed target-brand distinct Rx
divided by all distinct Rx in the selected generic (when selected) for the same doctor or territory.
It is descriptive, sample-dependent and should not be interpreted as the doctor's actual preference.
Brand percentages may total above 100% if multiple brands occur on the same prescription.
Data source: locally imported prescription workbook. No national benchmark is inferred.</p>
<p style="font:14px/1.6 Arial;">This is for your review and necessary follow-up.<br/>Regards,<br/>Prescriber Intelligence</p>
</td></tr></table></body></html>"""
    text=(f"Prescription review for {division} {region}\n"
          f"Scope: {scope}\nObserved Rx: {total}\nPrescribers: {prescribers}\n"
          +(f"Target brand: {brand}, Rx: {target_rx}, share: {pct(target_rx,total)}\n" if brand else "")
          +"Open with an HTML-capable email client to see the full formatted report.")
    return {"html":body,"text":text,"rx":total,"prescribers":prescribers,
            "target_rx":target_rx,"scope":scope,"territories":territories}
