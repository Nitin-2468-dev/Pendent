from amaranth import *
from amaranth.sim import Simulator
from amaranth.back import rtlil, verilog
from amaranth.lib.wiring import In, Out
from amaranth.lib import wiring
from amaranth.back import verilog
from pathlib import Path

print("Running from:", Path.cwd())
print("Python file:", Path(__file__).resolve())

class Clocked_FixedMult(Elaboratable):
    "multiplies two 8-bit with 12 fractions"
    
    def __init__(self, a , b):
        self.a = Signal(signed(16), init=a)
        self.b = Signal(signed(16), init=b)
        self.product = Signal(signed(32)) 
        
    def elaborate(self, platform):
        m = Module()
        m.d.sync += self.product.eq((self.a * self.b) >> 12)
        return m
    

a = int(-1.5 * (1 << 12)) # -6,144
b = int(2.5 * (1 << 12))  # 10,240

dut = Clocked_FixedMult(a, b)
sim = Simulator(dut)
sim.add_clock(1e-6)

async def bench(ctx):
    
    await ctx.tick()
    
    ans = ctx.get(dut.product)

    print("A        : " , a / (1 << 12) , "(raw: " , a , ")")
    print("B        : " , b / (1 << 12) , "(raw: " , b , ")")
    print("----------------------")
    print("product : " , ans / (1 << 12) , "(raw: " , ans , ")") # shoud be -15360
    
    #assert ans == 15360
    #print("Assertion passed!")
    
sim.add_testbench(bench)
sim.run()

verilog_code = verilog.convert(
    dut,
    name="Clocked_FixedMult",
    ports=[dut.a, dut.b, dut.product],
)

Path("Clocked_FixedMult.v").write_text(verilog_code)