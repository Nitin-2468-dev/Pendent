#include "VFLIPPipeline.h"
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
