from amaranth import *
from amaranth.lib.wiring import In, Out
from amaranth.lib.memory import Memory
from amaranth.sim import Simulator
from amaranth.lib import wiring

class Smallmemory(Elaboratable):
    "16 bit Memory stroage 16 bits data"
    
    # defaut is unsinged 
    
    def __init__(self):
        self.write_enable = Signal(1 ,name="write_enable")
        self.write_Addr = Signal(4, name="write_Addr")
        self.data_in = Signal(16, name="data_in")
        self.read_Addr = Signal(4, name="read_Addr")
        self.data_out = Signal(16, name="read_enable")

    
    def elaborate(self, platform):
        m = Module()
        
        mem = Memory(
            shape=unsigned(16),
            depth=16,
            init=[],
        )
        
        m.submodules.mem = mem
        
        # Write port
        wp = mem.write_port()
        
        m.d.comb += [
            wp.addr.eq(self.write_Addr),
            wp.data.eq(self.data_in),
            wp.en.eq(self.write_enable)
        ]
        
        rp = mem.read_port(domain="sync")
        m.d.comb += [
            rp.addr.eq(self.read_Addr),
            self.data_out.eq(rp.data),
        ]
        
        return m
    
dut = Smallmemory()
sim = Simulator(dut)
sim.add_clock(1e-6)



async def bench(ctx):
    ctx.set(dut.data_in, 42)
    ctx.set(dut.write_Addr, 7)
    ctx.set(dut.write_enable,1)
    
    await ctx.tick() # storage the values.
    
    ctx.set(dut.write_enable , 0)
    ctx.set(dut.read_Addr , 7)
    
    await ctx.tick()
    out = ctx.get(dut.data_out)
    print(f"Addr(7) : {out} (42)")
    assert out == 42
    
    ctx.set(dut.data_in, 100)
    ctx.set(dut.write_Addr, 3)
    ctx.set(dut.write_enable,1)
    
    await ctx.tick() 
    
    ctx.set(dut.data_in, 200)
    await ctx.tick() 
    ctx.set(dut.read_Addr , 3)
    
    await ctx.tick()
    out = ctx.get(dut.data_out)
    print(f"Addr(3) : {out} (200)")
    assert out == 200
    ctx.set(dut.write_enable , 0)
    ctx.set(dut.data_in, 500)
    ctx.set(dut.write_Addr, 1)
    ctx.set(dut.read_Addr , 1)
    await ctx.tick()
    
    out = ctx.get(dut.data_out)
    print(f"Addr(1) : {out} (0)")
    # assert out == 0
    
    
sim.add_testbench(bench)
# sim.run()
    
with sim.write_vcd("mem.vcd"):
    sim.run()