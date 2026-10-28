
`default_nettype none
`timescale 1ns / 1ps

module tb ();

    // Clock and control signals
    reg clk;
    reg rst_n;
    reg ena;

    // Tiny Tapeout input pins
    reg [7:0] ui_in;
    reg [7:0] uio_in;

    // Tiny Tapeout output pins
    wire [7:0] uo_out;
    wire [7:0] uio_out;
    wire [7:0] uio_oe;

    // Instantiate the design being tested
    tt_um_example dut (
        .ui_in  (ui_in),
        .uo_out (uo_out),
        .uio_in (uio_in),
        .uio_out(uio_out),
        .uio_oe (uio_oe),
        .ena    (ena),
        .clk    (clk),
        .rst_n  (rst_n)
    );

    // Clock generation
    initial clk = 0;
    always #5 clk = ~clk;

    // Waveform output
    initial begin
        $dumpfile("tb.vcd");
        $dumpvars(0, tb);
    end

    // Basic simulation
    initial begin
        ena = 1;
        rst_n = 0;
        ui_in = 0;
        uio_in = 0;

        // Hold reset for two clock cycles
        repeat (2) @(posedge clk);
        @(negedge clk);
        rst_n = 1;

        // Test 1: 7 + 8 + 1 = 16
        ui_in = {4'd8, 4'd7};
        uio_in = 8'd1;

        @(posedge clk);
        #1;
        $display("7 + 8 + 1 = %0d", uo_out[4:0]);
        if (uo_out[4:0] !== 5'd16)
            $error("Test 1 failed!");

        // Test 2: 15 + 15 + 1 = 31
        @(negedge clk);
        ui_in = {4'd15, 4'd15};
        uio_in = 8'd1;

        @(posedge clk);
        #1;
        $display("15 + 15 + 1 = %0d", uo_out[4:0]);
        if (uo_out[4:0] !== 5'd31)
            $error("Test 2 failed!");

        $display("Simulation complete");
        $finish;
    end

endmodule

`default_nettype wire
