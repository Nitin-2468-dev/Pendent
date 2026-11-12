#!/usr/bin/env python3
"""
Generate a GTKWave-compatible VCD waveform from the PENDENT Amaranth RTL.

Run from the repository root:
    python waveform.py

This simulates the real TTUmFlipPendant RTL. The external PSRAM data input is
held at zero and the I2C SDA input is held high (idle/NACK), so this is an RTL
control-flow waveform, not a model of the physical memories or sensors.
"""

from pathlib import Path

from amaranth.sim import Simulator

from asic import TTUmFlipPendant


def main():
    dut = TTUmFlipPendant()
    sim = Simulator(dut)
    sim.add_clock(1e-6)  # 1 MHz simulation clock; functional timing is in cycles

    core = dut.system.core
    psram = core.psram
    i2c = dut.system.i2c

    traces = [
        dut.ui_in,
        dut.uio_in,
        dut.uo_out,
        dut.uio_out,
        dut.uio_oe,

        # Fluid engine control
        core.start,
        core.busy,
        core.done,
        core.stage,
        core.gx,
        core.gy,
        core.velocity_overflow,

        # PSRAM controller and external bus
        psram.init_done,
        psram.ready,
        psram.req,
        psram.we,
        psram.addr,
        psram.wdata,
        psram.rdata,
        psram.rvalid,
        psram.done,
        psram.busy,
        psram.sclk,
        psram.ce_n,
        psram.dq_i,
        psram.dq_o,
        psram.dq_oe,

        # I2C activity from the top-level system
        i2c.busy,
        i2c.scl_o,
        i2c.scl_oe,
        i2c.sda_i,
        i2c.sda_o,
        i2c.sda_oe,
        i2c.ack_error,

        # System-level state
        dut.system.clock_gated_sleep,
        dut.system.frame_sync,
    ]

    async def bench(ctx):
        # ui_in:
        # bit 0 = LIS2DW12 sleep interrupt (asserted)
        # bit 3 = enable automatic frame timing
        # bit 4 = accelerometer SA0
        # bit 5 = force awake
        #
        # uio_in bit 4 is I2C SDA input; bits 0..3 are PSRAM DQ input.
        ctx.set(dut.ui_in, 0b111001)
        ctx.set(dut.uio_in, 0b10000)

        # Let the boot sequence, PSRAM initialization, and fluid engine run.
        # 250,000 cycles at the simulated 1 MHz clock = 250 ms.
        for _ in range(250_000):
            await ctx.tick()

    sim.add_testbench(bench)

    out = Path("build/waveforms")
    out.mkdir(parents=True, exist_ok=True)
    vcd_path = out / "pendent.vcd"
    gtkw_path = out / "pendent.gtkw"

    with vcd_path.open("w") as vcd_file, gtkw_path.open("w") as gtkw_file:
        with sim.write_vcd(vcd_file, gtkw_file, traces=traces):
            sim.run()

    print(f"Waveform written to: {vcd_path.resolve()}")
    print("Open it with: gtkwave build/waveforms/pendent.vcd")


if __name__ == "__main__":
    main()
