#!/usr/bin/env python3
import argparse
import csv
import math
import subprocess
import sys
from pathlib import Path

import numpy as np

from amaranth import ClockDomain, ClockSignal, Elaboratable, Module, ResetSignal, Signal
from asic import FLIPPipeline, PendantSystemTop, TTUmFlipPendant

AIR = 0
WATER = 1
SOLID = 2

class ExternalSPIRAM:
    def __init__(self, size=65536):
        self.memory = np.zeros(size, dtype=np.uint8)

    def write_block(self, addr, data_bytes):
        data = np.frombuffer(data_bytes, dtype=np.uint8)
        end = addr + len(data)
        self.memory[addr:end] = data

    def read_block(self, addr, length):
        return self.memory[addr:addr + length].tobytes()

class FixedFlip:
    def __init__(self):
        self.grid_size = 16
        self.amount = 16 ** 2          # 256 particles (PW=16, PH=16)
        self.gravity_mag = 60.0        # GMAG = 60.0 cells/s^2
        self.dt = 1.0 / 60.0           # DT = 1/60 s
        self.flip_ratio = 0.95         # FLIP_RATIO = 0.95
        self.wall_friction = 1.0
        self.k = 3.0
        self.vmax = 40.0               # VMAX = 40.0
        self.O = 1.6
        self.itterations = 30          # SOLVE_ITERS = 30
        self.spacing = 0.65            # SPACING = 0.65
        self.rest_density_f = 1.0 / (self.spacing ** 2)
        self.rest_density = int(round(self.rest_density_f * 1024))
        self.min_distance = 0.6        # MIN_DIST = 2 * PRAD = 0.6
        self.push_relax = 0.6          # PUSH_RELAX = 0.6
        self.push_itters = 2

        self.fix_scale = 4096.0

        self.ram = ExternalSPIRAM(65536)

        self._build_container()
        self.reset()

    def _quantize(self, arr):
        return np.floor(arr * self.fix_scale + 0.5).astype(np.float32) / self.fix_scale

    def _build_container(self):
        N = self.grid_size
        ix, iy = np.indices((N, N))
        c = N / 2.0
        self.inside = ((ix + 0.5 - c) ** 2 + (iy + 0.5 - c) ** 2) < 70.0
        self.center = np.array([c, c], dtype=np.float32)
        self.s = np.where(self.inside, 1.0, 0.0).astype(np.float32)

        sp = np.pad(self.s, 1)
        self.sx0 = sp[0:N, 1:N + 1]
        self.sx1 = sp[2:N + 2, 1:N + 1]
        self.sy0 = sp[1:N + 1, 0:N]
        self.sy1 = sp[1:N + 1, 2:N + 2]
        self.non_solid_nbrs = np.maximum(self.sx0 + self.sx1 + self.sy0 + self.sy1, 1.0)

        self.u_open = sp[0:N + 1, 1:N + 1] * sp[1:N + 2, 1:N + 1]
        self.v_open = sp[1:N + 1, 0:N + 1] * sp[1:N + 1, 1:N + 2]

        self.wall_r = 7.75

    def reset(self, seed=1):
        rng = np.random.default_rng(seed)
        self.positions = np.zeros((self.amount, 2), dtype=np.float32)
        self.velocity = np.zeros((self.amount, 2), dtype=np.float32)

        side = int(round(np.sqrt(self.amount)))
        xs = self.center[0] + (np.arange(side) - side / 2.0 + 0.5) * self.spacing
        ys = 2.5 + (np.arange(side) + 0.5) * self.spacing
        xx, yy = np.meshgrid(xs, ys)
        self.positions[:, 0] = xx.ravel()
        self.positions[:, 1] = yy.ravel()
        self.positions += (rng.random((self.amount, 2)) - 0.5) * self.spacing * 0.2
        self.positions = self._quantize(self.positions)

        N = self.grid_size
        self.u = np.zeros((N + 1, N), dtype=np.float32)
        self.u_sum = np.zeros((N + 1, N), dtype=np.float32)
        self.u_weight = np.zeros((N + 1, N), dtype=np.float32)
        self.u_old = np.zeros((N + 1, N), dtype=np.float32)
        self.u_valid = np.zeros((N + 1, N), dtype=np.float32)

        self.v = np.zeros((N, N + 1), dtype=np.float32)
        self.v_sum = np.zeros((N, N + 1), dtype=np.float32)
        self.v_weight = np.zeros((N, N + 1), dtype=np.float32)
        self.v_old = np.zeros((N, N + 1), dtype=np.float32)
        self.v_valid = np.zeros((N, N + 1), dtype=np.float32)

        self.Pressure = np.zeros((N, N), dtype=np.float32)
        self.density = np.zeros((N, N), dtype=np.float32)
        self.particle_count = np.zeros((N, N), dtype=np.int32)
        self.divergence = np.zeros((N, N), dtype=np.float32)
        self.cell_type = np.zeros((N, N), dtype=np.int32)

        self.gravity = np.array([0.0, -self.gravity_mag], dtype=np.float32)
        self.swirl_phase = 0.0

        self.Particle_to_Grid()
        self.update_cell_type()
        self._flush_to_ram()

    def _flush_to_ram(self):
        self.ram.write_block(0x0000, self.positions.tobytes())
        self.ram.write_block(0x0800, self.velocity.tobytes())
        self.ram.write_block(0x1000, self.u.tobytes())
        self.ram.write_block(0x1440, self.v.tobytes())
        self.ram.write_block(0x1880, self.density.tobytes())

    def _pull_from_ram(self):
        n_bytes = self.amount * 8
        self.positions = np.frombuffer(
            self.ram.read_block(0x0000, n_bytes), dtype=np.float32
        ).reshape(self.amount, 2).copy()
        self.velocity = np.frombuffer(
            self.ram.read_block(0x0800, n_bytes), dtype=np.float32
        ).reshape(self.amount, 2).copy()

    def apply_gravity(self, gx_8bit=0, gy_8bit=-60):
        g = np.array([gx_8bit, gy_8bit], dtype=np.float32) * (self.gravity_mag / 60.0)
        self.gravity = g
        self.velocity += g * self.dt
        self.velocity = np.clip(self.velocity, -self.vmax, self.vmax)

    def apply_stir(self, mouse_xy, mouse_vel):
        d = self.positions - mouse_xy[None, :]
        d2 = (d * d).sum(axis=1)
        f = np.exp(-d2 / 8.0)  # sigma = 2 cells
        sp = float(np.hypot(mouse_vel[0], mouse_vel[1]))
        t = np.clip(sp / 4.0, 0.0, 1.0)
        smooth = t * t * (3.0 - 2.0 * t)
        self.velocity += (mouse_vel[None, :] - self.velocity) * (f * 0.5 * smooth)[:, None]

    def apply_shake(self, frame_idx=1):
        rng = np.random.default_rng(frame_idx * 977 + 1)
        self.velocity += (rng.random((self.amount, 2), dtype=np.float32) - 0.5) * 30.0

    def push_apart(self):
        md = self.min_distance
        p = self.positions
        for _ in range(self.push_itters):
            d = p[:, None, :] - p[None, :, :]
            d2 = (d * d).sum(axis=-1)
            I, J = np.nonzero(np.triu((d2 < md * md) & (d2 > 1e-10), 1))
            if len(I) == 0:
                break
            dv = p[I] - p[J]
            dist = np.sqrt((dv * dv).sum(axis=1))
            corr = dv * (self.push_relax * 0.5 * (md - dist) / dist)[:, None]
            np.add.at(p, I, corr)
            np.add.at(p, J, -corr)
        self.positions = p.astype(np.float32)

    def collide_walls(self):
        r = self.positions - self.center
        dist = np.hypot(r[:, 0], r[:, 1])
        out = dist > self.wall_r
        if out.any():
            n = r[out] / dist[out][:, None]
            self.positions[out] = self.center + n * self.wall_r
            vn = (self.velocity[out] * n).sum(axis=1)
            vn = np.maximum(vn, 0.0)
            self.velocity[out] -= n * vn[:, None]
            if self.wall_friction < 1.0:
                vv = self.velocity[out]
                vnn = (vv * n).sum(axis=1)[:, None] * n
                self.velocity[out] = vnn + (vv - vnn) * self.wall_friction

    def update_cell_type(self):
        N = self.grid_size
        self.cell_type.fill(AIR)
        self.cell_type[~self.inside] = SOLID

        self.particle_count.fill(0)
        ci = np.clip(np.floor(self.positions[:, 0]).astype(np.int32), 0, N - 1)
        cj = np.clip(np.floor(self.positions[:, 1]).astype(np.int32), 0, N - 1)
        np.add.at(self.particle_count, (ci, cj), 1)

        water = ((self.particle_count > 0) | (self.density > 0.1 * self.rest_density_f)) & self.inside
        self.cell_type[water] = WATER

        ct = np.pad(self.cell_type, 1, constant_values=SOLID)
        self.u_valid = ((ct[0:N + 1, 1:N + 1] != AIR) | (ct[1:N + 2, 1:N + 1] != AIR)).astype(np.float32)
        self.v_valid = ((ct[1:N + 1, 0:N + 1] != AIR) | (ct[1:N + 1, 1:N + 2] != AIR)).astype(np.float32)

    def _corners(self, gx, gy, shape):
        gx = np.clip(gx, 0.0, shape[0] - 1.0 - 1e-4)
        gy = np.clip(gy, 0.0, shape[1] - 1.0 - 1e-4)
        i0 = np.floor(gx).astype(np.int32)
        j0 = np.floor(gy).astype(np.int32)
        dx = gx - i0
        dy = gy - j0
        idx = ((i0, j0), (i0 + 1, j0), (i0 + 1, j0 + 1), (i0, j0 + 1))
        w = ((1.0 - dx) * (1.0 - dy), dx * (1.0 - dy), dx * dy, (1.0 - dx) * dy)
        return idx, w

    def _scatter(self, total, weight, gx, gy, values=None):
        idx, w = self._corners(gx, gy, weight.shape)
        for (i, j), wk in zip(idx, w):
            np.add.at(weight, (i, j), wk)
            if values is not None:
                np.add.at(total, (i, j), values * wk)

    def _gather(self, new, old, weight, gx, gy, valid):
        idx, w = self._corners(gx, gy, weight.shape)
        wsum = 0.0
        vnew = 0.0
        vdelta = 0.0
        for (i, j), wk in zip(idx, w):
            wv = wk * valid[i, j]
            wsum += wv
            vnew += new[i, j] * wv
            vdelta += (new[i, j] - old[i, j]) * wv
        ok = wsum > 1e-5
        safe = np.where(ok, wsum, 1.0)
        return vnew / safe, vdelta / safe, ok

    def Particle_to_Grid(self):
        p = self.positions
        for a in (self.u_sum, self.u_weight, self.v_sum, self.v_weight, self.density):
            a.fill(0.0)
        self._scatter(self.u_sum, self.u_weight, p[:, 0], p[:, 1] - 0.5, self.velocity[:, 0])
        self._scatter(self.v_sum, self.v_weight, p[:, 0] - 0.5, p[:, 1], self.velocity[:, 1])
        self._scatter(None, self.density, p[:, 0] - 0.5, p[:, 1] - 0.5)

        self.u.fill(0.0)
        self.v.fill(0.0)
        m = self.u_weight > 1e-6
        self.u[m] = self.u_sum[m] / self.u_weight[m]
        m = self.v_weight > 1e-6
        self.v[m] = self.v_sum[m] / self.v_weight[m]

        self.u *= self.u_open
        self.v *= self.v_open
        self.density[~self.inside] = 0.0

        self.u = self._quantize(self.u)
        self.v = self._quantize(self.v)
        self.u_old = self.u.copy()
        self.v_old = self.v.copy()

    def Divergence(self):
        wi, wj = np.where(self.cell_type == WATER)
        if len(wi) == 0:
            self.Pressure.fill(0.0)
            self.divergence.fill(0.0)
            return

        self.Pressure[self.cell_type != WATER] = 0.0

        red = (wi + wj) % 2 == 0
        sets = [(wi[red], wj[red]), (wi[~red], wj[~red])]

        for _ in range(self.itterations):
            for i, j in sets:
                s = self.non_solid_nbrs[i, j]
                d = (self.u[i + 1, j] - self.u[i, j]) + (self.v[i, j + 1] - self.v[i, j])
                compression = np.maximum(self.density[i, j] / self.rest_density_f - 1.0, 0.0)
                d = d - self.k * compression
                p = -d / s * self.O
                self.Pressure[i, j] += p
                self.u[i, j] -= p * self.sx0[i, j]
                self.u[i + 1, j] += p * self.sx1[i, j]
                self.v[i, j] -= p * self.sy0[i, j]
                self.v[i, j + 1] += p * self.sy1[i, j]

        self.u = self._quantize(self.u)
        self.v = self._quantize(self.v)
        self.Pressure = self._quantize(self.Pressure)

        self.divergence.fill(0.0)
        self.divergence[wi, wj] = (self.u[wi + 1, wj] - self.u[wi, wj]) + (self.v[wi, wj + 1] - self.v[wi, wj])

    def Grid_to_Particle(self):
        p = self.positions
        r = self.flip_ratio
        for comp, (new, old, valid, gx, gy) in enumerate((
            (self.u, self.u_old, self.u_valid, p[:, 0], p[:, 1] - 0.5),
            (self.v, self.v_old, self.v_valid, p[:, 0] - 0.5, p[:, 1])
        )):
            vnew, vdelta, ok = self._gather(new, old, valid, gx, gy, valid)
            v = self.velocity[:, comp]
            v_pic = np.where(ok, vnew, v)
            v_flip = np.where(ok, v + vdelta, v)
            self.velocity[:, comp] = (1.0 - r) * v_pic + r * v_flip

        self.velocity = np.clip(self.velocity, -self.vmax, self.vmax)

    def update(self, gx_8bit=0, gy_8bit=-60, stir_pos=None, stir_vel=None, shake=False, frame_idx=1):
        self._pull_from_ram()

        self.apply_gravity(gx_8bit, gy_8bit)
        if stir_pos is not None and stir_vel is not None:
            self.apply_stir(stir_pos, stir_vel)
        if shake:
            self.apply_shake(frame_idx)

        self.positions += self.velocity * self.dt
        self.positions = self._quantize(self.positions)

        self.push_apart()
        self.collide_walls()
        self.positions = self._quantize(self.positions)
        self.velocity = self._quantize(self.velocity)

        self.Particle_to_Grid()
        self.update_cell_type()

        self.Divergence()
        self.Grid_to_Particle()

        self._flush_to_ram()

SHIFT = 12
SCALE = 1 << SHIFT                    # 4096
HALF_CELL_Q12 = 1 << (SHIFT - 1)      # 2048 (0.5 cells)

NX = 16
NY = 16
NP = 256

CEN_Q12 = 8 * SCALE                   # 32768 (8.0)
WALL_R_Q12 = int(round(7.75 * SCALE)) # 31744 (7.75)
WALL_R2_Q8 = int(round(7.75 * 7.75 * 256))  # 15376 (r^2 in Q8.8)

MIN_DIST_Q12 = int(round(0.6 * SCALE))      # 2458 (0.6)
MIN_DIST_SQ_Q12 = (MIN_DIST_Q12 * MIN_DIST_Q12) >> SHIFT  # 1474 (0.36 * 4096)

VMAX_Q12 = 40 * SCALE                 # 163840 (40.0 cells/s)
DT_Q12 = 68

FLIP_R_Q12 = int(round(0.95 * SCALE)) # 3891
PIC_R_Q12 = SCALE - FLIP_R_Q12        # 205 (3891 + 205 = 4096)

SPACING_Q12 = int(round(0.65 * SCALE))
REST_DENSITY_F = 1.0 / (0.65 * 0.65)  # 2.3668639
REST_DENSITY_Q12 = int(round(REST_DENSITY_F * SCALE))     # 9695
INV_REST_DENSITY_Q12 = int(round(SCALE / REST_DENSITY_F)) # 1731
WATER_DENS_THS_Q12 = int(round(0.1 * REST_DENSITY_F * SCALE))  # 969
DRIFT_K_INT = 3                       # Density drift stiffness = 3

OMEGA_INV_S_LUT = np.array([
    0,
    int(round(1.6 * SCALE / 1)),  # 6554
    int(round(1.6 * SCALE / 2)),  # 3277
    int(round(1.6 * SCALE / 3)),  # 2185
    int(round(1.6 * SCALE / 4)),  # 1638
], dtype=np.int32)

PUSH_LUT = np.zeros(64, dtype=np.int32)
for _idx in range(64):
    _d2 = max((_idx + 0.5) * 32.0 / SCALE, 1e-4)
    _d = math.sqrt(_d2)
    if _d < 0.6:
        PUSH_LUT[_idx] = min(int(round(SCALE * 0.6 * 0.5 * (0.6 - _d) / _d)), 8 * SCALE)

WALL_INV_R_LUT = np.zeros(64, dtype=np.int32)
for _idx in range(64):
    _r2 = (WALL_R2_Q8 + (_idx + 0.5) * 64.0) / 256.0
    WALL_INV_R_LUT[_idx] = int(round(SCALE / math.sqrt(_r2)))

class HardwareFlip:
    def __init__(self):
        self.grid_size = NX
        self.amount = NP
        self.gravity_mag = 60.0
        self.dt = 1.0 / 60.0
        self.spacing = 0.65
        self.rest_density_f = REST_DENSITY_F
        self.wall_r = 7.75
        self.itterations = 30
        self.center = np.array([8.0, 8.0], dtype=np.float32)

        self.ram = ExternalSPIRAM(65536)

        self.last_pair_checks = 0
        self.naive_pair_checks = (NP * (NP - 1)) // 2  # 32,640
        self.clock_gated_sleep = False
        self.sleep_Hold_frames = 0
        self._last_gx = 0
        self._last_gy = -60

        self._build_container_rom()
        self.reset()

    def _build_container_rom(self):
        ix, iy = np.indices((NX, NY), dtype=np.int32)
        dist_sq_x4 = (2 * ix - 15) ** 2 + (2 * iy - 15) ** 2
        self.inside = dist_sq_x4 < 280  # 216 active cells

        s = np.where(self.inside, 1, 0).astype(np.int32)
        sp = np.pad(s, 1)
        self.sx0 = sp[0:NX, 1:NY + 1]
        self.sx1 = sp[2:NX + 2, 1:NY + 1]
        self.sy0 = sp[1:NX + 1, 0:NY]
        self.sy1 = sp[1:NX + 1, 2:NY + 2]
        self.s_count = self.sx0 + self.sx1 + self.sy0 + self.sy1

        self.u_open = (sp[0:NX + 1, 1:NY + 1] & sp[1:NX + 2, 1:NY + 1]).astype(np.int32)
        self.v_open = (sp[1:NX + 1, 0:NY + 1] & sp[1:NX + 1, 1:NY + 2]).astype(np.int32)

    def reset(self, seed=1):
        rng = np.random.default_rng(seed)
        side = 16
        xs = 8.0 + (np.arange(side) - side / 2.0 + 0.5) * self.spacing
        ys = 2.5 + (np.arange(side) + 0.5) * self.spacing
        xx, yy = np.meshgrid(xs, ys)
        pos_f = np.zeros((NP, 2), dtype=np.float32)
        pos_f[:, 0] = xx.ravel()
        pos_f[:, 1] = yy.ravel()
        pos_f += (rng.random((NP, 2)) - 0.5) * self.spacing * 0.2

        self.pos_q12 = np.floor(pos_f * SCALE + 0.5).astype(np.int32)
        self.vel_q12 = np.zeros((NP, 2), dtype=np.int32)

        self.u_q12 = np.zeros((NX + 1, NY), dtype=np.int32)
        self.u_old_q12 = np.zeros((NX + 1, NY), dtype=np.int32)
        self.u_sum_q12 = np.zeros((NX + 1, NY), dtype=np.int32)
        self.u_weight_q12 = np.zeros((NX + 1, NY), dtype=np.int32)
        self.u_valid = np.zeros((NX + 1, NY), dtype=np.int32)

        self.v_q12 = np.zeros((NX, NY + 1), dtype=np.int32)
        self.v_old_q12 = np.zeros((NX, NY + 1), dtype=np.int32)
        self.v_sum_q12 = np.zeros((NX, NY + 1), dtype=np.int32)
        self.v_weight_q12 = np.zeros((NX, NY + 1), dtype=np.int32)
        self.v_valid = np.zeros((NX, NY + 1), dtype=np.int32)

        self.density_q12 = np.zeros((NX, NY), dtype=np.int32)
        self.pressure_q12 = np.zeros((NX, NY), dtype=np.int32)
        self.divergence_q12 = np.zeros((NX, NY), dtype=np.int32)
        self.particle_count = np.zeros((NX, NY), dtype=np.int32)
        self.cell_type = np.zeros((NX, NY), dtype=np.int32)

        self.cell_head = np.full(NX * NY, -1, dtype=np.int16)
        self.particle_next = np.full(NP, -1, dtype=np.int16)

        self.gravity = np.array([0.0, -self.gravity_mag], dtype=np.float32)
        self.clock_gated_sleep = False
        self.sleep_Hold_frames = 0

        self.p2g_q12()
        self.update_cell_type_q12()
        self._sync_views_and_ram()

    def _sync_views_and_ram(self):
        self.ram.write_block(0x0000, self.pos_q12.astype(np.uint16).tobytes())
        self.ram.write_block(0x0400, (self.vel_q12 >> 2).astype(np.int16).tobytes())
        self.ram.write_block(0x0800, (self.u_q12 >> 2).astype(np.int16).tobytes())
        self.ram.write_block(0x0A20, (self.v_q12 >> 2).astype(np.int16).tobytes())
        self.ram.write_block(0x0C40, self.density_q12.astype(np.uint16).tobytes())
        self.ram.write_block(0x0E40, self.cell_head.tobytes())
        self.ram.write_block(0x1040, self.particle_next.tobytes())

        self.positions = self.pos_q12.astype(np.float32) / SCALE
        self.velocity = self.vel_q12.astype(np.float32) / SCALE
        self.density = self.density_q12.astype(np.float32) / SCALE
        self.u = self.u_q12.astype(np.float32) / SCALE
        self.v = self.v_q12.astype(np.float32) / SCALE
        self.Pressure = self.pressure_q12.astype(np.float32) / SCALE
        self.divergence = self.divergence_q12.astype(np.float32) / SCALE

    # Stage 1: Integer Gravity & Advection
    def apply_gravity_and_advect_q12(self, gx_8bit=0, gy_8bit=-60):
        self.gravity[0] = float(gx_8bit)
        self.gravity[1] = float(gy_8bit)

        dv_x = int(gx_8bit) * DT_Q12
        dv_y = int(gy_8bit) * DT_Q12

        self.vel_q12[:, 0] = np.clip(self.vel_q12[:, 0] + dv_x, -VMAX_Q12, VMAX_Q12)
        self.vel_q12[:, 1] = np.clip(self.vel_q12[:, 1] + dv_y, -VMAX_Q12, VMAX_Q12)

        self.pos_q12[:, 0] += (self.vel_q12[:, 0] * DT_Q12) >> SHIFT
        self.pos_q12[:, 1] += (self.vel_q12[:, 1] * DT_Q12) >> SHIFT

    # Stage 2A: O(N) Spatial Hash Grid + LUT Push-Apart (Zero sqrt/div)
    def push_apart_spatial_hash_q12(self):
        pos = self.pos_q12
        head = self.cell_head
        nxt = self.particle_next
        pair_checks = 0

        nbr_offsets = ((1, 0), (-1, 1), (0, 1), (1, 1))

        for _ in range(2):
            head.fill(-1)
            for p_id in range(NP):
                cx = int(pos[p_id, 0]) >> SHIFT
                cy = int(pos[p_id, 1]) >> SHIFT
                cx = 0 if cx < 0 else (15 if cx > 15 else cx)
                cy = 0 if cy < 0 else (15 if cy > 15 else cy)
                c_idx = (cy << 4) | cx
                nxt[p_id] = head[c_idx]
                head[c_idx] = p_id

            for cy in range(NY):
                for cx in range(NX):
                    c_idx = (cy << 4) | cx
                    p_i = int(head[c_idx])
                    while p_i != -1:
                        px_i = int(pos[p_i, 0])
                        py_i = int(pos[p_i, 1])

                        p_j = int(nxt[p_i])
                        while p_j != -1:
                            pair_checks += 1
                            dx = px_i - int(pos[p_j, 0])
                            dy = py_i - int(pos[p_j, 1])
                            if -MIN_DIST_Q12 < dx < MIN_DIST_Q12 and -MIN_DIST_Q12 < dy < MIN_DIST_Q12:
                                d2_q12 = (dx * dx + dy * dy) >> SHIFT
                                if 0 < d2_q12 < MIN_DIST_SQ_Q12:
                                    factor = int(PUSH_LUT[d2_q12 >> 5])
                                    corr_x = (dx * factor) >> SHIFT
                                    corr_y = (dy * factor) >> SHIFT
                                    px_i += corr_x
                                    py_i += corr_y
                                    pos[p_j, 0] -= corr_x
                                    pos[p_j, 1] -= corr_y
                            p_j = int(nxt[p_j])

                        for ox, oy in nbr_offsets:
                            nx_c = cx + ox
                            ny_c = cy + oy
                            if 0 <= nx_c < NX and 0 <= ny_c < NY:
                                p_j = int(head[(ny_c << 4) | nx_c])
                                while p_j != -1:
                                    pair_checks += 1
                                    dx = px_i - int(pos[p_j, 0])
                                    dy = py_i - int(pos[p_j, 1])
                                    if -MIN_DIST_Q12 < dx < MIN_DIST_Q12 and -MIN_DIST_Q12 < dy < MIN_DIST_Q12:
                                        d2_q12 = (dx * dx + dy * dy) >> SHIFT
                                        if 0 < d2_q12 < MIN_DIST_SQ_Q12:
                                            factor = int(PUSH_LUT[d2_q12 >> 5])
                                            corr_x = (dx * factor) >> SHIFT
                                            corr_y = (dy * factor) >> SHIFT
                                            px_i += corr_x
                                            py_i += corr_y
                                            pos[p_j, 0] -= corr_x
                                            pos[p_j, 1] -= corr_y
                                    p_j = int(nxt[p_j])

                        pos[p_i, 0] = px_i
                        pos[p_i, 1] = py_i
                        p_i = int(nxt[p_i])

        self.last_pair_checks = pair_checks // 2

    # Stage 2B: LUT Circular Wall Collision (Zero sqrt, Zero division)
    def collide_walls_lut_q12(self):
        rx = (self.pos_q12[:, 0] - CEN_Q12).astype(np.int64)
        ry = (self.pos_q12[:, 1] - CEN_Q12).astype(np.int64)
        r2_q8 = (rx * rx + ry * ry) >> 16

        out = np.nonzero(r2_q8 > WALL_R2_Q8)[0]
        if len(out) > 0:
            lut_idx = np.clip((r2_q8[out] - WALL_R2_Q8) >> 6, 0, 63).astype(np.int32)
            inv_r_q12 = WALL_INV_R_LUT[lut_idx].astype(np.int64)

            nx_q12 = (rx[out] * inv_r_q12) >> SHIFT
            ny_q12 = (ry[out] * inv_r_q12) >> SHIFT

            self.pos_q12[out, 0] = (CEN_Q12 + ((nx_q12 * WALL_R_Q12) >> SHIFT)).astype(np.int32)
            self.pos_q12[out, 1] = (CEN_Q12 + ((ny_q12 * WALL_R_Q12) >> SHIFT)).astype(np.int32)

            vx = self.vel_q12[out, 0].astype(np.int64)
            vy = self.vel_q12[out, 1].astype(np.int64)
            vn_q12 = np.maximum((vx * nx_q12 + vy * ny_q12) >> SHIFT, 0)

            self.vel_q12[out, 0] = (vx - ((vn_q12 * nx_q12) >> SHIFT)).astype(np.int32)
            self.vel_q12[out, 1] = (vy - ((vn_q12 * ny_q12) >> SHIFT)).astype(np.int32)

    def _corners_q12(self, gx_q12, gy_q12, shape):
        max_x = ((shape[0] - 1) << SHIFT) - 1
        max_y = ((shape[1] - 1) << SHIFT) - 1
        gx = np.clip(gx_q12, 0, max_x)
        gy = np.clip(gy_q12, 0, max_y)

        i0 = gx >> SHIFT
        j0 = gy >> SHIFT
        dx = gx & (SCALE - 1)
        dy = gy & (SCALE - 1)
        om_dx = SCALE - dx
        om_dy = SCALE - dy

        idx = ((i0, j0), (i0 + 1, j0), (i0 + 1, j0 + 1), (i0, j0 + 1))
        w = (
            (om_dx * om_dy) >> SHIFT,
            (dx * om_dy) >> SHIFT,
            (dx * dy) >> SHIFT,
            (om_dx * dy) >> SHIFT,
        )
        return idx, w

    def _scatter_q12(self, total, weight, gx_q12, gy_q12, values_q12=None):
        idx, w = self._corners_q12(gx_q12, gy_q12, weight.shape)
        for (i, j), wk in zip(idx, w):
            np.add.at(weight, (i, j), wk)
            if values_q12 is not None:
                weighted_val = (values_q12.astype(np.int64) * wk) >> SHIFT
                np.add.at(total, (i, j), weighted_val.astype(np.int32))

    def _gather_q12(self, new_q12, old_q12, gx_q12, gy_q12, valid):
        idx, w = self._corners_q12(gx_q12, gy_q12, new_q12.shape)
        wsum = np.zeros(NP, dtype=np.int64)
        vnew_acc = np.zeros(NP, dtype=np.int64)
        vdelta_acc = np.zeros(NP, dtype=np.int64)

        for (i, j), wk in zip(idx, w):
            wv = (wk * valid[i, j]).astype(np.int64)
            wsum += wv
            vnew_acc += new_q12[i, j].astype(np.int64) * wv
            vdelta_acc += (new_q12[i, j] - old_q12[i, j]).astype(np.int64) * wv

        ok = wsum > 0
        safe_w = np.where(ok, wsum, 1)
        vnew_out = np.where(ok, vnew_acc // safe_w, 0).astype(np.int32)
        vdelta_out = np.where(ok, vdelta_acc // safe_w, 0).astype(np.int32)
        return vnew_out, vdelta_out, ok

    def p2g_q12(self):
        for arr in (self.u_sum_q12, self.u_weight_q12, self.v_sum_q12, self.v_weight_q12, self.density_q12):
            arr.fill(0)

        px = self.pos_q12[:, 0]
        py = self.pos_q12[:, 1]
        self._scatter_q12(self.u_sum_q12, self.u_weight_q12, px, py - HALF_CELL_Q12, self.vel_q12[:, 0])
        self._scatter_q12(self.v_sum_q12, self.v_weight_q12, px - HALF_CELL_Q12, py, self.vel_q12[:, 1])
        self._scatter_q12(None, self.density_q12, px - HALF_CELL_Q12, py - HALF_CELL_Q12)

        self.u_q12.fill(0)
        self.v_q12.fill(0)

        mu = self.u_weight_q12 > 0
        self.u_q12[mu] = ((self.u_sum_q12[mu].astype(np.int64) << SHIFT) // self.u_weight_q12[mu]).astype(np.int32)

        mv = self.v_weight_q12 > 0
        self.v_q12[mv] = ((self.v_sum_q12[mv].astype(np.int64) << SHIFT) // self.v_weight_q12[mv]).astype(np.int32)

        self.u_q12 *= self.u_open
        self.v_q12 *= self.v_open
        self.density_q12[~self.inside] = 0

        self.u_old_q12[:] = self.u_q12
        self.v_old_q12[:] = self.v_q12

    def update_cell_type_q12(self):
        self.cell_type.fill(AIR)
        self.cell_type[~self.inside] = SOLID

        self.particle_count.fill(0)
        ci = np.clip(self.pos_q12[:, 0] >> SHIFT, 0, NX - 1)
        cj = np.clip(self.pos_q12[:, 1] >> SHIFT, 0, NY - 1)
        np.add.at(self.particle_count, (ci, cj), 1)

        water = ((self.particle_count > 0) | (self.density_q12 > WATER_DENS_THS_Q12)) & self.inside
        self.cell_type[water] = WATER

        ct = np.pad(self.cell_type, 1, constant_values=SOLID)
        self.u_valid = ((ct[0:NX + 1, 1:NY + 1] != AIR) | (ct[1:NX + 2, 1:NY + 1] != AIR)).astype(np.int32)
        self.v_valid = ((ct[1:NX + 1, 0:NY + 1] != AIR) | (ct[1:NX + 1, 1:NY + 2] != AIR)).astype(np.int32)

    # Stage 4: Integer Red-Black Pressure Solver (Uses OMEGA_INV_S_LUT)
    def divergence_solve_q12(self):
        wi, wj = np.where(self.cell_type == WATER)
        if len(wi) == 0:
            self.pressure_q12.fill(0)
            self.divergence_q12.fill(0)
            return

        self.pressure_q12[self.cell_type != WATER] = 0
        red = (wi + wj) % 2 == 0
        sets = [(wi[red], wj[red]), (wi[~red], wj[~red])]

        for _ in range(self.itterations):
            for i, j in sets:
                s_idx = self.s_count[i, j]
                omega_inv_s = OMEGA_INV_S_LUT[s_idx].astype(np.int64)

                div_q12 = (
                    (self.u_q12[i + 1, j] - self.u_q12[i, j])
                    + (self.v_q12[i, j + 1] - self.v_q12[i, j])
                ).astype(np.int64)

                comp_q12 = np.maximum(
                    ((self.density_q12[i, j].astype(np.int64) * INV_REST_DENSITY_Q12) >> SHIFT) - SCALE,
                    0,
                )
                div_q12 -= DRIFT_K_INT * comp_q12

                p_q12 = ((-div_q12 * omega_inv_s) >> SHIFT).astype(np.int32)
                self.pressure_q12[i, j] += p_q12

                self.u_q12[i, j] -= p_q12 * self.sx0[i, j]
                self.u_q12[i + 1, j] += p_q12 * self.sx1[i, j]
                self.v_q12[i, j] -= p_q12 * self.sy0[i, j]
                self.v_q12[i, j + 1] += p_q12 * self.sy1[i, j]

        self.divergence_q12.fill(0)
        self.divergence_q12[wi, wj] = (
            (self.u_q12[wi + 1, wj] - self.u_q12[wi, wj])
            + (self.v_q12[wi, wj + 1] - self.v_q12[wi, wj])
        )

    def g2p_q12(self):
        px = self.pos_q12[:, 0]
        py = self.pos_q12[:, 1]

        for comp, (new, old, valid, gx, gy) in enumerate((
            (self.u_q12, self.u_old_q12, self.u_valid, px, py - HALF_CELL_Q12),
            (self.v_q12, self.v_old_q12, self.v_valid, px - HALF_CELL_Q12, py),
        )):
            vnew, vdelta, ok = self._gather_q12(new, old, gx, gy, valid)
            v_cur = self.vel_q12[:, comp].astype(np.int64)
            v_pic = np.where(ok, vnew, v_cur).astype(np.int64)
            v_flip = np.where(ok, v_cur + vdelta, v_cur).astype(np.int64)

            blended = (PIC_R_Q12 * v_pic + FLIP_R_Q12 * v_flip) >> SHIFT
            self.vel_q12[:, comp] = np.clip(blended, -VMAX_Q12, VMAX_Q12).astype(np.int32)

    def apply_stir(self, mouse_xy, mouse_vel):
        mx_q12 = int(round(mouse_xy[0] * SCALE))
        my_q12 = int(round(mouse_xy[1] * SCALE))
        mvx_q12 = int(round(mouse_vel[0] * SCALE))
        mvy_q12 = int(round(mouse_vel[1] * SCALE))

        dx = (self.pos_q12[:, 0] - mx_q12).astype(np.int64)
        dy = (self.pos_q12[:, 1] - my_q12).astype(np.int64)
        d2_q12 = (dx * dx + dy * dy) >> SHIFT
        near = d2_q12 < (6 * SCALE)
        if np.any(near):
            w_q12 = np.maximum(SCALE - (d2_q12[near] // 6), 0)
            self.vel_q12[near, 0] += (((mvx_q12 - self.vel_q12[near, 0]) * w_q12) >> (SHIFT + 1)).astype(np.int32)
            self.vel_q12[near, 1] += (((mvy_q12 - self.vel_q12[near, 1]) * w_q12) >> (SHIFT + 1)).astype(np.int32)

    def apply_shake(self, frame_idx=1):
        rng = np.random.default_rng(frame_idx * 977 + 1)
        jitter = rng.integers(-15 * SCALE, 15 * SCALE, size=(NP, 2), dtype=np.int32)
        self.vel_q12 = np.clip(self.vel_q12 + jitter, -VMAX_Q12, VMAX_Q12)

    def update(
        self,
        gx_8bit=0,
        gy_8bit=-60,
        stir_pos=None,
        stir_vel=None,
        shake=False,
        frame_idx=1,
        lis_sleep_state=False,
    ):
        accel_changed = (
            abs(int(gx_8bit) - self._last_gx) > 1
            or abs(int(gy_8bit) - self._last_gy) > 1
        )
        self._last_gx = int(gx_8bit)
        self._last_gy = int(gy_8bit)

        if accel_changed or stir_pos is not None or shake:
            self.clock_gated_sleep = False
            self.sleep_Hold_frames = 0

        if self.clock_gated_sleep:
            self.last_pair_checks = 0
            return

        prev_pos = self.pos_q12.copy()

        self.apply_gravity_and_advect_q12(gx_8bit, gy_8bit)
        if stir_pos is not None and stir_vel is not None:
            self.apply_stir(stir_pos, stir_vel)
        if shake:
            self.apply_shake(frame_idx)

        self.push_apart_spatial_hash_q12()
        self.collide_walls_lut_q12()
        self.p2g_q12()
        self.update_cell_type_q12()
        self.divergence_solve_q12()
        self.g2p_q12()

        mean_pos_delta = int(np.abs(self.pos_q12 - prev_pos).mean())
        if (mean_pos_delta < 32 or lis_sleep_state) and not accel_changed and stir_pos is None and not shake:
            self.sleep_Hold_frames += 1
            if self.sleep_Hold_frames >= 90:
                self.clock_gated_sleep = True
        else:
            self.sleep_Hold_frames = 0

        self._sync_views_and_ram()

for _ref_name in ("simulation_fixed", "sim_hardware_model"):
    sys.modules.setdefault(_ref_name, sys.modules[__name__])

PARTICLE_FIELDS = ("pos_x", "pos_y", "vel_x", "vel_y")
SCENARIOS = {
    "dense_cluster": (35, -60),
    "wall_mixed": (-35, 60),
    "four_clusters": (60, 0),
}

def grid_points(side, spacing, cx, cy):
    start = -(side - 1) / 2.0
    return [(cx + (start + c) * spacing, cy + (start + r) * spacing)
            for r in range(side) for c in range(side)]

def make_case(model, scenario, seed):
    model.reset(seed=seed)
    if scenario == "dense_cluster":
        pts = grid_points(16, 0.10, 8.5, 8.5)
        model.pos_q12 = np.rint(np.asarray(pts) * SCALE).astype(np.int32)
        vel = np.zeros((NP, 2), dtype=np.int32)
        for i in range(NP):
            vel[i, 0] = ((i % 5) - 2) * 96
            vel[i, 1] = (((i // 5) % 5) - 2) * 96
        model.vel_q12 = vel
    elif scenario == "four_clusters":
        centers = ((5.5, 5.5), (10.5, 5.5), (5.5, 10.5), (10.5, 10.5))
        pts = []
        for cx, cy in centers:
            pts.extend(grid_points(8, 0.12, cx, cy))
        model.pos_q12 = np.rint(np.asarray(pts) * SCALE).astype(np.int32)
        vel = np.zeros((NP, 2), dtype=np.int32)
        for i in range(NP):
            vel[i, 0] = ((i % 7) - 3) * 64
            vel[i, 1] = (((i // 7) % 7) - 3) * 64
        model.vel_q12 = vel
    elif scenario == "wall_mixed":
        pos = model.pos_q12.copy()
        vel = model.vel_q12.copy()
        for i in range(16):
            angle = 2 * math.pi * i / 16 + math.pi / 32
            nx, ny = math.cos(angle), math.sin(angle)
            speed = 8.0 if i % 2 == 0 else -8.0
            pos[i, 0] = round(CEN_Q12 + 7.68 * SCALE * nx)
            pos[i, 1] = round(CEN_Q12 + 7.68 * SCALE * ny)
            vel[i, 0] = round(speed * SCALE * nx)
            vel[i, 1] = round(speed * SCALE * ny)
        for j in range(16, 24):
            angle = 2 * math.pi * (j - 16) / 8 + math.pi / 16
            nx, ny = math.cos(angle), math.sin(angle)
            pos[j, 0] = round(CEN_Q12 + 7.60 * SCALE * nx)
            pos[j, 1] = round(CEN_Q12 + 7.60 * SCALE * ny)
            vel[j, 0] = round(-5.0 * SCALE * ny)
            vel[j, 1] = round(5.0 * SCALE * nx)
        model.pos_q12, model.vel_q12 = pos, vel
    else:
        raise ValueError("unknown scenario: " + scenario)

def write_particles(path, pos, vel):
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(("index",) + PARTICLE_FIELDS)
        for i in range(NP):
            writer.writerow((i, int(pos[i, 0]), int(pos[i, 1]),
                             int(vel[i, 0]), int(vel[i, 1])))

def generate_vectors(scenario, seed, gx, gy, frames, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    model = HardwareFlip()
    make_case(model, scenario, seed)
    write_particles(out_dir / "input_particles.csv", model.pos_q12, model.vel_q12)
    for frame in range(1, frames + 1):
        model.update(gx_8bit=gx, gy_8bit=gy, frame_idx=frame)
        write_particles(out_dir / ("expected_frame_%d.csv" % frame),
                        model.pos_q12, model.vel_q12)
    write_particles(out_dir / "expected_particles.csv", model.pos_q12, model.vel_q12)
    print("Generated %s: %d frames, seed=%d, gx=%d, gy=%d." %
          (scenario, frames, seed, gx, gy))

def compare_results(expected_path, actual_path):
    def load(path):
        with path.open(newline="") as f:
            rows = list(csv.DictReader(f))
        values = {}
        for row in rows:
            idx = int(row["index"])
            if idx in values:
                raise ValueError("duplicate particle index %d in %s" % (idx, path))
            values[idx] = {field: int(row[field]) for field in PARTICLE_FIELDS}
        if set(values) != set(range(NP)):
            raise ValueError("%s must contain particle indices 0..255" % path)
        return values
    expected, actual = load(expected_path), load(actual_path)
    mismatches, max_abs = [], 0
    for i in range(NP):
        for field in PARTICLE_FIELDS:
            e, a = expected[i][field], actual[i][field]
            delta = a - e
            max_abs = max(max_abs, abs(delta))
            if delta:
                mismatches.append((i, field, e, a, delta))
    if not mismatches:
        print("PASS: exact match for all 256 particles x 4 fields (1024 values).")
        print("Maximum absolute error: 0 Q4.12 LSBs.")
        return True
    print("FAIL: %d / 1024 values differ; max error %d Q4.12 LSBs." %
          (len(mismatches), max_abs))
    for item in mismatches[:20]:
        print("  particle, field, expected, actual, delta:", *item)
    return False

def export_verilog(path, export_system=False):
    from amaranth import ClockDomain, ClockSignal, Elaboratable, Module, ResetSignal
    from amaranth.back import verilog

    class ExportTop(Elaboratable):
        def __init__(self):
            self.core = FLIPPipeline(particle_memory_backend="sram")
        def elaborate(self, platform):
            m = Module()
            m.domains.sync = ClockDomain("sync")
            m.submodules.core = self.core
            return m

    top = ExportTop()
    dut = top.core
    ports = [
        ClockSignal("sync"), ResetSignal("sync"),
        dut.start, dut.gx, dut.gy, dut.busy, dut.done, dut.stage,
        dut.velocity_overflow,
        dut.sram_en, dut.sram_we, dut.sram_addr, dut.sram_wdata, dut.sram_rdata,
        dut.host_ready,
        dut.host_write_req, dut.host_write_addr,
        dut.host_write_pos_x, dut.host_write_pos_y,
        dut.host_write_vel_x, dut.host_write_vel_y,
        dut.host_read_req, dut.host_read_addr, dut.host_read_valid,
        dut.host_read_pos_x, dut.host_read_pos_y,
        dut.host_read_vel_x, dut.host_read_vel_y,
        dut.p2g_cycle_count, dut.pressure_iteration_index,
        dut.g2p_processed_count,
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(verilog.convert(top, name="FLIPPipeline", ports=ports))
    print("Exported %s (%s bytes)." % (path, format(path.stat().st_size, ",")))

    if export_system:
        class ExportSystemTop(Elaboratable):
            def __init__(self):
                self.sys = PendantSystemTop(particle_memory_backend="sram")
            def elaborate(self, platform):
                m = Module()
                m.domains.sync = ClockDomain("sync")
                m.submodules.sys = self.sys
                return m

        sys_top = ExportSystemTop()
        s = sys_top.sys
        sys_ports = [
            ClockSignal("sync"), ResetSignal("sync"),
            s.frame_sync, s.lis_int2_sleep, s.clock_gated_sleep, s.sleep_hold_frames,
            s.i2c_scl_o, s.i2c_scl_oe, s.i2c_sda_i, s.i2c_sda_o, s.i2c_sda_oe,
            s.core.sram_en, s.core.sram_we, s.core.sram_addr, s.core.sram_wdata, s.core.sram_rdata,
            s.core.busy, s.core.done, s.core.stage,
        ]
        sys_path = path.parent / "PendantSystemTop.v"
        sys_path.write_text(verilog.convert(sys_top, name="PendantSystemTop", ports=sys_ports))
        print("Exported %s (%s bytes)." % (sys_path, format(sys_path.stat().st_size, ",")))

        class ExportTTUmTop(Elaboratable):
            def __init__(self):
                self.ui_in = Signal(8, name="ui_in")
                self.uo_out = Signal(8, name="uo_out")
                self.uio_in = Signal(8, name="uio_in")
                self.uio_out = Signal(8, name="uio_out")
                self.uio_oe = Signal(8, name="uio_oe")
                self.ena = Signal(name="ena")
                self.clk = Signal(name="clk")
                self.rst_n = Signal(name="rst_n")
                self.tt = TTUmFlipPendant()

            def elaborate(self, platform):
                m = Module()
                m.domains.sync = ClockDomain("sync", local=True)
                m.submodules.tt = self.tt
                m.d.comb += [
                    ClockSignal("sync").eq(self.clk),
                    ResetSignal("sync").eq(~self.rst_n),
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
            tt_top.ena, tt_top.clk, tt_top.rst_n,
        ]
        tt_v = verilog.convert(tt_top, name="tt_um_flip_pendant", ports=tt_ports)
        tt_path = path.parent / "project.v"
        tt_path.write_text(tt_v)
        print("Exported %s (%s bytes)." % (tt_path, format(tt_path.stat().st_size, ",")))

CPP_TESTBENCH = r"""#include "VFLIPPipeline.h"
#include "verilated.h"

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

namespace {
constexpr unsigned PARTICLES = 256;
constexpr std::size_t SRAM_WORDS = 1024;
constexpr std::uint64_t MAX_CHAIN_CYCLES = 1'200'000;
#ifndef FRAME_COUNT
#define FRAME_COUNT 3
#endif
struct Particle { std::int32_t px, py, vx, vy; };

std::uint32_t mask20(std::int32_t value) {
    return static_cast<std::uint32_t>(value) & 0xFFFFFu;
}
std::int32_t signed20(std::uint32_t value) {
    value &= 0xFFFFFu;
    if (value & 0x80000u) value |= 0xFFF00000u;
    return static_cast<std::int32_t>(value);
}

bool load_particles(const std::string& path, std::array<Particle, PARTICLES>& particles) {
    std::ifstream in(path);
    if (!in) { std::cerr << "ERROR: cannot open input CSV: " << path << '\n'; return false; }
    std::string line;
    if (!std::getline(in, line)) return false; // header
    std::array<bool, PARTICLES> seen{};
    while (std::getline(in, line)) {
        if (line.empty()) continue;
        std::replace(line.begin(), line.end(), ',', ' ');
        std::istringstream row(line);
        unsigned index; Particle p{};
        if (!(row >> index >> p.px >> p.py >> p.vx >> p.vy) || index >= PARTICLES || seen[index]) {
            std::cerr << "ERROR: malformed/duplicate particle row: " << line << '\n'; return false;
        }
        particles[index] = p; seen[index] = true;
    }
    for (unsigned i = 0; i < PARTICLES; ++i) if (!seen[i]) {
        std::cerr << "ERROR: missing particle " << i << '\n'; return false;
    }
    return true;
}

void tick(VFLIPPipeline& dut, std::array<std::uint32_t, SRAM_WORDS>& sram) {
    dut.clk = 0; dut.eval();
    const bool en = dut.sram_en, we = dut.sram_we;
    const std::uint32_t addr = dut.sram_addr, wdata = dut.sram_wdata;
    if (en && addr >= SRAM_WORDS) {
        std::cerr << "ERROR: SRAM address out of range: " << addr << '\n'; std::exit(2);
    }
    dut.clk = 1; dut.eval();
    if (en) {
        if (we) sram[addr] = wdata;
        else dut.sram_rdata = sram[addr];
    }
    dut.eval(); dut.clk = 0; dut.eval();
}

bool wait_ready(VFLIPPipeline& dut, std::array<std::uint32_t, SRAM_WORDS>& sram,
                unsigned limit, const std::string& where) {
    for (unsigned i = 0; i < limit; ++i) {
        if (dut.host_ready) return true;
        tick(dut, sram);
    }
    std::cerr << "ERROR: host_ready timeout at " << where << " stage="
              << unsigned(dut.stage) << '\n'; return false;
}

bool host_write(VFLIPPipeline& dut, std::array<std::uint32_t, SRAM_WORDS>& sram,
                unsigned index, const Particle& p) {
    if (!wait_ready(dut, sram, 100, "before write")) return false;
    dut.host_write_addr = index;
    dut.host_write_pos_x = mask20(p.px); dut.host_write_pos_y = mask20(p.py);
    dut.host_write_vel_x = mask20(p.vx); dut.host_write_vel_y = mask20(p.vy);
    dut.host_write_req = 1; tick(dut, sram); dut.host_write_req = 0;
    if (!wait_ready(dut, sram, 100, "write commit")) return false;
    const unsigned b = index * 4;
    if (sram[b] != mask20(p.px) || sram[b+1] != mask20(p.py) ||
        sram[b+2] != mask20(p.vx) || sram[b+3] != mask20(p.vy)) {
        std::cerr << "ERROR: SRAM initialization mismatch at particle " << index << '\n';
        return false;
    }
    return true;
}

bool host_read(VFLIPPipeline& dut, std::array<std::uint32_t, SRAM_WORDS>& sram,
               unsigned index, Particle& p) {
    if (!wait_ready(dut, sram, 100, "before read")) return false;
    dut.host_read_addr = index; dut.host_read_req = 1;
    tick(dut, sram); dut.host_read_req = 0;
    for (unsigned i = 0; i < 100; ++i) {
        if (dut.host_read_valid) {
            p = {signed20(dut.host_read_pos_x), signed20(dut.host_read_pos_y),
                 signed20(dut.host_read_vel_x), signed20(dut.host_read_vel_y)};
            return true;
        }
        tick(dut, sram);
    }
    std::cerr << "ERROR: host_read_valid timeout for particle " << index << '\n';
    return false;
}
}

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    if (argc != 5) {
        std::cerr << "Usage: " << argv[0] << " input_particles.csv actual_particles.csv gx gy\n";
        return 2;
    }
    const int gx = std::stoi(argv[3]), gy = std::stoi(argv[4]);
    if (gx < -128 || gx > 127 || gy < -128 || gy > 127) return 2;
    std::array<Particle, PARTICLES> input{};
    if (!load_particles(argv[1], input)) return 2;

    VFLIPPipeline dut;
    std::array<std::uint32_t, SRAM_WORDS> sram{};
    dut.clk = 0; dut.rst = 1; dut.start = 0; dut.gx = gx; dut.gy = gy;
    dut.sram_rdata = 0; dut.host_write_req = 0; dut.host_write_addr = 0;
    dut.host_write_pos_x = 0; dut.host_write_pos_y = 0;
    dut.host_write_vel_x = 0; dut.host_write_vel_y = 0;
    dut.host_read_req = 0; dut.host_read_addr = 0;
    for (int i = 0; i < 5; ++i) tick(dut, sram);
    dut.rst = 0; for (int i = 0; i < 3; ++i) tick(dut, sram);

    std::cout << "[1/4] Loading all 256 input particles into SRAM...\n";
    for (unsigned i = 0; i < PARTICLES; ++i) {
        if (!host_write(dut, sram, i, input[i])) return 1;
    }
    std::cout << "      All 256 particles initialized and verified.\n";

    std::cout << "[2/4] Running " << FRAME_COUNT << " consecutive frames (SRAM is NOT reloaded)...\n";
    for (unsigned frame = 1; frame <= FRAME_COUNT; ++frame) {
        if (dut.busy) {
            std::cerr << "ERROR: DUT busy before frame " << frame << " start.\n";
            return 1;
        }
        dut.start = 1; tick(dut, sram); dut.start = 0;
        bool completed = false; std::uint64_t cycles = 0;
        for (; cycles < MAX_CHAIN_CYCLES; ++cycles) {
            tick(dut, sram);
            if (dut.done) { completed = true; ++cycles; break; }
        }
        if (!completed) {
            std::cerr << "ERROR: frame " << frame << " timeout after " << cycles
                      << " cycles; stage=" << unsigned(dut.stage)
                      << " pressure_iteration=" << unsigned(dut.pressure_iteration_index)
                      << " g2p_processed=" << unsigned(dut.g2p_processed_count) << '\n';
            return 1;
        }
        if (dut.busy || dut.g2p_processed_count != PARTICLES) {
            std::cerr << "ERROR: frame " << frame << " completion invalid; busy="
                      << unsigned(dut.busy) << " g2p_processed="
                      << unsigned(dut.g2p_processed_count) << '\n';
            return 1;
        }
        std::cout << "      Frame " << frame << " completed in " << cycles
                  << " cycles; all 256 particles processed.\n";
    }

    std::cout << "[3/4] Reading all 256 particles back from SRAM...\n";
    std::ofstream out(argv[2]);
    if (!out) { std::cerr << "ERROR: cannot create output CSV.\n"; return 2; }
    out << "index,pos_x,pos_y,vel_x,vel_y\n";
    for (unsigned i = 0; i < PARTICLES; ++i) {
        Particle p{};
        if (!host_read(dut, sram, i, p)) return 1;
        out << i << ',' << p.px << ',' << p.py << ',' << p.vx << ',' << p.vy << '\n';
    }
    out.close();
    std::cout << "      Readback saved to " << argv[2] << '\n';
    std::cout << "[4/4] PASS: exported RTL completed consecutive frames and returned the full particle state.\n";
    dut.final(); return 0;
}
"""

def run(args):
    root = Path.cwd()
    build = args.build_dir
    build.mkdir(parents=True, exist_ok=True)
    rtl = build / "FLIPPipeline.v"
    export_verilog(rtl, export_system=args.export_only)
    if args.export_only:
        return 0
    cpp = build / "tb_multiframe.cpp"
    cpp.write_text(CPP_TESTBENCH)
    obj = build / "verilator_obj"
    obj.mkdir(parents=True, exist_ok=True)
    cmd = [
        "verilator", "--cc", "--exe", "--build", "--top-module", "FLIPPipeline",
        "--Mdir", str(obj), "-j", "0", "-Wno-fatal", "-Wno-CASEINCOMPLETE",
        "-CFLAGS", "-std=c++17 -O2 -DFRAME_COUNT=%d" % args.frames,
        str(rtl.resolve()), str(cpp.resolve()),
    ]
    print("[build] " + " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)
    exe = obj / "VFLIPPipeline"
    all_ok = True
    for scenario in args.scenarios:
        gx, gy = SCENARIOS[scenario]
        out = build / scenario
        generate_vectors(scenario, args.seed, gx, gy, args.frames, out)
        actual = out / "actual_particles.csv"
        print("[RTL] %s: %d frames, gx=%d gy=%d" %
              (scenario, args.frames, gx, gy), flush=True)
        subprocess.run([str(exe.resolve()), str((out / "input_particles.csv").resolve()),
                        str(actual.resolve()), str(gx), str(gy)], check=True)
        all_ok = compare_results(out / "expected_particles.csv", actual) and all_ok
    if all_ok:
        print("PASS: all selected multi-frame stress configurations matched the Python reference.")
        return 0
    return 1

def main():
    parser = argparse.ArgumentParser(description="FLIP RTL testbench runner")
    parser.add_argument("--frames", type=int, default=10, help="consecutive frames (2..10)")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--scenario", choices=("all",) + tuple(SCENARIOS), default="all")
    parser.add_argument("--build-dir", type=Path, default=Path("build/standalone_tb"))
    parser.add_argument("--export-only", action="store_true",
                        help="only export the SRAM-backed RTL; do not invoke Verilator")
    args = parser.parse_args()
    if not 2 <= args.frames <= 10:
        parser.error("--frames must be between 2 and 10")
    args.scenarios = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    try:
        return run(args)
    except subprocess.CalledProcessError as exc:
        print("ERROR: external command failed:", exc, file=sys.stderr)
        return exc.returncode or 1

if __name__ == "__main__":
    raise SystemExit(main())
