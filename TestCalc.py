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
    "strain_fail": 0.0233,        # 2.33% (measured per ISO 527-4)
    "lap_shear": 7.37,            # MPa (tau)
    "max_temp": 55.5,             # C
    "shore_d": 70,
    "cloth_width_mm": 300,
    "stitching_overlap_mm": 50
}

# --- 3. ISO 24817 FIXED DESIGN STRAIN ---
ISO_STRAIN_LIMIT = 0.008

# --- 4. TAPER RATIO ---
# ISO 24817 Sec. 7.5.8 / ASME PCC-2: taper is required at each end
# of the repair to avoid step-change stress concentration.
# Typical slope is 1:8 (rise:run), so ltaper = TAPER_RATIO x t_repair
TAPER_RATIO = 8


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


# ======================================================================
# CALCULATION ENGINES
# ======================================================================

def calc_iso24817(pressure_mpa, od, wall, rem_wall, yield_strength, ec, repair_class):
    """
    ISO 24817 repair thickness calculation.
    Uses the FIXED design strain ect = 0.008 (0.8%).

    Type A: t = (1/(Ec*ect)) * (P*D/2 - Sa*ts)   -> steel credited
    Type B: t = (P*D) / (2*Ec*ect)                 -> no steel credit
    """
    total_hoop_demand = (pressure_mpa * od) / 2.0

    if repair_class == "Type A":
        steel_contribution = yield_strength * rem_wall
        composite_demand = max(0.0, total_hoop_demand - steel_contribution)
    else:
        steel_contribution = 0.0
        composite_demand = total_hoop_demand

    if composite_demand > 0:
        t_required = composite_demand / (ec * ISO_STRAIN_LIMIT)
    else:
        t_required = 0.0

    return t_required, ISO_STRAIN_LIMIT, composite_demand, steel_contribution


def calc_asme_pcc2(pressure_mpa, od, wall, rem_wall, yield_strength, ec,
                   design_factor, temp, repair_class):
    """
    ASME PCC-2 repair thickness calculation.
    Derives design strain from measured failure strain / safety factor.
    """
    safety_factor = 1.0 / design_factor
    temp_factor = 0.95 if temp > 40 else 1.0
    design_strain = (PROWRAP["strain_fail"] * temp_factor) / safety_factor

    if repair_class == "Type A":
        allowable_steel_stress = yield_strength * design_factor
        p_steel_capacity = (2 * allowable_steel_stress * rem_wall) / od
        p_composite_design = max(0, pressure_mpa - p_steel_capacity)
    else:
        p_steel_capacity = 0.0
        p_composite_design = pressure_mpa

    if p_composite_design > 0:
        t_required = (p_composite_design * od) / (2 * ec * design_strain)
    else:
        t_required = 0.0

    return t_required, design_strain, p_composite_design, p_steel_capacity


def calc_overlap(final_thickness, design_strain, od, rem_wall):
    """
    ISO 24817:2017, Section 7.5.8, Equation (20) - SAME formula for Type A and Type B.
    
    lover >= (Ea x ea x tmin) / tau
    
    Where:
      Ea    = axial modulus of repair laminate (MPa)
      ea    = allowable axial strain (mm/mm) - same as circumferential design strain
      tmin  = repair laminate thickness (mm)
      tau   = lap shear strength of adhesive interface (MPa)

    Additional geometric minimum from shell theory:
      lover >= sqrt(D x ts)   [stress redistribution zone in cylinder]

    Absolute minimum: 50 mm
    """
    ea = PROWRAP["modulus_axial"]
    tau = PROWRAP["lap_shear"]

    # ISO 24817 Eq. (20): shear-based load transfer
    l_shear = (ea * design_strain * final_thickness) / tau

    # Geometric minimum: stress redistribution zone
    l_geom = math.sqrt(od * max(rem_wall, 0.1))

    # Absolute minimum per standard
    l_min = 50.0

    overlap = max(l_shear, l_geom, l_min)
    return overlap, l_shear, l_geom


def calc_taper(final_thickness):
    """
    ISO 24817 Sec. 7.5.8 / ASME PCC-2: taper at each repair end.
    Slope 1:8 -> ltaper = 8 x t_repair (each side).
    Prevents step-change stress concentration at repair termination.
    """
    return TAPER_RATIO * final_thickness


def calc_total_repair_length(defect_length, overlap, taper):
    """
    ISO 24817 Sec. 7.5.8: Total axial extent of repair.
    
    l_total = l_defect + 2 x l_over + 2 x l_taper
    """
    return defect_length + 2 * overlap + 2 * taper


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


# ======================================================================
# PDF GENERATOR
# ======================================================================

def create_pdf(report_data):
    """Generates a PDF report and returns it as bytes."""
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
        pdf.set_font("Arial", '', 11)
        for key, val in data_dict.items():
            pdf.cell(105, 6, txt=safe_text(f"{key}:"), border=0)
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

    rc = report_data['repair_class']
    rc_desc = "Load Sharing (steel + composite)" if rc == "Type A" else "Full Replacement (composite carries all)"

    add_section("2. Defect Assessment", {
        "Defect Mechanism": report_data['defect_type'],
        "Defect Location": report_data['defect_loc'],
        "Remaining Wall": f"{report_data['rem_wall']} mm",
        "Axial Length": f"{report_data['length']} mm",
        "Wall Loss": f"{report_data['wall_loss_ratio']*100:.1f} %",
        "Repair Class (ISO 24817)": f"{rc} - {rc_desc}",
    })

    # Primary result
    std = report_data['selected_standard']
    r = report_data['results']['ISO 24817'] if std in ["ISO 24817", "Both"] else report_data['results']['ASME PCC-2']

    add_section(f"3. Repair Design ({std if std != 'Both' else 'ISO 24817 - Governing'})", {
        "Calculation Standard": std if std != "Both" else "ISO 24817 (Governing)",
        "Repair Class": rc,
        "Design Strain (ect)": f"{r['design_strain']*100:.3f} % ({r['strain_note']})",
        "Steel Contribution": f"{r['steel_contribution']:.1f} N/mm" if rc == "Type A" else "None (Type B)",
        "Required Plies": f"{r['num_plies']} Layers",
        "Repair Thickness": f"{r['final_thickness']:.2f} mm",
        "Overlap (lover, each side)": f"{r['overlap']:.1f} mm [ISO 24817 Eq.20]",
        "Taper (ltaper, each side)": f"{r['taper']:.1f} mm [1:{TAPER_RATIO} slope]",
        "Total Repair Length": f"{r['total_length']:.0f} mm = {report_data['length']}+2x{r['overlap']:.0f}+2x{r['taper']:.0f}",
        "Procurement Length": f"{r['proc_length']} mm ({r['num_bands']} Bands)",
    })

    # If both standards, add ASME comparison
    if std == "Both":
        r_asme = report_data['results']['ASME PCC-2']
        add_section("3b. Comparison: ASME PCC-2 Result", {
            "Calculation Standard": "ASME PCC-2",
            "Repair Class": rc,
            "Design Strain": f"{r_asme['design_strain']*100:.3f} %",
            "Required Plies": f"{r_asme['num_plies']} Layers",
            "Repair Thickness": f"{r_asme['final_thickness']:.2f} mm",
            "Overlap (each side)": f"{r_asme['overlap']:.1f} mm",
            "Taper (each side)": f"{r_asme['taper']:.1f} mm",
            "Total Repair Length": f"{r_asme['total_length']:.0f} mm",
            "Procurement Length": f"{r_asme['proc_length']} mm ({r_asme['num_bands']} Bands)",
        })

        pdf.set_font("Arial", 'B', 10)
        pdf.set_text_color(180, 0, 0)
        diff = r['num_plies'] - r_asme['num_plies']
        if diff > 0:
            pdf.multi_cell(0, 6, txt=safe_text(
                f"IMPORTANT: ISO 24817 requires {diff} additional layer(s) vs ASME PCC-2 "
                f"due to fixed strain limit (ect=0.008)."
            ))
        pdf.set_text_color(0, 0, 0)
        pdf.ln(3)

    # Design notes
    pdf.set_font("Arial", 'I', 9)
    pdf.set_text_color(100, 100, 100)
    pdf.multi_cell(0, 5, txt=safe_text(
        f"* Repair Class {rc} selected by engineer. "
        f"Design life = {report_data['design_life']} years. "
        f"Design factor f = {report_data['design_factor']}. "
        f"Overlap per ISO 24817 Eq.20: lover = (Ea x ea x tmin) / tau. "
        f"Taper ratio 1:{TAPER_RATIO}."
    ))
    pdf.set_text_color(0, 0, 0)
    pdf.ln(5)

    # Material procurement
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
        f"5. Overlap: {r['overlap']:.0f} mm full-thickness extension beyond defect each side.",
        f"6. Taper: {r['taper']:.0f} mm taper zone (1:{TAPER_RATIO}) at each repair end.",
        f"7. Total axial extent: {r['total_length']:.0f} mm minimum.",
        f"8. Quality Control: Minimum average Shore D hardness of {PROWRAP['shore_d']} required."
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


# ======================================================================
# MAIN CALCULATION RUNNER
# ======================================================================

def run_calculation(customer, location, report_no, od, wall, pressure, temp,
                    defect_type, defect_loc, length, rem_wall, yield_strength,
                    design_factor, design_life, selected_standard, repair_class):
    # --- Input Validation ---
    errors = []
    if temp > PROWRAP["max_temp"]:
        errors.append(f"❌ **CRITICAL:** Operating temperature ({temp}°C) exceeds Prowrap limit of {PROWRAP['max_temp']}°C.")
    if rem_wall > wall:
        errors.append("❌ **INPUT ERROR:** Remaining wall cannot exceed nominal wall thickness.")
    if rem_wall <= 0 and repair_class == "Type A":
        errors.append("❌ **INPUT ERROR:** Type A requires remaining wall > 0. Use Type B for through-wall defects.")
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

    # --- ISO 24817 Path (ect = 0.008 fixed) ---
    if selected_standard in ["ISO 24817", "Both"]:
        t_iso, strain_iso, composite_demand_iso, steel_contrib_iso = calc_iso24817(
            pressure_mpa, od, wall, rem_wall, yield_strength, ec, repair_class
        )
        n_iso = math.ceil(t_iso / PROWRAP["ply_thickness"])
        min_plies = 4 if defect_type == "Leak" else 2
        n_iso = max(n_iso, min_plies)

        if st.session_state.force_3_layers and n_iso < 3:
            n_iso = 3

        ft_iso = n_iso * PROWRAP["ply_thickness"]

        # Overlap: ISO 24817 Eq. 20 - same formula for Type A and Type B
        ov_iso, ov_shear_iso, ov_geom_iso = calc_overlap(ft_iso, strain_iso, od, rem_wall)
        # Taper: 1:8 slope at each end
        taper_iso = calc_taper(ft_iso)
        # Total length
        total_len_iso = calc_total_repair_length(length, ov_iso, taper_iso)
        nb_iso, pl_iso, sqm_iso, ep_iso = calc_procurement(total_len_iso, od, n_iso)

        results["ISO 24817"] = {
            "t_required": t_iso, "design_strain": strain_iso,
            "strain_note": "Fixed per ISO 24817 (ect=0.008)",
            "composite_pressure": composite_demand_iso / (od / 2) if od > 0 else 0,
            "steel_capacity_mpa": (2 * steel_contrib_iso) / od if od > 0 else 0,
            "steel_contribution": steel_contrib_iso,
            "num_plies": n_iso, "final_thickness": ft_iso,
            "overlap": ov_iso, "overlap_shear": ov_shear_iso, "overlap_geom": ov_geom_iso,
            "taper": taper_iso,
            "total_length": total_len_iso,
            "num_bands": nb_iso, "proc_length": pl_iso,
            "sqm": sqm_iso, "epoxy_kg": ep_iso,
            "repair_class": repair_class,
        }

    # --- ASME PCC-2 Path ---
    if selected_standard in ["ASME PCC-2", "Both"]:
        t_asme, strain_asme, p_comp_asme, p_steel_asme = calc_asme_pcc2(
            pressure_mpa, od, wall, rem_wall, yield_strength, ec,
            design_factor, temp, repair_class
        )
        n_asme = math.ceil(t_asme / PROWRAP["ply_thickness"])
        min_plies = 4 if defect_type == "Leak" else 2
        n_asme = max(n_asme, min_plies)

        if st.session_state.force_3_layers and n_asme < 3:
            n_asme = 3

        ft_asme = n_asme * PROWRAP["ply_thickness"]

        # Overlap: same Eq. 20 formula
        ov_asme, ov_shear_asme, ov_geom_asme = calc_overlap(ft_asme, strain_asme, od, rem_wall)
        # Taper
        taper_asme = calc_taper(ft_asme)
        # Total length
        total_len_asme = calc_total_repair_length(length, ov_asme, taper_asme)
        nb_asme, pl_asme, sqm_asme, ep_asme = calc_procurement(total_len_asme, od, n_asme)

        results["ASME PCC-2"] = {
            "t_required": t_asme, "design_strain": strain_asme,
            "strain_note": f"Derived: {PROWRAP['strain_fail']*100:.2f}% / SF",
            "composite_pressure": p_comp_asme,
            "steel_capacity_mpa": p_steel_asme,
            "steel_contribution": p_steel_asme * od / 2,
            "num_plies": n_asme, "final_thickness": ft_asme,
            "overlap": ov_asme, "overlap_shear": ov_shear_asme, "overlap_geom": ov_geom_asme,
            "taper": taper_asme,
            "total_length": total_len_asme,
            "num_bands": nb_asme, "proc_length": pl_asme,
            "sqm": sqm_asme, "epoxy_kg": ep_asme,
            "repair_class": repair_class,
        }

    # ====================================================================
    # DISPLAY RESULTS
    # ====================================================================
    st.success("✅ Calculation Complete")

    # Repair class banner
    if repair_class == "Type A":
        st.info(
            f"🔵 **Repair Class: Type A (Load Sharing)** — "
            f"Steel remaining wall ({rem_wall} mm) credited. Composite shares the hoop load."
        )
    else:
        st.error(
            f"🔴 **Repair Class: Type B (Full Replacement)** — "
            f"No steel credit. Composite carries 100% of hoop stress."
        )

    # Governing result
    if selected_standard == "Both":
        gov_key = max(results, key=lambda k: results[k]['num_plies'])
        gov = results[gov_key]
    else:
        gov_key = selected_standard
        gov = results[gov_key]

    # --- Top-level metrics ---
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Required Plies", f"{gov['num_plies']}", f"{gov['final_thickness']:.2f} mm")
    m2.metric("Design Strain (εct)", f"{gov['design_strain']*100:.3f} %")
    m3.metric("Overlap (each side)", f"{gov['overlap']:.1f} mm")
    m4.metric("Taper (each side)", f"{gov['taper']:.1f} mm")
    m5.metric("Total Repair Length", f"{gov['total_length']:.0f} mm")
    m6.metric("Epoxy Needed", f"{gov['epoxy_kg']:.1f} kg")

    if selected_standard == "Both":
        st.caption(f"☝️ Metrics shown for **{gov_key}** (governing — more conservative)")

    # --- Length breakdown ---
    st.markdown("---")
    st.markdown(f"**Repair Length Breakdown (ISO 24817 Sec. 7.5.8):** "
                f"`{length:.0f}` (defect) + 2 × `{gov['overlap']:.1f}` (overlap) "
                f"+ 2 × `{gov['taper']:.1f}` (taper) = **{gov['total_length']:.0f} mm**")
    st.caption(f"Overlap governed by: Eq.20 shear = {gov['overlap_shear']:.1f} mm, "
               f"geometric √(D×ts) = {gov['overlap_geom']:.1f} mm, "
               f"minimum = 50 mm → **{gov['overlap']:.1f} mm** "
               f"| Taper: 1:{TAPER_RATIO} × {gov['final_thickness']:.2f} mm = {gov['taper']:.1f} mm")

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
            st.write(f"**Repair Class:** {repair_class}")
            st.write(f"**Design Strain (εct):** {r_iso['design_strain']*100:.3f}% — *Fixed*")
            if repair_class == "Type A":
                st.write(f"**Steel Contribution:** {r_iso['steel_contribution']:.1f} N/mm")
            else:
                st.write("**Steel Contribution:** None (Type B)")
            st.write(f"**Thickness:** {r_iso['t_required']:.2f} mm → {r_iso['num_plies']} plies ({r_iso['final_thickness']:.2f} mm)")
            st.write(f"**Overlap:** {r_iso['overlap']:.1f} mm | **Taper:** {r_iso['taper']:.1f} mm")
            st.write(f"**Total Length:** {r_iso['total_length']:.0f} mm")
            st.write(f"**Fabric:** {r_iso['sqm']:.2f} m² | **Epoxy:** {r_iso['epoxy_kg']:.1f} kg")

        with col_vs:
            st.markdown("<br><br><br>", unsafe_allow_html=True)
            st.markdown("## vs")

        with col_asme:
            is_gov_asme = gov_key == "ASME PCC-2"
            badge = " 🏛️ GOVERNING" if is_gov_asme else ""
            st.markdown(f"#### ASME PCC-2{badge}")
            r_asme = results["ASME PCC-2"]
            st.write(f"**Repair Class:** {repair_class}")
            st.write(f"**Design Strain:** {r_asme['design_strain']*100:.3f}% — *Derived*")
            if repair_class == "Type A":
                st.write(f"**Steel Contribution:** {r_asme['steel_contribution']:.1f} N/mm")
            else:
                st.write("**Steel Contribution:** None (Type B)")
            st.write(f"**Thickness:** {r_asme['t_required']:.2f} mm → {r_asme['num_plies']} plies ({r_asme['final_thickness']:.2f} mm)")
            st.write(f"**Overlap:** {r_asme['overlap']:.1f} mm | **Taper:** {r_asme['taper']:.1f} mm")
            st.write(f"**Total Length:** {r_asme['total_length']:.0f} mm")
            st.write(f"**Fabric:** {r_asme['sqm']:.2f} m² | **Epoxy:** {r_asme['epoxy_kg']:.1f} kg")

        # Delta
        diff = results["ISO 24817"]["num_plies"] - results["ASME PCC-2"]["num_plies"]
        if diff > 0:
            st.warning(
                f"⚠️ **ISO 24817 requires {diff} more layer(s)** than ASME PCC-2 ({repair_class}). "
                f"ISO fixed εct = 0.008, ASME derives ε = {results['ASME PCC-2']['design_strain']*100:.3f}%."
            )
        elif diff < 0:
            st.info("ℹ️ ASME PCC-2 is more conservative in this case (unusual — check inputs).")
        else:
            st.info("ℹ️ Both standards yield the same number of plies for this defect.")

        st.markdown("---")

    # --- Upgrade prompt ---
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
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("### Defect Info")
            st.write(f"**Mechanism:** {defect_type} ({defect_loc})")
            st.write(f"**Wall Loss:** {wall_loss_ratio*100:.1f}%")
            st.write(f"**Remaining Wall:** {rem_wall} mm of {wall} mm")
        with c2:
            st.markdown("### Repair Class & Overlap")
            st.write(f"**Class:** {repair_class}")
            if repair_class == "Type A":
                st.write(f"Sa x ts = {yield_strength} x {rem_wall} = **{yield_strength * rem_wall:.1f} N/mm**")
            else:
                st.write("No steel credit (Type B)")
            st.write(f"**Overlap formula:** ISO 24817 Eq. 20")
            st.write(f"lover = (Ea x εa x t) / τ = ({PROWRAP['modulus_axial']} x {gov['design_strain']:.4f} x {gov['final_thickness']:.2f}) / {PROWRAP['lap_shear']}")
            st.write(f"= **{gov['overlap_shear']:.1f} mm** (shear)")
            st.write(f"√(D x ts) = √({od} x {rem_wall}) = **{gov['overlap_geom']:.1f} mm** (geometric)")
            st.write(f"**Governing overlap:** {gov['overlap']:.1f} mm")
        with c3:
            st.markdown("### Strain Philosophy")
            if selected_standard in ["ISO 24817", "Both"]:
                st.write(f"**ISO 24817 εct:** {ISO_STRAIN_LIMIT*100:.1f}% — Fixed")
            if selected_standard in ["ASME PCC-2", "Both"]:
                asme_strain = results.get("ASME PCC-2", {}).get("design_strain", 0)
                st.write(f"**ASME PCC-2 ε:** {asme_strain*100:.3f}% — Derived")
            if selected_standard == "Both":
                ratio = asme_strain / ISO_STRAIN_LIMIT if ISO_STRAIN_LIMIT > 0 else 0
                st.write(f"**Ratio:** ASME strain is {ratio:.1f}x the ISO limit")

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
            - **Op. Temp:** {temp} C
            """)
        with c_defect:
            st.warning("**2. Defect Description**")
            st.markdown(f"""
            - **Mechanism:** {defect_type} ({defect_loc})
            - **Remaining Wall:** {rem_wall} mm
            - **Axial Length:** {length} mm
            - **Wall Loss:** {wall_loss_ratio*100:.1f}%
            - **Repair Class:** {repair_class}
            """)
        with c_repair:
            st.success(f"**3. Repair Design ({gov_key})**")
            st.markdown(f"""
            - **Repair Class:** {repair_class}
            - **Total Plies:** {gov['num_plies']} Layers ({gov['final_thickness']:.2f} mm)
            - **Design Strain:** {gov['design_strain']*100:.3f}%
            - **Overlap:** {gov['overlap']:.1f} mm (each side)
            - **Taper:** {gov['taper']:.1f} mm (each side, 1:{TAPER_RATIO})
            - **Total Length:** {gov['total_length']:.0f} mm
            - **Bands:** {gov['num_bands']} x 300mm
            - **Procurement:** {gov['proc_length']} mm
            - **Epoxy:** {gov['epoxy_kg']:.1f} kg
            """)
            st.caption(f"*{gov_key}, {repair_class}. Life: {design_life} yrs, f = {design_factor}.*")

        st.markdown("---")
        st.markdown("### 📋 Installation Checklist")
        st.markdown(f"""
        1. **Surface Prep:** Grit blast to **SA 2.5**; Profile **>60um**.
        2. **Primer/Filler:** Apply Prowrap Filler to defect area to restore OD profile.
        3. **Lamination:** Saturate Carbon Cloth. Apply **{gov['num_plies']} layers** per band.
        4. **Wrapping:** Use **{gov['num_bands']} band(s)** of 300mm cloth.
        5. **Overlap:** **{gov['overlap']:.0f} mm** full-thickness extension beyond defect each side.
        6. **Taper:** **{gov['taper']:.0f} mm** gradual taper (1:{TAPER_RATIO}) at each repair end.
        7. **Total Extent:** Minimum **{gov['total_length']:.0f} mm** axial coverage.
        8. **Quality Control:** Minimum average Shore D hardness of **{PROWRAP['shore_d']}** required.
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
    except Exception as pdf_error:
        st.error(f"⚠️ Could not generate PDF. Error: {pdf_error}")


# ======================================================================
# APP ENTRY POINT
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

        repair_class = st.sidebar.selectbox(
            "Repair Class (ISO 24817 Sec. 7.2)",
            ["Type A", "Type B"],
            index=1,
            help=(
                "Type A: Steel remaining wall credited (load sharing). "
                "Type B: No steel credit - composite carries full pressure. "
                "Engineer's decision - overrides automatic classification."
            ),
            on_change=reset_calc
        )

        selected_standard = st.sidebar.selectbox(
            "Calculation Standard",
            ["Both", "ISO 24817", "ASME PCC-2"],
            help="ISO 24817 uses fixed ect=0.008. ASME PCC-2 derives strain from test data.",
            on_change=reset_calc
        )
        design_life = st.sidebar.number_input("Design Life [years]", value=20, min_value=1, on_change=reset_calc)
        df = st.sidebar.number_input("Design Factor (f)", value=0.72, min_value=0.1, max_value=1.0, on_change=reset_calc,
                                     help="Used by ASME PCC-2. ISO 24817 uses fixed ect=0.008 regardless.")

        if st.sidebar.button("Calculate & Optimize", type="primary"):
            st.session_state.calc_active = True
            st.session_state.force_3_layers = False

        if st.session_state.calc_active:
            run_calculation(customer, location, report_no, od, wall, pres, temp,
                            type_, loc_, len_, rem_, yield_str, df, design_life,
                            selected_standard, repair_class)

    except Exception as e:
        st.error(f"⚠️ Application Error: {e}")


if __name__ == "__main__":
    main()
