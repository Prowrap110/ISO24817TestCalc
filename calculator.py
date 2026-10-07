"""Rev1: Sonatrach PR 900.3 R4 qualification calculations, in mm and MPa."""
import math

REVISION = "Rev1"
PROWRAP = {
    "ply_thickness": 0.83, "modulus_circ": 45460.0,
    "modulus_axial": 43800.0, "tensile_circ": 574.1,
    "tensile_axial": 563.67, "poisson": 0.066,
    "lap_shear": 14.76, "long_term_lap_shear": 9.63,
    "shore_d": 79.1, "tg": 108.18, "hdt": 115.5,
}
R4_STRAIN = 0.008
DEFAULT_INPUTS = dict(
    od=508.0, wall=8.7, remaining=1.74, yield_strength=358.5,
    defect_length=254.0, defect_width=127.0, repair_length=550.0,
    spool_length=3600.0, cloth_width=300.0, row_overlap=50.0,
    seam_overlap=50.0, waste_percent=10.0,
    measured_yield_confirmed=False, mechanical_report="", repair_design_ref="",
)


def calculate(inputs):
    p = dict(DEFAULT_INPUTS)
    p.update(inputs)
    positive = ("od", "wall", "remaining", "yield_strength", "defect_length",
                "defect_width", "repair_length", "spool_length", "cloth_width")
    for key in positive + ("row_overlap", "seam_overlap", "waste_percent"):
        try:
            p[key] = float(p[key])
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be a finite number") from None
        if not math.isfinite(p[key]) or p[key] < 0 or (key in positive and p[key] == 0):
            raise ValueError(f"{key} must be finite and {'positive' if key in positive else 'non-negative'}")
        if p[key] > 1e9:
            raise ValueError(f"{key} exceeds the calculator numerical input range")
    if p["remaining"] >= p["wall"]:
        raise ValueError("Residual wall must be below healthy wall thickness")
    if 2 * p["wall"] >= p["od"]:
        raise ValueError("Pipe wall must be less than half the outside diameter")
    if p["row_overlap"] >= p["cloth_width"]:
        raise ValueError("Row overlap must be less than cloth width")
    if p["repair_length"] < p["defect_length"]:
        raise ValueError("Repair length cannot be shorter than the defect")
    if p["defect_width"] >= math.pi * p["od"]:
        raise ValueError("Localized defect width must be less than the pipe circumference")

    od, wall, remaining, strength = (p[k] for k in ("od", "wall", "remaining", "yield_strength"))
    pressure = 2 * wall * strength / od
    thickness = (pressure * od / 2 - strength * remaining) / (PROWRAP["modulus_circ"] * R4_STRAIN)
    plies = math.ceil(thickness / PROWRAP["ply_thickness"])
    rows = 1 + max(0, math.ceil((p["repair_length"] - p["cloth_width"]) /
                              (p["cloth_width"] - p["row_overlap"])))
    laid = p["cloth_width"] + (rows - 1) * (p["cloth_width"] - p["row_overlap"])
    # Use actual laid coverage when it exceeds the requested design length.
    spool_limit = 6 * od + max(p["repair_length"], laid)
    cloth = rows * plies * (math.pi * od + p["seam_overlap"]) / 1000
    checks = []

    def check(name, status, detail):
        checks.append(dict(name=name, status=status, detail=detail))

    check("Diameter", "PASS" if od > 100 else "FAIL", "D > 100 mm (R4 p. 8).")
    for name, value, limit in (("Defect length", p["defect_length"], od / 2),
                               ("Defect width", p["defect_width"], od / 4)):
        equal = math.isclose(value, limit, rel_tol=0, abs_tol=1e-9)
        status = "REVIEW" if equal else ("PASS" if value > limit else "FAIL")
        check(name, status, f"Boundary {limit:g} mm: R4 p. 8 uses >=; p. 15 uses >. Equality requires resolution.")
    check("Defect depth", "PASS" if math.isclose(remaining / wall, .2, abs_tol=1e-9) else "FAIL",
          "Target is 80% wall loss / 20% residual wall (R4 p. 8); machining tolerance requires agreement.")
    check("Spool length", "PASS" if p["spool_length"] > spool_limit else "FAIL",
          f"Length must exceed {spool_limit:.3f} mm using actual laid extent. Drawing must also show >3D each side (R4 pp. 8, 15).")
    confirmed = p["measured_yield_confirmed"] and str(p["mechanical_report"]).strip()
    check("Measured yield", "PASS" if confirmed else "REVIEW",
          "User-declared measured value and report reference supplied." if confirmed else
          "Default 358.5 MPa is an illustrative SMYS value; enter measured yield and mechanical report (R4 p. 10).")
    check("Repair design", "PASS" if str(p["repair_design_ref"]).strip() else "REVIEW",
          "Reference is user supplied; repair length, overlaps, taper and fibre direction require an approved drawing. R4 supplies no repair-length formula.")
    check("Two-hour hardening", "REVIEW",
          "R4 p. 10 requires backfill readiness within 2 h near 25 C. TDS p. 5 gives 4 h touch dry / 24 h full cure; separate evidence needed.")
    check("Qualification release", "REVIEW",
          "Calculation is not qualification approval. RCL/third-party inspection, mechanical/dimensional PV, Class 3 personnel and witnessed testing remain required.")
    return dict(
        inputs=p, pressure_mpa=pressure, pressure_bar=pressure * 10,
        thickness_mm=thickness, plies=plies,
        effective_thickness_mm=plies * PROWRAP["ply_thickness"],
        num_rows=rows, laid_length_mm=laid, spool_length_limit_mm=spool_limit,
        cloth_length_m=cloth, area_m2=cloth * p["cloth_width"] / 1000,
        procurement_length_m=cloth * (1 + p["waste_percent"] / 100),
        ridge_limit_mm=min(1.0, .2 * thickness),
        application_limit_minutes=50 if math.isclose(od, 508, abs_tol=.01) else
                                  (45 if math.isclose(od, 406.4, abs_tol=.01) else None),
        checks=checks, status="INPUT CHECK FAILED" if any(c["status"] == "FAIL" for c in checks) else "REVIEW REQUIRED",
    )
