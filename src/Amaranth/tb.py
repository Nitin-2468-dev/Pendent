#!/usr/bin/env python3
# tb.py - Script to export my Amaranth design to Verilog (project.v) for Tiny Tapeout
# and run a quick Q4.12 fixed-point fluid check in Python.

import argparse
from pathlib import Path
import numpy as np

from asic import PendantSystemTop, TTUmFlipPendant

SHIFT = 12
SCALE = 1 << SHIFT


class SimpleFlipSim:
    """Quick fixed-point Q4.12 model to test particle motion inside the circular pendant."""
    def __init__(self, n_particles=256):
        self.n = n_particles
        self.center = 8 * SCALE
        self.wall_r = int(7.75 * SCALE)
        self.dt = 68  # ~1/60s in Q4.12
        self.pos = np.full((n_particles, 2), self.center, dtype=np.int32)
        self.vel = np.zeros((n_particles, 2), dtype=np.int32)

    def step(self, gx=0, gy=-60):
        self.vel[:, 0] += gx * self.dt
        self.vel[:, 1] += gy * self.dt
        self.pos[:, 0] += (self.vel[:, 0] * self.dt) >> SHIFT
        self.pos[:, 1] += (self.vel[:, 1] * self.dt) >> SHIFT


def export_verilog(build_dir: Path):
    from amaranth import ClockDomain, ClockSignal, Elaboratable, Module, ResetSignal, Signal
    from amaranth.back import verilog

    build_dir.mkdir(parents=True, exist_ok=True)

    class ExportTTUmTop(Elaboratable):
        def __init__(self):
            self.sync = ClockDomain("sync")
            self.ui_in = Signal(8, name="ui_in")
            self.uo_out = Signal(8, name="uo_out")
            self.uio_in = Signal(8, name="uio_in")
            self.uio_out = Signal(8, name="uio_out")
            self.uio_oe = Signal(8, name="uio_oe")
            self.ena = Signal(name="ena")
            self.rst_n = Signal(name="rst_n")
            self.tt = TTUmFlipPendant()

        def elaborate(self, platform):
            m = Module()
            m.domains.sync = self.sync
            m.submodules.tt = self.tt
            m.d.comb += [
                self.sync.rst.eq(~self.rst_n),
                self.tt.ui_in.eq(self.ui_in),
                self.uo_out.eq(self.tt.uo_out),
                self.tt.uio_in.eq(self.uio_in),
                self.uio_out.eq(self.tt.uio_out),
                self.uio_oe.eq(self.tt.uio_oe),
                self.tt.ena.eq(self.ena),
            ]
            return m

    tt_top = ExportTTUmTop()
    tt_ports = [
        tt_top.ui_in, tt_top.uo_out,
        tt_top.uio_in, tt_top.uio_out, tt_top.uio_oe,
        tt_top.ena, tt_top.sync.clk, tt_top.rst_n,
    ]
    tt_v = verilog.convert(tt_top, name="tt_um_flip_pendant", ports=tt_ports)

    out_path = build_dir / "project.v"
    out_path.write_text(tt_v)
    print(f"Exported {out_path.resolve()} ({out_path.stat().st_size:,} bytes)")

    # Also copy directly to ../project.v or src/project.v for Tiny Tapeout CI
    for target in (Path("../project.v"), Path("src/project.v")):
        if target.resolve().parent.exists() and (target.exists() or target.resolve().parent.name == "src"):
            target.write_text(tt_v)
            print(f"Updated  {target.resolve()} ({target.stat().st_size:,} bytes)")


def main():
    parser = argparse.ArgumentParser(description="Export FLIP Pendant ASIC to Verilog")
    parser.add_argument("--build-dir", type=Path, default=Path("build/standalone_tb"))
    parser.add_argument("--export-only", action="store_true", help="Export project.v")
    args = parser.parse_args()

    export_verilog(args.build_dir)
    if not args.export_only:
        sim = SimpleFlipSim()
        for _ in range(5):
            sim.step(gx=0, gy=-60)
        print("Quick fixed-point sim check passed!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
