// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Model implementation (design independent parts)

#include "VFLIPPipeline__pch.h"

//============================================================
// Constructors

VFLIPPipeline::VFLIPPipeline(VerilatedContext* _vcontextp__, const char* _vcname__)
    : VFLIPPipeline{_vcontextp__, _vcname__, true} {}

VFLIPPipeline::VFLIPPipeline(VerilatedContext* _vcontextp__, const char* _vcname__, bool _vcisRoot__)
    : VerilatedModel{*_vcontextp__}
    , vlSymsp{new VFLIPPipeline__Syms(contextp(), this, _vcname__, _vcisRoot__)}
    , m_evalLoop{*this, /*convergeLimit:*/ 10000}
    , rst{vlSymsp->vlInst.TOP.__VprimaryPorts.rst}
    , start{vlSymsp->vlInst.TOP.__VprimaryPorts.start}
    , gx{vlSymsp->vlInst.TOP.__VprimaryPorts.gx}
    , gy{vlSymsp->vlInst.TOP.__VprimaryPorts.gy}
    , sram_rdata{vlSymsp->vlInst.TOP.__VprimaryPorts.sram_rdata}
    , host_write_req{vlSymsp->vlInst.TOP.__VprimaryPorts.host_write_req}
    , host_write_addr{vlSymsp->vlInst.TOP.__VprimaryPorts.host_write_addr}
    , host_write_pos_x{vlSymsp->vlInst.TOP.__VprimaryPorts.host_write_pos_x}
    , host_write_pos_y{vlSymsp->vlInst.TOP.__VprimaryPorts.host_write_pos_y}
    , host_write_vel_x{vlSymsp->vlInst.TOP.__VprimaryPorts.host_write_vel_x}
    , host_write_vel_y{vlSymsp->vlInst.TOP.__VprimaryPorts.host_write_vel_y}
    , host_read_req{vlSymsp->vlInst.TOP.__VprimaryPorts.host_read_req}
    , host_read_addr{vlSymsp->vlInst.TOP.__VprimaryPorts.host_read_addr}
    , busy{vlSymsp->vlInst.TOP.__VprimaryPorts.busy}
    , done{vlSymsp->vlInst.TOP.__VprimaryPorts.done}
    , stage{vlSymsp->vlInst.TOP.__VprimaryPorts.stage}
    , velocity_overflow{vlSymsp->vlInst.TOP.__VprimaryPorts.velocity_overflow}
    , sram_en{vlSymsp->vlInst.TOP.__VprimaryPorts.sram_en}
    , sram_we{vlSymsp->vlInst.TOP.__VprimaryPorts.sram_we}
    , sram_addr{vlSymsp->vlInst.TOP.__VprimaryPorts.sram_addr}
    , sram_wdata{vlSymsp->vlInst.TOP.__VprimaryPorts.sram_wdata}
    , host_ready{vlSymsp->vlInst.TOP.__VprimaryPorts.host_ready}
    , host_read_valid{vlSymsp->vlInst.TOP.__VprimaryPorts.host_read_valid}
    , host_read_pos_x{vlSymsp->vlInst.TOP.__VprimaryPorts.host_read_pos_x}
    , host_read_pos_y{vlSymsp->vlInst.TOP.__VprimaryPorts.host_read_pos_y}
    , host_read_vel_x{vlSymsp->vlInst.TOP.__VprimaryPorts.host_read_vel_x}
    , host_read_vel_y{vlSymsp->vlInst.TOP.__VprimaryPorts.host_read_vel_y}
    , p2g_cycle_count{vlSymsp->vlInst.TOP.__VprimaryPorts.p2g_cycle_count}
    , pressure_iteration_index{vlSymsp->vlInst.TOP.__VprimaryPorts.pressure_iteration_index}
    , g2p_processed_count{vlSymsp->vlInst.TOP.__VprimaryPorts.g2p_processed_count}
    , clk{vlSymsp->vlInst.TOP.__VprimaryPorts.clk}
    , rootp{&(vlSymsp->vlInst.TOP)}
{
    // Register model with the context
    contextp()->addModel(this);
}

VFLIPPipeline::VFLIPPipeline(const char* _vcname__)
    : VFLIPPipeline(Verilated::threadContextp(), _vcname__)
{
}

//============================================================
// Destructor

VFLIPPipeline::~VFLIPPipeline() {
    delete vlSymsp;
}

//============================================================
// Evaluation function

#ifdef VL_DEBUG
void VFLIPPipeline___024root___eval_debug_assertions(VFLIPPipeline___024root* vlSelf);
#endif  // VL_DEBUG
VL_ATTR_COLD void VFLIPPipeline___024root___eval_static(VFLIPPipeline___024root* vlSelf);
VL_ATTR_COLD void VFLIPPipeline___024root___eval_initial(VFLIPPipeline___024root* vlSelf);
VL_ATTR_COLD bool VFLIPPipeline___024root___eval_stl(VFLIPPipeline___024root* vlSelf, ::CData/*0:0*/ firstIteration);
void VFLIPPipeline___024root___eval_sample(VFLIPPipeline___024root* vlSelf);
bool VFLIPPipeline___024root___eval_ico(VFLIPPipeline___024root* vlSelf, ::CData/*0:0*/ firstIteration);
bool VFLIPPipeline___024root___eval_act(VFLIPPipeline___024root* vlSelf);
bool VFLIPPipeline___024root___eval_inact(VFLIPPipeline___024root* vlSelf);
bool VFLIPPipeline___024root___eval_nba(VFLIPPipeline___024root* vlSelf);
bool VFLIPPipeline___024root___eval_obs(VFLIPPipeline___024root* vlSelf);
bool VFLIPPipeline___024root___eval_react(VFLIPPipeline___024root* vlSelf);
void VFLIPPipeline___024root___eval_postponed(VFLIPPipeline___024root* vlSelf);
VL_ATTR_COLD void VFLIPPipeline___024root___eval_final(VFLIPPipeline___024root* vlSelf);
VL_ATTR_COLD void VFLIPPipeline___024root___eval_dump_triggers__stl(VFLIPPipeline___024root* vlSelf);
VL_ATTR_COLD void VFLIPPipeline___024root___eval_dump_triggers__ico(VFLIPPipeline___024root* vlSelf);
VL_ATTR_COLD void VFLIPPipeline___024root___eval_dump_triggers__act(VFLIPPipeline___024root* vlSelf);
VL_ATTR_COLD void VFLIPPipeline___024root___eval_dump_triggers__nba(VFLIPPipeline___024root* vlSelf);
VL_ATTR_COLD void VFLIPPipeline___024root___eval_dump_triggers__obs(VFLIPPipeline___024root* vlSelf);
VL_ATTR_COLD void VFLIPPipeline___024root___eval_dump_triggers__react(VFLIPPipeline___024root* vlSelf);

void VFLIPPipeline::eval_step() {
    VL_DEBUG_IF(VL_DBG_MSGF("+++++TOP Evaluate VFLIPPipeline::eval_step\n"); );
    m_evalLoop.eval();
}

void VFLIPPipeline::evalBegin() {
#ifdef VL_DEBUG
    // Debug assertions
    VFLIPPipeline___024root___eval_debug_assertions(&(vlSymsp->vlInst.TOP));
#endif  // VL_DEBUG
    vlSymsp->__Vm_deleter.deleteAll();
}

void VFLIPPipeline::evalEnd() {
    // Evaluate cleanup
    Verilated::endOfEval(vlSymsp->__Vm_evalMsgQp);
}

void VFLIPPipeline::evalStatic() {
    VFLIPPipeline___024root___eval_static(&(vlSymsp->vlInst.TOP));
}

void VFLIPPipeline::evalInitial() {
    VFLIPPipeline___024root___eval_initial(&(vlSymsp->vlInst.TOP));
}

bool VFLIPPipeline::evalStl(bool firstIteration) {
    return VFLIPPipeline___024root___eval_stl(&(vlSymsp->vlInst.TOP), firstIteration);
}

void VFLIPPipeline::evalSample() {
    VFLIPPipeline___024root___eval_sample(&(vlSymsp->vlInst.TOP));
}

bool VFLIPPipeline::evalIco(bool firstIteration) {
    return VFLIPPipeline___024root___eval_ico(&(vlSymsp->vlInst.TOP), firstIteration);
}

bool VFLIPPipeline::evalAct() {
    return VFLIPPipeline___024root___eval_act(&(vlSymsp->vlInst.TOP));
}

bool VFLIPPipeline::evalInact() {
    return VFLIPPipeline___024root___eval_inact(&(vlSymsp->vlInst.TOP));
}

bool VFLIPPipeline::evalNba() {
    return VFLIPPipeline___024root___eval_nba(&(vlSymsp->vlInst.TOP));
}

bool VFLIPPipeline::evalObs() {
    return VFLIPPipeline___024root___eval_obs(&(vlSymsp->vlInst.TOP));
}

bool VFLIPPipeline::evalReact() {
    return VFLIPPipeline___024root___eval_react(&(vlSymsp->vlInst.TOP));
}

void VFLIPPipeline::evalPostponed() {
    VFLIPPipeline___024root___eval_postponed(&(vlSymsp->vlInst.TOP));
}

void VFLIPPipeline::evalFinal() {
    VFLIPPipeline___024root___eval_final(&(vlSymsp->vlInst.TOP));
}

VL_ATTR_COLD void VFLIPPipeline::dumpTriggersStl() {
    VFLIPPipeline___024root___eval_dump_triggers__stl(&(vlSymsp->vlInst.TOP));
}

VL_ATTR_COLD void VFLIPPipeline::dumpTriggersIco() {
    VFLIPPipeline___024root___eval_dump_triggers__ico(&(vlSymsp->vlInst.TOP));
}

VL_ATTR_COLD void VFLIPPipeline::dumpTriggersAct() {
    VFLIPPipeline___024root___eval_dump_triggers__act(&(vlSymsp->vlInst.TOP));
}

VL_ATTR_COLD void VFLIPPipeline::dumpTriggersNba() {
    VFLIPPipeline___024root___eval_dump_triggers__nba(&(vlSymsp->vlInst.TOP));
}

VL_ATTR_COLD void VFLIPPipeline::dumpTriggersObs() {
    VFLIPPipeline___024root___eval_dump_triggers__obs(&(vlSymsp->vlInst.TOP));
}

VL_ATTR_COLD void VFLIPPipeline::dumpTriggersReact() {
    VFLIPPipeline___024root___eval_dump_triggers__react(&(vlSymsp->vlInst.TOP));
}

//============================================================
// Events and timing
bool VFLIPPipeline::eventsPending() { return false; }

uint64_t VFLIPPipeline::nextTimeSlot() {
    VL_FATAL_MT(__FILE__, __LINE__, "", "No delays in the design");
    return 0;
}

//============================================================
// Utilities

const char* VFLIPPipeline::name() const {
    return vlSymsp->name();
}

//============================================================
// Invoke final blocks

VL_ATTR_COLD void VFLIPPipeline::final() {
    contextp()->executingFinal(true);
    evalFinal();
    contextp()->executingFinal(false);
}

//============================================================
// Implementations of abstract methods from VerilatedModel

const char* VFLIPPipeline::hierName() const { return vlSymsp->name(); }
const char* VFLIPPipeline::modelName() const { return "VFLIPPipeline"; }
unsigned VFLIPPipeline::threads() const { return 1; }
void VFLIPPipeline::prepareClone() const { contextp()->prepareClone(); }
void VFLIPPipeline::atClone() const {
    contextp()->threadPoolpOnClone();
}
