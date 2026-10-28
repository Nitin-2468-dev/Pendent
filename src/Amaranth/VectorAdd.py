from amaranth import *
from amaranth.sim import Simulator
from amaranth.back import rtlil, verilog
from amaranth.lib.wiring import In, Out
from amaranth.lib import wiring


class VectorAdd(wiring.Component):
    "Add two 16-bit vectors with 12 fractions"
    
    ax:In(signed(16))
    ay:In(signed(16))
    bx:In(signed(16))
    by:In(signed(16))
    
    rx:Out(signed(17))
    ry:Out(signed(17))
    
    def elaborate(self, platform):
        m = Module()
        
        m.d.comb += self.rx.eq(self.ax + self.bx)
        m.d.comb += self.ry.eq(self.ay + self.by)
        
        return m
    
dut = VectorAdd()

async def bench(ctx):
    ax = int(1.5 * (1 << 12))  # 6144
    ay = int(-0.5 * (1 << 12))  # 2048
    bx = int(2.0 * (1 << 12))  # 6144
    by = int(1.25 * (1 << 12)) # 5120

    ctx.set(dut.ax, ax)
    ctx.set(dut.bx, bx)
    ctx.set(dut.ay, ay)
    ctx.set(dut.by, by)
    
    
    await ctx.delay(1e-6)

    rx = ctx.get(dut.rx)
    ry = ctx.get(dut.ry)

    print("ax        : " , ax / (1 << 12) , "(raw: " , ax , ")")
    print("bx        : " , bx / (1 << 12) , "(raw: " , bx , ")")
    print("----------------------")
    print("rx        : " , rx / (1 << 12) , "(raw: " , rx , ")")     
    
    print("ay        : " , ay / (1 << 12) , "(raw: " , ay , ")")
    print("by        : " , by / (1 << 12) , "(raw: " , by , ")")
    print("----------------------")
    print("ry        : " , ry / (1 << 12) , "(raw: " , ry , ")")     
    
    
    assert rx / (1 << 12) == 3.5
    assert ry / (1 << 12) == 0.75 
    #print("Assertion passed!")
    
sim = Simulator(dut)
sim.add_testbench(bench)
sim.run()