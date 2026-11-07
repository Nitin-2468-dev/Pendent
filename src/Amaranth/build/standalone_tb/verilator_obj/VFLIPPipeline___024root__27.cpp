// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design implementation internals
// See VFLIPPipeline.h for the primary calling header

#include "VFLIPPipeline__pch.h"

void VFLIPPipeline___024root___trigger_orInto__act_vec_vec(::VlUnpacked<::QData/*63:0*/, 1> &out, const ::VlUnpacked<::QData/*63:0*/, 1> &in) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    VFLIPPipeline___024root___trigger_orInto__act_vec_vec\n"); );
    // Locals
    ::IData/*31:0*/ n;
    // Body
    n = 0U;
    do {
        out[n] = (out[n] | in[n]);
        n = ((::IData)(1U) + n);
    } while ((0U >= n));
}

void VFLIPPipeline___024root___trigger_clear__act(::VlUnpacked<::QData/*63:0*/, 1> &out) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    VFLIPPipeline___024root___trigger_clear__act\n"); );
    // Locals
    ::IData/*31:0*/ n;
    // Body
    n = 0U;
    do {
        out[n] = 0ULL;
        n = ((::IData)(1U) + n);
    } while ((1U > n));
}

#ifdef VL_DEBUG
void VFLIPPipeline___024root___eval_debug_assertions(VFLIPPipeline___024root* vlSelf) {
    VL_DEBUG_IF(VL_DBG_MSGF("+    VFLIPPipeline___024root___eval_debug_assertions\n"); );
    VFLIPPipeline__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;
    auto& vlSelfRef = std::ref(*vlSelf).get();
    // Body
    if (VL_UNLIKELY(((vlSelfRef.__VprimaryPorts.rst 
                      & 0xfeU)))) {
        Verilated::overWidthError("rst");
    }
    if (VL_UNLIKELY(((vlSelfRef.__VprimaryPorts.start 
                      & 0xfeU)))) {
        Verilated::overWidthError("start");
    }
    if (VL_UNLIKELY(((vlSelfRef.__VprimaryPorts.host_write_req 
                      & 0xfeU)))) {
        Verilated::overWidthError("host_write_req");
    }
    if (VL_UNLIKELY(((vlSelfRef.__VprimaryPorts.host_write_pos_x 
                      & 0xfff00000U)))) {
        Verilated::overWidthError("host_write_pos_x");
    }
    if (VL_UNLIKELY(((vlSelfRef.__VprimaryPorts.host_write_pos_y 
                      & 0xfff00000U)))) {
        Verilated::overWidthError("host_write_pos_y");
    }
    if (VL_UNLIKELY(((vlSelfRef.__VprimaryPorts.host_write_vel_x 
                      & 0xfff00000U)))) {
        Verilated::overWidthError("host_write_vel_x");
    }
    if (VL_UNLIKELY(((vlSelfRef.__VprimaryPorts.host_write_vel_y 
                      & 0xfff00000U)))) {
        Verilated::overWidthError("host_write_vel_y");
    }
    if (VL_UNLIKELY(((vlSelfRef.__VprimaryPorts.host_read_req 
                      & 0xfeU)))) {
        Verilated::overWidthError("host_read_req");
    }
    if (VL_UNLIKELY(((vlSelfRef.__VprimaryPorts.clk 
                      & 0xfeU)))) {
        Verilated::overWidthError("clk");
    }
}
#endif  // VL_DEBUG
