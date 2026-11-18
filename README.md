# PACKET_HOG

10-node ESP32-C5 scanner carrier board. One master, a bank of scan nodes, single USB-C power in.

Status: **PacketHog-V2 first batch is sold out. A restock order has been placed** (no firm arrival date, no preorders; the store page reopens when boards are in hand). V1 (first batch of 8) is also sold out. Every V2 board is assembled and checked before it ships.

## What it is

Packet Hog C5 is a carrier board built around the Seeed XIAO ESP32-C5. One master node coordinates a bank of scanner nodes over ESP-NOW, each scanning dual-band Wi-Fi (2.4/5 GHz) and BLE. The whole array runs off a single USB-C input.

Built deliberately barebones with power distribution, node bank, antenna breakout, nothing else.

Board size: 183.7mm x 121.1mm (7.23 x 4.77 in), 1.6mm thick. Standard case: 188.1mm x 125.5mm, about 29mm tall. Fan case: about 45.5mm tall.

## Buy it

PacketHog-V2: **$100**, shipping to the US only right now. Same price for every option. **Currently sold out, restock ordered.** Restock alert signup: [tally.so/r/Z9Elga](https://tally.so/r/Z9Elga)

[fusedstamen.com/packethogv2](https://fusedstamen.com/packethogv2)

Options at checkout when available: soldered RP-SMA connectors, or bare board (as received from assembly, SMA positions empty). Every board comes with the standard printed case. A case with a 30mm fan opening is available to print from this repo if you want one. Name and Discord are optional at checkout; I only need a shipping address and email.

Modules (Seeed XIAO ESP32-C5), antennas and fan not included. Outside the US, message me on Discord first - import VAT, duties and carrier fees are paid by the buyer on delivery.

## Case hardware

- Standard case: 4x M3x25 screws into M3 heat-set inserts.
- Fan case lid: 4x M3x40 (about 2.5mm of thread engagement; use M3x45 if it feels loose).
- Fan: 5V, 2-pin, 30mm. Check the fan thickness against the fan case. Fan screws are 2-4x M3x8 to M3x10 self-tapping. Specific fans are untested.

**Note on the RP-SMA connectors (J1-J10):** they're mounted to the board for physical support only - there's no PCB trace routing antenna signal to them. Each node module's signal reaches its SMA connector through a short U.FL-to-RP-SMA pigtail from the module itself, not through the board's copper. Same setup as the Piglet, in case that's caused confusion before.

**Mounting orientation:** every header position follows the same rule. Seat each XIAO module so its USB-C port faces the same side as the nearby capacitor (e.g. C11 sits next to the H1A/H1B pair) - that side matches the direction the onboard USB-C (J11) faces. The module's U.FL antenna pad ends up on the opposite side. Get this backwards and the module won't seat or power on correctly; double check before powering on.

## Version history

- **Prototype 1** - First routed prototype. Had a wiring mistake around the CH224K USB-C PD negotiation chip: on a "smart" PD-negotiating charger, the board could get handed the wrong voltage, which risked damaging the nodes. Safe with plain 5V "dumb" chargers only.
- **Prototype 2** - CH224K removed entirely; replaced with 5.1kΩ pull-down resistors on CC1/CC2, forcing 5V-default behavior regardless of charger. Also added reverse-polarity protection, a fuse at the power input, bulk + per-node decoupling capacitors, and 10 edge-mounted SMA connectors for external antennas. Had a layout flaw: SMA connector mounts sat too close to the header pins, leaving insufficient clearance to hand-solder/route pigtail connections without crowding the header footprints. Also shipped without mounting holes, so boards couldn't be securely fastened into a case.
- **PacketHog-V1** - Fixes the clearance flaw by widening the board (77.1mm to 121.1mm) to give proper spacing between the SMA connectors and the header rows. Added M3 mounting holes. Rounded board corners. SMA connectors hand-soldered (not PCBA-populated). First batch of 8 sold out.
- **PacketHog-V2** - Current revision. Power traces widened from 0.5mm to 1.0mm (the USB-C-to-fuse run is limited by the connector pad width). Added a 2-pin fan header (5V + GND, factory assembled). Added an AUX 5V/GND through-hole header, unpopulated, same pinout as the fan header (square pad GND, round pad +5V). Added 7 labelled test points: USB input voltage, between fuse and diode, 5V rail, far-end 5V, and 3x GND. Silkscreen cleanup; back label says V2. Power parts unchanged from V1. Still hand-soldered through-hole RP-SMA (mechanical only), plain USB-C 5V with no PD, 3A maximum (PTC fuse, fan counts against it).
- **Planned for V3** - Power switch, power LED, onboard U.FL plus edge SMA, battery input, possibly 4-layer.

**Known issue:** some nodes drop out with certain off-brand USB cables or power banks. Cause not yet measured; V2 does not claim to fix it. Use a decent USB-C cable and a supply that can deliver 5V at 3A.

## PacketHog-20

Unreleased 20-socket layout in `hardware/PacketHog-20/`. PacketHog-V2 above is unchanged and is still the board for sale. This board has not been fabricated or powered.

20 XIAO ESP32-C5 sockets, 2 rows of 10. Nodes 1–10 run along the top edge and 11–20 along the bottom, on the same 35 mm SMA pitch as V2. Board size: 432.05 mm × 86.10 mm (17.01 × 3.39 in), 1.6 mm thick, 2-layer, 1 oz. Corners are rounded at a 3 mm radius. The V2 case does not fit, and there is no case for this board. Seat each module the same way as V2: USB-C toward the nearby capacitor, the same direction the board USB connector (J21) faces. V2 fits a U.FL beside each SMA and a short trace between the center pins. This board leaves that connector and that trace off. The antenna is still the module's own U.FL and a pigtail to the SMA.

The USB-C input is the V2 circuit, shifted to the right edge: 5.1 kΩ on CC1/CC2, series Schottky, PTC fuse. That path cannot feed 20 radios. The high-current input is J22, a Phoenix MKDS 1,5/2-5.08 screw terminal on the left. Square pad is GND, round pad is VIN, and the wire openings face the board edge. F2 is a Littelfuse 0451010, a 10 A very-fast Nano2 fuse, in series with Q1, an onsemi NTMFS002P03P8Z P-channel MOSFET. Its Rds(on) maximum is 2.3 mΩ at Vgs = −4.5 V, about 18 mV and 0.15 W at 8 A using that datasheet maximum. The package is CASE 506EZ. The footprint on the board is the library SO-8 FL land ONSemi_SO-8FL_488AA, which matches the 506EZ recommended land. The exposed drain pad is not a hand-solder package.

Q2, an MMBT3904, pulls the gate down only while the fused input is present, so the FET turns on for the screw terminal and stays off when only USB is connected. USB then cannot backfeed into J22, and the USB Schottky stays reverse-biased while the FET drop is tens of millivolts. D4, a BZT52C12, clamps the gate-source voltage. It does not clamp the input. The body diode and the channel both pass a higher VIN onto the 5 V rail. The silk says 5V ONLY. A 12 V supply on J22 would destroy the modules. Reverse polarity on J22 leaves the FET off.

The screw terminal, the USB input, and the buck share an unswitched +5V island. On the back of the inlet that tie is 2.8 mm. It has not been measured at the array current. Q7, another NTMFS002P03P8Z, connects the island to the load net. Its source is the island and its drain is the load, so the body diode does not run the radios when the FET is off. From there a 2.8 mm spine feeds a 4.0 mm bus along the top, ending at x = 419.50 mm, and a 3.2 mm bus along the bottom, from the bulk capacitor at x = 77.70 mm to x = 413.50 mm. A rough IPC-2221 figure for 10 A on 1 oz external copper at a 20 °C rise is about 4.6 mm, and the spine stays 2.8 mm because the header pins sit next to it. An estimate of simultaneous transmit, about 0.44 A per node at 5 V, is about 8.9 A. The spine and the 8 A buck below are sized under that estimate. An average scan is far below simultaneous transmit. None of this drop or heating has been measured.

SW1 is a C&K JS202011CQN, a maintained DPDT slide switch. One pole grounds Q7's gate in the ON position. R23, 100 kΩ to the island, holds the gate up when that pole is open, so the FET stays off. The other pole grounds the base of Q8, an MMBT3904, in the ON position. When the switch is open, R22, 100 kΩ from the pack, turns Q8 on and holds the buck enable low. The switch carries gate and base current, not the radio current. Charging stays on the fused input and continues while the radios are off. USB is on the island side of Q7, so the board USB does not run the radios with the switch open either. The silk says ON on the wired throw. The C&K pin drawing was not available, so that direction has not been checked. If the slider is backwards, both positions still exist and the silk names the one that is wired on. Q7 uses the same 2.3 mΩ maximum, about 18 mV and 0.15 W at 8 A from that datasheet figure. That drop has not been measured. The switch does not clamp the input. The inlet silk still says 5V ONLY.

The pack is external: a 2S Li-ion pack with its own BMS, plugged into J23, an XT30PW-M. Onboard 18650 holders were rejected. One cell cannot supply the array at 5 V, and a holder adds reverse insertion and height. Library silk marks J23 pad 2 as + and pad 1 as −. That marking is the library silk and has not been checked against the AMASS drawing. Confirm it before building a cable. J24 is a JST XH B3B-XH-A balance header. Pin 1 is pack−, pin 2 is the mid-cell sense, and pin 3 is cell+ on the cell side of Q3, the same node as J23 pad 2. The balance plug is a sense connection for the charger. It is not pack protection, and pin 3 must stay on the cell side of Q3 so the cable does not bypass the reverse-polarity FET.

Q3, another NTMFS002P03P8Z, has its drain toward the pack and its source on the protected PACK rail. A reversed pack leaves the FET off. A correct pack bootstraps through the body diode and the FET turns on. This does not clamp the pack voltage.

U1 is an Injoinic IP2326 boost charger. It charges the pack from the fused screw-terminal input (VIN_F). With the adapter unplugged the charger input is open, so the buck cannot feed the charger. Charge current is about 1 A (90.9 kΩ on ISET). The charge timer is 12 h (120 kΩ on TIME_SET), so a larger pack can hit the timeout and stop early. The NTC pin is a fixed 51 kΩ to ground, not a cell thermistor. CON_SEL and VSET are open, which selects 2S and 8.4 V. The datasheet application note's series 0.5 Ω on VIN is omitted, and so is the balance-bleed resistor. The pack BMS does the balance bleed. A 1 A charge into 2S is on the order of 2 A from the 5 V input. That current shares F2 with the radios. Full transmit while charging sits at the 10 A hold rating of the fuse.

U2 is a TI TPS56837 8 A synchronous buck, 500 kHz, set to about 5.0 V (73.2 kΩ / 10.0 kΩ). Q4 connects the buck onto the unswitched island through another P-channel FET, and Q5 holds the buck off while the adapter is present, so the adapter runs the radios and the charger fills the pack. Q8 does that same hold from the pack while SW1 is open, so an unloaded buck does not drain the pack with the radios off. The enable pin is held by those transistors. Its absolute maximum is 6 V, so it stays off the pack. The 5 V output needs the pack above about 5.5 V. The pack BMS should cut the pack off before that. TI's thermal numbers are from a 4-layer evaluation board. This board is 2-layer 1 oz, so 8 A continuous will run hotter. That has not been measured.

On J21 the four stacked GND lands, A1, A12, B1, and B12, are 1.08 mm long. GCT's recommended land is 1.15 mm. Each land is 0.07 mm shorter on the end next to the Ø0.65 locating peg, and the far end stays on the datasheet coordinate, so those holes meet the 0.25 mm clearance rule. The signal and VBUS pads stay at 1.15 mm. PacketHog-V2 still uses the 1.15 mm lands, so J11 still has those four hole-clearance errors.

The ground zone was refilled in KiCad 10.0.8 on 2026-11-17, after the onboard U.FL connectors were removed. DRC reports no unconnected nets, no errors, and no warnings. The V2 back logo was removed. Shifted onto this outline it covered the top-row connectors. The schematic in that folder is still the 10-node drawing. Do not update the PCB from it. The PCB is the netlist.

## Status of what's tested

| Component | Status |
|---|---|
| Power distribution | Tested |
| Fully populated board scanning | Tested |
| PacketHog-V1 board fab/assembly | Tested |
| PacketHog-V2 board fab/assembly | Tested (each board checked before shipping) |
| Fan case (30mm) | Complete, files in this repo |
| Antenna path (module -> U.FL/SMA pigtail) | Tested |

## Thermal notes

I ran a thermal test on a V1 board in a closed case in a room at about 78F (25.5C). After 75+ minutes of running, the air inside the case levelled off around 96F (36C) and the nodes measured about 102-110F (39-43C) with a thermocouple. An IR thermometer read higher, 108-118F (42-48C), which is typical of IR on shiny surfaces, so treat the thermocouple numbers as the more reliable set. The test was on V1; V2 uses the same power parts with wider copper.

For reference, Espressif rates the ESP32-C5 modules for an operating ambient temperature of -40C to 85C (185F). The Seeed XIAO ESP32-C5 board is listed at 0C to 85C. Nodes ran well inside that range in my test, so I don't think a fan is necessary. The fan header and fan case are there if you want extra airflow or plan to run in a hot environment, such as a car parked in the sun. Those limits are ambient ratings, so a very hot environment leaves less margin.

Test data: [Packet_Hog-v1-Thermal_Testing.xlsx](./Packet_Hog-v1-Thermal_Testing.xlsx)

## License

Licensed under **CC BY-NC 4.0** - see [LICENSE](./LICENSE) for full terms.

Short version: you're free to build one for yourself and modify it for personal, non-commercial use. Selling anything built from this design - boards, kits, or products - requires explicit permission from me first. See the LICENSE file for exactly what that means.

## Contact

- Discord: `Fusedstamen`
- GitHub: [github.com/FusedStamen](https://github.com/FusedStamen)

If you want to use this commercially, reach out through one of the above. Don't assume permission - wait for a yes.

## Name

"Packet Hog" - a reference to [Bilmuri](https://bilmuri.com), not a fork or rename of anyone else's project.
