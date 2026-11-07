// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Symbol table internal header
//
// Internal details; most calling programs do not need this header,
// unless using verilator public meta comments.

#ifndef VERILATED_VFLIPPIPELINE__SYMS_H_
#define VERILATED_VFLIPPIPELINE__SYMS_H_  // guard

#include "verilated.h"

// INCLUDE MODEL CLASS

#include "VFLIPPipeline.h"

// INCLUDE MODULE CLASSES
#include "VFLIPPipeline___024root.h"

// SYMS CLASS (contains all model state)
class alignas(VL_CACHE_LINE_BYTES) VFLIPPipeline__Syms final : public VerilatedSyms {
  public:
    // INTERNAL STATE
    VFLIPPipeline* const __Vm_modelp;
    const bool __Vm_isRoot;
    std::string __Vm_topNames[2];
    VlDeleter __Vm_deleter;
    bool& __Vm_didInit;

    // MODULE INSTANCE STATE
    union {
        struct {
            VFLIPPipeline___024root        TOP;
        } vlInst;
    };

    // CONSTRUCTORS
    VFLIPPipeline__Syms(VerilatedContext* contextp, VFLIPPipeline* modelp, const char* namep, bool isRoot);
    ~VFLIPPipeline__Syms();

    // METHODS
    const char* name() const { return vlInst.TOP.vlNamep; }
};

#endif  // guard
