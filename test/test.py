
import cocotb
from cocotb.triggers import Timer


@cocotb.test()
async def test_adder(dut):
    # Test 1: 7 + 8 + 1 = 16
    a, b, carry_in = 7, 8, 1

    dut.ui_in.value = (b << 4) | a
    dut.uio_in.value = carry_in

    await Timer(1, unit="ns")

    result = int(dut.uo_out.value) & 0x1F
    print(f"{a} + {b} + {carry_in} = {result}")
    assert result == 16

    # Test 2: 15 + 15 + 1 = 31
    a, b, carry_in = 15, 15, 1

    dut.ui_in.value = (b << 4) | a
    dut.uio_in.value = carry_in

    await Timer(1, unit="ns")

    result = int(dut.uo_out.value) & 0x1F
    print(f"{a} + {b} + {carry_in} = {result}")
    assert result == 31
