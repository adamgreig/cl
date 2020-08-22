import subprocess
import nmigen as nm
from nmigen.build import Resource, Pins, PinsN, Attrs, Clock, Subsignal
from nmigen.vendor.lattice_ecp5 import LatticeECP5Platform


class UART(nm.Elaboratable):
    def __init__(self, data, divider=217, n=8):
        assert divider >= 1
        self.valid = nm.Signal()
        self.tx_o = nm.Signal()
        self.data = nm.Const(data, n)
        self.divider = divider
        self.n = n

    def elaborate(self, platform):
        m = nm.Module()
        tx_div = nm.Signal(range(self.divider))
        tx_reg = nm.Signal(self.n+2, reset=1)
        tx_cnt = nm.Signal(range(self.n+3))
        m.d.comb += self.tx_o.eq(tx_reg[0])
        with m.If(tx_cnt == 0):
            # Idle
            with m.If(self.valid):
                m.d.sync += [
                    tx_reg.eq(nm.Cat(0, self.data, 1)),
                    tx_cnt.eq(self.n+2),
                    tx_div.eq(self.divider - 1),
                ]
        with m.Else():
            # Transmitting
            with m.If(tx_div != 0):
                # Wait for clock divider
                m.d.sync += tx_div.eq(tx_div - 1)
            with m.Else():
                # Update output state
                m.d.sync += [
                    tx_reg.eq(nm.Cat(tx_reg[1:], 1)),
                    tx_cnt.eq(tx_cnt - 1),
                    tx_div.eq(self.divider - 1),
                ]

        return m


class ColorLite5A75E_V6_0_Platform(LatticeECP5Platform):
    device = "LFE5U-25F"
    package = "BG256"
    speed = "6"
    default_clk = "clk25"
    lvcmos = Attrs(IO_TYPE="LVCMOS33")
    resources = [
        Resource("clk25", 0, Pins("P6", dir="i"), Clock(25e6), lvcmos),
        Resource("led", 0, Pins("T6", dir="o"), lvcmos),
        Resource("key", 0, PinsN("R7", dir="i"), lvcmos),
        Resource(
            "flash", 0,
            Subsignal("cs", Pins("N8", dir="o"), lvcmos),
            Subsignal("so", Pins("T7", dir="i"), lvcmos),
            Subsignal("si", Pins("T8", dir="o"), lvcmos)),
        Resource(
            "led_common", 0,
            Subsignal("a", Pins("N5", dir="o"), lvcmos),
            Subsignal("b", Pins("N3", dir="o"), lvcmos),
            Subsignal("c", Pins("P3", dir="o"), lvcmos),
            Subsignal("d", Pins("P4", dir="o"), lvcmos),
            Subsignal("e", Pins("N4", dir="o"), lvcmos),
            Subsignal("clk", Pins("M3", dir="o"), lvcmos),
            Subsignal("lat", Pins("N1", dir="o"), lvcmos),
            Subsignal("oe", Pins("M4", dir="o"), lvcmos)),
        Resource(
            "eth_common", 0,
            Subsignal("reset", PinsN("R6", dir="o"), lvcmos)),
    ]
    connectors = []

    leds = [
        # R0, G0, B0, R1, G1, B1
        ['C4', 'D4', 'E4', 'D3', 'E3', 'F4'],           # J1
        ['F3', 'F5', 'G3', 'G4', 'H3', 'H4'],           # J2
        ['G5', 'H5', 'J5', 'J4', 'B1', 'C2'],           # J3
        ['C1', 'D1', 'E2', 'E1', 'F2', 'F1'],           # J4
        ['G2', 'G1', 'H2', 'K5', 'K4', 'L3'],           # J5
        ['L4', 'L5', 'P2', 'R2', 'T2', 'R3'],           # J6
        ['T3', 'R4', 'M5', 'P5', 'N6', 'N7'],           # J7
        ['P7', 'M7', 'P8', 'R8', 'M8', 'M9'],           # J8
        ['P11', 'N11', 'M11', 'T13', 'R12', 'R13'],     # J9
        ['R14', 'T14', 'D16', 'C15', 'C16', 'B16'],     # J10
        ['B15', 'C14', 'T15', 'P15', 'R15', 'P12'],     # J11
        ['P13', 'N12', 'N13', 'M13', 'P14', 'N14'],     # J12
        ['H15', 'H14', 'G16', 'F16', 'G15', 'F15'],     # J13
        ['E15', 'E16', 'L12', 'L13', 'M14', 'L14'],     # J14
        ['J13', 'K13', 'J12', 'H13', 'H12', 'G12'],     # J15
        ['G14', 'G13', 'F12', 'F13', 'F14', 'E14'],     # J16
    ]

    # Currently unknown inputs/outputs/bidirectional
    inputs = [
        'A10', 'A12', 'J1', 'J2', 'J3', 'K1', 'K2', 'K3', 'L15', 'L16', 'M15',
        'M16', 'P16', 'R16']
    outputs = [
        'A6', 'A7', 'A8', 'A9', 'A15', 'B5', 'B6', 'B7', 'B8', 'B9', 'B10',
        'C7', 'C8', 'C9', 'C10', 'D8', 'D9', 'E8', 'E9', 'E12', 'E13', 'J14',
        'J15', 'J16', 'K12', 'K14', 'K15', 'K16', 'L1', 'L2', 'M1', 'M2', 'M6',
        'M12', 'P1', 'R1', 'R5']
    bidis = [
        'A2', 'A3', 'A4', 'A5', 'A11', 'A13', 'A14', 'B2', 'B3', 'B4', 'B11',
        'B12', 'B13', 'B14', 'C3', 'C5', 'C6', 'C11', 'C12', 'C13', 'D5', 'D6',
        'D7', 'D10', 'D11', 'D12', 'D13', 'D14', 'E5', 'E6', 'E7', 'E10',
        'E11', 'T4']

    def __init__(self):
        lvcmos = self.lvcmos
        for jidx, pins in enumerate(self.leds):
            self.resources += [Resource(
                "led_rgb", jidx,
                Subsignal("r0", Pins(pins[0], dir="o"), lvcmos),
                Subsignal("g0", Pins(pins[1], dir="o"), lvcmos),
                Subsignal("b0", Pins(pins[2], dir="o"), lvcmos),
                Subsignal("r1", Pins(pins[3], dir="o"), lvcmos),
                Subsignal("g1", Pins(pins[4], dir="o"), lvcmos),
                Subsignal("b1", Pins(pins[5], dir="o"), lvcmos))]
        for pin in self.outputs:
            self.resources += [Resource(pin, 0, Pins(pin, dir="o"), lvcmos)]
        for pin in self.inputs:
            self.resources += [Resource(pin, 0, Pins(pin, dir="i"), lvcmos)]
        for pin in self.bidis:
            self.resources += [Resource(pin, 0, Pins(pin, dir="io"), lvcmos)]
        super().__init__()


class Top(nm.Elaboratable):
    def elaborate(self, platform):
        m = nm.Module()

        # Use OSCG so we can still clock with PHYs in reset
        # (otherwise, the PHYs stop running the XO).
        m.domains.sync = cd_osc = nm.ClockDomain("sync")
        m.submodules.oscg = nm.Instance("OSCG", p_DIV=12, o_OSC=cd_osc.clk)

        # Hold PHYs in reset
        m.d.comb += platform.request("eth_common").reset.eq(1)

        # Flash LED
        led = platform.request("led")
        ctr = nm.Signal(22)
        m.d.sync += ctr.eq(ctr + 1)
        m.d.comb += led.o.eq(ctr[-1])

        # UART on outputs
        v = nm.Signal()
        p = nm.Signal()
        m.d.sync += p.eq(ctr[-4]), v.eq(p != ctr[-4])
        for idx, pin in enumerate(platform.outputs):
            print(f"{idx:02X} {pin}")
            uart = UART(idx)
            m.submodules += uart
            m.d.comb += platform.request(pin).o.eq(uart.tx_o), uart.valid.eq(v)

        return m


def main():
    platform = ColorLite5A75E_V6_0_Platform()
    platform.build(Top(), ecppack_opts=["--compress"])
    subprocess.run(["ffp", "ecp5", "program", "build/top.bit"])


if __name__ == "__main__":
    main()
