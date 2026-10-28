from amaranth import *
from amaranth.sim import Simulator
from amaranth.lib import wiring
from amaranth.lib.wiring import In, Out


class Particle(wiring.Component):
    vx: In(signed(16))
    x: Out(signed(17))

    def __init__(self):
        super().__init__()
        self.position = Signal(signed(17), init=0)

    def elaborate(self, platform):
        m = Module()

        # TODO 1: Connect the output x to the stored position
        m.d.comb += self.x.eq(self.position)

        #TODO 2: Update the stored position by adding vx
        m.d.sync += self.position.eq(self.x + self.vx)

        return m
    
dut = Particle()
sim = Simulator(dut)
sim.add_clock(1e-6)

async def bench(ctx):
    ctx.set(dut.vx, 2048)  # 0.5 in Q12

    print("Initial:", ctx.get(dut.x) / 4096)

    await ctx.tick()
    print("After 1 tick:", ctx.get(dut.x) / 4096)

    await ctx.tick()
    print("After 2 ticks:", ctx.get(dut.x) / 4096)

    await ctx.tick()
    print("After 3 ticks:", ctx.get(dut.x) / 4096)
    
    # The expected positions are 0.0, 0.5, 1.0, and 1.5

sim.add_testbench(bench)
sim.run()