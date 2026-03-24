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
    "modulus_axial": 43800,       # MPa
    "tensile_strength": 574.1,    # MPa (Sc)
    "strain_fail": 0.0233,        # 2.33% (measured per ISO 527-4)
    "lap_shear": 7.37,            # MPa
    "max_temp": 55.5,             # °C
    "shore_d": 70,
    "cloth_width_mm": 300,
    "stitching_overlap_mm": 50
}

# --- 3. ISO 24817 FIXED DESIGN STRAIN ---
# Per ISO 24817 / Sonatrach PR 700.012: εct is a code-mandated constant,
# NOT derived from measured failure strain. It is the short-term allowable
# circumferential strain of the composite, fixed at 0.8%.
ISO_STRAIN_LIMIT = 0.008


def safe_text(text):
    """Safely replaces Turkish/Special characters to prevent PDF encoding crashes."""
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


def calc_iso24817(pressure_mpa, od, wall, rem_wall, yield_strength, ec, defect_type, defect_loc, wall_loss_ratio):
    """
    ISO 24817 repair thickness calculation.
    Uses the FIXED design strain εct = 0.008 (0.8%).
    
    Formula: t_repair = (1 / (Ec × εct)) × ((pf × D / 2) − Sa × ts)
    
    Where:
      pf  = design pressure (MPa)
      D   = pipe outer diameter (mm)
      Sa  = pipe yield strength (MPa)
      ts  = remaining wall thickness (mm)
      Ec  = composite circumferential modulus (MPa)
      εct = 0.008 (ISO 24817 code-mandated short-term strain limit)
    """
    is_through_wall = defect_type in ["Leak", "Crack"]
    is_severe = wall_loss_ratio > 0.80

    # Steel contribution to hoop resistance
    if is_through_wall or is_severe:
        steel_contribution = 0.0  # No credit for remaining steel
    else:
        steel_contribution = yield_strength * rem_wall

    # Composite must carry the deficit
    total_hoop_demand = (pressure_mpa * od) / 2.0
    composite_demand = max(0.0, total_hoop_demand - steel_contribution)

    if composite_demand > 0:
        t_required = composite_demand / (ec * ISO_STRAIN_LIMIT)
    else:
        t_required = 0.0

    return t_required, ISO_STRAIN_LIMIT, composite_demand, steel_contribution


def calc_asme_pcc2(pressure_mpa, od, wall, rem_wall, yield_strength, ec, design_factor, temp,
                   defect_type, defect_loc, wall_loss_ratio):
    """
    ASME PCC-2 repair thickness calculation.
    Derives the design strain from measured failure strain divided by a safety factor.
    
    Formula: t_repair = (P_composite × D) / (2 × Ec × ε_design)
    
    Where ε_design = ε_fail × temp_factor / (1/design_factor)
    """
    safety_factor = 1.0 / design_factor
    temp_factor = 0.95 if temp > 40 else 1.0
    design_strain = (PROWRAP["strain_fail"] * temp_factor) / safety_factor

    is_through_wall = defect_type in ["Leak", "Crack"]
    is_severe = wall_loss_ratio > 0.65

    # Allowable steel stress (derated by design factor)
    allowable_steel_stress = yield_strength * design_factor

    if is_through_wall or defect_loc == "Internal" or is_severe:
        p_steel_capacity = 0.0
    else:
        p_steel_capacity = (2 * allowable_steel_stress * rem_wall) / od

    # Type A vs Type B logic
    if defect_type == "Corrosion" and defect_loc == "External" and not is_severe:
        calc_method = "Type A (Load Sharing)"
    elif defect_type == "Dent":
        calc_method = "Type A (Dent Reinforcement)"
    else:
        calc_method = "Type B (Total Replacement)"

    if "Type A" in calc_method and p_steel_capacity > 0:
        p_composite_design = max(0, pressure_mpa - p_steel_capacity)
    else:
        p_composite_design = pressure_mpa

    if p_composite_design > 0:
        t_required = (p_composite_design * od) / (2 * ec * design_strain)
    else:
        t_required = 0.0

    return t_required, design_strain, p_composite_design, p_steel_capacity, calc_method


def calc_overlap(num_plies, final_thickness, design_strain, safety_factor, calc_method_overlap):
    """Calculate axial overlap length based on repair type."""
    if "Type A" in calc_method_overlap:
        overlap = max(50.0, 3.0 * final_thickness)
    else:
        hoop_load = final_thickness * PROWRAP["modulus_circ"] * design_strain
        allowable_shear = PROWRAP["lap_shear"] / safety_factor
        overlap = max(hoop_load / allowable_shear, 50.0)
    return overlap


def calc_procurement(total_repair_length, od, num_plies):
    """Calculate material procurement quantities."""
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


def create_pdf(report_data):
    """Generates a PDF report and returns it as bytes."""
    pdf = FPDF()
    pdf.add_page()

    # Title
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, txt="PROWRAP COMPOSITE REPAIR REPORT", ln=True, align='C')
    pdf.set_font("Arial", 'I', 10)
    pdf.cell(0, 8, txt=f"Standard: {report_data['standard_label']}", ln=True, align='C')
    pdf.ln(5)

    def add_section(title, data_dict):
        pdf.set_font("Arial", 'B', 12)
        pdf.set_fill_color(200, 220, 255)
        pdf.cell(0, 8, txt=title, ln=True, fill=True)
        pdf.set_font("Arial", '', 11)
        for key, val in data_dict.items():
            pdf.cell(95, 6, txt=safe_text(f"{key}:"), border=0)
            pdf.cell(0, 6, txt=safe_text(str(val)), ln=True, border=0)
        pdf.ln(5)

    add_section("1. Project & Pipeline Data", {
        "Customer": report_data['customer'],
        "Location": report_data['location'],
        "Report No": report_data['report_no'],
        "Pipe Outer Diameter": f"{report_data['od']} mm",
        "Nominal Wall Thickness": f"{report_data['wall']} mm",
        "Pipe Yield Strength": f"{report_data['yield_str']} MPa",
        "Design Pressure": f"{report_data['pressure']} bar",
        "Operating Temperature": f"{report_data['temp']} C"
    })

    add_section("2. Defect Assessment", {
        "Defect Mechanism": report_data['defect_type'],
        "Defect Location": report_data['defect_loc'],
        "Remaining Wall": f"{report_data['rem_wall']} mm",
        "Axial Length": f"{report_data['length']} mm",
        "Wall Loss": f"{report_data['wall_loss_ratio']*100:.1f} %",
    })

    # --- Primary Result ---
    std = report_data['selected_standard']
    r = report_data['results'][std] if std != "Both" else report_data['results']['ISO 24817']

    add_section(f"3. Repair Design ({std if std != 'Both' else 'ISO 24817 - Governing'})", {
        "Calculation Standard": std if std != "Both" else "ISO 24817 (Governing)",
        "Design Strain (ect)": f"{r['design_strain']*100:.3f} % ({r['strain_note']})",
        "Required Plies": f"{r['num_plies']} Layers",
        "Repair Thickness": f"{r['final_thickness']:.2f} mm",
        "Min. Required Repair Length": f"{r['iso_length']:.0f} mm",
        "Procurement Length": f"{r['proc_length']} mm ({r['num_bands']} Bands)",
    })

    # If both standards, add comparison
    if std == "Both":
        r_asme = report_data['results']['ASME PCC-2']
        add_section("3b. Comparison: ASME PCC-2 Result", {
            "Calculation Standard": "ASME PCC-2",
            "Design Strain": f"{r_asme['design_strain']*100:.3f} %",
            "Required Plies": f"{r_asme['num_plies']} Layers",
            "Repair Thickness": f"{r_asme['final_thickness']:.2f} mm",
            "Min. Required Repair Length": f"{r_asme['iso_length']:.0f} mm",
            "Procurement Length": f"{r_asme['proc_length']} mm ({r_asme['num_bands']} Bands)",
        })

        # Comparison note
        pdf.set_font("Arial", 'B', 10)
        pdf.set_text_color(180, 0, 0)
        diff_plies = r['num_plies'] - r_asme['num_plies']
        if diff_plies > 0:
            pdf.multi_cell(0, 6, txt=safe_text(
                f"IMPORTANT: ISO 24817 requires {diff_plies} additional layer(s) vs ASME PCC-2 "
                f"due to the fixed strain limit (ect=0.008). ISO 24817 is the more conservative standard."
            ))
        pdf.set_text_color(0, 0, 0)
        pdf.ln(3)

    # Note about design life
    pdf.set_font("Arial", 'I', 9)
    pdf.set_text_color(100, 100, 100)
    pdf.multi_cell(0, 5, txt=safe_text(
        f"* Note: Design life = {report_data['design_life']} years. "
        f"Design factor f = {report_data['design_factor']}."
    ))
    pdf.set_text_color(0, 0, 0)
    pdf.ln(5)

    # Material procurement (use governing result)
    add_section("4. Material Procurement", {
        "Fabric Needed (300mm Roll)": f"{r['sqm']:.2f} sqm",
        "Epoxy Required": f"{r['epoxy_kg']:.1f} kg"
    })

    # Method statement
    pdf.set_font("Arial", 'B', 12)
    pdf.set_fill_color(200, 220, 255)
    pdf.cell(0, 8, txt="5. Installation Checklist (Method Statement)", ln=True, fill=True)
    pdf.set_font("Arial", '', 11)

    steps = [
        "1. Surface Prep: Grit blast to SA 2.5; Profile >60 microns.",
        "2. Primer/Filler: Apply Prowrap Filler to defect area to restore OD.",
        f"3. Lamination: Saturate Carbon Cloth. Apply {r['num_plies']} layers per band.",
        f"4. Wrapping: Use {r['num_bands']} band(s) of 300mm cloth.",
        f"5. Quality Control: Minimum average Shore D hardness of {PROWRAP['shore_d']} required."
    ]
    for step in steps:
        pdf.multi_cell(0, 6, txt=safe_text(step))

    if r['num_plies'] == 2:
        pdf.ln(2)
        pdf.set_font("Arial", 'B', 10)
        pdf.set_text_color(200, 0, 0)
        pdf.multi_cell(0, 6, txt="NOTE: Protap recommends min. 3 layer repair if subject to harsh/corrosive environments per ISO 24817.")
        pdf.set_text_color(0, 0, 0)

    output = pdf.output(dest='S')
    if isinstance(output, str):
        return output.encode('latin-1', 'replace')
    return bytes(output)


def run_calculation(customer, location, report_no, od, wall, pressure, temp,
                    defect_type, defect_loc, length, rem_wall, yield_strength,
                    design_factor, design_life, selected_standard):
    # --- Input Validation ---
    errors = []
    if temp > PROWRAP["max_temp"]:
        errors.append(f"❌ **CRITICAL:** Operating temperature ({temp}°C) exceeds Prowrap limit of {PROWRAP['max_temp']}°C.")
    if rem_wall > wall:
        errors.append("❌ **INPUT ERROR:** Remaining wall cannot exceed nominal wall thickness.")
    if errors:
        for err in errors:
            st.error(err)
        return

    pressure_mpa = pressure * 0.1
    wall_loss_ratio = (wall - rem_wall) / wall
    ec = PROWRAP["modulus_circ"]
    safety_factor = 1.0 / design_factor

    # ====================================================================
    # DUAL CALCULATION ENGINE
    # ====================================================================
    results = {}

    # --- ISO 24817 Path (εct = 0.008 fixed) ---
    if selected_standard in ["ISO 24817", "Both"]:
        t_iso, strain_iso, composite_demand_iso, steel_contrib_iso = calc_iso24817(
            pressure_mpa, od, wall, rem_wall, yield_strength, ec,
            defect_type, defect_loc, wall_loss_ratio
        )
        n_iso = math.ceil(t_iso / PROWRAP["ply_thickness"])
        min_plies = 4 if defect_type == "Leak" else 2
        n_iso = max(n_iso, min_plies)

        if st.session_state.force_3_layers and n_iso < 3:
            n_iso = 3

        ft_iso = n_iso * PROWRAP["ply_thickness"]

        # Overlap: ISO uses shear-controlled for through-wall, geometry otherwise
        if defect_type in ["Leak", "Crack"] or wall_loss_ratio > 0.80:
            overlap_method = "Type B (Shear Controlled)"
        elif defect_type == "Corrosion" and defect_loc == "External":
            overlap_method = "Type A (Geometry Controlled)"
        else:
            overlap_method = "Type B (Shear Controlled)"

        ov_iso = calc_overlap(n_iso, ft_iso, strain_iso, safety_factor, overlap_method)
        total_len_iso = length + 2 * ov_iso
        nb_iso, pl_iso, sqm_iso, ep_iso = calc_procurement(total_len_iso, od, n_iso)

        results["ISO 24817"] = {
            "t_required": t_iso, "design_strain": strain_iso,
            "strain_note": "Fixed per ISO 24817 (ect=0.008)",
            "composite_pressure": composite_demand_iso / (od / 2) if od > 0 else 0,
            "steel_capacity_mpa": (2 * steel_contrib_iso) / od if od > 0 else 0,
            "num_plies": n_iso, "final_thickness": ft_iso,
            "overlap": ov_iso, "iso_length": total_len_iso,
            "num_bands": nb_iso, "proc_length": pl_iso,
            "sqm": sqm_iso, "epoxy_kg": ep_iso,
            "calc_method": overlap_method,
        }

    # --- ASME PCC-2 Path (strain from measured failure / safety factor) ---
    if selected_standard in ["ASME PCC-2", "Both"]:
        t_asme, strain_asme, p_comp_asme, p_steel_asme, method_asme = calc_asme_pcc2(
            pressure_mpa, od, wall, rem_wall, yield_strength, ec,
            design_factor, temp, defect_type, defect_loc, wall_loss_ratio
        )
        n_asme = math.ceil(t_asme / PROWRAP["ply_thickness"])
        min_plies = 4 if defect_type == "Leak" else 2
        n_asme = max(n_asme, min_plies)

        if st.session_state.force_3_layers and n_asme < 3:
            n_asme = 3

        ft_asme = n_asme * PROWRAP["ply_thickness"]

        if "Type A" in method_asme:
            overlap_method_asme = "Type A (Geometry Controlled)"
        else:
            overlap_method_asme = "Type B (Shear Controlled)"

        ov_asme = calc_overlap(n_asme, ft_asme, strain_asme, safety_factor, overlap_method_asme)
        total_len_asme = length + 2 * ov_asme
        nb_asme, pl_asme, sqm_asme, ep_asme = calc_procurement(total_len_asme, od, n_asme)

        results["ASME PCC-2"] = {
            "t_required": t_asme, "design_strain": strain_asme,
            "strain_note": f"Derived: {PROWRAP['strain_fail']*100:.2f}% / SF",
            "composite_pressure": p_comp_asme,
            "steel_capacity_mpa": p_steel_asme,
            "num_plies": n_asme, "final_thickness": ft_asme,
            "overlap": ov_asme, "iso_length": total_len_asme,
            "num_bands": nb_asme, "proc_length": pl_asme,
            "sqm": sqm_asme, "epoxy_kg": ep_asme,
            "calc_method": method_asme,
        }

    # ====================================================================
    # DISPLAY RESULTS
    # ====================================================================
    st.success("✅ Calculation Complete")

    # Determine the governing (most conservative) result for display
    if selected_standard == "Both":
        gov_key = max(results, key=lambda k: results[k]['num_plies'])
        gov = results[gov_key]
        non_gov_key = [k for k in results if k != gov_key][0]
        non_gov = results[non_gov_key]
    else:
        gov_key = selected_standard
        gov = results[gov_key]

    # --- Top-level metrics ---
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Required Plies", f"{gov['num_plies']}", f"{gov['final_thickness']:.2f} mm")
    m2.metric("Design Strain (εct)", f"{gov['design_strain']*100:.3f} %")
    m3.metric("Req. Repair Length", f"{gov['iso_length']:.0f} mm")
    m4.metric("Optimized Fabric", f"{gov['sqm']:.2f} m²")
    m5.metric("Epoxy Needed", f"{gov['epoxy_kg']:.1f} kg")

    if selected_standard == "Both":
        st.caption(f"☝️ Metrics shown for **{gov_key}** (governing — more conservative)")

    st.markdown("---")

    # --- Comparison Table (when Both selected) ---
    if selected_standard == "Both":
        st.markdown("### ⚖️ Standard Comparison")

        col_iso, col_vs, col_asme = st.columns([5, 1, 5])

        with col_iso:
            is_gov_iso = gov_key == "ISO 24817"
            badge = " 🏛️ GOVERNING" if is_gov_iso else ""
            st.markdown(f"#### ISO 24817{badge}")
            r_iso = results["ISO 24817"]
            st.write(f"**Design Strain (εct):** {r_iso['design_strain']*100:.3f}% — *Fixed (code-mandated)*")
            st.write(f"**Theoretical Thickness:** {r_iso['t_required']:.2f} mm")
            st.write(f"**Required Plies:** {r_iso['num_plies']} layers → {r_iso['final_thickness']:.2f} mm")
            st.write(f"**Repair Length:** {r_iso['iso_length']:.0f} mm")
            st.write(f"**Fabric:** {r_iso['sqm']:.2f} m² | **Epoxy:** {r_iso['epoxy_kg']:.1f} kg")

        with col_vs:
            st.markdown("<br><br><br>", unsafe_allow_html=True)
            st.markdown("## vs")

        with col_asme:
            is_gov_asme = gov_key == "ASME PCC-2"
            badge = " 🏛️ GOVERNING" if is_gov_asme else ""
            st.markdown(f"#### ASME PCC-2{badge}")
            r_asme = results["ASME PCC-2"]
            st.write(f"**Design Strain:** {r_asme['design_strain']*100:.3f}% — *Derived from test data*")
            st.write(f"**Theoretical Thickness:** {r_asme['t_required']:.2f} mm")
            st.write(f"**Required Plies:** {r_asme['num_plies']} layers → {r_asme['final_thickness']:.2f} mm")
            st.write(f"**Repair Length:** {r_asme['iso_length']:.0f} mm")
            st.write(f"**Fabric:** {r_asme['sqm']:.2f} m² | **Epoxy:** {r_asme['epoxy_kg']:.1f} kg")

        # Delta callout
        diff = results["ISO 24817"]["num_plies"] - results["ASME PCC-2"]["num_plies"]
        if diff > 0:
            st.warning(
                f"⚠️ **ISO 24817 requires {diff} more layer(s)** than ASME PCC-2 for the same defect. "
                f"This is because ISO uses a fixed εct = 0.008 (0.8%), while ASME derives "
                f"ε = {results['ASME PCC-2']['design_strain']*100:.3f}% from tested failure strain. "
                f"The ISO approach is ~{results['ISO 24817']['num_plies']/results['ASME PCC-2']['num_plies']:.1f}× "
                f"more conservative on layer count."
            )
        elif diff < 0:
            st.info("ℹ️ ASME PCC-2 is more conservative in this case (unusual — check inputs).")
        else:
            st.info("ℹ️ Both standards yield the same number of plies for this defect.")

        st.markdown("---")

    # --- Upgrade prompt for 2-ply results ---
    is_upgraded = st.session_state.force_3_layers and gov['num_plies'] >= 3
    if gov['num_plies'] == 2 and not is_upgraded:
        col_warn, col_btn = st.columns([3, 1])
        with col_warn:
            st.warning("⚠️ **PROTAP Recommendation:** Min. 3 layers for harsh/corrosive environments per ISO 24817.")
        with col_btn:
            if st.button("⬆️ Upgrade to 3 layers?", use_container_width=True):
                st.session_state.force_3_layers = True
                st.rerun()
    elif is_upgraded:
        st.info("ℹ️ **Design Upgraded:** Minimum 3 layers applied per PROTAP recommendation.")

    st.markdown("---")

    # --- Tabs ---
    tab1, tab2 = st.tabs(["📊 Engineering Analysis", "📄 Method Statement"])

    with tab1:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("### Defect Analysis")
            st.write(f"**Mechanism:** {defect_type} ({defect_loc})")
            st.write(f"**Wall Loss:** {wall_loss_ratio*100:.1f}%")
            st.write(f"**Remaining Wall:** {rem_wall} mm of {wall} mm")
        with c2:
            st.markdown("### Strain Philosophy")
            if selected_standard in ["ISO 24817", "Both"]:
                st.write(f"**ISO 24817 εct:** {ISO_STRAIN_LIMIT*100:.1f}% — Fixed, code-mandated")
            if selected_standard in ["ASME PCC-2", "Both"]:
                asme_strain = results.get("ASME PCC-2", {}).get("design_strain", 0)
                st.write(f"**ASME PCC-2 ε:** {asme_strain*100:.3f}% — Derived from {PROWRAP['strain_fail']*100:.2f}% failure / SF={safety_factor:.2f}")
            if selected_standard == "Both":
                ratio = asme_strain / ISO_STRAIN_LIMIT if ISO_STRAIN_LIMIT > 0 else 0
                st.write(f"**Ratio:** ASME strain is {ratio:.1f}× the ISO limit")
                st.caption("ISO's conservative fixed strain ensures a consistent safety margin regardless of supplier test data.")

    with tab2:
        st.markdown("## 🛠️ Prowrap Repair Method Statement")
        st.markdown("---")

        c_pipe, c_defect, c_repair = st.columns(3)
        with c_pipe:
            st.info("**1. Pipeline Parameters**")
            st.markdown(f"""
            - **Diameter:** {od} mm
            - **Nominal Wall:** {wall} mm
            - **Grade:** {yield_strength} MPa
            - **Design Pressure:** {pressure} bar
            - **Op. Temp:** {temp} °C
            """)
        with c_defect:
            st.warning("**2. Defect Description**")
            st.markdown(f"""
            - **Mechanism:** {defect_type} ({defect_loc})
            - **Remaining Wall:** {rem_wall} mm
            - **Axial Length:** {length} mm
            - **Wall Loss:** {wall_loss_ratio*100:.1f}%
            """)
        with c_repair:
            st.success(f"**3. Repair Design ({gov_key})**")
            st.markdown(f"""
            - **Total Plies:** {gov['num_plies']} Layers
            - **Repair Thickness:** {gov['final_thickness']:.2f} mm
            - **Design Strain:** {gov['design_strain']*100:.3f}%
            - **Req. Length (calc):** {gov['iso_length']:.0f} mm
            - **Axial Band(s):** {gov['num_bands']} × 300mm
            - **Procurement Len:** {gov['proc_length']} mm
            - **Epoxy Total:** {gov['epoxy_kg']:.1f} kg
            """)
            st.caption(f"*Calculated per {gov_key}. Design life: {design_life} years, f = {design_factor}.*")

        st.markdown("---")
        st.markdown("### 📋 Installation Checklist")
        st.markdown(f"""
        1. **Surface Prep:** Grit blast to **SA 2.5**; Profile **>60µm**.
        2. **Primer/Filler:** Apply Prowrap Filler to defect area to restore OD profile.
        3. **Lamination:** Saturate Carbon Cloth. Apply **{gov['num_plies']} layers** per band.
        4. **Wrapping:** Use **{gov['num_bands']} band(s)** of 300mm cloth.
        5. **Quality Control:** Minimum average Shore D hardness of **{PROWRAP['shore_d']}** required.
        """)

    # --- PDF Generator ---
    st.divider()
    try:
        report_data = {
            "customer": customer, "location": location, "report_no": report_no,
            "od": od, "wall": wall, "yield_str": yield_strength,
            "pressure": pressure, "temp": temp,
            "defect_type": defect_type, "defect_loc": defect_loc,
            "rem_wall": rem_wall, "length": length,
            "wall_loss_ratio": wall_loss_ratio,
            "design_factor": design_factor, "design_life": design_life,
            "selected_standard": selected_standard,
            "standard_label": f"{selected_standard} | ISO 24817 / ASME PCC-2" if selected_standard == "Both" else selected_standard,
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
    except Exception as pdf_error:
        st.error(f"⚠️ Could not generate PDF. Error: {pdf_error}")


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
        st.markdown(f"**Dual Standard:** ISO 24817 (εct=0.008) & ASME PCC-2 | **T-Limit:** {PROWRAP['max_temp']}°C")

        st.sidebar.header("1. Project Info")
        customer = st.sidebar.text_input("Customer", value="PROTAP", on_change=reset_calc)
        location = st.sidebar.text_input("Location", value="Turkey", on_change=reset_calc)
        report_no = st.sidebar.text_input("Report No", value="24-152", on_change=reset_calc)

        st.sidebar.header("2. Pipeline Data")
        od = st.sidebar.number_input("Pipe OD [mm]", value=457.2, on_change=reset_calc)
        wall = st.sidebar.number_input("Nominal Wall [mm]", value=9.53, on_change=reset_calc)
        yield_str = st.sidebar.number_input("Pipe Yield [MPa]", value=359.0, on_change=reset_calc)

        st.sidebar.header("3. Service Conditions")
        pres = st.sidebar.number_input("Design Pressure [bar]", value=50.0, on_change=reset_calc)
        temp = st.sidebar.number_input("Op. Temperature [°C]", value=40.0, on_change=reset_calc)

        st.sidebar.header("4. Defect Data")
        type_ = st.sidebar.selectbox("Mechanism", ["Corrosion", "Dent", "Leak", "Crack"], on_change=reset_calc)
        loc_ = st.sidebar.selectbox("Location", ["External", "Internal"], on_change=reset_calc)
        len_ = st.sidebar.number_input("Defect Length [mm]", value=100.0, on_change=reset_calc)
        rem_ = st.sidebar.number_input("Remaining Wall [mm]", value=4.5, on_change=reset_calc)

        st.sidebar.header("5. Design Settings")
        selected_standard = st.sidebar.selectbox(
            "Calculation Standard",
            ["Both", "ISO 24817", "ASME PCC-2"],
            help="ISO 24817 uses fixed εct=0.008. ASME PCC-2 derives strain from test data. 'Both' shows a side-by-side comparison.",
            on_change=reset_calc
        )
        design_life = st.sidebar.number_input("Design Life [years]", value=20, min_value=1, on_change=reset_calc)
        df = st.sidebar.number_input("Design Factor (f)", value=0.72, min_value=0.1, max_value=1.0, on_change=reset_calc,
                                     help="Used by ASME PCC-2 path. ISO 24817 path uses fixed εct=0.008 regardless of this factor.")

        if st.sidebar.button("Calculate & Optimize", type="primary"):
            st.session_state.calc_active = True
            st.session_state.force_3_layers = False

        if st.session_state.calc_active:
            run_calculation(customer, location, report_no, od, wall, pres, temp,
                            type_, loc_, len_, rem_, yield_str, df, design_life, selected_standard)

    except Exception as e:
        st.error(f"⚠️ Application Error: {e}")


if __name__ == "__main__":
    main()
