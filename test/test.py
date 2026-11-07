# SPDX-FileCopyrightText: © 2026 Nitin Swarnkar
# SPDX-License-Identifier: Apache-2.0

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles


@cocotb.test()
async def test_project(dut):
    dut._log.info("Starting tt_um_flip_pendant reset and boot peripheral check")

    # 25 MHz system clock (40 ns period)
    clock = Clock(dut.clk, 40, unit="ns")
    cocotb.start_soon(clock.start())

    # Initialize inputs: pull-ups on I2C SDA (uio_in[4]=1) and SCL (uio_in[5]=1)
    dut.ena.value = 1
    dut.ui_in.value = 0b0010_1000  # force_awake=1, auto_run_en=1
    dut.uio_in.value = 0b0011_0000
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 10)

    dut._log.info(f"Post-reset uo_out={dut.uo_out.value} uio_out={dut.uio_out.value} uio_oe={dut.uio_oe.value}")

    # Check static output/enable pins immediately after reset release:
    # uio_out[7] = is31_sdb must be 1 (IS31FL3741A enabled) and uio_oe[7] = 1
    uio_out_val = int(dut.uio_out.value)
    uio_oe_val = int(dut.uio_oe.value)
    assert (uio_out_val >> 7) & 1 == 1, "IS31FL3741A SDB (uio_out[7]) should be driven high"
    assert (uio_oe_val >> 7) & 1 == 1, "IS31FL3741A SDB (uio_oe[7]) output enable must be 1"
    assert (uio_oe_val >> 6) & 1 == 1, "PSRAM translator OE# (uio_oe[6]) output enable must be 1"

    # Wait for the I2C master to assert busy (uo_out[6]) as LIS2DW12 boot init begins
    saw_i2c_busy = False
    saw_scl_toggle = False
    for _ in range(500):
        await ClockCycles(dut.clk, 1)
        uo = int(dut.uo_out.value)
        oe = int(dut.uio_oe.value)
        if (uo >> 6) & 1:
            saw_i2c_busy = True
        if (oe >> 5) & 1:
            saw_scl_toggle = True
        if saw_i2c_busy and saw_scl_toggle:
            break

    assert saw_i2c_busy, "I2C master (uo_out[6]) did not become busy for LIS2DW12 init"
    assert saw_scl_toggle, "I2C SCL open-drain enable (uio_oe[5]) did not toggle"
    dut._log.info("Verified reset, IS31FL3741A SDB, and LIS2DW12 I2C boot sequence start!")
