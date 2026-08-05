# Domain: FORKLIFT (provisional -- not in the master prompt's domain list)

ARCHITECTURE.md Sec8 Q1: the reference workbook you supplied is a Forklift/HIL
example (GeneB, variants A1/A2/B), not one of bcm|telematics|chassis|adas|powertrain.
This file exists so the pipeline can run end-to-end against that sample data;
treat it as provisional until you confirm whether Forklift is a real 6th domain.

- Typical signals: CAN_HIL_PwrCtrlMode, MDL_SWH_DIR_STATE, MDL_SWH_Park_Brake,
  Slope_Assist_Enabled, Tire_Angle_Sensor, Power_Select.
- Common test focus: slope-assist activation/estimation, power-control mode
  transitions, load/tolerance boundaries (Config_Tol_* parameters).
