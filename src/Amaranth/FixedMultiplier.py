from amaranth import *
from amaranth.sim import Simulator
from amaranth.back import rtlil, verilog
from amaranth.lib.wiring import In, Out
from amaranth.lib import wiring
from amaranth.back import verilog
from pathlib import Path

print("Running from:", Path.cwd())
print("Python file:", Path(__file__).resolve())

class FixedMultiplier(wiring.Component):
    "multiplies two 8-bit with 12 fractions"
    
    a:In(signed(16))
    b:In(signed(16))
        
    product:Out(signed(32))
    
    def elaborate(self, platform):
        m = Module()
        m.d.comb += self.product.eq((self.a * self.b) >> 12)
        return m
    

dut = FixedMultiplier()

async def bench(ctx):
    a = int(-1.5 * (1 << 12)) # -6,144
    b = int(2.5 * (1 << 12))  # 10,240

    ctx.set(dut.a, a)
    ctx.set(dut.b, b)

    await ctx.delay(1e-6)

    ans = ctx.get(dut.product)

    print("A        : " , a / (1 << 12) , "(raw: " , a , ")")
    print("B        : " , b / (1 << 12) , "(raw: " , b , ")")
    print("----------------------")
    print("product : " , ans / (1 << 12) , "(raw: " , ans , ")") # shoud be -15360
    
    #assert ans == 15360
    #print("Assertion passed!")
    
sim = Simulator(dut)
sim.add_testbench(bench)
sim.run()


with open("FixedMultiplier.v", "w") as f:
    f.write(verilog.convert(
                dut,
                ports=[dut.a, dut.b, dut.product],
                )
            )