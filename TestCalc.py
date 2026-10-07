"""Streamlit entry point for the Sonatrach R4 qualification calculator, Rev1."""
import json
import streamlit as st
from calculator import DEFAULT_INPUTS, PROWRAP, R4_STRAIN, REVISION, calculate
from report import create_pdf

st.set_page_config(page_title="Prowrap R4 Test Calculator | Rev1", page_icon="🔧", layout="wide")


def main():
    st.title("Prowrap Sonatrach Test Calculator")
    st.caption("Rev1 | Sonatrach PR 900.3 R4 | Material source: TDS PRW 110-H.pdf")
    st.info("Qualification-spool calculation using R4's specified equation. Example inputs are editable; the result is not a field-repair design or qualification approval.")
    st.sidebar.header("Project")
    customer = st.sidebar.text_input("Customer", "PROTAP / Sonatrach")
    report_no = st.sidebar.text_input("Report number", "R4-Rev1")
    p = dict(DEFAULT_INPUTS)
    st.sidebar.header("Pipe and measured steel properties")
    fields = [
        ("od", "Outside diameter D [mm]"),
        ("wall", "Healthy wall thickness t [mm]"),
        ("remaining", "Residual wall thickness ts [mm]"),
        ("yield_strength", "Steel yield strength Sa [MPa]"),
    ]
    for key, label in fields:
        p[key] = st.sidebar.number_input(label, value=p[key], format="%.3f", key=key)
    p["measured_yield_confirmed"] = st.sidebar.checkbox("Yield value is measured, not nominal SMYS")
    p["mechanical_report"] = st.sidebar.text_input("Mechanical test report reference")
    st.sidebar.caption("358.5 MPa is an example only. R4 requires measured yield strength.")
    st.sidebar.header("Defect and spool")
    for key, label in [
        ("defect_length", "Axial defect length L [mm]"),
        ("defect_width", "Circumferential defect width W [mm]"),
        ("repair_length", "Repair length from design [mm]"),
        ("spool_length", "Actual spool length [mm]"),
    ]:
        p[key] = st.sidebar.number_input(label, value=p[key], format="%.3f", key=key)
    p["repair_design_ref"] = st.sidebar.text_input("Approved repair drawing / calculation reference")
    st.sidebar.caption("550 mm is an example repair length, not a length calculated by R4. Include the designed taper extent.")
    st.sidebar.header("Cloth layout estimate")
    for key, label in [
        ("cloth_width", "Cloth width [mm]"), ("row_overlap", "Axial row overlap [mm]"),
        ("seam_overlap", "Circumferential seam overlap [mm]"), ("waste_percent", "Quantity allowance [%]"),
    ]:
        p[key] = st.sidebar.number_input(label, value=p[key], format="%.2f", key=key)
    try:
        r = calculate(p)
    except ValueError as exc:
        st.error(str(exc))
        st.stop()
    st.subheader("Calculated results")
    cols = st.columns(4)
    cols[0].metric("Test pressure Pf", f"{r['pressure_mpa']:.4f} MPa", f"{r['pressure_bar']:.3f} bar")
    cols[1].metric("Required composite thickness", f"{r['thickness_mm']:.4f} mm")
    cols[2].metric("Plies per axial row", r["plies"], f"{r['effective_thickness_mm']:.2f} mm installed")
    cols[3].metric("Spool length must exceed", f"{r['spool_length_limit_mm']:.1f} mm")
    if r["status"] == "INPUT CHECK FAILED":
        st.error("Input checks failed. The displayed arithmetic does not establish an acceptable test specimen.")
    else:
        st.warning("Review required: resolve the items below before the qualification test.")
    st.table(r["checks"])
    st.caption("PASS applies only to the named input check. References and measured-value declarations are entered by the user, not independently verified by this calculator.")

    with st.expander("Equations and source traceability", expanded=True):
        st.latex(r"P_f=\frac{2tS_a}{D}")
        st.latex(r"t_{repair}=\frac{P_fD/2-S_at_s}{E_c\varepsilon_{ct}}")
        st.latex(r"N=\lceil t_{repair}/t_{ply}\rceil,\quad t_{installed}=N t_{ply}")
        st.write("R4 p. 9: Ec = 45,460 MPa from TDS p. 2; strain = 0.008 prescribed by R4; ply thickness = 0.83 mm. R4 p. 10: measured steel yield strength and healthy wall determine Pf.")
        st.write("Remaining steel-wall contribution is retained as required by R4. No Type A/B switch, service-life claim or unsupported ASME design-strain calculation is applied.")

    st.subheader("Layout and material estimate")
    st.write(f"{r['num_rows']} axial rows cover {r['laid_length_mm']:.1f} mm at {p['cloth_width']:.1f} mm cloth width and {p['row_overlap']:.1f} mm row overlap.")
    st.write(f"Nominal-OD cloth estimate: {r['cloth_length_m']:.2f} m ({r['area_m2']:.2f} m²). With {p['waste_percent']:.1f}% allowance: {r['procurement_length_m']:.2f} m.")
    st.caption("Estimate includes a circumferential seam for every ply and row. It excludes increasing circumference through laminate thickness, filler buildup and taper details. Confirm the cutting schedule before ordering. Resin quantity is not inferred from an unsupported kg/m² factor.")
    st.write(f"Ridge criterion: maximum {r['ridge_limit_mm']:.2f} mm under R4 p. 11. Row overlap creates extra thickness; the approved drawing must address taper, fibre continuity and full-thickness coverage.")
    st.caption("Spool threshold uses the greater of requested repair length and laid cloth extent. Verify >3D clearance on each side and transition geometry on the specimen drawing.")

    st.subheader("R4 test and application requirements")
    limit = r["application_limit_minutes"]
    st.write(f"Application duration: maximum {limit} minutes for this diameter." if limit else "Application duration: obtain the RCL limit for this diameter; R4 states 45 min for 16-inch and 50 min for 20-inch only.")
    st.write("Phase I: ramp to the intact pipe design pressure over at least 30 seconds, then hold 15 seconds. That design pressure is a separate RCL-confirmed input, not automatically Pf.")
    st.write(f"Phase II: reach calculated Pf = {r['pressure_mpa']:.4f} MPa, hold 30 seconds, then depressurize. R4 removes the burst phase.")
    st.write("Inspect after resistance testing using R4 p. 11. Use qualified Class 3 personnel, accepted RT/PT and dimensional/mechanical records, and calibrated pressure/temperature instrumentation.")
    st.warning("Hardening remains unresolved: R4 requires backfill readiness within 2 hours near 25°C. The supplied TDS states touch dry 4 hours and full cure 24 hours; it does not demonstrate the two-hour criterion.")
    with st.expander("Verified material data and installation notes"):
        st.table([{"Property": k, "Value": v} for k, v in {
            "Circumferential modulus [MPa]":45460, "Axial modulus [MPa]":43800,
            "Ply thickness [mm]":.83, "Circumferential tensile strength [MPa]":574.1,
            "Axial tensile strength [MPa]":563.67, "Lap shear [MPa]":14.76,
            "Long-term lap shear [MPa]":9.63, "Shore D test result":79.1,
            "Tg [°C]":108.18, "HDT [°C]":115.5,
        }.items()])
        st.write("TDS p. 2 lists failure strains 2.33 and 2.43 with units mm/mm. These entries require clarification and are not converted to percentages or used in this calculation.")
        st.write("Shore D 79.1 is a reported test result, not an installation acceptance threshold. Tg/HDT are not allowable service-temperature limits; no 55.5°C limit is established by this TDS.")
        st.write("TDS pp. 4–5: primer 2:1, filler 4:1, saturator 4:1 by volume. Surface profile approximately 60–80 µm; R4 describes blasting. Saturator pot life approximately 25 min and filler 30 min at 25°C.")
    metadata = {"customer": customer, "report_no": report_no, "revision": REVISION}
    st.download_button("Download Rev1 calculation report (PDF)", create_pdf(r, metadata),
                       file_name="Prowrap_R4_Rev1_Calculation.pdf", mime="application/pdf")
    st.download_button("Download calculation record (JSON)", json.dumps({"metadata":metadata, **r}, indent=2),
                       file_name="Prowrap_R4_Rev1_Record.json", mime="application/json")


if __name__ == "__main__":
    main()
