FC22S / EmWolf Sectionalizer Test Scenarios

Digital input mapping:
  DI1 = Close
  DI2 = Open

Important:
  These projects include the configurable digital_input_names field used by WolfEye.
  All fault stages use:
      end_type = DI_TOGGLE
      digital_input = 2
  meaning: wait for the sectionalizer Open feedback on DI2.

Current wiring:
  DUT IA <- Tester IN
  DUT IB <- Tester IB
  DUT IC <- Tester IC
  Tester IA = 0.0 (damaged / unused)

Normal current:
  Logical IA = 0.05 A
  Logical IB = 0.05 A
  Logical IC = 0.05 A

Fault currents remain unchanged from the previous version.
Maximum injected current amplitude = 0.45 A.

Files:
  01_OC_3PH.json  - FC22S 3-phase overcurrent
  02_LL_AB.json   - FC22S A-B line-to-line fault
  03_EF_A.json    - FC22S A-phase earth fault
  04_SEF_A.json   - FC22S sensitive earth fault
  05_LLG_AB.json  - FC22S A-B-to-ground fault
  06_NPS.json     - FC22S negative phase sequence

Sequence in each file:
  NORMAL (5 s)
      ->
  FAULT_WAIT_OPEN (DI2 = Open)
      ->
  POST_OPEN_ZERO (infinite)
