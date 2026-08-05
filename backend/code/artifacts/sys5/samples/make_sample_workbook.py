"""Generates a tiny sample SYS2 requirements workbook for end-to-end testing.
Not part of the pipeline itself -- run once to (re)create samples/sample_requirements.xlsx.
"""

from pathlib import Path

from openpyxl import Workbook

OUT = Path(__file__).parent / "sample_requirements.xlsx"


def main() -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Requirements"
    ws.append(["Requirement ID", "Feature", "Description", "Qualification Tag"])
    ws.append(["REQ_001", "Slope Assist Activation", "System shall enable slope assist when Slope_Assist_Enabled is set and slope angle exceeds threshold.", "SYS Qualification"])
    ws.append(["REQ_002", "Slope Assist Activation", "System shall disable slope assist when vehicle speed exceeds high threshold on flat ground.", "SYS5"])
    ws.append(["REQ_003", "Power Control Mode", "System shall report the active power control mode (H/P/S/E/L) via CAN within 200ms of a mode-switch request.", "Sys Qualification"])
    ws.append(["", "", "", ""])  # junk row: should be excluded
    ws.append(["Notes", "", "internal only, not a requirement", ""])  # junk row: heading pattern

    ws2 = wb.create_sheet("Other")
    ws2.append(["Requirement ID", "Feature", "Description", "Qualification Tag"])
    ws2.append(["REQ_101", "Diagnostics", "System shall log a diagnostic trouble code when battery discharge exceeds configured tolerance.", "sys qualification"])
    ws2.append(["REQ_102", "Infotainment", "System shall display trip odometer on the dashboard.", "not applicable"])  # should be filtered OUT (no keyword match)

    wb.save(OUT)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
