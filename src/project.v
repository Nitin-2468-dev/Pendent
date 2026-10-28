
`default_nettype none

module tt_um_example (
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);

    wire [3:0] a = ui_in[3:0];
    wire [3:0] b = ui_in[7:4];
    wire       c_in = uio_in[0];
    wire [4:0] sum;

    // The actual Amaranth-generated adder
    adder_core adder_inst (
        .a(a),
        .b(b),
        .c_in(c_in),
        .Sum(sum)
    );

    assign uo_out = {3'b000, sum};
    assign uio_out = 8'b0;
    assign uio_oe = 8'b0;

    wire _unused = &{ena, clk, rst_n, uio_in[7:1], 1'b0};

endmodule

`default_nettype wire
