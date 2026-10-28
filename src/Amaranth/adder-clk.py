from amaranth import *
from amaranth.sim import Simulator
from amaranth.back import rtlil, verilog
# import amaranth_playground
from amaranth.lib.wiring import In, Out
from amaranth.lib import wiring

class Adder(Elaboratable):
    "Adds to 4 bits value together Clocked"
        
    def __init__(self, a , b , carry_in):
        self.a = Signal(4,init=a)    # 1111 15
        self.b = Signal(4,init=b)    # 1111 15 
        self.c_in = Signal(1,init=carry_in) # 1 
        self.Sum = Signal(5)  # max is 31 , 
        
    def elaborate(self, platfrom):
        m = Module()

        ans = Signal(5)
        m.d.comb += self.Sum.eq(self.a + self.b + self.c_in)
        return m


a = 5
b = 5
c = 1

dut = Adder(a , b , c)
sim = Simulator(dut)

async def bench(ctx):

    ans = ctx.get(dut.Sum)
    
    print("A        : " , a) # 5
    print("B        : " , b) # 5 
    print("Carry in : " , c) # 1
    print("----------------------")
    print("sum : " , ans ) # 11 01011
    
    ctx.set(dut.a , 15)
    ctx.set(dut.b , 15)
    ctx.set(dut.c_in , 1)
    
    print("A        : " , 15) # 15
    print("B        : " , 15) # 15 
    print("Carry in : " , 1) # 1
    print("----------------------")
    
    ans = ctx.get(dut.Sum)
    print("sum : " , ans ) # 31 11111 (1 + 2  + 4 + 8 + 16) 

    # assert ans == 0
    

sim.add_testbench(bench)
# sim.run()

with sim.write_vcd("Adder_clk.vcd"):
    sim.run()

with open("Adder_Clk.v", "w") as f:
    f.write(verilog.convert(dut,name="adder_core", ports=[dut.a,dut.b,dut.c_in,dut.Sum]))

