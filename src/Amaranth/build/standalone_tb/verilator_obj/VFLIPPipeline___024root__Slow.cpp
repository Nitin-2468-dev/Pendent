// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Design implementation internals
// See VFLIPPipeline.h for the primary calling header

#include "VFLIPPipeline__pch.h"

void VFLIPPipeline___024root___ctor_var_reset(VFLIPPipeline___024root* vlSelf);

void VFLIPPipeline___024root__ctor(VFLIPPipeline___024root* vlSelf, VFLIPPipeline__Syms* symsp, const char* namep) {
    vlSelf->vlSymsp = symsp;
    vlSelf->vlNamep = strdup(namep);
    // Construct members
    // Reset structure values
    VFLIPPipeline___024root___ctor_var_reset(vlSelf);
}

VFLIPPipeline___024root::VFLIPPipeline___024root(VFLIPPipeline__Syms* symsp, const char* namep) {
    VFLIPPipeline___024root__ctor(this, symsp, namep);
}

void VFLIPPipeline___024root__dtor(VFLIPPipeline___024root* vlSelf) {
    // Destroy members
    VL_DO_DANGLING(std::free(const_cast<char*>(vlSelf->vlNamep)), vlSelf->vlNamep);
}

VFLIPPipeline___024root::~VFLIPPipeline___024root() {
    VFLIPPipeline___024root__dtor(this);
}
