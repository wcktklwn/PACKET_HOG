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

## PacketHog-18

Unreleased 18-socket layout in `hardware/PacketHog-18/`. PacketHog-V2 above is unchanged and is still the board for sale. This board has not been fabricated or powered.

18 XIAO ESP32-C5 sockets, 2 rows of 9. Nodes 1–9 run along the top edge and 10–18 along the bottom, on the same 35 mm SMA pitch as V2. Outline is 330.1 mm × 86.1 mm, 1.6 mm, 2-layer. The V2 case does not fit, and there is no case for this board. Seat each module the same way as V2: USB-C toward the nearby capacitor, the same direction the board USB connector (J19) faces.

The USB-C input is the V2 circuit, shifted to the right edge: 5.1 kΩ on CC1/CC2, series Schottky, PTC fuse. That path cannot feed 18 radios. The input for a full array is J20, a Phoenix MKDS 1,5/2-5.08 screw terminal on the left. Square pad is GND, round pad is VIN, and the wire openings face the board edge. F2 is a Littelfuse 0451010, a 10 A very-fast Nano2 fuse, in series with Q1, an onsemi NTMFS002P03P8Z P-channel MOSFET. Its Rds(on) maximum is 2.3 mΩ at Vgs = −4.5 V, about 18 mV and 0.15 W at 8 A using that datasheet maximum. The package is CASE 506EZ. The footprint on the board is the library SO-8 FL land ONSemi_SO-8FL_488AA, which matches the 506EZ recommended land. The exposed drain pad is not a hand-solder package.

Q2, an MMBT3904, pulls the gate down only while the fused input is present, so the FET turns on for the screw terminal and stays off when only USB is connected. USB then cannot backfeed into J20, and the USB Schottky stays reverse-biased while the FET drop is tens of millivolts. D4, a BZT52C12, clamps the gate-source voltage. It does not clamp the input. This is not over-voltage protection: the body diode and the channel both pass a higher VIN onto the 5 V rail. The silk says 5V ONLY. A 12 V supply on J20 would destroy the modules. Reverse polarity on J20 leaves the FET off.

+5 V leaves the FET on a 2.8 mm spine, then a 4.0 mm bus along the top (ending at x = 392.85 mm) and a 3.2 mm bus along the bottom (ending at x = 386 mm). Past that, the original 1 mm trace still feeds the last socket. That segment carries one node. None of this drop or heating has been measured, and the board has not been powered.

On J19 the four stacked GND lands, A1, A12, B1, and B12, are 1.08 mm long. GCT's recommended land is 1.15 mm. Each land is 0.07 mm shorter on the end next to the Ø0.65 locating peg, and the far end stays on the datasheet coordinate, so those holes meet the 0.25 mm clearance rule. The signal and VBUS pads stay at 1.15 mm. PacketHog-V2 still uses the 1.15 mm lands, so J11 still has those four hole-clearance errors.

The ground zone was refilled in KiCad 10.0.8 and it covers the new columns and the inlet. DRC reports no unconnected nets and no errors. Warnings remain: 79 library-footprint notes, 55 silk-over-copper items, 4 library-footprint mismatches, 3 silk overlaps, and one dangling end on the wide bottom bus. The schematic in that folder is still the 10-node drawing. Do not update the PCB from it. The PCB is the netlist.

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
