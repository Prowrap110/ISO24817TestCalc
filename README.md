# Prowrap Sonatrach Test Calculator Rev1

Streamlit entry point: `TestCalc.py`.

This revision calculates the qualification-spool pressure and composite thickness specified by Sonatrach PR 900.3 R4, using material properties from the user-supplied TDS PRW 110-H.pdf. It is not a general ISO 24817 / ASME PCC-2 field-repair design engine or a qualification approval.

## Verified benchmark

For D=508 mm, healthy wall=8.7 mm, residual wall=1.74 mm, illustrative yield=358.5 MPa, Ec=45460 MPa and ply thickness=0.83 mm:

- Pf = 12.2793307087 MPa (122.7933070866 bar)
- Calculated repair thickness = 6.860866696 mm
- 9 plies per axial row; installed thickness 7.47 mm
- With 550 mm actual repair extent, spool length must exceed 3598 mm

358.5 MPa is an illustrative nominal input. Replace it with the measured steel yield and report reference required by R4 before test release.

## Rev1 corrections

- Replaced unsupported dual-standard claims and assumed ASME strain/temperature factors with the traceable R4 qualification equation.
- Preserved residual steel-wall credit and calculated Pf from healthy wall and measured-yield input.
- Corrected lap shear to 14.76 MPa; included long-term lap shear 9.63 MPa and Shore D test result 79.1.
- Removed unsupported 55.5 C service limit, Shore D >=70 release rule and resin kg/m2 assumption.
- Did not silently convert TDS failure strain 2.33/2.43 mm/mm to percentages; R4 independently specifies 0.008.
- Added defect depth/dimensions, actual laid extent and strict spool-length checks.
- Repair length, row overlap and seam overlap are engineering inputs requiring a design reference, not values derived from R4.
- Corrected row coverage and nominal-OD cloth estimate to include every circumferential seam; separated allowance.
- Added R4 application duration, Phase II 30-second hold/depressurization, and removal of burst testing.
- Flags unresolved two-hour hardening and exact-boundary discrepancy between R4 text and drawing.
- PDF and JSON use the same calculation result as the screen. Outputs explicitly retain review status.

## Source traceability

- R4 p. 8: specimen geometry, 80% wall loss, diameter and spool length.
- R4 p. 9: thickness equation, strain 0.008, qualified Class 3 personnel.
- R4 p. 10: measured yield, pressure equation/hold, application and hardening limits.
- R4 p. 11: post-test acceptance.
- R4 p. 15: dimensioned schematic; strict inequalities conflict with p. 8 at exact defect boundaries.
- TDS p. 2: material test results. Tg/HDT and Shore D values are not release limits.
- TDS pp. 4-5: mixing ratios, surface profile and cure data.

Original source documents are not included in this public repository. The earlier calculator is retained in Git history.

## Run and verify

```sh
pip install -r requirements.txt
python -m unittest discover -p "test_*.py" -v
streamlit run TestCalc.py
```
