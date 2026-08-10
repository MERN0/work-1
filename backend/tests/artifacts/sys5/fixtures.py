"""Synthetic input workbooks that reproduce the awkward shapes of the real TMHC files.

Deliberately included quirks, because these are what break naive parsers:

* header rows that are not row 1, with title/notes text floating above them;
* vertically merged cells (a requirement spanning rows, a signal spanning its inputs);
* per-feature ``○`` columns whose headers Excel stores as numbers (``5`` for ``005``);
* compound commands laid out as blocks rather than a table;
* duplicate ``Units`` headers.
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

FEATURE_SHEET = "005"
FEATURE_GROUP = "Ramp / Slope Control"
FEATURE_NAME = "005 - Ramp / Slope Control"

REQUIREMENT_HEADERS = [
    "Requirement ID",
    "Object Heading",
    "Object Text",
    "Category",
    "Variant",
    "Priority",
    "Verification Method",
    "Verification Stage",
    "Verification Criteria",
    "Source",
    "Status",
    "Remarks",
]


def _write(sheet, rows: list[list], start_row: int = 1) -> None:
    for r_offset, row in enumerate(rows):
        for c_offset, value in enumerate(row):
            if value not in (None, ""):
                sheet.cell(row=start_row + r_offset, column=1 + c_offset, value=value)


def build_requirements_workbook(path: Path) -> Path:
    """The SYS2 requirements file: a feature sheet plus the three master sheets."""
    workbook = Workbook()

    # --- feature sheet 005 ---------------------------------------------------
    sheet = workbook.active
    sheet.title = FEATURE_SHEET
    # Two rows of floating notes above the real header, as in the real file.
    _write(sheet, [["TE_TMHC_HILS Development & Testing_System Requirements"], ["Rev 4.2"]])
    _write(sheet, [REQUIREMENT_HEADERS], start_row=3)

    rows = [
        ["TMHC_SYSRS_GR005001", "Feature Group", FEATURE_GROUP, "Heading", "-", "-", "-", "-",
         "-", "", "-", "-"],
        ["TMHC_SYSRS_GR005002", "Feature Name", FEATURE_NAME, "Heading", "-", "-", "-", "-",
         "-", "", "-", "-"],
        ["TMHC_SYSRS_GR005004", "Purpose",
         "Suppress the sliding down (when starting on a hill road) and limit the rolling back "
         "speed (when stopped on a slope) by regenerative breaking.",
         "Information", "-", "-", "-", "-", "-",
         "geneB_FunctionSpecList_forShare(Running Control)", "-", "-"],
        ["TMHC_SYSRS_GR005005", "Overview",
         "This feature maintains or adjusts the speed and torque of the truck while moving "
         "downhill in both forward and reverse directions. Anti-rollback function limits the "
         "truck's downward speed below the rollback speed when the accelerator pedal is released.",
         "Information", "-", "-", "-", "-", "-", "SystemRequirement_2.X_20260318", "-", "-"],
        # Selected requirement 1 — keyword in the Verification Stage column.
        ["TMHC_SYSRS_GR005010", "Anti-rollback speed limit",
         "When the truck is stopped on a slope of 5 deg and the accelerator pedal is released, "
         "the system shall limit the rollback speed to 0.5 km/h.",
         "Functional Requirement", "A1", "P1", "Testing", "SYS5 Test",
         "Rollback speed shall not exceed 0.5 km/h",
         "SystemRequirement_2.X_20260318 5.1.1.3", "Approved", ""],
        # Selected requirement 2 — keyword spelled differently, different column.
        ["TMHC_SYSRS_GR005011", "Maximum speed limitation",
         "The maximum speed limitation function shall limit vehicle speed to 10 km/h when "
         "configured, and the operator shall not exceed this limit regardless of accelerator "
         "pedal position.",
         "Functional Requirement", "A1", "P1", "Testing", "System Qualification",
         "Displayed speed shall remain at 10 km/h", "SystemRequirement_2.X 5.1.1.4",
         "Approved", ""],
        # Not selected — no SYS5 keyword anywhere in the row.
        ["TMHC_SYSRS_GR005012", "Diagnostics",
         "The controller shall record a fault code when the slope sensor is disconnected.",
         "Functional Requirement", "A1", "P2", "Review", "Design Review", "-", "-", "Draft", ""],
    ]
    _write(sheet, rows, start_row=4)
    # A vertical merge across the Variant cells of the two selected requirements,
    # mirroring how the real sheet merges shared metadata.
    sheet.merge_cells(start_row=8, start_column=5, end_row=9, end_column=5)

    # --- feature sheet 006 ---------------------------------------------------
    # A second feature so multi-sheet runs (req_sheet_name="") are covered, and so
    # feature-column tracing has something it must *not* leak across.
    second = workbook.create_sheet("006")
    _write(second, [REQUIREMENT_HEADERS])
    _write(
        second,
        [
            ["TMHC_SYSRS_GR006001", "Feature Group", "Parking Brake", "Heading", "-", "-", "-",
             "-", "-", "", "-", "-"],
            ["TMHC_SYSRS_GR006002", "Feature Name", "006 - Parking Brake", "Heading", "-", "-",
             "-", "-", "-", "", "-", "-"],
            ["TMHC_SYSRS_GR006010", "Parking brake lamp",
             "When the parking brake is engaged, the system shall illuminate the parking "
             "brake lamp within 200 ms.",
             "Functional Requirement", "A1", "P1", "Testing", "SYS5 Test",
             "Lamp shall be ON within 200 ms", "SystemRequirement_2.X 5.2.1.1", "Approved", ""],
        ],
        start_row=2,
    )

    # --- Master Comm Matrix (CAN) -------------------------------------------
    can = workbook.create_sheet("Master Comm Matrix (CAN)")
    _write(
        can,
        [
            [
                "Signal ID", "Message Name", "Message IDs", "Logical Signal Name",
                "Signal Name", "Signal Description", 4, 5, 6,
            ],
            ["TMHC_SYSRS_DBC0001", "DrvL_PDO1_Rx", "0x211", "Commanded_RPM",
             "DrvL_Rx1_CmdSpd", "Command motor speed [rpm]", None, "○", None],
            ["TMHC_SYSRS_DBC0005", "DrvL_PDO1_Tx", "0x191", "Motor_Actual_RPM",
             "DrvL_Tx1_ActSpd", "Motor Actual RPM (Detection)", None, "○", None],
            ["TMHC_SYSRS_DBC0009", "Disp_PDO1_Rx", "0x221", "Displayed_Vehicle_Speed",
             "Disp_Rx1_DispSpeed", "Displayed vehicle speed", "○", "○", None],
            ["TMHC_SYSRS_DBC0084", "Disp_PDO1_Rx", "0x221", "Parking_Brake_Lamp",
             "Disp_Rx1_ParkingLamp", "parking brake lamp", None, None, "○"],
        ],
    )

    # --- Master Input Output Signals ----------------------------------------
    io = workbook.create_sheet("Master Input Output Signals")
    _write(
        io,
        [
            ["Signal ID", "Logical Signal Name", "Signal Type", 4, 5, 6],
            ["TMHC_SYSRS_IO0005", "Accelerator_Sensor", "Sensor", None, "○", None],
            ["TMHC_SYSRS_IO0006", "Direction_Switch_Forward_Reverse", "Switch", None, "○", None],
            ["TMHC_SYSRS_IO0007", "PKB_Switch", "Switch", None, "○", None],
            ["TMHC_SYSRS_IO0009", "Slope_Angle_Sensor", "Sensor", None, "○", None],
            ["TMHC_SYSRS_IO0022", "Vehicle_Speed", "CAN", "○", "○", None],
            ["TMHC_SYSRS_IO0030", "Fork_Height_Sensor", "Sensor", None, None, "○"],
        ],
    )

    # --- Master List - App Parameter ----------------------------------------
    params = workbook.create_sheet("Master List - App Parameter")
    _write(
        params,
        [
            [
                "Parameter ID", "Parameter Name", "Parameter Description(purpose)",
                "Parameter Type", "Unit", "Parameter Valid Value", "Parameter default value",
                "Parameter min Value", "Parameter max Value", "Resolution",
                "Linked System Requirement", 5,
            ],
            ["TMHC_SYSRS_PARM0020", "Maximum_Speed_Limit_Range", "Maximum Speed Limitation value",
             "Configuration", "km/h", "-", "OFF", 2, 20, 1, "TMHC_SYSRS_GR005011", "○"],
            ["TMHC_SYSRS_PARM0025", "Slope_Detection_Latency",
             "Time within which a slope should be detected", "Configuration", "ms", "-", 300,
             300, 1000, 1, "TMHC_SYSRS_GR005010", "○"],
        ],
    )

    # Sheets the pipeline must ignore rather than misread.
    _write(workbook.create_sheet("Cover Page"), [["TE_TMHC_HILS System Requirements"]])
    _write(workbook.create_sheet("Help"), [["Section", "Description"], ["Requirement ID", "..."]])

    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    return path


def build_command_list_workbook(path: Path) -> Path:
    """TE_TMHC_Command_List.xlsx."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Command List"
    _write(
        sheet,
        [
            ["SL.No.", "Type", "Command name", "Message Name", "Signal Description",
             "Signal Name", "Index (Hex)", "SubIndex (Hex)"],
            [1, "CAN", "CAN_Main_DispSpeed", "Disp_PDO1_Rx", "Displayed vehicle speed",
             "Disp_Rx1_DispSpeed", "", ""],
            [2, "CAN", "CAN_DrvL_ActSpd", "DrvL_PDO1_Tx", "Motor Actual RPM",
             "DrvL_Tx1_ActSpd", "", ""],
            [3, "CAN", "CAN_Main_Cmd_D_Motor", "DrvL_PDO1_Rx", "Command motor speed",
             "DrvL_Rx1_CmdSpd", "", ""],
            [4, "CAN", "CAN_HIL_ComData_SpeedMax", "Main_SDO_Rx", "Maximum speed limit (From HIL)",
             "Main_RxS_0x3560_0x05", "0x3560", "0x05"],
            [5, "CAN", "CAN_Main_ComData_SpeedMax", "Main_SDO_Tx", "Maximum speed limit (From Main)",
             "Main_TxS_0x3560_0x05", "0x3560", "0x05"],
        ],
    )
    workbook.save(path)
    return path


def build_compound_commands_workbook(path: Path) -> Path:
    """TE_TMHC_Compound_Commands.xlsx — block structured, not tabular."""
    workbook = Workbook()

    set_sheet = workbook.active
    set_sheet.title = "Compound Commands (Set)"
    _write(
        set_sheet,
        [
            ["Cover"],
            [],
            ["Compound Driving_Initial_Settings", "Parameter Settings", "Units",
             "Expected Value", "Units", "Whether to execute the command", "Remarks"],
            ["Set MDL_SWH_DIR_STATE", "FWD", "", "", "", "Yes", "Turn direction Switch to Forward"],
            ["Wait", 100, "ms", "", "", "Yes", "Time delay is given as 100 ms"],
            ["Set MDL_SWH_Park_Brake", "OFF", "", "", "", "Yes", "Release the Park Brake"],
            [],
            ["Compound Key_Off_A1", "Parameter Settings", "Units", "Expected Value", "Units",
             "Whether to execute the command", "Remarks"],
            ["Set MDL_SWH_VBKY", "OFF", "", "", "", "Yes", "Key switch OFF"],
            ["Wait", 500, "ms", "", "", "Yes", "Wait for the key-off sequence to complete"],
        ],
    )

    verify_sheet = workbook.create_sheet("Compound Command (Verify)")
    _write(
        verify_sheet,
        [
            [],
            ["Compound Verifying_Power_On_A1", "Parameter Settings", "Units", "Expected Value",
             "Units", "Whether to execute the command", "Remarks"],
            ["Verify MDL_PS_B48V", "", "", 52, "V", "Yes", "Electric source through battery"],
            ["Verify MDL_PS_VBBT", "", "", "ON", "", "Yes", "Electric source direct to battery"],
            ["Wait", 500, "ms", "", "", "Yes", "Time delay is given as 500 ms"],
        ],
    )

    workbook.save(path)
    return path


def build_keyword_library_workbook(path: Path) -> Path:
    """TE_TMHC_HILS_..._Keyword_Library_Description_Sheet.xlsx."""
    workbook = Workbook()

    keywords = workbook.active
    keywords.title = "Keyword description"
    _write(
        keywords,
        [
            [],
            [],
            ["SL.no", "Keywords", "Description", "Example", "Status"],
            [1, "Set <Signal_Name>", "Keyword can be used to set a variable.",
             "Set MDL_SWH_Forward", "Created"],
            [2, "Verify <Signal_Name>", "Keyword can be used to verify a variable.",
             "Verify CAN_Main_DispSpeed", "Created"],
            [3, "Wait", "Keyword can be used to set a wait.", "Wait", "Created"],
            [4, "Read <Signal_Name>", "Keyword used to read a value.",
             "Read CAN_Main_DispSpeed", "Created"],
        ],
    )

    library = workbook.create_sheet("Library List")
    _write(
        library,
        [
            [],
            ["SL.no", "Library", "Library Description"],
            [1, "Lib_Ramp Signal_Name(Start=X,Stop=X,Step=X,Time=X)",
             "Ramp the signal value from Start to Stop at a given rate of increment."],
            [2, "Lib_Verify_Diff (Signal_1,Signal_2,Condition)",
             "Subtracts both signals and verifies with the condition."],
        ],
    )

    workbook.save(path)
    return path


def build_configuration_workbook(path: Path) -> Path:
    """TE_TMHC_Configuration_File.xlsx."""
    workbook = Workbook()

    tolerances = workbook.active
    tolerances.title = "Tolerances"
    _write(
        tolerances,
        [
            ["Sl No", "Tolerance Configuration", "Description", "Example", "Unit", "Value",
             "Tolerance Unit", "Remarks"],
            [1, "Config_Tol_Spd", "Tolerance for Vehicle speed", "4 (Config_Tol_Spd)", "km/hr",
             "0.5,1.5", "units", "First value positive side, second negative side"],
            [2, "Config_Tol_rpm", "Tolerance for motor rpm", "1875 (Config_Tol_rpm)", "rpm",
             "5,5", "units", ""],
            [3, "Config_Tol_RBS", "Tolerance for rollback speed", "0.5 (Config_Tol_RBS)", "rpm",
             "1,1", "units", ""],
            [4, "Config_Tol_Deg", "Tolerance for Tilt angle", "0 (Config_Tol_Deg)", "deg",
             "1,1", "deg", ""],
        ],
    )

    configurations = workbook.create_sheet("Configurations")
    _write(
        configurations,
        [
            ["Sl No", "Signal Name", "Signal Description", "Configuration", "Remarks"],
            [1, "Main_RxS_0x2020_0x01", "ComData_PwrCtrlMode",
             "0x00:H, 0x01:P, 0x02:S, 0x03:E, 0x04:L, 0x10:Original Mode", ""],
        ],
    )

    mapping = workbook.create_sheet("Model_Input_Mapping")
    _write(
        mapping,
        [
            ["Sl.No.", "Signal", "Test Case Input", "Model Input", "Model Output to ECU", "Remark"],
            [1, "MDL_SWH_VBKY", "ON", 1, "", ""],
            [None, None, "OFF", 0, "0 (low)", ""],
            [2, "MDL_SEN_Accelerator_Pedal", 30, 30, "2.35 - PS1 (VRA1)", ""],
            [None, None, 0, 0, "", ""],
            [3, "MDL_SWH_DIR_STATE", "FWD", 1, "0V (DSF) - Low", "Forward"],
            [None, None, "NEUTRAL", 2, "5V (DSF) - High", "Neutral"],
            [None, None, "BWD", 3, "5V (DSF) - High", "Backward"],
            [4, "MDL_SWH_Park_Brake", "ON", 1, "5 - High (SPB)", "Brake in action"],
            [None, None, "OFF", 0, "0 - Low (SPB)", "Brake release"],
            [5, "MDL_SEN_Slope_Angle", 20, 20, "", ""],
            [None, None, -20, -20, "", ""],
        ],
    )
    # The Signal column is merged across each signal's input rows in the real file.
    for start, end in ((2, 3), (4, 5), (6, 8), (9, 10), (11, 12)):
        mapping.merge_cells(start_row=start, start_column=2, end_row=end, end_column=2)

    globals_sheet = workbook.create_sheet("Global_Variables")
    _write(
        globals_sheet,
        [
            ["Sl No", "Variable", "Value", "Description"],
            [1, "Global_Test_Mode", "HIL", "Execution mode"],
        ],
    )

    _write(workbook.create_sheet("Truck Model Info"), [["Model", "TICO_HILS_2.0"]])

    workbook.save(path)
    return path


def build_all(directory: Path) -> dict[str, Path]:
    """Write the complete synthetic input set into ``directory``."""
    directory.mkdir(parents=True, exist_ok=True)
    return {
        "requirements": build_requirements_workbook(
            directory / "TE_TMHC_HILS Development & Testing_System Requirements.xlsx"
        ),
        "commands": build_command_list_workbook(directory / "TE_TMHC_Command_List.xlsx"),
        "compounds": build_compound_commands_workbook(
            directory / "TE_TMHC_Compound_Commands.xlsx"
        ),
        "keywords": build_keyword_library_workbook(
            directory / "TE_TMHC_HILS_Keyword_Library_Description_Sheet.xlsx"
        ),
        "configuration": build_configuration_workbook(
            directory / "TE_TMHC_Configuration_File.xlsx"
        ),
    }
