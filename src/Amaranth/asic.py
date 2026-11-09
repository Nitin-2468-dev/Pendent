# asic.py - 2D FLIP Fluid Simulation ASIC for Tiny Tapeout
# My first ASIC design using Amaranth HDL!
#
# Hardware peripherals on the pendant PCB:
#   - ESP-PSRAM64H (QPI PSRAM at 12.5 MHz) for storing particles & 16x16 grid
#   - LIS2DW12 accelerometer (I2C 0x18/0x19) for gravity tilt (gx, gy) + sleep wake
#   - IS31FL3741A 216-LED matrix driver (I2C 0x30) for rendering water density

from amaranth import Cat, Const, Elaboratable, Module, Mux, Signal, signed, unsigned

SHIFT = 12
SCALE = 1 << SHIFT          # 4096 (Q4.12 fixed-point)
HALF_CELL = 1 << (SHIFT - 1)

NX = 16
NY = 16
NP = 256
CELL_COUNT = NX * NY

CEN_Q12 = 8 << SHIFT        # 8.0 cells (container center)
WALL_R_Q12 = 31744          # 7.75 cells (container radius)
MIN_DIST_Q12 = 2458         # 0.60 cells (particle push-apart distance)
VMAX_Q12 = 40 << SHIFT      # max velocity clamp
WATER_THS_Q12 = 969         # water density threshold
REST_DENS_Q12 = 9695        # rest density in Q4.12


def inside_circle(x4, y4):
    """8-gate symmetry check for (2x - 15)^2 + (2y - 15)^2 < 280 on a 16x16 grid."""
    fx = Mux(x4[3], (~x4[:3]) & 0x7, x4[:3])
    fy = Mux(y4[3], (~y4[:3]) & 0x7, y4[:3])
    return (fx + fy) >= 4


class PsramController(Elaboratable):
    """Compact 32-bit word QPI PSRAM controller for ESP-PSRAM64H.

    Handles power-up, SPI init commands (0x66 -> CE# high -> 0x99 -> CE# high -> 0x35),
    and 32-bit word reads (0xEB) / writes (0x02) at 4-byte aligned addresses.
    """
    ST_BOOT_WAIT = 0
    ST_SPI_CMD   = 1
    ST_SPI_GAP   = 2
    ST_IDLE      = 3
    ST_QPI_SHIFT = 4
    ST_QPI_DUMMY = 5
    ST_QPI_READ  = 6
    ST_DONE      = 7

    def __init__(self, sys_clk_hz=25_000_000, qpi_clk_hz=12_500_000):
        # Short power-up wait for hardware; still initializes cleanly after reset
        self.boot_cycles = max(16, sys_clk_hz // 10_000)

        self.req = Signal()
        self.we = Signal()
        self.addr = Signal(13)       # 8192 words (32 KB) is plenty for our 18 KB map
        self.wdata = Signal(32)
        self.rdata = Signal(32)
        self.ready = Signal()
        self.done = Signal()
        self.rvalid = Signal()
        self.init_done = Signal()
        self.busy = Signal(init=1)
        self.error = Signal()

        # External QPI pins + level shifter control
        self.sclk = Signal()
        self.ce_n = Signal(init=1)
        self.dq_i = Signal(4)
        self.dq_o = Signal(4)
        self.dq_oe = Signal(4)
        self.translator_dir = Signal()
        self.translator_oe_n = Signal(4, init=0b1111)

    def elaborate(self, platform):
        m = Module()

        state = Signal(3, init=self.ST_BOOT_WAIT)
        timer = Signal(range(self.boot_cycles + 1))
        init_step = Signal(2)
        bit_cnt = Signal(4)
        qpi_clk = Signal()
        we_lat = Signal()
        shifter = Signal(64)
        spi_byte = Signal(8)

        active_bus = (
            (state == self.ST_SPI_CMD)
            | (state == self.ST_QPI_SHIFT)
            | (state == self.ST_QPI_DUMMY)
            | (state == self.ST_QPI_READ)
        )

        driving_qpi = (state == self.ST_QPI_SHIFT)
        driving_spi = (state == self.ST_SPI_CMD)
        driving_boot = (state == self.ST_BOOT_WAIT)

        m.d.comb += [
            self.sclk.eq(qpi_clk),
            self.ce_n.eq(~active_bus),
            self.ready.eq((state == self.ST_IDLE) & self.init_done),
            self.busy.eq(state != self.ST_IDLE),
            self.error.eq(0),

            self.dq_o.eq(
                Mux(driving_spi, Cat(spi_byte[7], Const(0, 3)),
                    Mux(driving_qpi, shifter[60:64], 0))
            ),
            self.dq_oe.eq(
                Mux(driving_boot | driving_qpi, 0b1111,
                    Mux(driving_spi, 0b0001, 0b0000))
            ),
            self.translator_dir.eq(self.dq_oe != 0),
            self.translator_oe_n.eq(
                Mux(self.dq_oe != 0, ~self.dq_oe,
                    Mux(state == self.ST_QPI_READ, 0b0000, 0b1111))
            ),
        ]

        m.d.sync += [self.done.eq(0), self.rvalid.eq(0)]

        with m.Switch(state):
            with m.Case(self.ST_BOOT_WAIT):
                with m.If(timer == self.boot_cycles - 1):
                    m.d.sync += [
                        timer.eq(0),
                        spi_byte.eq(0x66),
                        bit_cnt.eq(0),
                        init_step.eq(0),
                        qpi_clk.eq(0),
                        state.eq(self.ST_SPI_CMD),
                    ]
                with m.Else():
                    m.d.sync += timer.eq(timer + 1)

            with m.Case(self.ST_SPI_CMD):
                with m.If(~qpi_clk):
                    m.d.sync += qpi_clk.eq(1)
                with m.Else():
                    m.d.sync += qpi_clk.eq(0)
                    with m.If(bit_cnt == 7):
                        # Pulse CE# high in ST_SPI_GAP after every SPI command (0x66, 0x99, 0x35)
                        m.d.sync += [bit_cnt.eq(0), timer.eq(0), state.eq(self.ST_SPI_GAP)]
                    with m.Else():
                        m.d.sync += [
                            spi_byte.eq(Cat(Const(0, 1), spi_byte[:7])),
                            bit_cnt.eq(bit_cnt + 1),
                        ]

            with m.Case(self.ST_SPI_GAP):
                with m.If(timer == 3):
                    m.d.sync += timer.eq(0)
                    with m.If(init_step == 0):
                        m.d.sync += [
                            spi_byte.eq(0x99),
                            bit_cnt.eq(0),
                            init_step.eq(1),
                            state.eq(self.ST_SPI_CMD),
                        ]
                    with m.Elif(init_step == 1):
                        m.d.sync += [
                            spi_byte.eq(0x35),
                            bit_cnt.eq(0),
                            init_step.eq(2),
                            state.eq(self.ST_SPI_CMD),
                        ]
                    with m.Else():
                        m.d.sync += [self.init_done.eq(1), state.eq(self.ST_IDLE)]
                with m.Else():
                    m.d.sync += timer.eq(timer + 1)

            with m.Case(self.ST_IDLE):
                m.d.sync += qpi_clk.eq(0)
                with m.If(self.req & self.init_done):
                    cmd = Mux(self.we, Const(0x02, 8), Const(0xEB, 8))
                    byte_addr = Cat(Const(0, 2), self.addr, Const(0, 9))
                    m.d.sync += [
                        we_lat.eq(self.we),
                        shifter.eq(Cat(self.wdata, byte_addr, cmd)),
                        bit_cnt.eq(0),
                        state.eq(self.ST_QPI_SHIFT),
                    ]

            with m.Case(self.ST_QPI_SHIFT):
                last_nibble = Mux(we_lat, Const(15, 4), Const(7, 4))
                with m.If(~qpi_clk):
                    m.d.sync += qpi_clk.eq(1)
                with m.Else():
                    m.d.sync += [
                        qpi_clk.eq(0),
                        shifter.eq(Cat(Const(0, 4), shifter[:60])),
                    ]
                    with m.If(bit_cnt == last_nibble):
                        m.d.sync += bit_cnt.eq(0)
                        with m.If(we_lat):
                            m.d.sync += state.eq(self.ST_DONE)
                        with m.Else():
                            m.d.sync += state.eq(self.ST_QPI_DUMMY)
                    with m.Else():
                        m.d.sync += bit_cnt.eq(bit_cnt + 1)

            with m.Case(self.ST_QPI_DUMMY):
                with m.If(~qpi_clk):
                    m.d.sync += qpi_clk.eq(1)
                with m.Else():
                    m.d.sync += qpi_clk.eq(0)
                    with m.If(bit_cnt == 5):
                        m.d.sync += [bit_cnt.eq(0), state.eq(self.ST_QPI_READ)]
                    with m.Else():
                        m.d.sync += bit_cnt.eq(bit_cnt + 1)

            with m.Case(self.ST_QPI_READ):
                with m.If(~qpi_clk):
                    # Shift incoming QPI nibbles MSB-first so readback matches write order
                    m.d.sync += [
                        qpi_clk.eq(1),
                        self.rdata.eq(Cat(self.dq_i, self.rdata[:28])),
                    ]
                with m.Else():
                    m.d.sync += qpi_clk.eq(0)
                    with m.If(bit_cnt == 7):
                        m.d.sync += [self.rvalid.eq(1), state.eq(self.ST_DONE)]
                    with m.Else():
                        m.d.sync += bit_cnt.eq(bit_cnt + 1)

            with m.Case(self.ST_DONE):
                m.d.sync += [self.done.eq(1), state.eq(self.ST_IDLE)]

        return m


class I2CMaster(Elaboratable):
    """Simple 400 kHz open-drain I2C master for LIS2DW12 and IS31FL3741A."""
    ST_IDLE    = 0
    ST_START_A = 1
    ST_START_B = 2
    ST_BIT_LOW = 3
    ST_BIT_HI  = 4
    ST_ACK_LOW = 5
    ST_ACK_HI  = 6
    ST_HOLD    = 7
    ST_STOP_A  = 8
    ST_STOP_B  = 9

    def __init__(self, sys_clk_hz=25_000_000, i2c_clk_hz=400_000):
        self.q_cycles = max(1, sys_clk_hz // (4 * i2c_clk_hz))

        self.cmd_start = Signal()
        self.cmd_stop = Signal()
        self.cmd_write = Signal()
        self.cmd_read = Signal()
        self.cmd_valid = Signal()
        self.cmd_ready = Signal()
        self.tx_data = Signal(8)
        self.tx_ack = Signal()

        self.rx_data = Signal(8)
        self.rx_valid = Signal()
        self.ack_error = Signal()
        self.busy = Signal()

        self.scl_o = Signal(init=0)
        self.scl_oe = Signal(init=0)
        self.sda_i = Signal(init=1)
        self.sda_o = Signal(init=0)
        self.sda_oe = Signal(init=0)

    def elaborate(self, platform):
        m = Module()

        state = Signal(4, init=self.ST_IDLE)
        timer = Signal(range(self.q_cycles + 1))
        bit_idx = Signal(3)
        shifter = Signal(8)
        is_read = Signal()
        send_ack = Signal()
        scl_high = Signal(init=1)
        sda_high = Signal(init=1)

        tick = timer == (self.q_cycles - 1)

        m.d.comb += [
            self.scl_o.eq(0),
            self.scl_oe.eq(~scl_high),
            self.sda_o.eq(0),
            self.sda_oe.eq(~sda_high),
            self.cmd_ready.eq((state == self.ST_IDLE) | (state == self.ST_HOLD)),
            self.busy.eq(state != self.ST_IDLE),
        ]

        m.d.sync += self.rx_valid.eq(0)

        with m.Switch(state):
            with m.Case(self.ST_IDLE, self.ST_HOLD):
                with m.If(self.cmd_valid):
                    m.d.sync += timer.eq(0)
                    with m.If(self.cmd_start):
                        m.d.sync += [
                            sda_high.eq(1), scl_high.eq(1),
                            self.ack_error.eq(0), state.eq(self.ST_START_A),
                        ]
                    with m.Elif(self.cmd_stop):
                        m.d.sync += [sda_high.eq(0), scl_high.eq(0), state.eq(self.ST_STOP_A)]
                    with m.Elif(self.cmd_write):
                        m.d.sync += [
                            shifter.eq(self.tx_data), bit_idx.eq(7), is_read.eq(0),
                            scl_high.eq(0), sda_high.eq(self.tx_data[7]), state.eq(self.ST_BIT_LOW),
                        ]
                    with m.Elif(self.cmd_read):
                        m.d.sync += [
                            bit_idx.eq(7), is_read.eq(1), send_ack.eq(self.tx_ack),
                            scl_high.eq(0), sda_high.eq(1), state.eq(self.ST_BIT_LOW),
                        ]

            with m.Case(self.ST_START_A):
                with m.If(tick):
                    m.d.sync += [timer.eq(0), sda_high.eq(0), state.eq(self.ST_START_B)]
                with m.Else():
                    m.d.sync += timer.eq(timer + 1)

            with m.Case(self.ST_START_B):
                with m.If(tick):
                    m.d.sync += [timer.eq(0), scl_high.eq(0), state.eq(self.ST_HOLD)]
                with m.Else():
                    m.d.sync += timer.eq(timer + 1)

            with m.Case(self.ST_BIT_LOW):
                with m.If(tick):
                    m.d.sync += [timer.eq(0), scl_high.eq(1), state.eq(self.ST_BIT_HI)]
                with m.Else():
                    m.d.sync += timer.eq(timer + 1)

            with m.Case(self.ST_BIT_HI):
                with m.If(tick):
                    next_shift = Cat(self.sda_i, shifter[:7])
                    m.d.sync += [timer.eq(0), scl_high.eq(0)]
                    with m.If(is_read):
                        m.d.sync += shifter.eq(next_shift)
                    with m.If(bit_idx == 0):
                        with m.If(is_read):
                            m.d.sync += [
                                self.rx_data.eq(next_shift),
                                self.rx_valid.eq(1),
                                sda_high.eq(~send_ack),
                            ]
                        with m.Else():
                            m.d.sync += sda_high.eq(1)
                        m.d.sync += state.eq(self.ST_ACK_LOW)
                    with m.Else():
                        m.d.sync += bit_idx.eq(bit_idx - 1)
                        with m.If(is_read):
                            m.d.sync += sda_high.eq(1)
                        with m.Else():
                            m.d.sync += [
                                sda_high.eq(shifter[6]),
                                shifter.eq(Cat(Const(0, 1), shifter[:7])),
                            ]
                        m.d.sync += state.eq(self.ST_BIT_LOW)
                with m.Else():
                    m.d.sync += timer.eq(timer + 1)

            with m.Case(self.ST_ACK_LOW):
                with m.If(tick):
                    m.d.sync += [timer.eq(0), scl_high.eq(1), state.eq(self.ST_ACK_HI)]
                with m.Else():
                    m.d.sync += timer.eq(timer + 1)

            with m.Case(self.ST_ACK_HI):
                with m.If(tick):
                    with m.If(~is_read & self.sda_i):
                        m.d.sync += self.ack_error.eq(1)
                    m.d.sync += [timer.eq(0), scl_high.eq(0), state.eq(self.ST_HOLD)]
                with m.Else():
                    m.d.sync += timer.eq(timer + 1)

            with m.Case(self.ST_STOP_A):
                with m.If(tick):
                    m.d.sync += [timer.eq(0), scl_high.eq(1), state.eq(self.ST_STOP_B)]
                with m.Else():
                    m.d.sync += timer.eq(timer + 1)

            with m.Case(self.ST_STOP_B):
                with m.If(tick):
                    m.d.sync += [timer.eq(0), sda_high.eq(1), state.eq(self.ST_IDLE)]
                with m.Else():
                    m.d.sync += timer.eq(timer + 1)

        return m


class LIS2DW12Controller(Elaboratable):
    """Configures LIS2DW12 accelerometer (0x18/0x19 via SA0) and polls X/Y gravity tilt."""
    def __init__(self):
        self.sa0 = Signal(init=1)
        self.init_req = Signal()
        self.poll_req = Signal()
        self.busy = Signal()
        self.done = Signal()
        self.gx = Signal(signed(8))
        self.gy = Signal(signed(8), init=-60)

        self.i2c_cmd_start = Signal()
        self.i2c_cmd_stop = Signal()
        self.i2c_cmd_write = Signal()
        self.i2c_cmd_read = Signal()
        self.i2c_cmd_valid = Signal()
        self.i2c_cmd_ready = Signal()
        self.i2c_tx_data = Signal(8)
        self.i2c_tx_ack = Signal()
        self.i2c_rx_data = Signal(8)
        self.i2c_rx_valid = Signal()

    def elaborate(self, platform):
        m = Module()

        state = Signal(2, init=0)
        sub_step = Signal(4)

        # 7-bit address is 001100x where x = SA0 -> write byte is 0x30 (SA0=0) or 0x32 (SA0=1)
        sad_w = Cat(Const(0, 1), self.sa0, Const(0b001100, 6))
        sad_r = Cat(Const(1, 1), self.sa0, Const(0b001100, 6))

        m.d.comb += self.busy.eq(state != 0)
        m.d.sync += self.done.eq(0)

        with m.Switch(state):
            with m.Case(0):
                with m.If(self.init_req):
                    m.d.sync += [sub_step.eq(0), state.eq(1)]
                with m.Elif(self.poll_req):
                    m.d.sync += [sub_step.eq(0), state.eq(2)]

            with m.Case(1):  # Configure CTRL1 (0x20) = 0x54 (100 Hz high-performance mode)
                with m.If(self.i2c_cmd_ready):
                    m.d.comb += self.i2c_cmd_valid.eq(1)
                    with m.Switch(sub_step):
                        with m.Case(0):
                            m.d.comb += self.i2c_cmd_start.eq(1)
                            m.d.sync += sub_step.eq(1)
                        with m.Case(1):
                            m.d.comb += [self.i2c_cmd_write.eq(1), self.i2c_tx_data.eq(sad_w)]
                            m.d.sync += sub_step.eq(2)
                        with m.Case(2):
                            m.d.comb += [self.i2c_cmd_write.eq(1), self.i2c_tx_data.eq(0x20)]
                            m.d.sync += sub_step.eq(3)
                        with m.Case(3):
                            m.d.comb += [self.i2c_cmd_write.eq(1), self.i2c_tx_data.eq(0x54)]
                            m.d.sync += sub_step.eq(4)
                        with m.Case(4):
                            m.d.comb += self.i2c_cmd_stop.eq(1)
                            m.d.sync += [self.done.eq(1), state.eq(0)]

            with m.Case(2):  # Burst read OUT_X_L..OUT_Y_H (0x28..0x2B), latch MSB bytes 0x29 & 0x2B
                with m.If(self.i2c_rx_valid):
                    with m.If(sub_step == 7):
                        m.d.sync += self.gx.eq(self.i2c_rx_data.as_signed())
                    with m.Elif(sub_step == 9):
                        m.d.sync += self.gy.eq(self.i2c_rx_data.as_signed())

                with m.If(self.i2c_cmd_ready):
                    m.d.comb += self.i2c_cmd_valid.eq(1)
                    with m.Switch(sub_step):
                        with m.Case(0):
                            m.d.comb += self.i2c_cmd_start.eq(1)
                            m.d.sync += sub_step.eq(1)
                        with m.Case(1):
                            m.d.comb += [self.i2c_cmd_write.eq(1), self.i2c_tx_data.eq(sad_w)]
                            m.d.sync += sub_step.eq(2)
                        with m.Case(2):
                            m.d.comb += [self.i2c_cmd_write.eq(1), self.i2c_tx_data.eq(0x28)]
                            m.d.sync += sub_step.eq(3)
                        with m.Case(3):
                            m.d.comb += self.i2c_cmd_start.eq(1)
                            m.d.sync += sub_step.eq(4)
                        with m.Case(4):
                            m.d.comb += [self.i2c_cmd_write.eq(1), self.i2c_tx_data.eq(sad_r)]
                            m.d.sync += sub_step.eq(5)
                        with m.Case(5, 6, 7):
                            m.d.comb += [self.i2c_cmd_read.eq(1), self.i2c_tx_ack.eq(1)]
                            m.d.sync += sub_step.eq(sub_step + 1)
                        with m.Case(8):
                            m.d.comb += [self.i2c_cmd_read.eq(1), self.i2c_tx_ack.eq(0)]
                            m.d.sync += sub_step.eq(9)
                        with m.Case(9):
                            m.d.comb += self.i2c_cmd_stop.eq(1)
                            m.d.sync += [self.done.eq(1), state.eq(0)]

        return m


class IS31FL3741AController(Elaboratable):
    """Unlocks IS31FL3741A (0x30) and streams 216 LED PWM brightness bytes."""
    def __init__(self):
        self.init_req = Signal()
        self.frame_req = Signal()
        self.busy = Signal()
        self.done = Signal()

        self.dens_rd_req = Signal()
        self.dens_rd_addr = Signal(8)
        self.dens_rd_valid = Signal()
        self.dens_rd_data = Signal(32)

        self.i2c_cmd_start = Signal()
        self.i2c_cmd_stop = Signal()
        self.i2c_cmd_write = Signal()
        self.i2c_cmd_valid = Signal()
        self.i2c_cmd_ready = Signal()
        self.i2c_tx_data = Signal(8)

    def elaborate(self, platform):
        m = Module()

        state = Signal(3, init=0)
        step = Signal(3)
        cell_scan = Signal(8)
        pwm_byte = Signal(8)
        page_sel = Signal(3)

        scan_inside = inside_circle(cell_scan[4:8], cell_scan[0:4])

        m.d.comb += [
            self.dens_rd_addr.eq(cell_scan),
            self.busy.eq(state != 0),
        ]
        m.d.sync += self.done.eq(0)

        with m.Switch(state):
            with m.Case(0):
                with m.If(self.init_req):
                    m.d.sync += [page_sel.eq(4), step.eq(0), state.eq(1)]
                with m.Elif(self.frame_req):
                    m.d.sync += [page_sel.eq(0), cell_scan.eq(0), step.eq(0), state.eq(1)]

            with m.Case(1):  # Unlock Command Register (0xFE = 0xC5) and select Page (0xFD = page_sel)
                with m.If(self.i2c_cmd_ready):
                    m.d.comb += self.i2c_cmd_valid.eq(1)
                    with m.Switch(step):
                        with m.Case(0, 5):
                            m.d.comb += self.i2c_cmd_start.eq(1)
                            m.d.sync += step.eq(step + 1)
                        with m.Case(1, 6):
                            m.d.comb += [self.i2c_cmd_write.eq(1), self.i2c_tx_data.eq(0x60)]
                            m.d.sync += step.eq(step + 1)
                        with m.Case(2):
                            m.d.comb += [self.i2c_cmd_write.eq(1), self.i2c_tx_data.eq(0xFE)]
                            m.d.sync += step.eq(3)
                        with m.Case(3):
                            m.d.comb += [self.i2c_cmd_write.eq(1), self.i2c_tx_data.eq(0xC5)]
                            m.d.sync += step.eq(4)
                        with m.Case(4):
                            m.d.comb += self.i2c_cmd_stop.eq(1)
                            m.d.sync += step.eq(5)
                        with m.Case(7):
                            m.d.comb += [self.i2c_cmd_write.eq(1), self.i2c_tx_data.eq(0xFD)]
                            m.d.sync += [
                                step.eq(0),
                                state.eq(Mux(page_sel == 4, 2, 3)),
                            ]

            with m.Case(2):  # Finish Page 4 select, then write Config (0x00=0x01 SSD=1) & GCC (0x01=0xFF)
                with m.If(self.i2c_cmd_ready):
                    m.d.comb += self.i2c_cmd_valid.eq(1)
                    with m.Switch(step):
                        with m.Case(0):
                            m.d.comb += [self.i2c_cmd_write.eq(1), self.i2c_tx_data.eq(0x04)]
                            m.d.sync += step.eq(1)
                        with m.Case(1):
                            m.d.comb += self.i2c_cmd_stop.eq(1)
                            m.d.sync += step.eq(2)
                        with m.Case(2):
                            m.d.comb += self.i2c_cmd_start.eq(1)
                            m.d.sync += step.eq(3)
                        with m.Case(3):
                            m.d.comb += [self.i2c_cmd_write.eq(1), self.i2c_tx_data.eq(0x60)]
                            m.d.sync += step.eq(4)
                        with m.Case(4):
                            m.d.comb += [self.i2c_cmd_write.eq(1), self.i2c_tx_data.eq(0x00)]
                            m.d.sync += step.eq(5)
                        with m.Case(5):
                            m.d.comb += [self.i2c_cmd_write.eq(1), self.i2c_tx_data.eq(0x01)]
                            m.d.sync += step.eq(6)
                        with m.Case(6):
                            m.d.comb += [self.i2c_cmd_write.eq(1), self.i2c_tx_data.eq(0xFF)]
                            m.d.sync += [step.eq(0), state.eq(4)]

            with m.Case(3):  # Finish Page 0 select, then burst-write 216 PWM bytes starting at reg 0x00
                with m.If((step >= 5) & ~scan_inside):
                    with m.If(cell_scan == 255):
                        m.d.sync += [step.eq(0), state.eq(4)]
                    with m.Else():
                        m.d.sync += cell_scan.eq(cell_scan + 1)
                with m.Elif(step == 5):
                    m.d.comb += self.dens_rd_req.eq(1)
                    with m.If(self.dens_rd_valid):
                        scaled = self.dens_rd_data >> 5
                        m.d.sync += [
                            pwm_byte.eq(Mux(scaled > 255, 255, scaled[:8])),
                            step.eq(6),
                        ]
                with m.Elif(self.i2c_cmd_ready):
                    m.d.comb += self.i2c_cmd_valid.eq(1)
                    with m.Switch(step):
                        with m.Case(0):
                            m.d.comb += [self.i2c_cmd_write.eq(1), self.i2c_tx_data.eq(0x00)]
                            m.d.sync += step.eq(1)
                        with m.Case(1):
                            m.d.comb += self.i2c_cmd_stop.eq(1)
                            m.d.sync += step.eq(2)
                        with m.Case(2):
                            m.d.comb += self.i2c_cmd_start.eq(1)
                            m.d.sync += step.eq(3)
                        with m.Case(3):
                            m.d.comb += [self.i2c_cmd_write.eq(1), self.i2c_tx_data.eq(0x60)]
                            m.d.sync += step.eq(4)
                        with m.Case(4):
                            # Send starting register sub-address 0x00 before streaming PWM data bytes
                            m.d.comb += [self.i2c_cmd_write.eq(1), self.i2c_tx_data.eq(0x00)]
                            m.d.sync += step.eq(5)
                        with m.Case(6):
                            m.d.comb += [self.i2c_cmd_write.eq(1), self.i2c_tx_data.eq(pwm_byte)]
                            with m.If(cell_scan == 255):
                                m.d.sync += [step.eq(0), state.eq(4)]
                            with m.Else():
                                m.d.sync += [cell_scan.eq(cell_scan + 1), step.eq(5)]

            with m.Case(4):
                with m.If(self.i2c_cmd_ready):
                    m.d.comb += [self.i2c_cmd_valid.eq(1), self.i2c_cmd_stop.eq(1)]
                    m.d.sync += [self.done.eq(1), state.eq(0)]

        return m


class PsramStreamFlipCore(Elaboratable):
    """Streaming 2D FLIP fluid engine using external QPI PSRAM and shift-add math."""
    BASE_PARTICLE = 0x0000
    BASE_DENSITY  = 0x0A40
    BASE_U        = 0x0D60
    BASE_V        = 0x0E70

    def __init__(self, sys_clk_hz=25_000_000, qpi_clk_hz=12_500_000):
        self.start = Signal()
        self.gx = Signal(signed(8))
        self.gy = Signal(signed(8))
        self.busy = Signal()
        self.done = Signal()
        self.stage = Signal(4)
        self.velocity_overflow = Signal()

        self.psram_sclk = Signal()
        self.psram_ce_n = Signal(init=1)
        self.psram_dq_i = Signal(4)
        self.psram_dq_o = Signal(4)
        self.psram_dq_oe = Signal(4)
        self.psram_translator_dir = Signal()
        self.psram_translator_oe_n = Signal(4, init=0b1111)
        self.psram_init_done = Signal()
        self.psram_busy = Signal()
        self.psram_error = Signal()

        self.dens_rd_req = Signal()
        self.dens_rd_addr = Signal(8)
        self.dens_rd_valid = Signal()
        self.dens_rd_data = Signal(32)

        self.psram = PsramController(sys_clk_hz=sys_clk_hz, qpi_clk_hz=qpi_clk_hz)

    def elaborate(self, platform):
        m = Module()
        m.submodules.psram = psram = self.psram

        m.d.comb += [
            self.psram_sclk.eq(psram.sclk),
            self.psram_ce_n.eq(psram.ce_n),
            psram.dq_i.eq(self.psram_dq_i),
            self.psram_dq_o.eq(psram.dq_o),
            self.psram_dq_oe.eq(psram.dq_oe),
            self.psram_translator_dir.eq(psram.translator_dir),
            self.psram_translator_oe_n.eq(psram.translator_oe_n),
            self.psram_init_done.eq(psram.init_done),
            self.psram_busy.eq(psram.busy),
            self.psram_error.eq(psram.error),
        ]

        state = Signal(3, init=0)
        sub = Signal(4)
        idx = Signal(9)

        px = Signal(signed(20))
        py = Signal(signed(20))
        vx = Signal(signed(20))
        vy = Signal(signed(20))
        prev_x = Signal(signed(20))
        prev_y = Signal(signed(20))
        accum = Signal(signed(24))

        m.d.comb += [
            self.busy.eq(state != 0),
            self.stage.eq(state),
            self.dens_rd_valid.eq((state == 0) & psram.rvalid),
            self.dens_rd_data.eq(psram.rdata),
        ]

        gx_dt = (self.gx << 6) + (self.gx << 2)
        gy_dt = (self.gy << 6) + (self.gy << 2)
        vx_next = vx + gx_dt
        vy_next = vy + gy_dt
        px_next = px + (((vx << 6) + (vx << 2)) >> SHIFT)
        py_next = py + (((vy << 6) + (vy << 2)) >> SHIFT)
        rx = px - CEN_Q12
        ry = py - CEN_Q12
        abs_rx = Mux(rx < 0, -rx, rx)
        abs_ry = Mux(ry < 0, -ry, ry)
        oct_r = Mux(abs_rx > abs_ry, abs_rx + (abs_ry >> 1), abs_ry + (abs_rx >> 1))
        hit_wall = oct_r > WALL_R_Q12
        dx_p = px - prev_x
        dy_p = py - prev_y
        too_close = (
            (idx != 0)
            & (dx_p > -MIN_DIST_Q12) & (dx_p < MIN_DIST_Q12)
            & (dy_p > -MIN_DIST_Q12) & (dy_p < MIN_DIST_Q12)
        )

        cell_x = px[12:16]
        cell_y = py[12:16]
        cell_addr = Cat(cell_y, cell_x)
        cell_ok = inside_circle(cell_x, cell_y)

        m.d.sync += self.done.eq(0)

        with m.Switch(state):
            with m.Case(0):
                with m.If(self.start & psram.init_done):
                    m.d.sync += [idx.eq(0), sub.eq(0), state.eq(1)]
                with m.Elif(self.dens_rd_req & psram.ready):
                    m.d.comb += [
                        psram.req.eq(1),
                        psram.we.eq(0),
                        psram.addr.eq(self.BASE_DENSITY + self.dens_rd_addr),
                    ]

            with m.Case(1):
                with m.If(sub == 0):
                    with m.If(psram.ready):
                        m.d.comb += [
                            psram.req.eq(1), psram.we.eq(1),
                            psram.addr.eq(self.BASE_DENSITY + idx[:8]),
                            psram.wdata.eq(0),
                        ]
                        m.d.sync += sub.eq(1)
                with m.Else():
                    with m.If(psram.done):
                        m.d.sync += sub.eq(0)
                        with m.If(idx == 255):
                            m.d.sync += [idx.eq(0), state.eq(2)]
                        with m.Else():
                            m.d.sync += idx.eq(idx + 1)

            with m.Case(2):
                base_p = idx[:8] << 2
                with m.Switch(sub):
                    with m.Case(0):
                        with m.If(psram.ready):
                            m.d.comb += [psram.req.eq(1), psram.we.eq(0), psram.addr.eq(base_p + 0)]
                            m.d.sync += sub.eq(1)
                    with m.Case(1):
                        with m.If(psram.rvalid):
                            m.d.sync += [px.eq(psram.rdata[:20].as_signed()), sub.eq(2)]
                    with m.Case(2):
                        with m.If(psram.ready):
                            m.d.comb += [psram.req.eq(1), psram.we.eq(0), psram.addr.eq(base_p + 1)]
                            m.d.sync += sub.eq(3)
                    with m.Case(3):
                        with m.If(psram.rvalid):
                            m.d.sync += [py.eq(psram.rdata[:20].as_signed()), sub.eq(4)]
                    with m.Case(4):
                        with m.If(psram.ready):
                            m.d.comb += [psram.req.eq(1), psram.we.eq(0), psram.addr.eq(base_p + 2)]
                            m.d.sync += sub.eq(5)
                    with m.Case(5):
                        with m.If(psram.rvalid):
                            m.d.sync += [vx.eq(psram.rdata[:20].as_signed()), sub.eq(6)]
                    with m.Case(6):
                        with m.If(psram.ready):
                            m.d.comb += [psram.req.eq(1), psram.we.eq(0), psram.addr.eq(base_p + 3)]
                            m.d.sync += sub.eq(7)
                    with m.Case(7):
                        with m.If(psram.rvalid):
                            m.d.sync += [vy.eq(psram.rdata[:20].as_signed()), sub.eq(8)]
                    with m.Case(8):
                        m.d.sync += [
                            px.eq(px_next), py.eq(py_next),
                            vx.eq(vx_next[:20].as_signed()), vy.eq(vy_next[:20].as_signed()),
                            sub.eq(9),
                        ]
                    with m.Case(9):
                        w_px = Mux(hit_wall, CEN_Q12 + (rx - (rx >> 3)), px)
                        w_py = Mux(hit_wall, CEN_Q12 + (ry - (ry >> 3)), py)
                        m.d.sync += [
                            px.eq(Mux(too_close, w_px + (dx_p >> 2), w_px)),
                            py.eq(Mux(too_close, w_py + (dy_p >> 2), w_py)),
                            vx.eq(Mux(hit_wall, -(vx >> 1), vx)),
                            vy.eq(Mux(hit_wall, -(vy >> 1), vy)),
                            prev_x.eq(w_px), prev_y.eq(w_py),
                            sub.eq(10),
                        ]
                    with m.Case(10):
                        with m.If(psram.ready):
                            m.d.comb += [
                                psram.req.eq(1), psram.we.eq(1),
                                psram.addr.eq(base_p + 0), psram.wdata.eq(Cat(px, Const(0, 12))),
                            ]
                            m.d.sync += sub.eq(11)
                    with m.Case(11):
                        with m.If(psram.done):
                            m.d.sync += sub.eq(12)
                    with m.Case(12):
                        with m.If(psram.ready):
                            m.d.comb += [
                                psram.req.eq(1), psram.we.eq(1),
                                psram.addr.eq(base_p + 1), psram.wdata.eq(Cat(py, Const(0, 12))),
                            ]
                            m.d.sync += sub.eq(13)
                    with m.Case(13):
                        with m.If(psram.done):
                            m.d.sync += [sub.eq(0), state.eq(3)]

            with m.Case(3):
                base_p = idx[:8] << 2
                with m.Switch(sub):
                    with m.Case(0):
                        with m.If(psram.ready):
                            m.d.comb += [
                                psram.req.eq(1), psram.we.eq(1),
                                psram.addr.eq(base_p + 2), psram.wdata.eq(Cat(vx, Const(0, 12))),
                            ]
                            m.d.sync += sub.eq(1)
                    with m.Case(1):
                        with m.If(psram.done):
                            m.d.sync += sub.eq(2)
                    with m.Case(2):
                        with m.If(psram.ready):
                            m.d.comb += [
                                psram.req.eq(1), psram.we.eq(1),
                                psram.addr.eq(base_p + 3), psram.wdata.eq(Cat(vy, Const(0, 12))),
                            ]
                            m.d.sync += sub.eq(3)
                    with m.Case(3):
                        with m.If(psram.done):
                            m.d.sync += sub.eq(4)
                    with m.Case(4):
                        with m.If(psram.ready):
                            m.d.comb += [
                                psram.req.eq(1), psram.we.eq(0),
                                psram.addr.eq(self.BASE_DENSITY + cell_addr),
                            ]
                            m.d.sync += sub.eq(5)
                    with m.Case(5):
                        with m.If(psram.rvalid):
                            m.d.sync += [accum.eq(psram.rdata[:24] + SCALE), sub.eq(6)]
                    with m.Case(6):
                        with m.If(psram.ready):
                            m.d.comb += [
                                psram.req.eq(1), psram.we.eq(1),
                                psram.addr.eq(self.BASE_DENSITY + cell_addr),
                                psram.wdata.eq(Mux(cell_ok, accum.as_unsigned(), 0)),
                            ]
                            m.d.sync += sub.eq(7)
                    with m.Case(7):
                        with m.If(psram.done):
                            m.d.sync += sub.eq(0)
                            with m.If(idx == 255):
                                m.d.sync += [self.done.eq(1), state.eq(0)]
                            with m.Else():
                                m.d.sync += [idx.eq(idx + 1), state.eq(2)]

        return m


class PendantSystemTop(Elaboratable):
    """Top-level coordinator: boots sensors, polls tilt, steps fluid, updates LEDs."""
    ST_BOOT_ACCEL      = 0
    ST_BOOT_ACCEL_WAIT = 1
    ST_BOOT_LED        = 2
    ST_BOOT_LED_WAIT   = 3
    ST_POLL_ACCEL      = 4
    ST_POLL_ACCEL_WAIT = 5
    ST_CHECK_SLEEP     = 6
    ST_RUN_FLIP        = 7
    ST_WAIT_FLIP       = 8
    ST_STREAM_LEDS     = 9
    ST_WAIT_LEDS       = 10

    def __init__(self, sys_clk_hz=25_000_000, qpi_clk_hz=12_500_000, i2c_clk_hz=400_000, **kwargs):
        self.core = PsramStreamFlipCore(sys_clk_hz=sys_clk_hz, qpi_clk_hz=qpi_clk_hz)
        self.i2c = I2CMaster(sys_clk_hz=sys_clk_hz, i2c_clk_hz=i2c_clk_hz)
        self.accel = LIS2DW12Controller()
        self.leds = IS31FL3741AController()

        self.frame_sync = Signal()
        self.lis_int2_sleep = Signal()
        self.accel_sa0 = Signal(init=1)
        self.clock_gated_sleep = Signal()
        self.sleep_hold_frames = Signal(7)

        self.i2c_scl_o = Signal(init=0)
        self.i2c_scl_oe = Signal(init=0)
        self.i2c_sda_i = Signal(init=1)
        self.i2c_sda_o = Signal(init=0)
        self.i2c_sda_oe = Signal(init=0)

    def elaborate(self, platform):
        m = Module()
        m.submodules.core = core = self.core
        m.submodules.i2c = i2c = self.i2c
        m.submodules.accel = accel = self.accel
        m.submodules.leds = leds = self.leds

        state = Signal(4, init=self.ST_BOOT_ACCEL)
        last_gx = Signal(signed(8), init=0)
        last_gy = Signal(signed(8), init=-60)

        use_led_i2c = (
            (state == self.ST_BOOT_LED)
            | (state == self.ST_BOOT_LED_WAIT)
            | (state == self.ST_STREAM_LEDS)
            | (state == self.ST_WAIT_LEDS)
        )

        dx = Signal(signed(9))
        dy = Signal(signed(9))
        accel_changed = Signal()

        m.d.comb += [
            accel.sa0.eq(self.accel_sa0),
            core.dens_rd_req.eq(leds.dens_rd_req),
            core.dens_rd_addr.eq(leds.dens_rd_addr),
            leds.dens_rd_valid.eq(core.dens_rd_valid),
            leds.dens_rd_data.eq(core.dens_rd_data),

            self.i2c_scl_o.eq(i2c.scl_o),
            self.i2c_scl_oe.eq(i2c.scl_oe),
            i2c.sda_i.eq(self.i2c_sda_i),
            self.i2c_sda_o.eq(i2c.sda_o),
            self.i2c_sda_oe.eq(i2c.sda_oe),

            accel.i2c_cmd_ready.eq(i2c.cmd_ready & ~use_led_i2c),
            accel.i2c_rx_data.eq(i2c.rx_data),
            accel.i2c_rx_valid.eq(i2c.rx_valid),
            leds.i2c_cmd_ready.eq(i2c.cmd_ready & use_led_i2c),

            i2c.cmd_start.eq(Mux(use_led_i2c, leds.i2c_cmd_start, accel.i2c_cmd_start)),
            i2c.cmd_stop.eq(Mux(use_led_i2c, leds.i2c_cmd_stop, accel.i2c_cmd_stop)),
            i2c.cmd_write.eq(Mux(use_led_i2c, leds.i2c_cmd_write, accel.i2c_cmd_write)),
            i2c.cmd_read.eq(Mux(use_led_i2c, 0, accel.i2c_cmd_read)),
            i2c.cmd_valid.eq(Mux(use_led_i2c, leds.i2c_cmd_valid, accel.i2c_cmd_valid)),
            i2c.tx_data.eq(Mux(use_led_i2c, leds.i2c_tx_data, accel.i2c_tx_data)),
            i2c.tx_ack.eq(Mux(use_led_i2c, 0, accel.i2c_tx_ack)),

            core.gx.eq(accel.gx),
            core.gy.eq(accel.gy),
            core.start.eq(state == self.ST_RUN_FLIP),
            accel.init_req.eq(state == self.ST_BOOT_ACCEL),
            accel.poll_req.eq(state == self.ST_POLL_ACCEL),
            leds.init_req.eq(state == self.ST_BOOT_LED),
            leds.frame_req.eq(state == self.ST_STREAM_LEDS),

            dx.eq(accel.gx - last_gx),
            dy.eq(accel.gy - last_gy),
            accel_changed.eq((dx > 1) | (dx < -1) | (dy > 1) | (dy < -1)),
        ]

        with m.Switch(state):
            with m.Case(self.ST_BOOT_ACCEL):
                m.d.sync += state.eq(self.ST_BOOT_ACCEL_WAIT)
            with m.Case(self.ST_BOOT_ACCEL_WAIT):
                with m.If(accel.done):
                    m.d.sync += state.eq(self.ST_BOOT_LED)
            with m.Case(self.ST_BOOT_LED):
                m.d.sync += state.eq(self.ST_BOOT_LED_WAIT)
            with m.Case(self.ST_BOOT_LED_WAIT):
                with m.If(leds.done):
                    m.d.sync += state.eq(self.ST_POLL_ACCEL)
            with m.Case(self.ST_POLL_ACCEL):
                with m.If(self.frame_sync):
                    m.d.sync += state.eq(self.ST_POLL_ACCEL_WAIT)
            with m.Case(self.ST_POLL_ACCEL_WAIT):
                with m.If(accel.done):
                    m.d.sync += state.eq(self.ST_CHECK_SLEEP)
            with m.Case(self.ST_CHECK_SLEEP):
                m.d.sync += [last_gx.eq(accel.gx), last_gy.eq(accel.gy)]
                with m.If(accel_changed | ~self.lis_int2_sleep):
                    m.d.sync += [
                        self.clock_gated_sleep.eq(0),
                        self.sleep_hold_frames.eq(0),
                        state.eq(self.ST_RUN_FLIP),
                    ]
                with m.Elif(self.clock_gated_sleep):
                    m.d.sync += state.eq(self.ST_POLL_ACCEL)
                with m.Else():
                    with m.If(self.sleep_hold_frames >= 89):
                        m.d.sync += [
                            self.clock_gated_sleep.eq(1),
                            state.eq(self.ST_POLL_ACCEL),
                        ]
                    with m.Else():
                        m.d.sync += [
                            self.sleep_hold_frames.eq(self.sleep_hold_frames + 1),
                            state.eq(self.ST_RUN_FLIP),
                        ]
            with m.Case(self.ST_RUN_FLIP):
                m.d.sync += state.eq(self.ST_WAIT_FLIP)
            with m.Case(self.ST_WAIT_FLIP):
                with m.If(core.done):
                    m.d.sync += state.eq(self.ST_STREAM_LEDS)
            with m.Case(self.ST_STREAM_LEDS):
                m.d.sync += state.eq(self.ST_WAIT_LEDS)
            with m.Case(self.ST_WAIT_LEDS):
                with m.If(leds.done):
                    m.d.sync += state.eq(self.ST_POLL_ACCEL)

        return m


class TTUmFlipPendant(Elaboratable):
    """Tiny Tapeout pin wrapper (ui_in, uo_out, uio_in, uio_out, uio_oe)."""
    def __init__(self, sys_clk_hz=25_000_000, qpi_clk_hz=12_500_000, i2c_clk_hz=400_000):
        self.frame_reload = max(1, sys_clk_hz // 60)

        self.ui_in = Signal(8, name="ui_in")
        self.uo_out = Signal(8, name="uo_out")
        self.uio_in = Signal(8, name="uio_in")
        self.uio_out = Signal(8, name="uio_out")
        self.uio_oe = Signal(8, name="uio_oe")
        self.ena = Signal(name="ena")

        self.system = PendantSystemTop(
            sys_clk_hz=sys_clk_hz,
            qpi_clk_hz=qpi_clk_hz,
            i2c_clk_hz=i2c_clk_hz,
        )

    def elaborate(self, platform):
        m = Module()
        m.submodules.system = sys_top = self.system
        core = sys_top.core

        frame_timer = Signal(range(self.frame_reload + 1))
        auto_tick = Signal()
        with m.If(frame_timer == self.frame_reload - 1):
            m.d.sync += [frame_timer.eq(0), auto_tick.eq(1)]
        with m.Else():
            m.d.sync += [frame_timer.eq(frame_timer + 1), auto_tick.eq(0)]

        lis_int2_sleep = self.ui_in[0]
        shake_btn = self.ui_in[1]
        ext_frame_sync = self.ui_in[2]
        auto_run_en = self.ui_in[3]
        accel_sa0 = self.ui_in[4]
        force_awake = self.ui_in[5]

        trans_oe_n = (
            core.psram_translator_oe_n[0]
            & core.psram_translator_oe_n[1]
            & core.psram_translator_oe_n[2]
            & core.psram_translator_oe_n[3]
        )

        m.d.comb += [
            sys_top.lis_int2_sleep.eq(lis_int2_sleep & ~shake_btn & ~force_awake),
            sys_top.frame_sync.eq(Mux(auto_run_en, auto_tick, ext_frame_sync)),
            sys_top.accel_sa0.eq(accel_sa0),

            core.psram_dq_i.eq(self.uio_in[0:4]),
            sys_top.i2c_sda_i.eq(self.uio_in[4]),

            self.uio_out.eq(Cat(
                core.psram_dq_o,
                Const(0, 1),
                Const(0, 1),
                trans_oe_n,
                Const(1, 1),
            )),
            self.uio_oe.eq(Cat(
                core.psram_dq_oe,
                sys_top.i2c_sda_oe,
                sys_top.i2c_scl_oe,
                Const(1, 1),
                Const(1, 1),
            )),
            self.uo_out.eq(Cat(
                core.psram_sclk,
                core.psram_ce_n,
                core.psram_translator_dir,
                core.busy,
                core.done,
                sys_top.clock_gated_sleep,
                sys_top.i2c.busy,
                core.psram_error | sys_top.i2c.ack_error | core.velocity_overflow,
            )),
        ]

        return m


FLIPPipeline = PsramStreamFlipCore
