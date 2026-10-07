"""PDF report uses the same result object displayed by the app."""
from io import BytesIO
from html import escape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


def create_pdf(result, metadata):
    buffer = BytesIO()
    styles = getSampleStyleSheet()
    styles["BodyText"].fontSize = 9
    styles["BodyText"].leading = 11
    flow = []
    def para(text, style="BodyText"):
        flow.append(Paragraph(escape(str(text)), styles[style]))
        flow.append(Spacer(1, 2 * mm))
    def table(rows):
        data = [[Paragraph(escape(str(c)), styles["BodyText"]) for c in row] for row in rows]
        t = Table(data, colWidths=[65*mm,110*mm], hAlign="LEFT")
        t.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),
                              ("GRID",(0,0),(-1,-1),.25,colors.lightgrey),
                              ("BOTTOMPADDING",(0,0),(-1,-1),4)]))
        flow.append(t)
        flow.append(Spacer(1,4*mm))
    p = result["inputs"]
    para("Prowrap Sonatrach Qualification Calculation", "Title")
    para("Rev1 | Sonatrach PR 900.3 R4 | TDS PRW 110-H.pdf")
    para(f"Customer: {metadata.get('customer','')} | Report: {metadata.get('report_no','')}")
    para("Status: " + result["status"], "Heading2")
    para("Calculation only. This report does not constitute field-repair design or qualification approval. PASS refers only to the named input check; source references are user-declared.")
    para("Inputs", "Heading2")
    table([[k.replace('_',' '),v] for k,v in p.items()])
    para("Calculation and layout", "Heading2")
    table([
        ["Test pressure",f"{result['pressure_mpa']:.6f} MPa / {result['pressure_bar']:.4f} bar"],
        ["Required thickness",f"{result['thickness_mm']:.6f} mm"],
        ["Plies / installed thickness",f"{result['plies']} / {result['effective_thickness_mm']:.2f} mm"],
        ["Axial rows / laid extent",f"{result['num_rows']} / {result['laid_length_mm']:.2f} mm"],
        ["Spool length",f"Must exceed {result['spool_length_limit_mm']:.3f} mm; also verify >3D clearance each side"],
        ["Nominal-OD cloth estimate",f"{result['cloth_length_m']:.3f} m / {result['area_m2']:.3f} m2"],
        ["Cloth with allowance",f"{result['procurement_length_m']:.3f} m"],
    ])
    para("R4 p. 10: Pf = 2*t*Sa/D. R4 p. 9: t_repair = (Pf*D/2 - Sa*ts)/(Ec*0.008). Ec = 45460 MPa and ply thickness = 0.83 mm from TDS p. 2. N = ceil(t_repair/0.83). Sa must be measured yield strength.")
    para("Repair length and overlaps require an approved design; no repair-length equation is supplied by R4. Cloth quantity includes seams but excludes diameter buildup, filler and taper. No resin consumption factor has been assumed.")
    para("Checks and outstanding evidence", "Heading2")
    for c in result["checks"]:
        para(f"{c['status']} - {c['name']}: {c['detail']}")
    para("Test and application requirements", "Heading2")
    limit = result['application_limit_minutes']
    para(f"Application duration: maximum {limit} minutes." if limit else "Obtain the RCL application duration for this diameter; R4 gives 45 minutes at 16 inch and 50 minutes at 20 inch.")
    para("Phase I: ramp to RCL-confirmed intact-pipe design pressure over at least 30 seconds, then hold 15 seconds. Phase II: reach calculated Pf, hold 30 seconds, then depressurize. No burst phase under R4.")
    para("Inspect after testing to R4 p. 11. Verify Class 3 personnel, mechanical/dimensional records, RT/PT, calibrated instrumentation and acceptance by RCL/third-party inspectors.")
    para("TDS: touch dry 4 hours, full cure 24 hours. These do not establish R4 two-hour backfill readiness near 25 C. Shore D 79.1 is a test result, not a release threshold.")
    para("TDS p. 2 failure-strain values 2.33/2.43 mm/mm have ambiguous units and are not used. Tg 108.18 C and HDT 115.5 C do not establish allowable service temperature. Unsupported ASME factors from the previous calculator are excluded.")
    para("TDS pp. 4-5: primer 2:1, putty 4:1, saturator 4:1 by volume; surface profile 60-80 microns. R4 describes blasting. Follow the qualified manufacturer procedure.")
    def footer(canvas, doc):
        canvas.setFont("Helvetica",8)
        canvas.drawString(18*mm,12*mm,"Prowrap | Sonatrach PR 900.3 R4 | Rev1 | Calculation subject to review")
        canvas.drawRightString(193*mm,12*mm,str(doc.page))
    SimpleDocTemplate(buffer, pagesize=(210*mm,297*mm), leftMargin=18*mm,rightMargin=17*mm,
                      topMargin=16*mm,bottomMargin=20*mm).build(flow,onFirstPage=footer,onLaterPages=footer)
    return buffer.getvalue()
