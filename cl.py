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


class Mem2Parallel(nm.Elaboratable):
    """
    When triggered on dv, clocks out n words from the start of read_port.
    """
    def __init__(self, read_port, div=5):
        # Inputs
        self.dv = nm.Signal()
        self.n = nm.Signal(read_port.addr.width)

        # Outputs
        self.o = nm.Signal(read_port.data.width)
        self.clk = nm.Signal()
        self.ready = nm.Signal()

        self.read_port = read_port
        self.div = div

    def elaborate(self, platform):
        m = nm.Module()

        n = nm.Signal(self.n.width)
        addr = self.read_port.addr
        ctr = nm.Signal(range(self.div))

        with m.FSM():
            with m.State("IDLE"):
                m.d.sync += n.eq(self.n), addr.eq(0)
                m.d.sync += self.o.eq(0)
                with m.If(self.dv):
                    m.next = "DATA"
            with m.State("DATA"):
                m.d.sync += ctr.eq(self.div - 2)
                m.d.sync += addr.eq(addr + 1)
                m.d.sync += self.o.eq(self.read_port.data)
                m.d.sync += self.clk.eq(0)
                m.next = "WAIT"
            with m.State("WAIT"):
                m.d.sync += ctr.eq(ctr - 1)
                m.d.sync += self.clk.eq(1)
                with m.If(ctr == 0):
                    with m.If(addr == n):
                        m.next = "IDLE"
                    with m.Else():
                        m.next = "DATA"
        return m


class RGMIIRx(nm.Elaboratable):
    def __init__(self, write_port):
        # Inputs
        self.rxd = nm.Signal(8)
        self.rxctl = nm.Signal(2)

        # Outputs
        self.dv = nm.Signal()
        self.n = nm.Signal(11)

        self.wp = write_port

    def elaborate(self, platform):
        m = nm.Module()

        n = nm.Signal(11)
        rxdv = self.rxctl[0]

        m.d.sync += self.wp.addr.eq(n)
        m.d.sync += self.wp.data.eq(self.rxd)

        with m.FSM():
            with m.State("IDLE"):
                m.d.comb += self.wp.en.eq(0)
                m.d.sync += self.dv.eq(0), self.n.eq(0)
                with m.If(rxdv):
                    m.d.sync += n.eq(1)
                    m.next = "DATA"
                with m.Else():
                    m.d.sync += n.eq(0)
            with m.State("DATA"):
                m.d.comb += self.wp.en.eq(1)
                m.d.sync += n.eq(n + 1)
                with m.If(~rxdv):
                    m.d.sync += self.dv.eq(1), self.n.eq(n), n.eq(0)
                    m.next = "IDLE"

        return m


class RGMIITx(nm.Elaboratable):
    def __init__(self, read_port):
        # Inputs
        self.dv = nm.Signal()
        self.n = nm.Signal(11)

        # Outputs
        self.txd = nm.Signal(8)
        self.txctl = nm.Signal(2)
        self.ready = nm.Signal()

        self.rp = read_port

    def elaborate(self, platform):
        m = nm.Module()
        n = nm.Signal(11)

        txen = nm.Signal()
        txerr = nm.Signal()
        m.d.comb += txerr.eq(0)
        m.d.comb += self.txctl[0].eq(txen), self.txctl[1].eq(txen ^ txerr)
        m.d.comb += self.txd.eq(self.rp.data)

        with m.FSM():
            with m.State("IDLE"):
                m.d.comb += self.ready.eq(1)
                m.d.sync += n.eq(self.n)
                with m.If(self.dv):
                    m.d.sync += txen.eq(1), self.rp.addr.eq(1)
                    m.next = "DATA"
                with m.Else():
                    m.d.sync += txen.eq(0), self.rp.addr.eq(0)
            with m.State("DATA"):
                m.d.comb += self.ready.eq(0)
                m.d.sync += txen.eq(1), self.rp.addr.eq(self.rp.addr + 1)
                with m.If(self.rp.addr == n - 1):
                    m.next = "IDLE"

        return m


def test_rgmii_tx():
    from nmigen.sim import pysim
    m = nm.Module()
    mem = nm.Memory(width=8, depth=64, init=b"Hello World! Ignore this.")
    m.submodules.rp = rp = mem.read_port(transparent=False)
    m.submodules.tx = tx = RGMIITx(rp)

    def tb():
        yield
        yield
        yield tx.n.eq(12)
        yield tx.dv.eq(1)
        yield
        yield tx.n.eq(0)
        yield tx.dv.eq(0)
        data = []
        for _ in range(16):
            yield
            if (yield tx.txctl[0]):
                data.append((yield tx.txd))
        assert bytes(data) == b"Hello World!"

    sim = pysim.Simulator(m)
    sim.add_clock(1/125e6)
    sim.add_sync_process(tb)
    with sim.write_vcd("rgmii_tx.vcd"):
        sim.run()


def test_mem_to_parallel():
    from nmigen.sim import pysim
    m = nm.Module()
    mem = nm.Memory(width=8, depth=64, init=b"Hello World! Ignore this.")
    m.submodules.rp = rp = mem.read_port()
    m.submodules.tx = tx = Mem2Parallel(rp)

    def tb():
        yield
        yield tx.n.eq(12)
        yield tx.dv.eq(1)
        yield
        yield tx.n.eq(0)
        yield tx.dv.eq(0)
        for _ in range(70):
            yield

    sim = pysim.Simulator(m)
    sim.add_clock(1/125e6)
    sim.add_sync_process(tb)
    with sim.write_vcd("mem2parallel.vcd"):
        sim.run()


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
            Subsignal("mdc", Pins("R5", dir="o"), lvcmos),
            Subsignal("mdio", Pins("T4", dir="io"), lvcmos),
            Subsignal("rst", PinsN("R6", dir="o"), lvcmos)),
        Resource(
            "phy", 0,
            Subsignal("txc", Pins("L1", dir="o"), lvcmos),
            Subsignal("txd", Pins("M2 M1 P1 R1", dir="o"), lvcmos),
            Subsignal("txctl", Pins("L2", dir="o"), lvcmos),
            Subsignal("rxc", Pins("J1", dir="i"), Clock(125e6), lvcmos),
            Subsignal("rxd", Pins("J3 K2 K1 K3", dir="i"), lvcmos),
            Subsignal("rxctl", Pins("J2", dir="i"), lvcmos)),
        Resource(
            "phy", 1,
            Subsignal("txc", Pins("J16", dir="o"), lvcmos),
            Subsignal("txd", Pins("K16 J15 J14 K15", dir="o"), lvcmos),
            Subsignal("txctl", Pins("K14", dir="o"), lvcmos),
            Subsignal("rxc", Pins("M16", dir="i"), Clock(125e6), lvcmos),
            Subsignal("rxd", Pins("M15 R16 L15 L16", dir="i"), lvcmos),
            Subsignal("rxctl", Pins("P16", dir="i"), lvcmos)),
        Resource(
            "sdram", 0,
            Subsignal("we", PinsN("B5", dir="o"), lvcmos),
            Subsignal("cas", PinsN("A6", dir="o"), lvcmos),
            Subsignal("ras", PinsN("B6", dir="o"), lvcmos),
            Subsignal("ba", Pins("B7 A8", dir="o"), lvcmos),
            Subsignal("a", Pins("A9 B9 B10 C10 D9 C9 E9 D8 E8 C7 B8", dir="o"),
                      lvcmos),
            Subsignal("d",
                      Pins("D5 C5 E5 C6 D6 E6 D7 E7 D10 C11 D11 C12 E10 C13 "
                           "D13 E11 A5 B4 A4 B3 A3 C3 A2 B2 D14 B14 A14 B13 "
                           "A13 B12 B11 A11", dir="io"),
                      lvcmos),
            Subsignal("clk", Pins("C8", dir="o"), lvcmos)),
    ]
    connectors = []

    # Used by __init__ to create each individual LED pin header
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
        ['P13', 'N12', 'N13', 'M12', 'P14', 'N14'],     # J12
        ['H15', 'H14', 'G16', 'F16', 'G15', 'F15'],     # J13
        ['E15', 'E16', 'L12', 'L13', 'M14', 'L14'],     # J14
        ['J13', 'K13', 'J12', 'H13', 'H12', 'G12'],     # J15
        ['G14', 'G13', 'F12', 'F13', 'F14', 'E14'],     # J16
    ]

    # Currently unknown inputs/outputs/bidirectional
    inputs = ['A10', 'A12']
    outputs = ['A7', 'A15', 'E12', 'E13', 'K12', 'M6', 'M13']
    bidis = ['D12']

    def __init__(self, *args, **kwargs):
        lvcmos = self.lvcmos

        # Create resources for each LED header
        for jidx, pins in enumerate(self.leds):
            self.resources += [Resource(
                "led_rgb", jidx,
                Subsignal("r0", Pins(pins[0], dir="o"), lvcmos),
                Subsignal("g0", Pins(pins[1], dir="o"), lvcmos),
                Subsignal("b0", Pins(pins[2], dir="o"), lvcmos),
                Subsignal("r1", Pins(pins[3], dir="o"), lvcmos),
                Subsignal("g1", Pins(pins[4], dir="o"), lvcmos),
                Subsignal("b1", Pins(pins[5], dir="o"), lvcmos))]

        # Create resources for each unknown pin
        for pin in self.outputs:
            self.resources += [Resource(pin, 0, Pins(pin, dir="o"), lvcmos)]
        for pin in self.inputs:
            self.resources += [Resource(pin, 0, Pins(pin, dir="i"), lvcmos)]
        for pin in self.bidis:
            self.resources += [Resource(pin, 0, Pins(pin, dir="io"), lvcmos)]
        super().__init__(*args, **kwargs)


class Top(nm.Elaboratable):
    def elaborate(self, platform):
        m = nm.Module()

        # Use OSCG so we can still clock with PHYs in reset
        # (otherwise, the PHYs stop running the XO).
        m.domains.sync = cd_osc = nm.ClockDomain("sync")
        m.submodules.oscg = nm.Instance("OSCG", p_DIV=12, o_OSC=cd_osc.clk)

        # Flash LED
        led = platform.request("led")
        ctr = nm.Signal(22)
        m.d.sync += ctr.eq(ctr + 1)
        m.d.comb += led.o.eq(ctr[-1])

        # Enable PHYs
        m.d.comb += platform.request("eth_common").rst.eq(0)

        # Connect PHY1
        phy1 = platform.request(
            "phy", 1, xdr={"rxd": 2, "rxctl": 2, "txd": 2, "txctl": 2})
        m.domains.rxc = cd_rxc = nm.ClockDomain("rxc")
        m.d.comb += [
            cd_rxc.clk.eq(phy1.rxc.i),
            phy1.rxd.i_clk.eq(phy1.rxc.i),
            phy1.rxctl.i_clk.eq(phy1.rxc.i),
            phy1.txc.o.eq(phy1.rxc.i),
            phy1.txd.o_clk.eq(phy1.rxc.i),
            phy1.txctl.o_clk.eq(phy1.rxc.i),
        ]

        # Create RGMII receiver
        dr_rxc = nm.DomainRenamer("rxc")
        rxmem = nm.Memory(width=8, depth=2048)
        m.submodules.rx_rp = rx_rp = rxmem.read_port(transparent=False)
        m.submodules.rx_wp = rx_wp = dr_rxc(rxmem.write_port())
        m.submodules.rgmii_rx = rgmii_rx = dr_rxc(RGMIIRx(rx_wp))
        m.d.comb += [
            rgmii_rx.rxd.eq(nm.Cat(phy1.rxd.i0, phy1.rxd.i1)),
            rgmii_rx.rxctl.eq(nm.Cat(phy1.rxctl.i0, phy1.rxctl.i1)),
        ]

        # Dummy TX packet sends some UDP data
        txpacket = [
            # Preamble and SFD
            0x55, 0x55, 0x55, 0x55, 0x55, 0x55, 0x55, 0xD5,
            # Destination MAC address
            0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
            # Source MAC address is made up locally-administered
            0x02, 0x00, 0x01, 0x02, 0x03, 0x04,
            # IPv4 ethertype
            0x08, 0x00,
            # IPv4 header
            0x45, 0x00, 0x04, 0x1c,
            0x00, 0x00, 0x40, 0x00,
            0x40, 0x11, 0x22, 0xc1,
            0x0a, 0x00, 0x00, 0x10,
            0x0a, 0x00, 0x00, 0x01,
            # UDP header
            0xb7, 0x69, 0x04, 0xd2,
            0x04, 0x08, 0x00, 0x00,
            # UDP payload
        ] + list(range(256))*4 + [
            # FCS
            0xc1, 0x35, 0x83, 0xf2,
        ]

        # Create RGMII transmitter
        txmem = nm.Memory(width=8, depth=2048, init=txpacket)
        m.submodules.tx_rp = tx_rp = dr_rxc(txmem.read_port(transparent=False))
        m.submodules.rgmii_tx = rgmii_tx = dr_rxc(RGMIITx(tx_rp))
        m.d.comb += [
            nm.Cat(phy1.txd.o0, phy1.txd.o1).eq(rgmii_tx.txd),
            nm.Cat(phy1.txctl.o0, phy1.txctl.o1).eq(rgmii_tx.txctl),
        ]
        ctr = nm.Signal(5)
        m.d.comb += rgmii_tx.n.eq(len(txpacket)), rgmii_tx.dv.eq(ctr == 16)
        with m.If(rgmii_tx.ready):
            m.d.sync += ctr.eq(ctr + 1)
        with m.Else():
            m.d.sync += ctr.eq(0)

        # Dump received packets over parallel interface
        m.submodules.m2p = m2p = Mem2Parallel(rx_rp, div=2)
        m.d.comb += m2p.n.eq(rgmii_rx.n), m2p.dv.eq(rgmii_rx.dv)
        led_j7 = platform.request("led_rgb", 6)
        led_j8 = platform.request("led_rgb", 7)
        m.d.comb += nm.Cat(
            led_j8.r0.o, led_j8.g0.o, led_j8.b0.o, led_j8.r1.o,
            led_j7.r0.o, led_j7.g0.o, led_j7.b0.o, led_j7.r1.o).eq(m2p.o)
        m.d.comb += led_j7.g1.o.eq(m2p.clk)

        # UART on unknown outputs
        """
        v = nm.Signal()
        p = nm.Signal()
        m.d.sync += p.eq(ctr[-4]), v.eq(p != ctr[-4])
        for idx, pin in enumerate(platform.outputs):
            print(f"{idx:02X} {pin}")
            uart = UART(idx)
            m.submodules += uart
            pin = platform.request(pin)
            m.d.comb += pin.o.eq(uart.tx_o), uart.valid.eq(v)
        """

        return m


def main():
    platform = ColorLite5A75E_V6_0_Platform(toolchain="Trellis")
    platform.build(Top(), ecppack_opts=["--compress"])
    subprocess.run(["ffp", "ecp5", "program", "build/top.bit"])


if __name__ == "__main__":
    main()
