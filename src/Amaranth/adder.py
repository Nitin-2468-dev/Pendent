from amaranth import *
from amaranth.sim import Simulator
from amaranth.back import rtlil, verilog
# import amaranth_playground
from amaranth.lib.wiring import In, Out
from amaranth.lib import wiring

class Adder(wiring.Component):
    "Adds to 4 bits value together"

    c_in: In(1) # carry in 1 bit
    a: In(4) # 4 bits for var A
    b: In(4) # 4 bits For var B
    Sum: Out(5) # 4 bits (max sum of var A and var B) (8192 = 4096 + 4096)
            
    def elaborate(self, platfrom):
        m = Module()

        m.d.comb +=  self.Sum.eq(Cat(self.a, Const(0, 1)) +  Cat(self.b, Const(0, 1)) + Cat(self.c_in, Const(0, 1)))
        return m


dut = Adder()

async def bench(ctx):
    ctx.set(dut.a, 7)
    ctx.set(dut.b, 8)
    ctx.set(dut.c_in, 1)

    await ctx.delay(1e-6)

    ans = ctx.get(dut.Sum)

    print("A        : " , 7)
    print("B        : " , 8)
    print("Carry in : " , 1)
    print("----------------------")
    print("sum : " , ans )

    assert ans == 16
    
sim = Simulator(dut)
sim.add_testbench(bench)
# sim.run()

with sim.write_vcd("Adder.vcd"):
    sim.run()

with open("Adder.v", "w") as f:
    f.write(verilog.convert(dut,name="adder_core", ports=[dut.a,dut.b,dut.c_in,dut.Sum]))

