<!---
This file is used to generate your project datasheet. Please fill in the information below and delete any unused
sections.
-->

## How it works

`tt_um_flip_pendant` is a dedicated hardware implementation of a 256-particle Q4.12 fixed-point PIC/FLIP fluid simulation engine designed for a 16x16 circular LED matrix pendant (216 active LEDs).

Each frame executes a 5-stage hardware pipeline:
1. **Gravity & Advection:** Updates 256 particle velocities and positions in Q4.12 fixed-point using the 8-bit `(gx, gy)` gravity vector polled from the external **LIS2DW12** accelerometer.
2. **Spatial-Hash 2-Pass Particle Separation & Circular Wall Collision:** Builds an $O(N)$ 16x16 spatial hash linked list in hardware, pushes overlapping particle pairs apart via a 64-entry repulsion ROM (`PUSH_LUT`), and projects exterior particles back onto the $R = 7.75$ circular boundary via an inverse-radius ROM (`WALL_INV_R_LUT`).
3. **Particle-to-Grid (P2G) & Cell Classification:** Scatters particle velocities and weights onto staggered $U$ ($17 \times 16$), $V$ ($16 \times 17$), and density ($16 \times 16$) grids using wire-sliced bilinear weights, normalizes face velocities, and classifies cells as `AIR`, `WATER`, or `SOLID`.
4. **30-Iteration Red-Black Gauss-Seidel Pressure Solver:** Solves for divergence-free velocity fields with density drift compensation and an over-relaxation LUT (`OMEGA_INV_S_LUT`).
5. **Grid-to-Particle (G2P) & Autonomous Sleep:** Blends PIC (5%) and FLIP (95%) velocities back onto the 256 particles. When the fluid settles and the accelerometer reports no motion for 90 consecutive frames (1.5 s), the controller asserts `clock_gated_sleep` until woken by `lis_int2_sleep` or `shake_btn`.

Particle state is stored in an external **ESP-PSRAM64H** (8 MB QPI PSRAM) via a 4-lane QPI burst controller and 5V-to-3.3V level-shifter control signals (`psram_trans_dir`, `psram_trans_oe_n`). Display output and accelerometer polling run over a shared 400 kHz open-drain I2C master connected to the **LIS2DW12** (`0x19`) and **IS31FL3741A** (`0x30`).

## How to test

1. Generate `src/project.v` from the Amaranth RTL bundle:
   ```bash
   python tb.py --export-only
   cp build/standalone_tb/project.v src/project.v
   ```
2. Run the standalone 10-frame Verilator differential stress suite (compares RTL against the golden Python Q4.12 reference model across `dense_cluster`, `wall_mixed`, and `four_clusters` with 0 LSB error):
   ```bash
   python tb.py --frames 10 --seed 1
   ```
3. Run the Tiny Tapeout Cocotb testbench inside `test/`:
   ```bash
   cd test && make -B
   ```

## External hardware

* **ESP-PSRAM64H** (3.3V 64 Mbit QPI PSRAM) + 5V/3.3V bidirectional level translator on `uo[2:0]`, `uio[3:0]`, and `uio[6]`.
* **LIS2DW12** 3-axis accelerometer on the I2C bus (`uio[4]` SDA, `uio[5]` SCL) + `INT2` wake pin on `ui[0]`.
* **IS31FL3741A** LED matrix driver (Adafruit 5201) driving 216 monochrome LEDs on the I2C bus (`uio[4]` SDA, `uio[5]` SCL) + `SDB` on `uio[7]`.
