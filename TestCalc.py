import streamlit as st
import math
from fpdf import FPDF

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(
    page_title="Prowrap Master Calculator",
    page_icon="🔧",
    layout="wide"
)

# --- 2. PROWRAP CERTIFIED DATA ---
PROWRAP = {
    "ply_thickness": 0.83,        # mm
    "modulus_circ": 45460,        # MPa (Ec)
    "modulus_axial": 43800,       # MPa (Ea)
    "tensile_strength": 574.1,    # MPa (Sc)
    "strain_fail_circ": 0.0233,   # 2.33% circumferential
    "strain_fail_axial": 0.0243,  # 2.43% axial
    "poisson": 0.066,             # v (circumferential direction)
    "lap_shear": 7.37,            # MPa (tau)
    "max_temp": 55.5,             # C
    "shore_d": 70,
    "cloth_width_mm": 300,
    "stitching_overlap_mm": 50
}

# --- 3. ISO 24817 FIXED DESIGN STRAIN ---
ISO_STRAIN_LIMIT = 0.008  # ect = ea = 0.008 for both directions


def safe_text(text):
    if not isinstance(text, str):
        return str(text)
    replacements = {
        'ı': 'i', 'İ': 'I', 'ş': 's', 'Ş': 'S',
        'ğ': 'g', 'Ğ': 'G', 'ü': 'u', 'Ü': 'U',
        'ö': 'o', 'Ö': 'O', 'ç': 'c', 'Ç': 'C',
        'ε': 'e', '≥': '>=', '≤': '<=', '×': 'x',
    }
    for tr, eng in replacements.items():
        text = text.replace(tr, eng)
    return text


# ======================================================================
# CALCULATION ENGINES
# ======================================================================

def calc_feq(pressure_mpa, od, fax=0.0, moment=0.0):
    """
    ISO 24817:2017, Section 7.5.1
    Feq = Fax + p * pi * D^2 / 4 + 4*M/D
    
    For capped pipe with no external loads: Feq = p * pi * D^2 / 4
    """
    f_endcap = pressure_mpa * math.pi * od**2 / 4.0
    f_bending = (4.0 * moment / od) if od > 0 else 0.0
    feq = fax + f_endcap + f_bending
    return feq, f_endcap


def calc_iso24817(pressure_mpa, od, wall, rem_wall, yield_strength,
                  ec, ea, v, feq, repair_class):
    """
    ISO 24817:2017 - Full Equations (1) and (2) for Type A.
    
    Eq (1) - Circumferential:
      tmin_c = (peq*D/2 - s*ts) / (Ec * ec)
      
    Eq (2) - Axial:
      tmin_a = (Feq/(pi*D) - s*ts) / (Ea * ea)
    
    For Type B: s*ts = 0 (no steel credit)
    """
    ec_strain = ISO_STRAIN_LIMIT
    ea_strain = ISO_STRAIN_LIMIT

    if repair_class == "Type A":
        steel_hoop = yield_strength * rem_wall       # s * ts (N/mm)
        steel_axial = yield_strength * rem_wall       # s * ts (N/mm)
    else:
        steel_hoop = 0.0
        steel_axial = 0.0

    # --- tmin_c: circumferential (Eq. 1 simplified) ---
    hoop_demand = (pressure_mpa * od) / 2.0
    composite_hoop = max(0.0, hoop_demand - steel_hoop)
    if composite_hoop > 0:
        tmin_c = composite_hoop / (ec * ec_strain)
    else:
        tmin_c = 0.0

    # --- tmin_a: axial (Eq. 2 simplified) ---
    axial_demand = feq / (math.pi * od)
    composite_axial = max(0.0, axial_demand - steel_axial)
    if composite_axial > 0:
        tmin_a = composite_axial / (ea * ea_strain)
    else:
        tmin_a = 0.0

    # --- tdesign = max of both ---
    tdesign = max(tmin_c, tmin_a)
    governing = "Circumferential" if tmin_c >= tmin_a else "Axial"

    return tdesign, tmin_c, tmin_a, ec_strain, ea_strain, steel_hoop, composite_hoop, composite_axial, governing


def calc_asme_pcc2(pressure_mpa, od, wall, rem_wall, yield_strength,
                   ec, ea, design_factor, temp, feq, repair_class):
    """
    ASME PCC-2 - derives design strain from measured failure strain / SF.
    Same dual-axis approach.
    """
    safety_factor = 1.0 / design_factor
    temp_factor = 0.95 if temp > 40 else 1.0
    ec_strain = (PROWRAP["strain_fail_circ"] * temp_factor) / safety_factor
    ea_strain = (PROWRAP["strain_fail_axial"] * temp_factor) / safety_factor

    if repair_class == "Type A":
        allowable_stress = yield_strength * design_factor
        steel_hoop = allowable_stress * rem_wall
        steel_axial = allowable_stress * rem_wall
    else:
        steel_hoop = 0.0
        steel_axial = 0.0

    # tmin_c
    hoop_demand = (pressure_mpa * od) / 2.0
    composite_hoop = max(0.0, hoop_demand - steel_hoop)
    tmin_c = composite_hoop / (ec * ec_strain) if composite_hoop > 0 else 0.0

    # tmin_a
    axial_demand = feq / (math.pi * od)
    composite_axial = max(0.0, axial_demand - steel_axial)
    tmin_a = composite_axial / (ea * ea_strain) if composite_axial > 0 else 0.0

    tdesign = max(tmin_c, tmin_a)
    governing = "Circumferential" if tmin_c >= tmin_a else "Axial"

    return tdesign, tmin_c, tmin_a, ec_strain, ea_strain, steel_hoop, composite_hoop, composite_axial, governing


def calc_overlap(od, wall):
    """
    Axial extent of repair overlay (each side).
    
    lover = 2 * sqrt(D * tsubstrate)
    
    Where:
      D          = pipe outer diameter (mm)
      tsubstrate = original nominal wall thickness (mm)
    """
    lover = 2.0 * math.sqrt(od * wall)
    return lover


def calc_total_repair_length(defect_length, overlap):
    """
    l_total = l_defect + 2 * l_over
    (No taper)
    """
    return defect_length + 2.0 * overlap


def calc_procurement(total_repair_length, od, num_plies):
    if total_repair_length <= PROWRAP["cloth_width_mm"]:
        num_bands = 1
        proc_length = 300
    else:
        num_bands = math.ceil((total_repair_length - 300) / 250) + 1
        proc_length = num_bands * 300

    circumference_m = (math.pi * od) / 1000
    axial_m = proc_length / 1000
    sqm = axial_m * circumference_m * num_plies
    epoxy = sqm * 1.2
    return num_bands, proc_length, sqm, epoxy


# ======================================================================
# PDF GENERATOR
# ======================================================================

def create_pdf(report_data):
    pdf = FPDF()
    pdf.add_page()

    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, txt="PROWRAP COMPOSITE REPAIR REPORT", ln=True, align='C')
    pdf.set_font("Arial", 'I', 10)
    pdf.cell(0, 8, txt=f"Standard: {report_data['standard_label']}", ln=True, align='C')
    pdf.ln(5)

    def add_section(title, data_dict):
        pdf.set_font("Arial", 'B', 12)
        pdf.set_fill_color(200, 220, 255)
        pdf.cell(0, 8, txt=title, ln=True, fill=True)
        pdf.set_font("Arial", '', 10)
        for key, val in data_dict.items():
            pdf.cell(105, 6, txt=safe_text(f"{key}:"), border=0)
            pdf.cell(0, 6, txt=safe_text(str(val)), ln=True, border=0)
        pdf.ln(5)

    add_section("1. Project & Pipeline Data", {
        "Customer": report_data['customer'],
        "Location": report_data['location'],
        "Report No": report_data['report_no'],
        "Pipe OD": f"{report_data['od']} mm",
        "Nominal Wall (tsubstrate)": f"{report_data['wall']} mm",
        "Pipe Yield Strength (s)": f"{report_data['yield_str']} MPa",
        "Design Pressure": f"{report_data['pressure']} bar",
        "Operating Temperature": f"{report_data['temp']} C",
        "Axial Load (Fax)": f"{report_data['fax']:.1f} N",
        "Bending Moment (M)": f"{report_data['moment']:.1f} N.mm",
        "Feq (calculated)": f"{report_data['feq']:.0f} N ({report_data['feq']/1000:.1f} kN)",
    })

    rc = report_data['repair_class']
    rc_desc = "Load Sharing" if rc == "Type A" else "Full Replacement"

    add_section("2. Defect Assessment", {
        "Defect Mechanism": report_data['defect_type'],
        "Defect Location": report_data['defect_loc'],
        "Remaining Wall (ts)": f"{report_data['rem_wall']} mm",
        "Axial Length": f"{report_data['length']} mm",
        "Wall Loss": f"{report_data['wall_loss_ratio']*100:.1f} %",
        "Repair Class": f"{rc} - {rc_desc}",
    })

    std = report_data['selected_standard']
    r = report_data['results']['ISO 24817'] if std in ["ISO 24817", "Both"] else report_data['results']['ASME PCC-2']

    add_section(f"3. Repair Design ({std if std != 'Both' else 'ISO 24817 - Governing'})", {
        "Standard": std if std != "Both" else "ISO 24817 (Governing)",
        "Repair Class": rc,
        "ec (circ. design strain)": f"{r['ec_strain']*100:.3f} %",
        "ea (axial design strain)": f"{r['ea_strain']*100:.3f} %",
        "tmin_c (circumferential)": f"{r['tmin_c']:.2f} mm",
        "tmin_a (axial)": f"{r['tmin_a']:.2f} mm",
        "tdesign (governing)": f"{r['tdesign']:.2f} mm ({r['governing']})",
        "Required Plies": f"{r['num_plies']} Layers ({r['final_thickness']:.2f} mm)",
        "lover (each side)": f"{r['overlap']:.1f} mm = 2*sqrt(D*tsubstrate)",
        "Total Repair Length": f"{r['total_length']:.0f} mm",
        "Procurement Length": f"{r['proc_length']} mm ({r['num_bands']} Bands)",
    })

    if std == "Both":
        r_asme = report_data['results']['ASME PCC-2']
        add_section("3b. ASME PCC-2 Comparison", {
            "Standard": "ASME PCC-2",
            "ec / ea": f"{r_asme['ec_strain']*100:.3f}% / {r_asme['ea_strain']*100:.3f}%",
            "tmin_c / tmin_a": f"{r_asme['tmin_c']:.2f} / {r_asme['tmin_a']:.2f} mm",
            "Required Plies": f"{r_asme['num_plies']} Layers ({r_asme['final_thickness']:.2f} mm)",
            "lover": f"{r_asme['overlap']:.1f} mm",
            "Total Repair Length": f"{r_asme['total_length']:.0f} mm",
        })

        diff = r['num_plies'] - r_asme['num_plies']
        if diff > 0:
            pdf.set_font("Arial", 'B', 10)
            pdf.set_text_color(180, 0, 0)
            pdf.multi_cell(0, 6, txt=safe_text(
                f"ISO 24817 requires {diff} additional layer(s) vs ASME PCC-2."
            ))
            pdf.set_text_color(0, 0, 0)
            pdf.ln(3)

    pdf.set_font("Arial", 'I', 9)
    pdf.set_text_color(100, 100, 100)
    pdf.multi_cell(0, 5, txt=safe_text(
        f"* Repair Class {rc} selected by engineer. "
        f"Design life = {report_data['design_life']} yrs, f = {report_data['design_factor']}. "
        f"lover = 2*sqrt(D*tsubstrate)."
    ))
    pdf.set_text_color(0, 0, 0)
    pdf.ln(5)

    add_section("4. Material Procurement", {
        "Fabric (300mm Roll)": f"{r['sqm']:.2f} sqm",
        "Epoxy Required": f"{r['epoxy_kg']:.1f} kg"
    })

    pdf.set_font("Arial", 'B', 12)
    pdf.set_fill_color(200, 220, 255)
    pdf.cell(0, 8, txt="5. Installation Checklist", ln=True, fill=True)
    pdf.set_font("Arial", '', 10)
    steps = [
        "1. Surface Prep: Grit blast to SA 2.5; Profile >60 microns.",
        "2. Primer/Filler: Apply Prowrap Filler to restore OD.",
        f"3. Lamination: Apply {r['num_plies']} layers per band.",
        f"4. Wrapping: Use {r['num_bands']} band(s) of 300mm cloth.",
        f"5. Overlap: {r['overlap']:.0f} mm full-thickness beyond defect each side.",
        f"6. Total axial extent: {r['total_length']:.0f} mm minimum.",
        f"7. Quality Control: Shore D hardness >= {PROWRAP['shore_d']}."
    ]
    for step in steps:
        pdf.multi_cell(0, 6, txt=safe_text(step))

    output = pdf.output(dest='S')
    if isinstance(output, str):
        return output.encode('latin-1', 'replace')
    return bytes(output)


# ======================================================================
# MAIN CALCULATION RUNNER
# ======================================================================

def run_calculation(customer, location, report_no, od, wall, pressure, temp,
                    defect_type, defect_loc, length, rem_wall, yield_strength,
                    design_factor, design_life, selected_standard, repair_class,
                    fax, moment):
    # Validation
    errors = []
    if temp > PROWRAP["max_temp"]:
        errors.append(f"❌ **CRITICAL:** Op. temp ({temp}C) exceeds Prowrap limit ({PROWRAP['max_temp']}C).")
    if rem_wall > wall:
        errors.append("❌ **INPUT ERROR:** Remaining wall > nominal wall.")
    if rem_wall <= 0 and repair_class == "Type A":
        errors.append("❌ **INPUT ERROR:** Type A requires remaining wall > 0.")
    if errors:
        for err in errors:
            st.error(err)
        return

    pressure_mpa = pressure * 0.1
    wall_loss_ratio = (wall - rem_wall) / wall
    ec = PROWRAP["modulus_circ"]
    ea = PROWRAP["modulus_axial"]
    v = PROWRAP["poisson"]
    safety_factor = 1.0 / design_factor

    # Step 1: Feq
    feq, f_endcap = calc_feq(pressure_mpa, od, fax, moment)

    results = {}

    # --- ISO 24817 ---
    if selected_standard in ["ISO 24817", "Both"]:
        tdesign, tmin_c, tmin_a, ec_s, ea_s, steel_h, comp_h, comp_a, gov = calc_iso24817(
            pressure_mpa, od, wall, rem_wall, yield_strength, ec, ea, v, feq, repair_class
        )
        n = math.ceil(tdesign / PROWRAP["ply_thickness"])
        min_plies = 4 if defect_type == "Leak" else 2
        n = max(n, min_plies)
        if st.session_state.force_3_layers and n < 3:
            n = 3
        ft = n * PROWRAP["ply_thickness"]

        # Overlap uses tmin_a and ea_strain
        ov = calc_overlap(od, wall)
        total_len = calc_total_repair_length(length, ov)
        nb, pl, sqm, ep = calc_procurement(total_len, od, n)

        results["ISO 24817"] = {
            "tdesign": tdesign, "tmin_c": tmin_c, "tmin_a": tmin_a,
            "ec_strain": ec_s, "ea_strain": ea_s,
            "steel_contribution": steel_h, "governing": gov,
            "num_plies": n, "final_thickness": ft,
            "overlap": ov,
            "total_length": total_len,
            "num_bands": nb, "proc_length": pl,
            "sqm": sqm, "epoxy_kg": ep,
            "strain_note": "Fixed (ect=ea=0.008)",
        }

    # --- ASME PCC-2 ---
    if selected_standard in ["ASME PCC-2", "Both"]:
        tdesign, tmin_c, tmin_a, ec_s, ea_s, steel_h, comp_h, comp_a, gov = calc_asme_pcc2(
            pressure_mpa, od, wall, rem_wall, yield_strength, ec, ea,
            design_factor, temp, feq, repair_class
        )
        n = math.ceil(tdesign / PROWRAP["ply_thickness"])
        min_plies = 4 if defect_type == "Leak" else 2
        n = max(n, min_plies)
        if st.session_state.force_3_layers and n < 3:
            n = 3
        ft = n * PROWRAP["ply_thickness"]

        ov = calc_overlap(od, wall)
        total_len = calc_total_repair_length(length, ov)
        nb, pl, sqm, ep = calc_procurement(total_len, od, n)

        results["ASME PCC-2"] = {
            "tdesign": tdesign, "tmin_c": tmin_c, "tmin_a": tmin_a,
            "ec_strain": ec_s, "ea_strain": ea_s,
            "steel_contribution": steel_h, "governing": gov,
            "num_plies": n, "final_thickness": ft,
            "overlap": ov,
            "total_length": total_len,
            "num_bands": nb, "proc_length": pl,
            "sqm": sqm, "epoxy_kg": ep,
            "strain_note": f"Derived from test data / SF",
        }

    # ====================================================================
    # DISPLAY
    # ====================================================================
    st.success("✅ Calculation Complete")

    # Repair class + Feq banner
    if repair_class == "Type A":
        st.info(f"🔵 **Type A (Load Sharing)** | Feq = {feq/1000:.1f} kN (end-cap: {f_endcap/1000:.1f} kN)")
    else:
        st.error(f"🔴 **Type B (Full Replacement)** | Feq = {feq/1000:.1f} kN (end-cap: {f_endcap/1000:.1f} kN)")

    # Governing result
    if selected_standard == "Both":
        gov_key = max(results, key=lambda k: results[k]['num_plies'])
        gov = results[gov_key]
    else:
        gov_key = selected_standard
        gov = results[gov_key]

    # Metrics
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Plies", f"{gov['num_plies']}", f"{gov['final_thickness']:.2f} mm")
    m2.metric("tmin_c", f"{gov['tmin_c']:.2f} mm")
    m3.metric("tmin_a", f"{gov['tmin_a']:.2f} mm")
    m4.metric("lover", f"{gov['overlap']:.1f} mm")
    m5.metric("Total Length", f"{gov['total_length']:.0f} mm")
    m6.metric("Epoxy", f"{gov['epoxy_kg']:.1f} kg")

    if selected_standard == "Both":
        st.caption(f"☝️ Showing **{gov_key}** (governing)")

    # Overlap breakdown
    st.markdown("---")
    st.markdown(f"**Overlap Calculation:**")
    st.markdown(
        f"lover = 2 x sqrt(D x tsubstrate) = 2 x sqrt({od} x {wall}) = **{gov['overlap']:.1f} mm**"
    )
    st.markdown(f"**Total:** {length:.0f} (defect) + 2 x {gov['overlap']:.1f} (overlap) = **{gov['total_length']:.0f} mm**")

    st.markdown("---")

    # Comparison
    if selected_standard == "Both":
        st.markdown("### ⚖️ Standard Comparison")
        col_iso, col_vs, col_asme = st.columns([5, 1, 5])

        with col_iso:
            badge = " 🏛️ GOV" if gov_key == "ISO 24817" else ""
            st.markdown(f"#### ISO 24817{badge}")
            ri = results["ISO 24817"]
            st.write(f"**εc / εa:** {ri['ec_strain']*100:.3f}% / {ri['ea_strain']*100:.3f}% — Fixed")
            st.write(f"**tmin_c:** {ri['tmin_c']:.2f} mm | **tmin_a:** {ri['tmin_a']:.2f} mm → **{ri['governing']}** governs")
            st.write(f"**Plies:** {ri['num_plies']} ({ri['final_thickness']:.2f} mm)")
            st.write(f"**lover:** {ri['overlap']:.1f} mm = 2*sqrt(D*t)")
            st.write(f"**Total:** {ri['total_length']:.0f} mm | {ri['sqm']:.2f} m² | {ri['epoxy_kg']:.1f} kg")

        with col_vs:
            st.markdown("<br><br>", unsafe_allow_html=True)
            st.markdown("## vs")

        with col_asme:
            badge = " 🏛️ GOV" if gov_key == "ASME PCC-2" else ""
            st.markdown(f"#### ASME PCC-2{badge}")
            ra = results["ASME PCC-2"]
            st.write(f"**εc / εa:** {ra['ec_strain']*100:.3f}% / {ra['ea_strain']*100:.3f}% — Derived")
            st.write(f"**tmin_c:** {ra['tmin_c']:.2f} mm | **tmin_a:** {ra['tmin_a']:.2f} mm → **{ra['governing']}** governs")
            st.write(f"**Plies:** {ra['num_plies']} ({ra['final_thickness']:.2f} mm)")
            st.write(f"**lover:** {ra['overlap']:.1f} mm = 2*sqrt(D*t)")
            st.write(f"**Total:** {ra['total_length']:.0f} mm | {ra['sqm']:.2f} m² | {ra['epoxy_kg']:.1f} kg")

        diff = results["ISO 24817"]["num_plies"] - results["ASME PCC-2"]["num_plies"]
        if diff > 0:
            st.warning(f"⚠️ ISO 24817 requires {diff} more layer(s) than ASME PCC-2.")
        elif diff < 0:
            st.info("ℹ️ ASME PCC-2 more conservative (check inputs).")
        else:
            st.info("ℹ️ Both standards yield same plies.")
        st.markdown("---")

    # Upgrade prompt
    is_upgraded = st.session_state.force_3_layers and gov['num_plies'] >= 3
    if gov['num_plies'] == 2 and not is_upgraded:
        cw, cb = st.columns([3, 1])
        with cw:
            st.warning("⚠️ **PROTAP:** Min. 3 layers recommended for harsh environments.")
        with cb:
            if st.button("⬆️ Upgrade to 3?", use_container_width=True):
                st.session_state.force_3_layers = True
                st.rerun()
    elif is_upgraded:
        st.info("ℹ️ Upgraded to min. 3 layers per PROTAP recommendation.")
    st.markdown("---")

    # Tabs
    tab1, tab2 = st.tabs(["📊 Engineering Analysis", "📄 Method Statement"])

    with tab1:
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("### Defect")
            st.write(f"**Type:** {defect_type} ({defect_loc})")
            st.write(f"**Wall Loss:** {wall_loss_ratio*100:.1f}%")
            st.write(f"**ts (remaining):** {rem_wall} mm of {wall} mm")
        with c2:
            st.markdown("### Axial Load (Feq)")
            st.write(f"**Fax:** {fax:.0f} N")
            st.write(f"**End-cap:** p x pi x D^2/4 = {f_endcap:.0f} N")
            st.write(f"**M:** {moment:.0f} N.mm")
            st.write(f"**Feq:** {feq:.0f} N = **{feq/1000:.1f} kN**")
            st.write(f"**Feq/(pi*D):** {feq/(math.pi*od):.1f} N/mm")
        with c3:
            st.markdown("### Design Thickness")
            st.write(f"**tmin_c:** {gov['tmin_c']:.2f} mm (circumferential)")
            st.write(f"**tmin_a:** {gov['tmin_a']:.2f} mm (axial)")
            st.write(f"**Governing:** {gov['governing']}")
            st.write(f"**tdesign:** {gov['tdesign']:.2f} mm → {gov['num_plies']} plies")

    with tab2:
        st.markdown("## 🛠️ Method Statement")
        st.markdown("---")
        c_pipe, c_defect, c_repair = st.columns(3)
        with c_pipe:
            st.info("**1. Pipeline**")
            st.markdown(f"""
            - **OD:** {od} mm
            - **Nom. Wall:** {wall} mm
            - **Yield:** {yield_strength} MPa
            - **Pressure:** {pressure} bar
            - **Temp:** {temp} C
            - **Feq:** {feq/1000:.1f} kN
            """)
        with c_defect:
            st.warning("**2. Defect**")
            st.markdown(f"""
            - **Type:** {defect_type} ({defect_loc})
            - **ts:** {rem_wall} mm
            - **Length:** {length} mm
            - **Wall Loss:** {wall_loss_ratio*100:.1f}%
            - **Class:** {repair_class}
            """)
        with c_repair:
            st.success(f"**3. Design ({gov_key})**")
            st.markdown(f"""
            - **Class:** {repair_class}
            - **Plies:** {gov['num_plies']} ({gov['final_thickness']:.2f} mm)
            - **tmin_c:** {gov['tmin_c']:.2f} mm | **tmin_a:** {gov['tmin_a']:.2f} mm
            - **lover:** {gov['overlap']:.1f} mm
            - **Total Length:** {gov['total_length']:.0f} mm
            - **Bands:** {gov['num_bands']} x 300mm
            - **Epoxy:** {gov['epoxy_kg']:.1f} kg
            """)

        st.markdown("---")
        st.markdown("### 📋 Installation Checklist")
        st.markdown(f"""
        1. **Surface Prep:** SA 2.5, profile >60um.
        2. **Filler:** Prowrap Filler to restore OD.
        3. **Lamination:** {gov['num_plies']} layers per band.
        4. **Wrapping:** {gov['num_bands']} band(s) of 300mm cloth.
        5. **Overlap:** {gov['overlap']:.0f} mm beyond defect each side.
        6. **Total Extent:** {gov['total_length']:.0f} mm minimum.
        7. **QC:** Shore D >= {PROWRAP['shore_d']}.
        """)

    # PDF
    st.divider()
    try:
        report_data = {
            "customer": customer, "location": location, "report_no": report_no,
            "od": od, "wall": wall, "yield_str": yield_strength,
            "pressure": pressure, "temp": temp, "fax": fax, "moment": moment,
            "feq": feq,
            "defect_type": defect_type, "defect_loc": defect_loc,
            "rem_wall": rem_wall, "length": length,
            "wall_loss_ratio": wall_loss_ratio,
            "design_factor": design_factor, "design_life": design_life,
            "selected_standard": selected_standard, "repair_class": repair_class,
            "standard_label": f"{selected_standard} | {repair_class}" if selected_standard != "Both" else f"ISO 24817 / ASME PCC-2 | {repair_class}",
            "results": results,
        }
        pdf_bytes = create_pdf(report_data)
        st.download_button(
            label="📄 Download Report as PDF",
            data=pdf_bytes,
            file_name=f"Prowrap_Repair_{safe_text(report_no)}.pdf",
            mime="application/pdf",
            type="primary"
        )
    except Exception as e:
        st.error(f"⚠️ PDF Error: {e}")


# ======================================================================
# APP ENTRY
# ======================================================================

def reset_calc():
    st.session_state.calc_active = False
    st.session_state.force_3_layers = False


def main():
    if 'calc_active' not in st.session_state:
        st.session_state.calc_active = False
    if 'force_3_layers' not in st.session_state:
        st.session_state.force_3_layers = False

    try:
        st.title("🔧 Prowrap Repair Master Calculator")
        st.markdown(f"**Dual Standard:** ISO 24817 & ASME PCC-2 | **T-Limit:** {PROWRAP['max_temp']}°C")

        st.sidebar.header("1. Project Info")
        customer = st.sidebar.text_input("Customer", value="PROTAP", on_change=reset_calc)
        location = st.sidebar.text_input("Location", value="Turkey", on_change=reset_calc)
        report_no = st.sidebar.text_input("Report No", value="24-152", on_change=reset_calc)

        st.sidebar.header("2. Pipeline Data")
        od = st.sidebar.number_input("Pipe OD [mm]", value=508.0, on_change=reset_calc)
        wall = st.sidebar.number_input("Nominal Wall (tsubstrate) [mm]", value=8.7, on_change=reset_calc)
        yield_str = st.sidebar.number_input("Pipe Yield (s) [MPa]", value=358.0, on_change=reset_calc)

        st.sidebar.header("3. Service Conditions")
        pres = st.sidebar.number_input("Design Pressure [bar]", value=122.6, on_change=reset_calc)
        temp = st.sidebar.number_input("Op. Temperature [C]", value=40.0, on_change=reset_calc)

        st.sidebar.header("4. Defect Data")
        type_ = st.sidebar.selectbox("Mechanism", ["Corrosion", "Dent", "Leak", "Crack"], on_change=reset_calc)
        loc_ = st.sidebar.selectbox("Location", ["External", "Internal"], on_change=reset_calc)
        len_ = st.sidebar.number_input("Defect Length [mm]", value=254.0, on_change=reset_calc)
        rem_ = st.sidebar.number_input("Remaining Wall (ts) [mm]", value=1.74, on_change=reset_calc)

        st.sidebar.header("5. Axial Loads (ISO 24817 Annex A)")
        fax = st.sidebar.number_input("Fax - Axial Load [N]", value=0.0, on_change=reset_calc,
                                      help="External axial load from stress analysis. 0 for unrestrained pipe.")
        moment = st.sidebar.number_input("M - Bending Moment [N.mm]", value=0.0, on_change=reset_calc,
                                         help="Applied bending moment. 0 for straight pipe.")

        st.sidebar.header("6. Design Settings")
        repair_class = st.sidebar.selectbox(
            "Repair Class (ISO 24817 Sec. 7.2)",
            ["Type A", "Type B"], index=1,
            help="Type A: steel credited. Type B: no steel credit. Engineer's decision.",
            on_change=reset_calc
        )
        selected_standard = st.sidebar.selectbox(
            "Calculation Standard",
            ["Both", "ISO 24817", "ASME PCC-2"],
            on_change=reset_calc
        )
        design_life = st.sidebar.number_input("Design Life [years]", value=20, min_value=1, on_change=reset_calc)
        df = st.sidebar.number_input("Design Factor (f)", value=0.72, min_value=0.1, max_value=1.0, on_change=reset_calc,
                                     help="ASME PCC-2 only. ISO uses fixed ect=0.008.")

        if st.sidebar.button("Calculate & Optimize", type="primary"):
            st.session_state.calc_active = True
            st.session_state.force_3_layers = False

        if st.session_state.calc_active:
            run_calculation(customer, location, report_no, od, wall, pres, temp,
                            type_, loc_, len_, rem_, yield_str, df, design_life,
                            selected_standard, repair_class, fax, moment)

    except Exception as e:
        st.error(f"⚠️ Application Error: {e}")


if __name__ == "__main__":
    main()
