"""Outlook classic-safe, 640px HTML email renderer.

All dynamic values are HTML escaped; content uses tables and explicit cell
styles rather than browser CSS layout. No remote assets or trackers.
"""
from html import escape
from string import Template

def esc(value):
    return escape(str(value if value is not None else ""),quote=True)

def heading(title,subtitle=""):
    return ('<tr><td style="padding:19px 24px 8px;">'
      '<p style="margin:0;font-family:Tahoma,sans-serif;font-size:17px;line-height:22px;'
      'font-weight:bold;color:#155670;">'+esc(title)+'</p>'
      +('<p style="margin:5px 0 0;font-family:Tahoma,sans-serif;font-size:11px;line-height:16px;color:#667784;">'+esc(subtitle)+'</p>' if subtitle else '')
      +'</td></tr>')

def data_table(headers,rows,widths=None):
    """Simple bounded-column table; accepts escaped plain text only."""
    if len(headers)>5:raise ValueError("Outlook report supports at most five columns")
    widths=widths or [round(100/len(headers))]*len(headers)
    s=['<tr><td class="mobile-pad" style="padding:5px 24px 9px;">',
       '<table class="responsive-data" role="presentation" width="100%" border="0" cellpadding="0" cellspacing="0" style="border-collapse:collapse;width:100%;">',
       '<tr>']
    for i,h in enumerate(headers):
        s.append('<td class="table-heading" width="'+str(widths[i])+'%" valign="top" bgcolor="#104f69" style="padding:8px 6px;'
                 'background-color:#104f69;border:1px solid #dae1e5;font-family:Tahoma,sans-serif;'
                 'font-weight:bold;font-size:11px;line-height:15px;color:#ffffff;">'+esc(h)+'</td>')
    s.append('</tr>')
    for idx,row in enumerate(rows):
        s.append('<tr class="data-row">')
        shade="#ffffff" if idx%2==0 else "#f3f6f7"
        for col,v in enumerate(row):
            s.append('<td class="data-cell" data-label="'+esc(headers[col])+'" valign="top" bgcolor="'+shade+'" style="padding:7px 6px;background-color:'+shade+
                     ';border:1px solid #dae1e5;word-break:break-word;font-family:Tahoma,sans-serif;'
                     'font-size:11px;line-height:16px;color:#273440;">'+esc(v)+'</td>')
        s.append('</tr>')
    if not rows:
        s.append('<tr><td colspan="'+str(len(headers))+'" style="padding:11px;color:#607080;'
                 'font:12px Tahoma,sans-serif;">No matching observations.</td></tr>')
    s.extend(['</table>','</td></tr>'])
    return ''.join(s)

def kpis(items):
    """Four static-width metrics, including missing data represented as N/A."""
    backgrounds=["#f5f7f9","#f5f7f9","#e4f4e9","#fff0f0"]
    colors=["#24313e","#24313e","#167144","#a72c3e"]
    cells=[]
    for i,(value,label) in enumerate(items):
        cells.append('<td class="kpi-cell" width="25%" valign="top" align="center" bgcolor="'+backgrounds[i]+
          '" style="background-color:'+backgrounds[i]+';border:4px solid #ffffff;'
          'padding:12px 4px;"><p style="margin:0;font-family:Tahoma,sans-serif;font-size:20px;'
          'line-height:25px;font-weight:bold;color:'+colors[i]+';">'+esc(value)+
          '</p><p style="margin:5px 0 0;font-family:Tahoma,sans-serif;font-size:11px;'
          'line-height:16px;color:#526473;">'+esc(label)+'</p></td>')
    return ('<tr><td style="padding:0 19px 6px;"><table role="presentation" width="100%" '
            'cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">'
            '<tr>'+''.join(cells)+'</tr></table></td></tr>')

def bullets(lines):
    content=''.join(
        '<tr><td width="24" valign="top" style="padding:4px 0;font:13px Tahoma,sans-serif;'
        'color:#ad3347;">'+str(i)+'.</td><td valign="top" style="padding:4px 0;'
        'font-family:Tahoma,sans-serif;font-size:12px;line-height:18px;'
        'color:#273440;">'+esc(line)+'</td></tr>' for i,line in enumerate(lines,1))
    return heading("Action points")+(
        '<tr><td style="padding:4px 24px 8px;"><table role="presentation" width="100%" '
        'cellpadding="0" cellspacing="0" border="0">'+content+'</table></td></tr>')

def note(text):
    return ('<tr><td style="padding:4px 24px 10px;"><p style="margin:0;'
            'font-family:Tahoma,sans-serif;font-size:11px;line-height:17px;'
            'color:#697988;">'+esc(text)+'</p></td></tr>')

OUTLOOK_TEMPLATE=Template("""<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="X-UA-Compatible" content="IE=edge">
<style type="text/css">
@media only screen and (max-width:680px) {
  .email-container {width:100% !important; max-width:100% !important;}
  .outer-pad {padding:0 !important;}
  .mobile-pad {padding-left:12px !important;padding-right:12px !important;}
  .kpi-cell {display:inline-block !important;box-sizing:border-box !important;width:50% !important;vertical-align:top !important;}
  .responsive-data,.responsive-data tbody,.responsive-data tr.data-row,
  .responsive-data td.data-cell {display:block !important;width:100% !important;box-sizing:border-box !important;}
  .responsive-data tr.data-row {margin:0 0 12px !important;border:1px solid #d6e0e4 !important;}
  .responsive-data td.table-heading {display:none !important;}
  .responsive-data td.data-cell {padding:7px 10px !important;border:0 !important;border-bottom:1px solid #e1e8ec !important;}
  .responsive-data td.data-cell:before {content:attr(data-label);display:block !important;font:700 10px Tahoma,sans-serif !important;color:#526775 !important;padding-bottom:3px !important;text-transform:uppercase !important;}
}
</style>
<title>Prescriber Intelligence — Regional Rx Review</title>
<!--[if mso]><style type="text/css">body,table,td,p{font-family:Tahoma,sans-serif !important;} table{border-collapse:collapse;}</style><![endif]-->
</head>
<body bgcolor="#eef1f3" style="margin:0;padding:0;background-color:#eef1f3;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#eef1f3" style="background-color:#eef1f3;border-collapse:collapse;">
<tr><td class="outer-pad" align="center" style="padding:20px 8px;">
<!--[if mso]><table role="presentation" width="640" align="center" border="0" cellpadding="0" cellspacing="0"><tr><td><![endif]-->
<table class="email-container" role="presentation" width="640" align="center" cellpadding="0" cellspacing="0" border="0" bgcolor="#ffffff" style="width:640px;max-width:640px;background-color:#ffffff;border-collapse:collapse;">
<tr><td bgcolor="#104f69" style="background-color:#104f69;padding:21px 24px;">
<p style="margin:0 0 6px;font-family:Tahoma,sans-serif;font-size:11px;line-height:16px;font-weight:bold;letter-spacing:1px;color:#d6eaf0;">PRESCRIBER INTELLIGENCE &nbsp;|&nbsp; $DIVISION &nbsp;|&nbsp; $PERIOD</p>
<p style="margin:0;font-family:Tahoma,sans-serif;font-size:22px;line-height:29px;font-weight:bold;color:#ffffff;">$REGION — $GENERIC Rx Review</p>
<p style="margin:7px 0 0;font-family:Tahoma,sans-serif;font-size:12px;line-height:18px;color:#d6eaf0;">Observed survey &nbsp;&bull;&nbsp; $SCOPE</p>
</td></tr>
<tr><td style="padding:22px 24px 9px;">
<p style="margin:0 0 10px;font-family:Tahoma,sans-serif;font-size:14px;line-height:20px;color:#273440;">Dear $RECIPIENT,</p>
<p style="margin:0;font-family:Tahoma,sans-serif;font-size:13px;line-height:21px;color:#273440;">$INTRO</p>
</td></tr>
$KPI_SECTION
$SUMMARY_NOTE
$ACTION_SECTION
$TOP_SECTION
$TERRITORY_TOP_SECTION
$BRAND_SECTION
$COMPETITOR_SECTION
$OPPORTUNITY_SECTION
$TERRITORY_SECTION
$METHOD_SECTION
<tr><td style="padding:9px 24px 18px;">
<p style="margin:0 0 12px;font-family:Tahoma,sans-serif;font-size:13px;line-height:20px;color:#273440;">This report is for your review and necessary follow-up. Please verify the data context before acting.</p>
<p style="margin:0;font-family:Tahoma,sans-serif;font-size:13px;line-height:20px;color:#273440;">Regards,<br><strong>Prescriber Intelligence</strong></p>
</td></tr>
<tr><td bgcolor="#eef2f5" style="background-color:#eef2f5;border-top:1px solid #d9e0e3;padding:12px 24px;"><p style="margin:0;font-family:Tahoma,sans-serif;font-size:11px;line-height:16px;color:#637480;">Internal analytical report &nbsp;|&nbsp; $DIVISION &nbsp;|&nbsp; $PERIOD &nbsp;|&nbsp; Not a national market-share estimate</p></td></tr>
</table>
<!--[if mso]></td></tr></table><![endif]-->
</td></tr></table></body></html>""")

def render_report(*,division,period,region,generic,scope,recipient,intro,kpi_items,
    summary_note,action_lines,top_rows,brand_rows,opportunity_rows,territory_rows,method_note,
    territory_top_rows=None,competitor_rows=None,top_n=10,opportunity_note=""):
    top_section=heading("Top observed prescribers")+data_table(
        ["Rank","Prescriber / Specialty","ASE / MPE","Rx / brand mix"],
        top_rows,[9,36,17,38])
    territory_top_section=heading(
        f"Top {int(top_n)} prescribers in each territory",
        "Rankings restart within each MPE; ordered by observed generic Rx count."
    )+data_table(
        ["ASE / MPE","Rank","Prescriber / specialty","Generic Rx / target Rx"],
        territory_top_rows or [],[18,9,42,31])
    brand_section=heading("Observed brand mix")+data_table(
        ["Brand","Observed Rx","% of generic scope"],
        brand_rows,[50,24,26])
    competitor_section=(heading("Regional competitor-wise Rx share",
        "Shares use distinct generic Rx within this RSE region as denominator.")
        +data_table(["Competitor brand","Company","Distinct Rx","Regional share"],
        competitor_rows or [],[29,31,18,22])) if competitor_rows is not None else ""
    opportunity_section=(heading("Competitor opportunity review",
        opportunity_note or "Confirmed competitor Rx with no observed target-brand Rx; survey-based.")
        +data_table(["ASE / MPE","Prescriber","Competitor brands","Rx"],
        opportunity_rows,[19,35,32,14])) if opportunity_rows else ""
    territory_section=heading("Territory review")+data_table(
        ["ASE / MPE","Rx","Target Rx / share","Leading prescribers"],
        territory_rows,[19,13,22,46])
    return OUTLOOK_TEMPLATE.substitute(
        DIVISION=esc(division),PERIOD=esc(period),REGION=esc(region),
        GENERIC=esc(generic),SCOPE=esc(scope),RECIPIENT=esc(recipient),
        INTRO=esc(intro),KPI_SECTION=kpis(kpi_items),
        SUMMARY_NOTE=note(summary_note),
        ACTION_SECTION=bullets(action_lines),
        TOP_SECTION=top_section,TERRITORY_TOP_SECTION=territory_top_section,
        BRAND_SECTION=brand_section,COMPETITOR_SECTION=competitor_section,
        OPPORTUNITY_SECTION=opportunity_section,TERRITORY_SECTION=territory_section,
        METHOD_SECTION=note(method_note))
