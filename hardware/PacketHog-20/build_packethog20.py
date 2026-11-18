#!/usr/bin/env python3
"""Build PacketHog-20 from the PacketHog-V2 PCB.

10 XIAO sockets become 20 (2 rows x 10). The original layout shifts right by
five column pitches and five cloned columns fill the left side. The V2 USB-C
circuit is unchanged and cannot run 20 radios. J21's four GND lands are
0.07 mm shorter on the locating-peg end so they clear the 0.25 mm hole rule.
The inlet is a 5 V screw terminal, a 10 A fuse, and a P-channel ideal-diode
OR onto the +5 V buses. Left of that inlet is a 2S pack connector, an IP2326
boost charger fed from the fused input, and a TPS56837 buck OR'd onto +5V.
"""

from __future__ import annotations

import copy
import math
import os
import shutil
import uuid
from pathlib import Path

ROOT = Path("/Users/wcktklwn/Documents/scripts/PACKET_HOG")
SRC = ROOT / "hardware" / "PacketHog-V2" / "PacketHog-V2.kicad_pcb"
DEST_DIR = ROOT / "hardware" / "PacketHog-20"
DEST_PCB = DEST_DIR / "PacketHog-20.kicad_pcb"

DX_SHIFT = 175.0  # 5 columns * 35 mm
COL_PITCH = 35.0
TEMPLATE_SMA_X = 135.0
NEW_SMA_X = [100.0, 135.0, 170.0, 205.0, 240.0]  # final, pre-shift coordinates
BUS_TOP_Y = 97.0
BUS_BOT_Y = 124.5
# Outline. The inlet stays where V2/18 put it. The bay is the new left margin.
BOARD_L = 8.0
BOARD_T = 54.45
BOARD_B = 140.55
# 1 oz external copper. The spine carries the whole array; the buses taper
# as columns tap off. 4.0 / 3.2 mm is the width that still clears the headers.
# The spine is the same 2.8 mm as the 18-node board. It is not re-sized here.
TOP_BUS_W = 4.0
BOT_BUS_W = 3.2
SPINE_X = 86.6
SPINE_W = 2.8
SPUR_W = 0.8
CLEARANCE = 0.2

KICAD_FP = Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints")


class A:
    __slots__ = ("t", "q")

    def __init__(self, t, q=False):
        self.t = str(t)
        self.q = q

    def __repr__(self):
        return f'"{self.t}"' if self.q else self.t


def parse(s: str):
    i = 0
    n = len(s)

    def skip():
        nonlocal i
        while i < n and s[i] in " \t\r\n":
            i += 1

    def one():
        nonlocal i
        skip()
        if i >= n:
            raise ValueError("eof")
        if s[i] == "(":
            i += 1
            items = []
            while True:
                skip()
                if s[i] == ")":
                    i += 1
                    return items
                items.append(one())
        if s[i] == '"':
            i += 1
            buf = []
            while i < n:
                c = s[i]
                if c == "\\":
                    i += 1
                    buf.append(s[i])
                    i += 1
                elif c == '"':
                    i += 1
                    return A("".join(buf), True)
                else:
                    buf.append(c)
                    i += 1
            raise ValueError("unterminated string")
        start = i
        while i < n and s[i] not in " \t\r\n()\"":
            i += 1
        return A(s[start:i], False)

    tree = one()
    skip()
    if i != n:
        raise ValueError(f"trailing at {i}")
    return tree


def head(node):
    if isinstance(node, list) and node and isinstance(node[0], A):
        return node[0].t
    return None


def kids(node, name):
    return [c for c in node if isinstance(c, list) and head(c) == name]


def kid(node, name):
    for c in node:
        if isinstance(c, list) and head(c) == name:
            return c
    return None


def num(atom):
    return float(atom.t)


def fmt(x):
    if abs(x - round(x)) < 1e-7:
        return str(int(round(x)))
    s = f"{x:.6f}".rstrip("0").rstrip(".")
    return s


def setnum(atom_or_idx_parent, value):
    raise RuntimeError("use assign")


def atom_num(parent, idx, value):
    parent[idx] = A(fmt(value), False)


def prop(fp, name):
    for c in fp:
        if isinstance(c, list) and head(c) == "property" and len(c) > 2 and c[1].t == name:
            return c[2].t
    return None


def set_prop(fp, name, value):
    for c in fp:
        if isinstance(c, list) and head(c) == "property" and len(c) > 2 and c[1].t == name:
            c[2] = A(value, True)
            return
    raise KeyError(name)


def set_prop_at(fp, name, x, y):
    for c in fp:
        if isinstance(c, list) and head(c) == "property" and len(c) > 2 and c[1].t == name:
            at = kid(c, "at")
            atom_num(at, 1, x)
            atom_num(at, 2, y)
            return
    raise KeyError(name)


def placement(fp):
    at = kid(fp, "at")
    x, y = num(at[1]), num(at[2])
    ang = num(at[3]) if len(at) > 3 else 0.0
    return x, y, ang, at


def set_placement(fp, x, y, ang=None):
    at = kid(fp, "at")
    atom_num(at, 1, x)
    atom_num(at, 2, y)
    if ang is not None:
        if len(at) > 3:
            atom_num(at, 3, ang)
        else:
            at.append(A(fmt(ang), False))


def rotate(px, py, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return (px * c + py * s, -px * s + py * c)


def new_uuid():
    return str(uuid.uuid4())


def retarget_uuids(node):
    if not isinstance(node, list):
        return
    if head(node) == "uuid" and len(node) > 1 and isinstance(node[1], A):
        node[1] = A(new_uuid(), True)
    for c in node:
        retarget_uuids(c)


def walk_nets(node, fn):
    if not isinstance(node, list):
        return
    if head(node) == "net" and len(node) > 1 and isinstance(node[1], A):
        fn(node, 1)
    for c in node:
        walk_nets(c, fn)


def emit(node, indent=0):
    if isinstance(node, A):
        if node.q:
            esc = node.t.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{esc}"'
        return node.t
    parts = [emit(c, indent + 1) for c in node]
    text = " ".join(parts)
    if "\n" not in text and len(text) < 120 and not any(isinstance(c, list) for c in node):
        return "(" + text + ")"
    pad = "\t" * indent
    inner = "\t" * (indent + 1)
    lines = []
    for c, p in zip(node, parts):
        if isinstance(c, list):
            lines.append(inner + p)
        else:
            # keep short leading atoms on the opening line
            lines.append(None)
    # opening line holds consecutive leading atoms
    lead = []
    rest = []
    for c, p in zip(node, parts):
        if not rest and not isinstance(c, list):
            lead.append(p)
        else:
            rest.append(inner + p)
    body = "(" + " ".join(lead)
    if rest:
        return body + "\n" + "\n".join(rest) + "\n" + pad + ")"
    return body + ")"


def shift_x_fields(node, dx, depth_footprint=False):
    """Shift absolute coordinates. Footprint internals stay local."""
    if not isinstance(node, list):
        return
    h = head(node)
    if h == "footprint":
        at = kid(node, "at")
        atom_num(at, 1, num(at[1]) + dx)
        return
    if h in ("at", "start", "end", "mid", "center", "xy"):
        atom_num(node, 1, num(node[1]) + dx)
        return
    for c in node:
        shift_x_fields(c, dx)


def layer_of(node):
    lay = kid(node, "layer")
    return lay[1].t if lay else None


def is_edge(node):
    return head(node) in ("gr_line", "gr_arc") and layer_of(node) == "Edge.Cuts"


# ---------- rename ----------

def node_number_from_ref(ref):
    # H12A -> 12, J5 -> 5, K10 -> 10
    i = 0
    while i < len(ref) and ref[i].isalpha():
        i += 1
    j = i
    while j < len(ref) and ref[j].isdigit():
        j += 1
    if i == j:
        return None, None, None
    return ref[:i], int(ref[i:j]), ref[j:]


def mapped_node(n):
    if 1 <= n <= 5:
        return n + 5
    if 6 <= n <= 10:
        return n + 10
    return None


def rename_existing(board):
    """Single pass. Each field is rewritten from its current value once."""

    def map_ref(ref):
        if ref == "J11":
            return "J21"
        prefix, n, suffix = node_number_from_ref(ref)
        if n is None or prefix not in ("H", "J", "K"):
            return ref
        if prefix == "H" and suffix not in ("A", "B"):
            return ref
        if prefix == "J" and (suffix != "" or not 1 <= n <= 10):
            return ref
        if prefix == "K" and suffix != "":
            return ref
        m = mapped_node(n)
        if m is None:
            return ref
        return f"{prefix}{m}{suffix}"

    def map_net(name):
        if name.startswith("SMA"):
            try:
                n = int(name[3:])
            except ValueError:
                return name
            m = mapped_node(n)
            if m is not None:
                return f"SMA{m}"
        return name

    for fp in kids(board, "footprint"):
        ref = prop(fp, "Reference")
        if ref:
            new = map_ref(ref)
            if new != ref:
                set_prop(fp, "Reference", new)
        walk_nets(fp, lambda node, idx: assign_net(node, idx, map_net))
    for seg in kids(board, "segment"):
        walk_nets(seg, lambda node, idx: assign_net(node, idx, map_net))
    for via in kids(board, "via"):
        walk_nets(via, lambda node, idx: assign_net(node, idx, map_net))
    for zone in kids(board, "zone"):
        walk_nets(zone, lambda node, idx: assign_net(node, idx, map_net))


def assign_net(node, idx, fn):
    cur = node[idx].t
    new = fn(cur)
    if new != cur:
        node[idx] = A(new, True)


# ---------- clone column ----------

TEMPLATE_REFS = {
    "J2": "top",
    "K2": "top",
    "H2A": "top",
    "H2B": "top",
    "C10": "top10",
    "C3": "top1",
    "J7": "bot",
    "K7": "bot",
    "H7A": "bot",
    "H7B": "bot",
    "C7": "bot10",
    "C5": "bot1",
}


def apply_clone_names(fp, top_n, bot_n, cap_ids):
    ref = prop(fp, "Reference")
    role = TEMPLATE_REFS[ref]
    if role == "top":
        if ref.startswith("H"):
            set_prop(fp, "Reference", f"H{top_n}{ref[-1]}")
        elif ref.startswith("J"):
            set_prop(fp, "Reference", f"J{top_n}")
        elif ref.startswith("K"):
            set_prop(fp, "Reference", f"K{top_n}")
    elif role == "bot":
        if ref.startswith("H"):
            set_prop(fp, "Reference", f"H{bot_n}{ref[-1]}")
        elif ref.startswith("J"):
            set_prop(fp, "Reference", f"J{bot_n}")
        elif ref.startswith("K"):
            set_prop(fp, "Reference", f"K{bot_n}")
    elif role == "top10":
        set_prop(fp, "Reference", cap_ids["top10"])
    elif role == "top1":
        set_prop(fp, "Reference", cap_ids["top1"])
    elif role == "bot10":
        set_prop(fp, "Reference", cap_ids["bot10"])
    elif role == "bot1":
        set_prop(fp, "Reference", cap_ids["bot1"])
    walk_nets(
        fp,
        lambda node, idx: assign_net(
            node,
            idx,
            lambda name: f"SMA{top_n}" if name == "SMA2" else f"SMA{bot_n}" if name == "SMA7" else name,
        ),
    )


def clone_columns(board, templates, template_segs, template_vias):
    clones = []
    for i, sma_x in enumerate(NEW_SMA_X):
        dx = sma_x - TEMPLATE_SMA_X
        top_n = i + 1
        # 11–15. Nodes 6–10 and 16–20 are the shifted originals.
        bot_n = i + 11
        cap_ids = {
            "top10": f"C{19 + i}",
            "top1": f"C{24 + i}",
            "bot10": f"C{29 + i}",
            "bot1": f"C{34 + i}",
        }
        for src in templates:
            fp = copy.deepcopy(src)
            retarget_uuids(fp)
            apply_clone_names(fp, top_n, bot_n, cap_ids)
            x, y, ang, _ = placement(fp)
            set_placement(fp, x + dx, y, ang)
            clones.append(fp)
        for src in template_segs:
            seg = copy.deepcopy(src)
            retarget_uuids(seg)
            for key in ("start", "end"):
                pt = kid(seg, key)
                atom_num(pt, 1, num(pt[1]) + dx)
            net = kid(seg, "net")[1].t
            if net == "SMA2":
                kid(seg, "net")[1] = A(f"SMA{top_n}", True)
            elif net == "SMA7":
                kid(seg, "net")[1] = A(f"SMA{bot_n}", True)
            clones.append(seg)
        for src in template_vias:
            via = copy.deepcopy(src)
            retarget_uuids(via)
            at = kid(via, "at")
            atom_num(at, 1, num(at[1]) + dx)
            clones.append(via)
    return clones


# ---------- geometry / pads ----------

def pad_center_and_aabb(fp, pad):
    ox, oy, fang, _ = placement(fp)
    at = kid(pad, "at")
    px, py = num(at[1]), num(at[2])
    pang = num(at[3]) if len(at) > 3 else 0.0
    lx, ly = rotate(px, py, fang)
    cx, cy = ox + lx, oy + ly
    size = kid(pad, "size")
    sx, sy = num(size[1]), num(size[2])
    shape = pad[3].t if len(pad) > 3 and isinstance(pad[3], A) else ""
    a = math.radians(pang)
    hw = abs(sx / 2 * math.cos(a)) + abs(sy / 2 * math.sin(a))
    hh = abs(sx / 2 * math.sin(a)) + abs(sy / 2 * math.cos(a))
    b = math.radians(fang)
    W = abs(hw * math.cos(b)) + abs(hh * math.sin(b))
    H = abs(hw * math.sin(b)) + abs(hh * math.cos(b))
    if shape in ("circle", "oval"):
        r = max(sx, sy) / 2
        W = H = r
    net = kid(pad, "net")
    netn = net[1].t if net else None
    return cx, cy, W, H, netn, pad[1].t


def iter_pads(board):
    for fp in kids(board, "footprint"):
        ref = prop(fp, "Reference")
        for pad in kids(fp, "pad"):
            if pad[2].t == "np_thru_hole":
                continue
            cx, cy, W, H, netn, num_ = pad_center_and_aabb(fp, pad)
            yield ref, num_, cx, cy, W, H, netn


def find_pad(board, ref, number):
    for fp in kids(board, "footprint"):
        if prop(fp, "Reference") != ref:
            continue
        for pad in kids(fp, "pad"):
            if pad[1].t == number:
                cx, cy, W, H, netn, _ = pad_center_and_aabb(fp, pad)
                return cx, cy, W, H, netn
    raise KeyError(ref + " pad " + number)


# ---------- construction helpers ----------

def seg(x1, y1, x2, y2, width, net, layer="F.Cu"):
    return [
        A("segment", False),
        [A("start", False), A(fmt(x1), False), A(fmt(y1), False)],
        [A("end", False), A(fmt(x2), False), A(fmt(y2), False)],
        [A("width", False), A(fmt(width), False)],
        [A("layer", False), A(layer, True)],
        [A("net", False), A(net, True)],
        [A("uuid", False), A(new_uuid(), True)],
    ]


def via_at(x, y, net="GND"):
    return [
        A("via", False),
        [A("at", False), A(fmt(x), False), A(fmt(y), False)],
        [A("size", False), A("0.6", False)],
        [A("drill", False), A("0.3", False)],
        [A("layers", False), A("F.Cu", True), A("B.Cu", True)],
        [A("net", False), A(net, True)],
        [A("uuid", False), A(new_uuid(), True)],
    ]


def gr_text(text, x, y, layer="F.SilkS", size=1.4, ang=0):
    return [
        A("gr_text", False),
        A(text, True),
        [A("at", False), A(fmt(x), False), A(fmt(y), False), A(fmt(ang), False)],
        [A("layer", False), A(layer, True)],
        [A("uuid", False), A(new_uuid(), True)],
        [
            A("effects", False),
            [
                A("font", False),
                [A("size", False), A(fmt(size), False), A(fmt(size), False)],
                [A("thickness", False), A("0.2", False)],
            ],
        ],
    ]


def gr_line(x1, y1, x2, y2):
    return [
        A("gr_line", False),
        [A("start", False), A(fmt(x1), False), A(fmt(y1), False)],
        [A("end", False), A(fmt(x2), False), A(fmt(y2), False)],
        [A("stroke", False), [A("width", False), A("0.1", False)], [A("type", False), A("default", False)]],
        [A("layer", False), A("Edge.Cuts", True)],
        [A("uuid", False), A(new_uuid(), True)],
    ]


def gr_arc(x1, y1, mx, my, x2, y2):
    return [
        A("gr_arc", False),
        [A("start", False), A(fmt(x1), False), A(fmt(y1), False)],
        [A("mid", False), A(fmt(mx), False), A(fmt(my), False)],
        [A("end", False), A(fmt(x2), False), A(fmt(y2), False)],
        [A("stroke", False), [A("width", False), A("0.1", False)], [A("type", False), A("default", False)]],
        [A("layer", False), A("Edge.Cuts", True)],
        [A("uuid", False), A(new_uuid(), True)],
    ]


def route_orth(x1, y1, x2, y2, width, net, prefer="v"):
    if abs(x1 - x2) < 1e-6 or abs(y1 - y2) < 1e-6:
        return [seg(x1, y1, x2, y2, width, net)]
    if prefer == "v":
        return [seg(x1, y1, x1, y2, width, net), seg(x1, y2, x2, y2, width, net)]
    return [seg(x1, y1, x2, y1, width, net), seg(x2, y1, x2, y2, width, net)]


def wire(pts, width, net, layer="F.Cu"):
    """Orthogonal polyline. A diagonal is a placement bug, not a route."""
    out = []
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        if abs(x1 - x2) < 1e-6 and abs(y1 - y2) < 1e-6:
            continue
        if abs(x1 - x2) > 1e-4 and abs(y1 - y2) > 1e-4:
            raise RuntimeError(f"diagonal {net} ({x1:.2f},{y1:.2f})-({x2:.2f},{y2:.2f})")
        out.append(seg(x1, y1, x2, y2, width, net, layer))
    return out


def set_pad_net(fp, number, net):
    for pad in kids(fp, "pad"):
        if pad[1].t == number:
            existing = kid(pad, "net")
            if existing:
                existing[1] = A(net, True)
            else:
                # insert before uuid if present
                node = [A("net", False), A(net, True)]
                for i, c in enumerate(pad):
                    if isinstance(c, list) and head(c) == "uuid":
                        pad.insert(i, node)
                        break
                else:
                    pad.append(node)


def load_mod(url, name):
    import urllib.request

    path = Path("/tmp") / name
    if not path.exists() or path.stat().st_size < 100:
        urllib.request.urlretrieve(url, path)
    return parse(path.read_text())


def load_local(rel):
    return parse((KICAD_FP / rel).read_text())


def prep_lib_fp(fp, libname, ref, value, x, y, ang):
    fp = copy.deepcopy(fp)
    fp[1] = A(libname, True)
    # drop version/generator noise is fine to keep
    # ensure uuid + at
    if kid(fp, "uuid") is None:
        # insert after layer
        idx = 2
        for i, c in enumerate(fp):
            if isinstance(c, list) and head(c) == "layer":
                idx = i + 1
                break
        fp.insert(idx, [A("uuid", False), A(new_uuid(), True)])
        fp.insert(idx + 1, [A("at", False), A(fmt(x), False), A(fmt(y), False), A(fmt(ang), False)])
    else:
        set_placement(fp, x, y, ang)
    retarget_uuids(fp)
    set_prop(fp, "Reference", ref)
    set_prop(fp, "Value", value)
    return fp


def make_power_terminal():
    """Phoenix MKDS 1,5/2-5.08. Pin 1 square = GND, pin 2 round = VIN.

    rot -90 puts the 5.08 mm pitch on +Y, same places as the old pin header,
    and the wire openings face the left board edge.
    """
    fp = load_local(
        "TerminalBlock_Phoenix.pretty/TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal.kicad_mod"
    )
    fp = prep_lib_fp(
        fp,
        "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal",
        "J22",
        "MKDS-1,5/2-5.08",
        80.5,
        76.0,
        -90,
    )
    set_pad_net(fp, "1", "GND")
    set_pad_net(fp, "2", "VIN")
    # Above the body, clear of the "5V ONLY" legend.
    set_prop_at(fp, "Reference", -6.0, -2.5)
    return fp


def _place(lib_rel, libname, ref, value, x, y, ang, nets):
    fp = prep_lib_fp(load_local(lib_rel), libname, ref, value, x, y, ang)
    for number, net in nets.items():
        set_pad_net(fp, number, net)
    return fp


def bus_end(board, y, width, x0):
    """Rightmost segment-end x for a horizontal bus that stops before foreign copper.

    The segment end-cap extends width/2 past the coordinate. Objects entirely
    to the left of the spine are ignored; the USB cluster is what stops the bus.
    """
    half = width / 2.0
    c0 = y - half - CLEARANCE
    c1 = y + half + CLEARANCE
    stops = []

    def hit(min_y, max_y):
        return not (max_y < c0 or min_y > c1)

    for ref, num_, x, py, w, h, net in iter_pads(board):
        if net == "+5V":
            continue
        if not hit(py - h, py + h):
            continue
        left = x - w
        if left > x0 + 1.0:
            stops.append(left - CLEARANCE - half)
    for v in kids(board, "via"):
        at = kid(v, "at")
        vx, vy = num(at[1]), num(at[2])
        net = kid(v, "net")[1].t if kid(v, "net") else "GND"
        if net == "+5V":
            continue
        r = num(kid(v, "size")[1]) / 2.0
        if not hit(vy - r, vy + r):
            continue
        if vx - r > x0 + 1.0:
            stops.append(vx - r - CLEARANCE - half)
    for s in kids(board, "segment"):
        net = kid(s, "net")[1].t
        layer = kid(s, "layer")[1].t if kid(s, "layer") else "F.Cu"
        if layer != "F.Cu" or net == "+5V":
            continue
        st, en = kid(s, "start"), kid(s, "end")
        x1, y1 = num(st[1]), num(st[2])
        x2, y2 = num(en[1]), num(en[2])
        sw = num(kid(s, "width")[1]) / 2.0
        length = math.hypot(x2 - x1, y2 - y1)
        steps = max(int(length / 0.25), 1)
        xs = []
        for i in range(steps + 1):
            t = i / steps
            px = x1 + (x2 - x1) * t
            py = y1 + (y2 - y1) * t
            if c0 - sw <= py <= c1 + sw and px - sw > x0 + 1.0:
                xs.append(px - sw)
        if xs:
            stops.append(min(xs) - CLEARANCE - half)
    if not stops:
        return x0 + 10.0
    return min(stops)


def add_power(board, fan_fp, c1_fp):
    """External 5 V inlet. The geometry matches the 18-node board.

    J22 screw terminal -> F2 10 A fuse -> Q1 drain. Q1 is a P-channel with
    source on +5V. Q2 pulls the gate down only while VIN_F is present, so a
    USB-only rail cannot turn the FET on and the body diode stays reverse
    biased. This is not over-voltage protection: a VIN above 5 V still reaches
    the modules through the channel and the body diode.

    fan_fp is unused. The terminal is a library footprint, not a stretched FAN1.
    """
    del fan_fp
    taken = {prop(fp, "Reference") for fp in kids(board, "footprint")}
    for ref in ("J22", "F2", "Q1", "Q2", "R3", "R4", "R5", "R6", "D4", "C39"):
        if ref in taken:
            raise RuntimeError(f"power ref {ref} already on the board")

    parts = [make_power_terminal()]
    # Nano2 body is long in local X. rot -90 stacks the pads on Y.
    # Pad 1 is the upper pad (toward J20).
    f2 = _place(
        "Fuse.pretty/Fuse_Littelfuse-NANO2-451_453.kicad_mod",
        "Fuse:Fuse_Littelfuse-NANO2-451_453",
        "F2",
        "0451010",
        80.5,
        90.6,
        -90,
        {"1": "VIN", "2": "VIN_F"},
    )
    parts.append(f2)
    # SO-8 FL, CASE 506EZ land pattern (KiCad library file is named 488AA;
    # pin pads 1.00 x 0.75 at 1.27 mm and the 4.56 mm drain match that drawing).
    # rot 180 puts sources and the gate on the right, drain on the left.
    # Pads 1-3 source, pad 4 gate, pad 5 drain + exposed pad.
    q1 = _place(
        "Package_SO.pretty/ONSemi_SO-8FL_488AA.kicad_mod",
        "Package_SO:ONSemi_SO-8FL_488AA",
        "Q1",
        "NTMFS002P03P8Z",
        81.6,
        105.2,
        180,
        {"1": "+5V", "2": "+5V", "3": "+5V", "4": "GATE", "5": "VIN_F"},
    )
    set_prop_at(q1, "Reference", 4.8, 0.2)
    parts.append(q1)
    # SOD-123 pad 1 is the banded cathode. rot -90 puts that pad above the anode.
    d4 = _place(
        "Diode_SMD.pretty/D_SOD-123.kicad_mod",
        "Diode_SMD:D_SOD-123",
        "D4",
        "BZT52C12",
        84.0,
        98.2,
        -90,
        {"1": "+5V", "2": "GATE"},
    )
    set_prop_at(d4, "Reference", 0.0, 3.1)
    parts.append(d4)
    # 0603. R3 holds the gate at the source (FET off) when VIN is absent.
    # rot 90 stacks the pads. Pad 1 (gate) is the lower pad, pad 2 (+5V) the upper,
    # so the pull-up can leave upward without crossing the gate rail.
    r3 = _place(
        "Resistor_SMD.pretty/R_0603_1608Metric.kicad_mod",
        "Resistor_SMD:R_0603_1608Metric",
        "R3",
        "100k",
        76.15,
        112.2,
        90,
        {"1": "GATE", "2": "+5V"},
    )
    set_prop_at(r3, "Reference", 1.6, 0.0)
    parts.append(r3)
    # 1k between the NPN collector and the gate. rot 90 stacks the pads so the
    # gate net hits the upper pad and the collector hits the lower pad.
    r4 = _place(
        "Resistor_SMD.pretty/R_0603_1608Metric.kicad_mod",
        "Resistor_SMD:R_0603_1608Metric",
        "R4",
        "1k",
        81.0,
        109.8,
        90,
        {"1": "Q2C", "2": "GATE"},
    )
    # Default ref lands on this part's own silk when the body is rotated.
    set_prop_at(r4, "Reference", 0.0, -2.3)
    parts.append(r4)
    # MMBT3904: pad 1 base, pad 2 emitter, pad 3 collector.
    q2 = _place(
        "Package_TO_SOT_SMD.pretty/SOT-23.kicad_mod",
        "Package_TO_SOT_SMD:SOT-23",
        "Q2",
        "MMBT3904",
        78.9,
        115.8,
        0,
        {"1": "Q2B", "2": "GND", "3": "Q2C"},
    )
    parts.append(q2)
    r5 = _place(
        "Resistor_SMD.pretty/R_0603_1608Metric.kicad_mod",
        "Resistor_SMD:R_0603_1608Metric",
        "R5",
        "47k",
        80.6,
        119.6,
        0,
        # Right-hand pad is VIN_F so the drain tap can reach it without
        # crossing the gate rail on the left.
        {"1": "Q2B", "2": "VIN_F"},
    )
    parts.append(r5)
    r6 = _place(
        "Resistor_SMD.pretty/R_0603_1608Metric.kicad_mod",
        "Resistor_SMD:R_0603_1608Metric",
        "R6",
        "100k",
        80.6,
        121.6,
        0,
        {"1": "GND", "2": "Q2B"},
    )
    parts.append(r6)
    c35 = copy.deepcopy(c1_fp)
    retarget_uuids(c35)
    set_prop(c35, "Reference", "C39")
    # y=128 clears the inlet parts. The gate parts sit above this courtyard.
    set_placement(c35, 80.5, 128.0, 0)
    parts.append(c35)
    for p in parts:
        board.append(p)

    tracks = []
    vin = find_pad(board, "J22", "2")
    f_in = find_pad(board, "F2", "1")
    f_out = find_pad(board, "F2", "2")
    tracks += [seg(vin[0], vin[1], f_in[0], f_in[1], 2.0, "VIN")]
    # Drain copper (footprint polygon, rot 180) is about x=79.10..83.20,
    # y=102.43..107.98. The fat trace lands inside that copper. It also fills
    # x=79.3..81.7 the whole way down from the fuse, so the gate must not
    # cross that column.
    tracks += [seg(f_out[0], f_out[1], f_out[0], 103.4, 2.4, "VIN_F")]
    # Q2 bias leaves the drain on its right side and enters R5's right pad.
    r5v = find_pad(board, "R5", "2")
    tracks += [
        seg(82.95, 106.0, 82.95, r5v[1], 0.4, "VIN_F"),
        seg(82.95, r5v[1], r5v[0], r5v[1], 0.4, "VIN_F"),
    ]

    # Sources are the three right-hand pads. Stub each into the spine.
    for n in ("1", "2", "3"):
        p = find_pad(board, "Q1", n)
        # 0.9 mm keeps the stub off the gate pad 1.27 mm away.
        tracks += [seg(p[0], p[1], SPINE_X, p[1], 0.9, "+5V")]
    gate = find_pad(board, "Q1", "4")
    # Drain copper reaches x=83.20, and there is no legal track between that
    # edge and the source pads. The gate leaves upward, climbs the open column
    # between the fuse and D4 (x=82.70), and crosses through the copper gap
    # between the two fuse pads (y=90.6) before dropping down the left side.
    rail_x = 77.30
    side_x = 82.70
    gy = 101.2
    gap_y = 90.6
    anode = find_pad(board, "D4", "2")
    r3g = find_pad(board, "R3", "1")
    r3v = find_pad(board, "R3", "2")
    r4g = find_pad(board, "R4", "2")
    tracks += [
        seg(gate[0], gate[1], gate[0], gy, 0.25, "GATE"),
        seg(gate[0], gy, side_x, gy, 0.25, "GATE"),
        seg(side_x, gy, side_x, gap_y, 0.25, "GATE"),
        seg(side_x, gap_y, rail_x, gap_y, 0.25, "GATE"),
        seg(rail_x, gap_y, rail_x, r3g[1], 0.25, "GATE"),
        seg(rail_x, r4g[1], r4g[0], r4g[1], 0.25, "GATE"),
        seg(rail_x, r3g[1], r3g[0], r3g[1], 0.25, "GATE"),
        seg(anode[0], anode[1], side_x, anode[1], 0.25, "GATE"),
        # Pull-up goes up the left edge, through the open strip above the fuse
        # pad (the pad is 3.15 mm along Y), and down into the spine. 0.25 mm
        # is all that fits between that pad and the gate run at y=90.6.
        seg(r3v[0], r3v[1], r3v[0], 90.10, 0.25, "+5V"),
        seg(r3v[0], 90.10, SPINE_X, 90.10, 0.25, "+5V"),
        seg(SPINE_X, 90.10, SPINE_X, BUS_TOP_Y, 0.25, "+5V"),
    ]
    cath = find_pad(board, "D4", "1")
    tracks += [seg(cath[0], cath[1], SPINE_X, cath[1], 0.5, "+5V")]

    # Collector rises on its own x into the lower pad of R4. The base drops
    # to the right of the emitter and reaches R5 from above, so it misses
    # both the collector and the VIN_F tap along y=119.6.
    col = find_pad(board, "Q2", "3")
    r4c = find_pad(board, "R4", "1")
    tracks += [
        seg(col[0], col[1], r4c[0], col[1], 0.3, "Q2C"),
        seg(r4c[0], col[1], r4c[0], r4c[1], 0.3, "Q2C"),
    ]
    base = find_pad(board, "Q2", "1")
    r5b = find_pad(board, "R5", "1")
    r6b = find_pad(board, "R6", "2")
    # Collector is to the right of the base and the emitter is directly below
    # it, so the base net steps left, drops clear of both, then comes back.
    tracks += [
        seg(base[0], base[1], 76.6, base[1], 0.25, "Q2B"),
        seg(76.6, base[1], 76.6, 118.75, 0.25, "Q2B"),
        seg(76.6, 118.75, r5b[0], 118.75, 0.25, "Q2B"),
        seg(r5b[0], 118.75, r5b[0], r5b[1], 0.25, "Q2B"),
        seg(r5b[0], r5b[1], r5b[0], 120.6, 0.25, "Q2B"),
        seg(r5b[0], 120.6, r6b[0], 120.6, 0.25, "Q2B"),
        seg(r6b[0], 120.6, r6b[0], r6b[1], 0.25, "Q2B"),
    ]
    em = find_pad(board, "Q2", "2")
    # Via sits below Q2's courtyard. y=118.0 keeps the 0.6 mm pad off that outline.
    tracks += [seg(em[0], em[1], em[0], 118.0, 0.4, "GND")]
    board.append(via_at(em[0], 118.0, "GND"))
    r6g = find_pad(board, "R6", "1")
    tracks += [seg(r6g[0], r6g[1], 78.2, r6g[1], 0.4, "GND")]
    board.append(via_at(78.2, r6g[1], "GND"))

    top_end = bus_end(board, BUS_TOP_Y, TOP_BUS_W, SPINE_X)
    bot_end = bus_end(board, BUS_BOT_Y, BOT_BUS_W, SPINE_X)
    # Keep a millimetre of overlap with the shifted 1 mm V2 buses (they begin
    # near x=246.5) and stop before the USB cluster the scanner just found.
    top_end = min(top_end, 428.0)
    bot_end = min(bot_end, 421.0)
    print(f"+5V bus ends top x={top_end:.2f} bottom x={bot_end:.2f}")
    if top_end < 360 or bot_end < 360:
        raise RuntimeError("wide +5V bus was stopped short of the array")
    tracks += [seg(SPINE_X, BUS_TOP_Y, SPINE_X, BUS_BOT_Y, SPINE_W, "+5V")]
    tracks += [seg(SPINE_X, BUS_TOP_Y, top_end, BUS_TOP_Y, TOP_BUS_W, "+5V")]
    c_pos = find_pad(board, "C39", "1")
    c_neg = find_pad(board, "C39", "2")
    if c_pos[4] != "+5V":
        c_pos, c_neg = c_neg, c_pos
    # The bottom bus starts in the bay so the buck OR can land on it, then
    # runs through the bulk cap and out to the array.
    bot_x0 = 62.0
    tracks += [seg(bot_x0, BUS_BOT_Y, bot_end, BUS_BOT_Y, BOT_BUS_W, "+5V")]
    tracks += [seg(c_pos[0], c_pos[1], c_pos[0], BUS_BOT_Y, 0.8, "+5V")]

    for i, sma_x in enumerate(NEW_SMA_X):
        top_n = i + 1
        bot_n = i + 11
        ptop = find_pad(board, f"H{top_n}B", "7")
        pbot = find_pad(board, f"H{bot_n}B", "7")
        tracks += [seg(ptop[0], ptop[1], ptop[0], BUS_TOP_Y, SPUR_W, "+5V")]
        tracks += [seg(pbot[0], pbot[1], pbot[0], BUS_BOT_Y, SPUR_W, "+5V")]
        for cref, by in (
            (f"C{19 + i}", BUS_TOP_Y),
            (f"C{24 + i}", BUS_TOP_Y),
            (f"C{29 + i}", BUS_BOT_Y),
            (f"C{34 + i}", BUS_BOT_Y),
        ):
            cpad = find_pad(board, cref, "1")
            tracks += [seg(cpad[0], cpad[1], cpad[0], by, SPUR_W, "+5V")]
        tie_x = sma_x + (149.5 - TEMPLATE_SMA_X)
        tracks += [seg(tie_x, BUS_TOP_Y, tie_x, BUS_BOT_Y, 1.0, "+5V")]

    labels = [
        gr_text("5V ONLY", 80.5, 66.8, size=1.0),
        gr_text("10A", 84.6, 87.2, size=1.0),
        gr_text("GND", 86.4, 74.6, size=0.8),
        gr_text("VIN", 86.4, 80.6, size=0.8),
    ]
    return tracks, labels


def move_mounting_holes(board):
    """Park the corner holes on the new left edge. The inlet is not their home."""
    for fp in kids(board, "footprint"):
        ref = prop(fp, "Reference")
        if ref == "MH1":
            set_placement(fp, BOARD_L + 4.55, BOARD_T + 4.55)
        elif ref == "MH2":
            set_placement(fp, BOARD_L + 4.55, BOARD_B - 4.55)


def _rratio(sx, sy):
    small = min(sx, sy)
    if small <= 0:
        return 0.25
    return min(0.25, 0.05 / small)


def _smd_pad(number, px, py, sx, sy, paste=None):
    node = [
        A("pad"),
        A(str(number), True),
        A("smd"),
        A("roundrect"),
        [A("at"), A(fmt(px)), A(fmt(py))],
        [A("size"), A(fmt(sx)), A(fmt(sy))],
        [A("layers"), A("F.Cu", True), A("F.Mask", True), A("F.Paste", True)],
        [A("roundrect_rratio"), A(fmt(_rratio(sx, sy)))],
    ]
    if paste is not None:
        node.append([A("solder_paste_margin_ratio"), A(fmt(paste))])
    node.append([A("uuid"), A(new_uuid(), True)])
    return node


def make_tps56837(ref, value, x, y, ang=0):
    """RPA0010A land, datasheet 4224047 rev A, footprint rotation 0 = top view.

    Pin 8 is four copper pieces with one pad number. Pads 6 and 9 are the
    only ones the stencil drawing shrinks (89% area).
    """
    paste = -0.0566
    pads = [
        _smd_pad("1", -0.75, 1.40, 0.25, 0.60),
        _smd_pad("2", -0.25, 1.40, 0.25, 0.60),
        _smd_pad("3", 0.25, 1.40, 0.25, 0.60),
        _smd_pad("4", 0.75, 1.40, 0.25, 0.60),
        _smd_pad("5", 1.40, 0.93, 0.60, 0.25),
        _smd_pad("6", 0.85, -0.37, 1.70, 0.25, paste),
        _smd_pad("7", 1.40, -0.87, 0.60, 0.25),
        # Pin 8 spine first, so find_pad returns a point a track can hit.
        _smd_pad("8", -0.65, -0.95, 2.10, 0.40),
        _smd_pad("8", -0.75, -1.43, 0.25, 0.56),
        _smd_pad("8", -0.25, -1.43, 0.25, 0.56),
        _smd_pad("8", 0.25, -1.43, 0.25, 0.56),
        _smd_pad("9", -0.65, 0.205, 2.10, 0.40, paste),
        _smd_pad("10", -1.40, 0.93, 0.60, 0.25),
    ]
    cy = 2.15
    fp = [
        A("footprint"),
        A("Package_DFN_QFN:TPS56837_RPA0010A", True),
        [A("version"), A("20260206")],
        [A("generator"), A("packethog20", True)],
        [A("layer"), A("F.Cu", True)],
        [A("uuid"), A(new_uuid(), True)],
        [A("at"), A(fmt(x)), A(fmt(y)), A(fmt(ang))],
        [
            A("property"),
            A("Reference", True),
            A(ref, True),
            [A("at"), A("0"), A("-2.9"), A("0")],
            [A("layer"), A("F.SilkS", True)],
            [A("effects"), [A("font"), [A("size"), A("0.8"), A("0.8")], [A("thickness"), A("0.12")]]],
        ],
        [
            A("property"),
            A("Value", True),
            A(value, True),
            [A("at"), A("0"), A("2.9"), A("0")],
            [A("layer"), A("F.Fab", True)],
            [A("effects"), [A("font"), [A("size"), A("0.8"), A("0.8")], [A("thickness"), A("0.12")]]],
        ],
        [A("attr"), A("smd")],
        [A("duplicate_pad_numbers_are_jumpers"), A("yes")],
        [
            A("fp_rect"),
            [A("start"), A(fmt(-cy)), A(fmt(-cy))],
            [A("end"), A(fmt(cy)), A(fmt(cy))],
            [A("stroke"), [A("width"), A("0.05")], [A("type"), A("solid")]],
            [A("fill"), A("no")],
            [A("layer"), A("F.CrtYd", True)],
        ],
    ]
    fp.extend(pads)
    return fp


def add_battery(board):
    """2S pack bay on the left of the inlet.

    J23 is the pack power connector. Q3 is a P-channel with its drain on the
    raw pack positive and its source on the protected PACK rail, so a reversed
    pack leaves the body diode off. U1 (IP2326) charges that rail from VIN_F
    only: with the adapter unplugged the fuse opens and the charger has no
    input. U2 (TPS56837) bucks PACK down to 5 V. Q4 ORs that onto the bottom
    +5V bus and Q5 holds the buck off while VIN_F is present, so the adapter
    and the pack do not fight.

    The pack has to include a BMS. The balance plug is a sense connection,
    not a second power path around Q3. NTC is a fixed resistor. None of this
    is over-voltage protection.
    """
    taken = {prop(fp, "Reference") for fp in kids(board, "footprint")}
    need = [
        "U1", "U2", "L1", "L2", "Q3", "Q4", "Q5", "Q6", "J23", "J24",
        "D5", "D6", "D7",
    ] + [f"R{n}" for n in range(7, 22)] + [f"C{n}" for n in range(40, 52)]
    hit = [r for r in need if r in taken]
    if hit:
        raise RuntimeError(f"battery refs already on the board: {hit}")

    parts = []
    # XT30PW-M, rot +90. Housing extends toward the left edge.
    # Library silk marks pad 2 "+", pad 1 "-". Confirm against the AMASS drawing
    # before a cable is built.
    j23 = _place(
        "Connector_AMASS.pretty/AMASS_XT30PW-M_1x02_P2.50mm_Horizontal.kicad_mod",
        "Connector_AMASS:AMASS_XT30PW-M_1x02_P2.50mm_Horizontal",
        "J23",
        "XT30PW-M",
        26.0,
        68.0,
        90,
        {"1": "GND", "2": "PACK_IN"},
    )
    set_prop_at(j23, "Reference", 2.2, 3.2)
    parts.append(j23)
    # JST XH 2S: pin 1 cell-, pin 2 mid, pin 3 cell+ (same node as XT30 +).
    j24 = _place(
        "Connector_JST.pretty/JST_XH_B3B-XH-A_1x03_P2.50mm_Vertical.kicad_mod",
        "Connector_JST:JST_XH_B3B-XH-A_1x03_P2.50mm_Vertical",
        "J24",
        "B3B-XH-A",
        16.0,
        82.0,
        0,
        {"1": "GND", "2": "VBATM", "3": "PACK_IN"},
    )
    set_prop_at(j24, "Reference", 2.5, -3.6)
    parts.append(j24)

    # rot 180: drain (pad 5) faces the XT30, sources face the charger.
    q3 = _place(
        "Package_SO.pretty/ONSemi_SO-8FL_488AA.kicad_mod",
        "Package_SO:ONSemi_SO-8FL_488AA",
        "Q3",
        "NTMFS002P03P8Z",
        40.0,
        72.0,
        180,
        {"1": "PACK", "2": "PACK", "3": "PACK", "4": "GATE3", "5": "PACK_IN"},
    )
    set_prop_at(q3, "Reference", 0.0, -4.2)
    parts.append(q3)
    # rot -90 puts the banded cathode (pad 1) on the upper pad.
    d5 = _place(
        "Diode_SMD.pretty/D_SOD-123.kicad_mod",
        "Diode_SMD:D_SOD-123",
        "D5",
        "BZT52C12",
        42.75,
        64.5,
        -90,
        {"1": "PACK", "2": "GATE3"},
    )
    set_prop_at(d5, "Reference", 2.6, 0.0)
    parts.append(d5)
    r7 = _place(
        "Resistor_SMD.pretty/R_0603_1608Metric.kicad_mod",
        "Resistor_SMD:R_0603_1608Metric",
        "R7",
        "100k",
        46.8,
        66.2,
        0,
        {"1": "GATE3", "2": "GND"},
    )
    parts.append(r7)

    u1 = _place(
        "Package_DFN_QFN.pretty/QFN-24-1EP_4x4mm_P0.5mm_EP2.5x2.5mm.kicad_mod",
        "Package_DFN_QFN:QFN-24-1EP_4x4mm_P0.5mm_EP2.5x2.5mm",
        "U1",
        "IP2326",
        54.0,
        74.0,
        0,
        {
            "4": "CHG_NTC",
            "6": "CHG_LED",
            "7": "CHG_TIME",
            "11": "CHG_ISET",
            "12": "CHG_EN",
            "13": "VIN_F",
            "14": "CHG_BST",
            "15": "CHG_LX",
            "16": "CHG_LX",
            "17": "CHG_LX",
            "18": "GND",
            "19": "CHG_VSYS",
            "20": "CHG_VSYS",
            "21": "PACK",
            "22": "PACK",
            "23": "VBATM",
            "24": "GND",
            "25": "GND",
        },
    )
    set_prop_at(u1, "Reference", 0.0, -3.5)
    parts.append(u1)
    # rot 0. KiCad does not rotate a pad's size with the footprint, so rot 90
    # leaves the 5.5 mm axis in Y and the two pads overlap. At rot 0 the long
    # axis is perpendicular to the 4.04 mm center spacing (gap about 2.6 mm).
    # Pad 1 (LX) is on the left, pad 2 (VSYS) on the right.
    l1 = _place(
        "Inductor_SMD.pretty/L_Coilcraft_XAL6030-XXX.kicad_mod",
        "Inductor_SMD:L_Coilcraft_XAL6030-XXX",
        "L1",
        "XAL6030-222MEC",
        66.5,
        72.0,
        0,
        {"1": "CHG_LX", "2": "CHG_VSYS"},
    )
    set_prop_at(l1, "Reference", 0.0, -4.6)
    parts.append(l1)

    def chip_c(ref, value, x, y, ang, nets):
        return _place(
            "Capacitor_SMD.pretty/C_0805_2012Metric.kicad_mod",
            "Capacitor_SMD:C_0805_2012Metric",
            ref,
            value,
            x,
            y,
            ang,
            nets,
        )

    def chip_r(ref, value, x, y, ang, nets):
        return _place(
            "Resistor_SMD.pretty/R_0603_1608Metric.kicad_mod",
            "Resistor_SMD:R_0603_1608Metric",
            ref,
            value,
            x,
            y,
            ang,
            nets,
        )

    parts.append(chip_c("C42", "22uF 25V", 66.5, 64.5, 0, {"1": "CHG_VSYS", "2": "GND"}))
    parts.append(chip_c("C43", "22uF 25V", 66.5, 61.0, 0, {"1": "CHG_VSYS", "2": "GND"}))
    # Pad 1 sits on the PACK column at the y=83 corner. Pad 2 is to the right,
    # off the rail, so the ground pad is not swallowed by the 0.8 mm trace.
    parts.append(chip_c("C44", "10uF 25V", 45.15, 83.0, 0, {"1": "PACK", "2": "GND"}))
    parts.append(chip_c("C40", "10uF 25V", 54.0, 84.8, 0, {"1": "GND", "2": "VIN_F"}))
    parts.append(chip_c("C41", "10uF 25V", 60.5, 84.8, 0, {"1": "VIN_F", "2": "GND"}))
    parts.append(
        _place(
            "Capacitor_SMD.pretty/C_0603_1608Metric.kicad_mod",
            "Capacitor_SMD:C_0603_1608Metric",
            "C45",
            "100nF",
            60.8,
            78.4,
            0,
            {"1": "CHG_BST", "2": "CHG_LX"},
        )
    )
    parts.append(chip_r("R17", "51k", 46.0, 74.25, 0, {"1": "GND", "2": "CHG_NTC"}))
    parts.append(chip_r("R18", "100", 46.0, 76.6, 0, {"1": "LED_A", "2": "CHG_LED"}))
    parts.append(
        _place(
            "LED_SMD.pretty/LED_0603_1608Metric.kicad_mod",
            "LED_SMD:LED_0603_1608Metric",
            "D7",
            "RED",
            40.2,
            76.6,
            0,
            {"1": "GND", "2": "LED_A"},
        )
    )
    parts.append(chip_r("R16", "120k", 48.0, 80.8, 0, {"1": "GND", "2": "CHG_TIME"}))
    parts.append(chip_r("R15", "90.9k", 55.2, 80.8, 0, {"1": "GND", "2": "CHG_ISET"}))
    parts.append(chip_r("R14", "5.1k", 62.8, 80.8, 0, {"1": "CHG_EN", "2": "VIN_F"}))

    u2 = make_tps56837("U2", "TPS56837", 32.0, 106.0, 0)
    for number, net in {
        "1": "BUCK_EN",
        "2": "BUCK_FB",
        "3": "GND",
        "6": "BUCK_SW",
        "7": "BUCK_BOOT",
        "8": "PACK",
        "9": "GND",
        "10": "BUCK_MODE",
    }.items():
        set_pad_net(u2, number, net)
    parts.append(u2)
    l2 = _place(
        "Inductor_SMD.pretty/L_Coilcraft_XAL1010-XXX.kicad_mod",
        "Inductor_SMD:L_Coilcraft_XAL1010-XXX",
        "L2",
        "XAL1010-332MED",
        50.0,
        106.0,
        0,
        {"1": "BUCK_SW", "2": "BUCK5"},
    )
    set_prop_at(l2, "Reference", 0.0, -7.0)
    parts.append(l2)
    # rot 0: sources face the inductor, drain faces the bus drop.
    q4 = _place(
        "Package_SO.pretty/ONSemi_SO-8FL_488AA.kicad_mod",
        "Package_SO:ONSemi_SO-8FL_488AA",
        "Q4",
        "NTMFS002P03P8Z",
        66.0,
        106.0,
        0,
        {"1": "BUCK5", "2": "BUCK5", "3": "BUCK5", "4": "GATE4", "5": "+5V"},
    )
    set_prop_at(q4, "Reference", 0.0, -4.2)
    parts.append(q4)
    parts.append(chip_c("C46", "10uF 25V", 30.0, 100.2, 0, {"1": "PACK", "2": "GND"}))
    parts.append(chip_c("C47", "10uF 25V", 37.2, 100.2, 0, {"1": "GND", "2": "PACK"}))
    parts.append(
        _place(
            "Capacitor_SMD.pretty/C_0603_1608Metric.kicad_mod",
            "Capacitor_SMD:C_0603_1608Metric",
            "C51",
            "100nF",
            38.6,
            103.3,
            0,
            {"1": "BUCK_BOOT", "2": "BUCK_SW"},
        )
    )
    # rot 90: pad 1 lower = GND, pad 2 upper = BUCK5.
    for ref, x in (("C48", 42.0), ("C49", 47.0), ("C50", 52.0)):
        parts.append(chip_c(ref, "22uF 25V", x, 119.0, 90, {"1": "GND", "2": "BUCK5"}))
    parts.append(chip_r("R19", "30.1k", 22.0, 104.2, 0, {"1": "GND", "2": "BUCK_MODE"}))
    parts.append(chip_r("R20", "73.2k", 22.0, 108.4, 0, {"1": "BUCK5", "2": "BUCK_FB"}))
    parts.append(chip_r("R21", "10.0k", 22.0, 111.8, 0, {"1": "GND", "2": "BUCK_FB"}))
    # R8 courtyard must clear L2 (courtyard right x=55.5). Half-width is 1.48.
    parts.append(chip_r("R8", "100k", 57.3, 111.6, 0, {"1": "BUCK5", "2": "GATE4"}))
    # R9 courtyard must clear D6 (courtyard right x=63.15). rot 90 half-width is 0.73.
    parts.append(chip_r("R9", "1k", 64.2, 115.4, 90, {"1": "Q6C", "2": "GATE4"}))
    parts.append(chip_r("R10", "47k", 54.2, 115.6, 0, {"1": "BUCK5", "2": "Q6B"}))
    parts.append(chip_r("R11", "100k", 63.6, 119.4, 0, {"1": "GND", "2": "Q6B"}))
    parts.append(chip_r("R12", "100k", 14.8, 113.4, 0, {"1": "Q5B", "2": "VIN_F"}))
    parts.append(chip_r("R13", "100k", 14.8, 116.6, 0, {"1": "GND", "2": "Q5B"}))
    parts.append(
        _place(
            "Diode_SMD.pretty/D_SOD-123.kicad_mod",
            "Diode_SMD:D_SOD-123",
            "D6",
            "BZT52C12",
            60.8,
            115.0,
            0,
            {"1": "BUCK5", "2": "GATE4"},
        )
    )
    parts.append(
        _place(
            "Package_TO_SOT_SMD.pretty/SOT-23.kicad_mod",
            "Package_TO_SOT_SMD:SOT-23",
            "Q5",
            "MMBT3904",
            14.8,
            108.6,
            0,
            {"1": "Q5B", "2": "GND", "3": "BUCK_EN"},
        )
    )
    parts.append(
        _place(
            "Package_TO_SOT_SMD.pretty/SOT-23.kicad_mod",
            "Package_TO_SOT_SMD:SOT-23",
            "Q6",
            "MMBT3904",
            58.2,
            119.4,
            0,
            {"1": "Q6B", "2": "GND", "3": "Q6C"},
        )
    )

    for p in parts:
        board.append(p)

    tracks = []
    labels = [
        gr_text("2S PACK", 34.5, 59.6, size=1.0),
        gr_text("BMS", 20.0, 78.2, size=0.8),
    ]
    # Routing is filled in by _route_battery so placement can be checked first.
    tracks += _route_battery(board)
    return tracks, labels


def _p(board, ref, number):
    cx, cy, _w, _h, _net = find_pad(board, ref, number)
    return (cx, cy)


def _route_battery(board):
    """Copper for the bay. Endpoints come from the pads; corners are explicit."""
    t = []
    # --- pack positive into Q3 drain, and the balance cell+ pin ---
    xt = _p(board, "J23", "2")
    drain = _p(board, "Q3", "5")
    t += wire([xt, (drain[0], xt[1]), drain], 1.2, "PACK_IN")
    bal = _p(board, "J24", "3")
    t += wire([xt, (bal[0], xt[1]), bal], 0.6, "PACK_IN")

    # --- Q3 gate: straight up the source side into D5, then R7 to a via ---
    gate = _p(board, "Q3", "4")
    z_a = _p(board, "D5", "2")
    z_k = _p(board, "D5", "1")
    t += wire([gate, (gate[0], z_a[1]), z_a], 0.25, "GATE3")
    r7g = _p(board, "R7", "1")
    r7n = _p(board, "R7", "2")
    # Around the left of D5. Dropping on the zener's own x runs through the
    # cathode, which is the PACK pad.
    t += wire([r7g, (r7g[0], 61.6), (41.0, 61.6), (41.0, z_a[1]), z_a], 0.25, "GATE3")
    t.append(via_at(r7n[0] + 1.6, r7n[1], "GND"))
    t += wire([r7n, (r7n[0] + 1.6, r7n[1])], 0.25, "GND")

    # --- protected PACK: source, down, up the gap, into VOUT and the zener ---
    src = _p(board, "Q3", "1")
    # The three source pads share an x and are not jumpers. A trace into pad 1
    # does not tie pad 2 or pad 3. Stop on pad 3: the gate pad is 0.52 mm past it.
    src3 = _p(board, "Q3", "3")
    t += wire([src, src3], 0.8, "PACK")
    vout = _p(board, "U1", "22")
    # 44.0 keeps the 0.8 mm column 0.37 mm off R17 and R18. 44.2 left 0.17 mm.
    # The corner still lands inside C44's PACK pad (that pad spans x 43.7–44.7).
    pack_x = 44.0
    # The 0.8 mm copper stops outside the QFN courtyard. A 0.25 mm neck
    # finishes onto the VOUT pin so it does not bridge the 0.5 mm pitch.
    t += wire(
        [src, (src[0], 83.0), (pack_x, 83.0), (pack_x, 69.2), (pack_x, z_k[1])],
        0.8,
        "PACK",
    )
    # Slot at x=53.25 so the VBATM stub can leave the top of the QFN without
    # crossing this rail. The wide copper stops outside that slot.
    t += wire([(pack_x, 69.2), (52.3, 69.2)], 0.8, "PACK")
    t += wire([(52.3, 69.2), (52.3, 66.2), (54.4, 66.2), (54.4, 69.2)], 0.4, "PACK")
    # The VBATM stub leaves pin 23 at x=53.25. A 0.4 mm finish on the VOUT pin
    # (x=53.75) is 0.175 mm from that stub. 0.25 mm leaves a 0.25 mm gap.
    t += wire([(54.4, 69.2), (vout[0], 69.2), (vout[0], 70.6), vout], 0.25, "PACK")
    vout2 = _p(board, "U1", "21")
    t += wire([(vout[0], 71.85), (vout2[0], 71.85)], 0.25, "PACK")
    t += wire([z_k, (pack_x, z_k[1])], 0.25, "PACK")
    c44g = _p(board, "C44", "2")
    t.append(via_at(c44g[0] + 1.8, c44g[1], "GND"))
    t += wire([c44g, (c44g[0] + 1.8, c44g[1])], 0.4, "GND")

    # --- charger switching ---
    lx_pins = [_p(board, "U1", n) for n in ("15", "16", "17")]
    tie_x = lx_pins[0][0] + 0.75
    for p in lx_pins:
        t += wire([p, (tie_x, p[1])], 0.25, "CHG_LX")
    t += wire([(tie_x, lx_pins[0][1]), (tie_x, lx_pins[-1][1])], 0.25, "CHG_LX")
    l1_lx = _p(board, "L1", "1")
    t += wire([(tie_x, lx_pins[1][1]), (l1_lx[0], lx_pins[1][1]), l1_lx], 0.5, "CHG_LX")
    bst = _p(board, "U1", "14")
    c45a = _p(board, "C45", "1")
    c45b = _p(board, "C45", "2")
    # Right of the VIN pin, and it stops above the EN run.
    t += wire([bst, (59.2, bst[1]), (59.2, c45a[1]), c45a], 0.25, "CHG_BST")
    t += wire([c45b, (c45b[0], lx_pins[1][1])], 0.25, "CHG_LX")
    vsys_pins = [_p(board, "U1", "19"), _p(board, "U1", "20")]
    t += wire([(vsys_pins[0][0], 71.85), (vsys_pins[1][0], 71.85)], 0.25, "CHG_VSYS")
    l1_vs = _p(board, "L1", "2")
    # Above both inductor pads. y=70.35 crosses the LX pad (it spans y 69.25–74.75).
    # The pin escape stays 0.25 mm so it does not widen past pin 19 toward PGND.
    t += wire([vsys_pins[0], (vsys_pins[0][0], 68.6)], 0.25, "CHG_VSYS")
    t += wire([(vsys_pins[0][0], 68.6), (l1_vs[0], 68.6)], 0.4, "CHG_VSYS")
    # Each cap's ground pad sits between its VSYS pad and L1. Leave upward,
    # then join the drop on the VSYS pad's own x.
    c42 = _p(board, "C42", "1")
    c43 = _p(board, "C43", "1")
    # y=58.6 is above C43's ground via. A stub to the right of either cap
    # crosses this drop, so each ground via leaves on the pad's own x.
    t += wire([c43, (c43[0], 58.6), (l1_vs[0], 58.6)], 0.4, "CHG_VSYS")
    t += wire([c42, (c42[0], 62.75), (l1_vs[0], 62.75)], 0.4, "CHG_VSYS")
    t += wire([(l1_vs[0], 58.6), l1_vs], 0.4, "CHG_VSYS")
    g = _p(board, "C43", "2")
    t.append(via_at(g[0], g[1] - 1.6, "GND"))
    t += wire([g, (g[0], g[1] - 1.6)], 0.4, "GND")
    g = _p(board, "C42", "2")
    t.append(via_at(g[0], g[1] + 1.4, "GND"))
    t += wire([g, (g[0], g[1] + 1.4)], 0.4, "GND")
    # Exposed pad and PGND.
    ep = _p(board, "U1", "25")
    t.append(via_at(ep[0], ep[1], "GND"))
    pgnd = _p(board, "U1", "18")
    t.append(via_at(pgnd[0] + 1.5, pgnd[1] - 0.45, "GND"))
    t += wire([pgnd, (pgnd[0] + 1.5, pgnd[1]), (pgnd[0] + 1.5, pgnd[1] - 0.45)], 0.25, "GND")

    # --- charger small signals, each leaving the QFN on its own column ---
    ntc = _p(board, "U1", "4")
    t += wire([ntc, _p(board, "R17", "2")], 0.25, "CHG_NTC")
    # y+1.15 sits between R17 and R18. y+1.5 was 0.075 mm from R18's pad.
    r17g = _p(board, "R17", "1")
    t.append(via_at(r17g[0], r17g[1] + 1.15, "GND"))
    t += wire([r17g, (r17g[0], r17g[1] + 1.15)], 0.25, "GND")
    led = _p(board, "U1", "6")
    r18 = _p(board, "R18", "2")
    t += wire([led, (led[0], r18[1]), r18], 0.25, "CHG_LED")
    # Back side. On the front the return has to cross the PACK column.
    led_a = _p(board, "D7", "2")
    r18a = _p(board, "R18", "1")
    t.append(via_at(led_a[0], led_a[1] + 1.6, "LED_A"))
    t += wire([led_a, (led_a[0], led_a[1] + 1.6)], 0.25, "LED_A")
    t.append(via_at(r18a[0], r18a[1] + 1.6, "LED_A"))
    t += wire([r18a, (r18a[0], r18a[1] + 1.6)], 0.25, "LED_A")
    t += wire(
        [(led_a[0], led_a[1] + 1.6), (r18a[0], r18a[1] + 1.6)],
        0.25,
        "LED_A",
        "B.Cu",
    )
    t.append(via_at(_p(board, "D7", "1")[0] - 1.5, _p(board, "D7", "1")[1], "GND"))
    t += wire([_p(board, "D7", "1"), (_p(board, "D7", "1")[0] - 1.5, _p(board, "D7", "1")[1])], 0.25, "GND")
    time_p = _p(board, "U1", "7")
    r16 = _p(board, "R16", "2")
    t += wire([time_p, (time_p[0], 77.25), (r16[0], 77.25), r16], 0.25, "CHG_TIME")
    iset = _p(board, "U1", "11")
    r15 = _p(board, "R15", "2")
    # The pin's own x runs through R15's ground pad. Step left of that pad,
    # under the resistor, and up into the ISET pad. EN owns x=55.25 down to
    # y=79.6, so this jog stays on the ground-pad side of EN.
    t += wire(
        [iset, (iset[0], 78.2), (53.5, 78.2), (53.5, 83.4), (r15[0], 83.4), r15],
        0.25,
        "CHG_ISET",
    )
    en = _p(board, "U1", "12")
    r14 = _p(board, "R14", "1")
    # Below C45. Stay left of R14's VIN pad; the riser on that pad is VIN_F.
    t += wire([en, (en[0], 79.6), (60.2, 79.6), (60.2, 82.6), (r14[0], 82.6), r14], 0.25, "CHG_EN")
    g = _p(board, "R15", "1")
    # Below the pad. A via to the left would sit on the ISET column at x=53.5.
    t.append(via_at(g[0], g[1] + 1.6, "GND"))
    t += wire([g, (g[0], g[1] + 1.6)], 0.25, "GND")
    g = _p(board, "R16", "1")
    t.append(via_at(g[0], g[1] + 1.6, "GND"))
    t += wire([g, (g[0], g[1] + 1.6)], 0.25, "GND")

    # --- VIN_F: hop under the gate rail, then F.Cu to the charger and Q5 ---
    f2 = _p(board, "F2", "2")
    t += wire([f2, (78.2, f2[1])], 0.6, "VIN_F")
    t.append(via_at(78.2, f2[1], "VIN_F"))
    t.append(via_at(72.0, f2[1], "VIN_F"))
    t += wire([(78.2, f2[1]), (72.0, f2[1])], 0.8, "VIN_F", "B.Cu")
    c40 = _p(board, "C40", "2")
    c41 = _p(board, "C41", "1")
    vin = _p(board, "U1", "13")
    t += wire([(72.0, f2[1]), (57.6, f2[1]), (57.6, c40[1]), c40, c41], 0.5, "VIN_F")
    # The pin cannot drop on F.Cu: CHG_EN owns y=79.6 and BST owns x=59.2.
    # The BST run is 0.5 mm above this pin, so the via sits below the stub
    # (a via on the pin row is 0.075 mm from that trace). Hop at x=57.2,
    # off lane 58, and return on the cap row.
    t += wire([vin, (57.2, vin[1]), (57.2, vin[1] + 0.35)], 0.25, "VIN_F")
    t.append(via_at(57.2, vin[1] + 0.35, "VIN_F"))
    t.append(via_at(57.2, c40[1], "VIN_F"))
    t += wire([(57.2, vin[1] + 0.35), (57.2, c40[1])], 0.25, "VIN_F", "B.Cu")
    # R14's VIN pad is the right one. Come up from below the input caps so the
    # trace does not run across the CHG_EN pad. y=87.4 clears the ground via
    # that sits under C41; the old riser at the pad row shorted that via.
    r14v = _p(board, "R14", "2")
    t += wire([c41, (c41[0], 87.4), (r14v[0], 87.4), r14v], 0.25, "VIN_F")
    g = _p(board, "C40", "1")
    t.append(via_at(g[0] - 1.8, g[1], "GND"))
    t += wire([g, (g[0] - 1.8, g[1])], 0.4, "GND")
    g = _p(board, "C41", "2")
    t.append(via_at(g[0], g[1] + 1.6, "GND"))
    t += wire([g, (g[0], g[1] + 1.6)], 0.4, "GND")

    # VBATM on the back so it can cross the PACK column.
    # The stub uses the slot in the PACK rail. On the back the run sits above
    # the XT30 ground pad (that pad reaches y=66.25) and above the J23 spoke,
    # then drops at x=22, left of the pad and right of the VIN_F hop. A drop
    # at x=30 would wall lane 36.
    vbatm = _p(board, "U1", "23")
    t.append(via_at(vbatm[0], 67.6, "VBATM"))
    t += wire([vbatm, (vbatm[0], 67.6)], 0.25, "VBATM")
    mid = _p(board, "J24", "2")
    t += wire(
        [
            (vbatm[0], 67.6),
            (vbatm[0], 65.2),
            (22.0, 65.2),
            (22.0, 80.0),
            (mid[0], 80.0),
            mid,
        ],
        0.3,
        "VBATM",
        "B.Cu",
    )
    # VBAT_GND (pin 24) is already net GND. A via above the pin sits on the
    # VBATM back-side run, so this one leaves to the left of the QFN.
    vg = _p(board, "U1", "24")
    t.append(via_at(vg[0] - 3.4, vg[1], "GND"))
    t += wire([vg, (vg[0] - 3.4, vg[1])], 0.25, "GND")

    # --- buck power ---
    sw = _p(board, "U2", "6")
    l2sw = _p(board, "L2", "1")
    # Neck stays inside the SW pad's height until it is clear of BOOT.
    t += wire([sw, (sw[0] + 1.55, sw[1])], 0.25, "BUCK_SW")
    t += wire([(sw[0] + 1.55, sw[1]), (l2sw[0], sw[1]), l2sw], 1.2, "BUCK_SW")
    boot = _p(board, "U2", "7")
    c51a = _p(board, "C51", "1")
    c51b = _p(board, "C51", "2")
    t += wire([boot, (boot[0], c51a[1]), c51a], 0.25, "BUCK_BOOT")
    t += wire([c51b, (c51b[0], sw[1])], 0.25, "BUCK_SW")

    # PACK into the buck input. Stop on C47's PACK pad (the right one) so the
    # column does not cross that cap's ground pad. A bus just below the two
    # input caps joins C46 and drops onto the VIN spine.
    vin8 = _p(board, "U2", "8")
    c46 = _p(board, "C46", "1")
    c47 = _p(board, "C47", "2")
    t += wire([(pack_x, 83.0), (pack_x, c47[1]), c47], 0.8, "PACK")
    t += wire(
        [c47, (c47[0], c47[1] + 1.8), (vin8[0], c47[1] + 1.8), (c46[0], c47[1] + 1.8), c46],
        0.6,
        "PACK",
    )
    t += wire([(vin8[0], c47[1] + 1.8), vin8], 0.8, "PACK")
    for ref, padn in (("C46", "2"), ("C47", "1")):
        g = _p(board, ref, padn)
        t.append(via_at(g[0], g[1] - 1.7, "GND"))
        t += wire([g, (g[0], g[1] - 1.7)], 0.4, "GND")

    # BUCK5 from the inductor to a source pad. The output caps tie below L2
    # and rise at x=50, in the gap between the SW pad and the output pad.
    src4 = _p(board, "Q4", "2")
    l2out = _p(board, "L2", "2")
    t += wire([(50.0, l2out[1]), l2out, (src4[0], l2out[1]), src4], 1.2, "BUCK5")
    # Same source-pad tie as Q3. The 1.2 mm run hits pad 2 only.
    t += wire([_p(board, "Q4", "1"), _p(board, "Q4", "3")], 0.8, "BUCK5")
    tops = []
    for ref in ("C48", "C49", "C50"):
        top = _p(board, ref, "2")
        bot = _p(board, ref, "1")
        tops.append(top)
        t.append(via_at(bot[0], bot[1] + 1.8, "GND"))
        t += wire([bot, (bot[0], bot[1] + 1.8)], 0.4, "GND")
    t += wire([tops[0], (50.0, tops[0][1]), tops[-1]], 0.8, "BUCK5")
    t += wire([(50.0, tops[0][1]), (50.0, l2out[1])], 1.0, "BUCK5")
    # Drain down onto the bottom bus. The bus already runs through x=62.
    drain4 = _p(board, "Q4", "5")
    t += wire([(drain4[0], drain4[1]), (drain4[0], BUS_BOT_Y)], 1.5, "+5V")

    gate4 = _p(board, "Q4", "4")
    r8g = _p(board, "R8", "2")
    r8s = _p(board, "R8", "1")
    t += wire([gate4, (gate4[0], r8g[1]), r8g], 0.25, "GATE4")
    t += wire([r8s, (l2out[0], r8s[1]), (l2out[0], l2out[1])], 0.25, "BUCK5")
    d6a = _p(board, "D6", "2")
    d6k = _p(board, "D6", "1")
    t += wire([d6a, (d6a[0], r8g[1])], 0.25, "GATE4")
    # Below R10. A run at the diode's y passes through R10's Q6B pad.
    t += wire([d6k, (d6k[0], 114.6), (54.0, 114.6), (54.0, l2out[1])], 0.4, "BUCK5")
    r9g = _p(board, "R9", "2")
    r9c = _p(board, "R9", "1")
    # Continue up the gate pin's x to the row that already ties R8 and D6.
    t += wire([r9g, (gate4[0], r9g[1]), (gate4[0], r8g[1])], 0.25, "GATE4")
    q6c = _p(board, "Q6", "3")
    t += wire([q6c, (q6c[0], r9c[1]), r9c], 0.25, "Q6C")
    q6b = _p(board, "Q6", "1")
    r10b = _p(board, "R10", "2")
    r10v = _p(board, "R10", "1")
    r11b = _p(board, "R11", "2")
    r11g = _p(board, "R11", "1")
    # R10 stays left of the collector. R11 goes under Q6: the gate and the
    # cathode trace both cross the row above D6.
    join = 117.6
    t += wire([q6b, (q6b[0], join)], 0.25, "Q6B")
    t += wire([r10b, (r10b[0], join), (q6b[0], join)], 0.25, "Q6B")
    t += wire(
        [r11b, (65.4, r11b[1]), (65.4, 121.5), (r10b[0], 121.5), (r10b[0], join)],
        0.25,
        "Q6B",
    )
    # Above the pad. The diode's own y is 0.6 mm below this pad and a trace
    # there touches it. y=114.6 stays 0.4 mm clear, then enters D6 from below.
    t += wire([r10v, (r10v[0], 114.6), (d6k[0], 114.6), d6k], 0.25, "BUCK5")
    t.append(via_at(r11g[0] - 1.6, r11g[1], "GND"))
    t += wire([r11g, (r11g[0] - 1.6, r11g[1])], 0.25, "GND")
    # To the right. A via below the emitter sits on the Q6B run under the part.
    q6e = _p(board, "Q6", "2")
    t.append(via_at(q6e[0] + 2.4, q6e[1], "GND"))
    t += wire([q6e, (q6e[0] + 2.4, q6e[1])], 0.3, "GND")

    # Feedback drops on R20's own column, below EN's pin. R21 is on that
    # same column, so the drop ties it on the way to the pad.
    fb = _p(board, "U2", "2")
    r20f = _p(board, "R20", "2")
    r20v = _p(board, "R20", "1")
    r21g = _p(board, "R21", "1")
    # Past the EN pin vertical (it ends at y=110.6), then left, then up
    # R20's column through the gap in EN's row.
    t += wire([fb, (fb[0], 112.2), (r20f[0], 112.2), r20f], 0.25, "BUCK_FB")
    cap = _p(board, "C48", "2")
    # Back side, so the sense can cross EN and Q5B. The ground bus itself
    # starts at x=86; spokes that would cross this run take another lane.
    t.append(via_at(r20v[0], r20v[1] + 1.5, "BUCK5"))
    t += wire([r20v, (r20v[0], r20v[1] + 1.5)], 0.25, "BUCK5")
    t.append(via_at(40.0, 117.2, "BUCK5"))
    t += wire([cap, (40.0, cap[1]), (40.0, 117.2)], 0.25, "BUCK5")
    t += wire(
        [(r20v[0], r20v[1] + 1.5), (r20v[0], 117.2), (40.0, 117.2)],
        0.25,
        "BUCK5",
        "B.Cu",
    )
    t.append(via_at(r21g[0] - 1.6, r21g[1], "GND"))
    t += wire([r21g, (r21g[0] - 1.6, r21g[1])], 0.25, "GND")
    mode = _p(board, "U2", "10")
    r19 = _p(board, "R19", "2")
    r19g = _p(board, "R19", "1")
    # Down, then up the right side of R19 so the run misses R20.
    t += wire([mode, (mode[0], 109.2), (24.6, 109.2), (24.6, 103.2), (r19[0], 103.2), r19], 0.25, "BUCK_MODE")
    t.append(via_at(r19g[0], r19g[1] - 1.6, "GND"))
    t += wire([r19g, (r19g[0], r19g[1] - 1.6)], 0.25, "GND")
    ag = _p(board, "U2", "3")
    # Right of the pin and below the row. A via on this pin's x sits 0.07 mm
    # from the feedback trace on the next pin.
    t.append(via_at(ag[0] + 1.05, ag[1] + 1.1, "GND"))
    t += wire([ag, (ag[0], ag[1] + 1.1), (ag[0] + 1.05, ag[1] + 1.1)], 0.25, "GND")
    pg = _p(board, "U2", "9")
    # Left, along the pad. A via below the pad is 0.10 mm from the MODE pin.
    t.append(via_at(pg[0] - 1.75, pg[1], "GND"))
    t += wire([pg, (pg[0] - 1.75, pg[1])], 0.3, "GND")

    # Buck enable: Q5 pulls EN down only while VIN_F is up.
    # Below the feedback row, then into the collector from the right. The
    # collector and R12's VIN pad share an x, so the drop stays off that x.
    en2 = _p(board, "U2", "1")
    q5c = _p(board, "Q5", "3")
    # Gap on R20's column. The jog goes above R20: a jog below the row would
    # cross the feedback horizontal, and a bar between the row and the pad
    # would cross the feedback vertical. The bar sits above the pad.
    t += wire([en2, (en2[0], 110.6), (23.7, 110.6)], 0.25, "BUCK_EN")
    t += wire(
        [
            (23.7, 110.6),
            (23.7, 107.0),
            (22.0, 107.0),
            (22.0, 110.6),
            (q5c[0], 110.6),
            q5c,
        ],
        0.25,
        "BUCK_EN",
    )
    q5b = _p(board, "Q5", "1")
    r12b = _p(board, "R12", "1")
    r12v = _p(board, "R12", "2")
    r13b = _p(board, "R13", "2")
    r13g = _p(board, "R13", "1")
    # Base and emitter share an x. R13's ground pad is directly below R12, so
    # the Q5B net reaches R13's right pad from underneath.
    t += wire([q5b, (11.2, q5b[1]), (11.2, 118.2), (r13b[0], 118.2), r13b], 0.25, "Q5B")
    t += wire([(11.2, r12b[1]), r12b], 0.25, "Q5B")
    # Sense VIN_F on the back. The via sits below R12: the Q5B spur owns the
    # pad row, and the hop has to clear the mounting hole (right edge 14.15)
    # and the XT30 peg (pad left edge 15.3). It crosses the spoke-bus line
    # only at that x, where no spoke joins. The bridge is above the XT30
    # ground pad, so J23 leaves to the right at y=68 and drops on lane 36.
    hop = 14.7
    bridge_y = 63.2
    # Above R12. The row below the part is the Q5B spur and the EN run.
    sense_y = r12v[1] - 1.2
    t += wire([r12v, (r12v[0], sense_y), (hop, sense_y)], 0.25, "VIN_F")
    t.append(via_at(hop, sense_y, "VIN_F"))
    y = f2[1]
    t += wire(
        [
            (hop, sense_y),
            (hop, bridge_y),
            (66.0, bridge_y),
            (66.0, y),
            (72.0, y),
        ],
        0.4,
        "VIN_F",
        "B.Cu",
    )
    t.append(via_at(r13g[0] - 1.5, r13g[1], "GND"))
    t += wire([r13g, (r13g[0] - 1.5, r13g[1])], 0.25, "GND")
    q5e = _p(board, "Q5", "2")
    t.append(via_at(q5e[0] - 1.6, q5e[1], "GND"))
    t += wire([q5e, (q5e[0] - 1.6, q5e[1])], 0.3, "GND")
    return t


def add_node_labels(board):
    labels = []
    for fp in kids(board, "footprint"):
        ref = prop(fp, "Reference") or ""
        if not ref.startswith("J"):
            continue
        # SMA connectors are the coaxial ones, not USB (J21) or the input (J22)
        name = fp[1].t
        if "SMA" not in name and "Coaxial" not in name and "BWSMA" not in name:
            # value or footprint name
            if "SMA" not in (prop(fp, "Value") or "") and "BWSMA" not in name:
                continue
        prefix, n, suffix = node_number_from_ref(ref)
        if prefix != "J" or suffix or n is None or n > 20:
            continue
        x, y, ang, _ = placement(fp)
        if y < 100:
            labels.append(gr_text(str(n), x - 6.5, 67.5, size=1.2))
        else:
            # y=128 sits on the SMA body silk of the original columns.
            labels.append(gr_text(str(n), x - 6.5, 123.2, size=1.2))
    return labels


def rebuild_outline(board):
    # drop old edge cuts
    board[:] = [c for c in board if not is_edge(c)]
    dxr = DX_SHIFT
    # Left edge moves out for the pack bay. Right edge follows the extra column.
    L, R = BOARD_L, 265.05 + dxr
    T, B = BOARD_T, BOARD_B
    # arcs use the 3 mm corner and the same mid inset (0.87868)
    ins = 0.87868
    items = [
        gr_arc(L, T + 3, L + ins, T + ins, L + 3, T),
        gr_line(L + 3, T, R - 3, T),
        gr_arc(R - 3, T, R - ins, T + ins, R, T + 3),
        gr_line(R, T + 3, R, B - 3),
        gr_arc(R, B - 3, R - ins, B - ins, R - 3, B),
        gr_line(R - 3, B, L + 3, B),
        gr_arc(L + 3, B, L + ins, B - ins, L, B - 3),
        gr_line(L, B - 3, L, T + 3),
    ]
    # zone outline
    for z in kids(board, "zone"):
        if kid(z, "net") and kid(z, "net")[1].t == "GND":
            poly = kid(z, "polygon")
            pts = kid(poly, "pts")
            zl, zr = L + ins, R - ins
            zt, zb = T + ins, B - ins
            pts[:] = [
                A("pts", False),
                [A("xy", False), A(fmt(zl), False), A(fmt(zt), False)],
                [A("xy", False), A(fmt(zr), False), A(fmt(zt), False)],
                [A("xy", False), A(fmt(zr), False), A(fmt(zb), False)],
                [A("xy", False), A(fmt(zl), False), A(fmt(zb), False)],
            ]
            # Keep the V2 pour, shifted with the original parts, so the right-hand
            # bank still has a ground plane. The new columns are tied in with
            # B.Cu spokes. Refill this zone in KiCad before fabrication.
            for filled in kids(z, "filled_polygon"):
                shift_fill(filled, DX_SHIFT)
    return items


def shift_fill(node, dx):
    if not isinstance(node, list):
        return
    if head(node) == "xy" and len(node) > 2:
        atom_num(node, 1, num(node[1]) + dx)
    for c in node:
        shift_fill(c, dx)


def pour_contains(board, x, y):
    """Even-odd test against the board-level GND fill on B.Cu."""

    def rings():
        for z in kids(board, "zone"):
            net = kid(z, "net")
            layer = kid(z, "layer")
            if not net or net[1].t != "GND":
                continue
            if not layer or layer[1].t != "B.Cu":
                continue
            for filled in kids(z, "filled_polygon"):
                pts = kid(filled, "pts")
                ring = []
                for c in pts:
                    if isinstance(c, list) and head(c) == "xy":
                        ring.append((num(c[1]), num(c[2])))
                if len(ring) > 2:
                    yield ring

    for ring in rings():
        inside = False
        n = len(ring)
        for i in range(n):
            x1, y1 = ring[i]
            x2, y2 = ring[(i + 1) % n]
            if (y1 > y) != (y2 > y):
                xhit = (x2 - x1) * (y - y1) / (y2 - y1) + x1
                if x < xhit:
                    inside = not inside
        if inside:
            return True
    return False


def add_gnd_return(board):
    """Tie GND left of the shifted pour into that pour on B.Cu.

    Header pins run in X, one row at a time. A vertical spoke on a ground
    pin misses the rest of its own header and hits the row below it, so
    those pins jog through the open band between rows and drop down a lane
    between columns. The bus sits in the open band between the bottom
    headers (y=110.6), where the shifted V2 fill is solid copper from
    about x=240 to the right side.
    """
    bus_y = 110.6
    bus_w = 4.0
    spoke_w = 0.6
    # Right of the input terminal. The MOSFET is F.Cu only, so the back-side
    # bus can pass under it. A 4 mm end cap stays off the terminal barrels.
    bus_x0 = 86.0
    bus_x1 = 400.0
    # These two points are the 18-node pour checks (110 and 180 in V2) shifted
    # by DX_SHIFT. The pour itself is the V2 fill, translated with the parts.
    if not pour_contains(board, 285, bus_y) or not pour_contains(board, 355, bus_y):
        raise RuntimeError("GND bus does not land in the shifted pour")
    # Lanes sit between pin columns. Bands sit between pin rows and the SMAs.
    # 18/36/58 serve the pack bay. 248 reaches the fifth clone column.
    lanes = (18.0, 36.0, 58.0, 86.0, 110.0, 145.0, 180.0, 213.0, 248.0)
    bands = (68.0, 82.0, 96.0, 126.0)
    cutoff = 272.0

    obstacles = []
    targets = []
    for fp in kids(board, "footprint"):
        ref = prop(fp, "Reference")
        for pad in kids(fp, "pad"):
            ptype = pad[2].t
            cx, cy, W, H, netn, _num = pad_center_and_aabb(fp, pad)
            rad = max(W, H)
            if ptype == "np_thru_hole":
                drill = kid(pad, "drill")
                if drill is not None:
                    rad = max(rad, num(drill[1]) / 2.0)
                obstacles.append((cx, cy, rad + 0.4))
                continue
            if ptype != "thru_hole":
                continue
            if netn == "GND" and cx < cutoff:
                targets.append((cx, cy, ref or ""))
            elif netn != "GND":
                obstacles.append((cx, cy, rad))

    # Spokes are B.Cu. A foreign back-side track is invisible to the pad scan,
    # so sample those segments or a spoke will cross the VIN_F hop.
    for s in kids(board, "segment"):
        net = kid(s, "net")[1].t
        layer = kid(s, "layer")[1].t if kid(s, "layer") else "F.Cu"
        if layer != "B.Cu" or net == "GND":
            continue
        st, en = kid(s, "start"), kid(s, "end")
        x1, y1 = num(st[1]), num(st[2])
        x2, y2 = num(en[1]), num(en[2])
        sw = num(kid(s, "width")[1]) / 2.0
        length = math.hypot(x2 - x1, y2 - y1)
        steps = max(int(length / 0.8), 1)
        for i in range(steps + 1):
            t = i / steps
            obstacles.append((x1 + (x2 - x1) * t, y1 + (y2 - y1) * t, sw))

    vias = []
    for fp in kids(board, "footprint"):
        if prop(fp, "Reference") != "C39":
            continue
        for pad in kids(fp, "pad"):
            cx, cy, _W, _H, netn, _num = pad_center_and_aabb(fp, pad)
            if netn == "GND":
                vias.append(via_at(cx, cy, "GND"))
                targets.append((cx, cy, "C39"))

    for v in kids(board, "via"):
        at = kid(v, "at")
        x, y = num(at[1]), num(at[2])
        net = kid(v, "net")[1].t if kid(v, "net") else "GND"
        if net == "GND" and x < cutoff:
            targets.append((x, y, "via"))
        elif net != "GND":
            # Segment samples use the trace half-width, which is thinner than
            # the via. A spoke can then sit 0.18 mm from the via. 0.35 covers
            # the 0.3 mm pad plus the router's 0.015 mm slack.
            obstacles.append((x, y, 0.35))

    def off_board(x1, y1, x2, y2, width):
        m = width / 2.0
        left, right = BOARD_L, 265.05 + DX_SHIFT
        top, bot = BOARD_T, BOARD_B
        if min(x1, x2) - m < left + 0.25:
            return True
        if max(x1, x2) + m > right - 0.25:
            return True
        if min(y1, y2) - m < top + 0.25:
            return True
        if max(y1, y2) + m > bot - 0.25:
            return True
        return False

    def blocked(points, width):
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            if abs(x1 - x2) < 1e-6 and abs(y1 - y2) < 1e-6:
                continue
            if off_board(x1, y1, x2, y2, width):
                return True
            for ox, oy, rad in obstacles:
                d = seg_point_dist(x1, y1, x2, y2, ox, oy)
                if d < rad + width / 2.0 + CLEARANCE - 0.015:
                    return True
        return False

    def clamp_x(x):
        return min(max(x, bus_x0), bus_x1)

    tracks = [seg(bus_x0, bus_y, bus_x1, bus_y, bus_w, "GND", "B.Cu")]
    missed = []
    for x, y, ref in targets:
        candidates = []
        candidates.append([(x, y), (x, bus_y), (clamp_x(x), bus_y)])
        for lx in sorted(lanes, key=lambda lane: abs(lane - x)):
            candidates.append([(x, y), (lx, y), (lx, bus_y), (clamp_x(lx), bus_y)])
        for band in sorted(bands, key=lambda b: abs(b - y)):
            for lx in sorted(lanes, key=lambda lane: abs(lane - x)):
                candidates.append(
                    [(x, y), (x, band), (lx, band), (lx, bus_y), (clamp_x(lx), bus_y)]
                )
        routed = None
        for pts in candidates:
            if not blocked(pts, spoke_w):
                routed = pts
                break
        if routed is None:
            missed.append((ref, round(x, 2), round(y, 2)))
            continue
        for (x1, y1), (x2, y2) in zip(routed, routed[1:]):
            if abs(x1 - x2) < 1e-6 and abs(y1 - y2) < 1e-6:
                continue
            tracks.append(seg(x1, y1, x2, y2, spoke_w, "GND", "B.Cu"))
    if missed:
        for item in missed[:40]:
            print(" UNROUTED", item)
        raise RuntimeError(f"{len(missed)} GND targets have no clear spoke")
    print(f"GND spokes {len(tracks)} segments, {len(targets)} targets")
    return tracks, vias


def update_title(board):
    tb = kid(board, "title_block")
    if tb is None:
        return
    for c in tb:
        if isinstance(c, list) and head(c) == "title":
            c[1] = A("PacketHog-20", True)
        elif isinstance(c, list) and head(c) == "date":
            c[1] = A("2026-11-17", True)
    tb.append([A("comment", False), A("1", False), A("20 XIAO ESP32-C5", True)])


def retitle_silkscreen(board):
    for c in board:
        if isinstance(c, list) and head(c) == "gr_text" and c[1].t == "V7":
            c[1] = A("20", True)
            c[:] = [x for x in c if head(x) != "render_cache"]


# ---------- checks ----------

def aabb_hit(a, b, gap):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return abs(ax - bx) < (aw + bw + gap) and abs(ay - by) < (ah + bh + gap)


def seg_point_dist(x1, y1, x2, y2, px, py):
    vx, vy = x2 - x1, y2 - y1
    l2 = vx * vx + vy * vy
    if l2 < 1e-12:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * vx + (py - y1) * vy) / l2))
    return math.hypot(px - (x1 + t * vx), py - (y1 + t * vy))


def check(board):
    problems = []
    pads = list(iter_pads(board))
    # pad vs pad
    for i in range(len(pads)):
        r1, n1, x1, y1, w1, h1, net1 = pads[i]
        for j in range(i + 1, len(pads)):
            r2, n2, x2, y2, w2, h2, net2 = pads[j]
            if net1 and net1 == net2:
                continue
            if r1 == r2:
                continue
            if aabb_hit((x1, y1, w1, h1), (x2, y2, w2, h2), CLEARANCE):
                problems.append(
                    f"pad {r1}/{n1}({net1}) vs {r2}/{n2}({net2}) at ({x1:.2f},{y1:.2f})-({x2:.2f},{y2:.2f})"
                )
    pad_layer = {}
    for fp in kids(board, "footprint"):
        ref = prop(fp, "Reference")
        for pad in kids(fp, "pad"):
            layers = kid(pad, "layers")
            names = {a.t for a in layers[1:]} if layers else set()
            pad_layer[(ref, pad[1].t)] = (pad[2].t, names)
    segs = []
    for s in kids(board, "segment"):
        st, en = kid(s, "start"), kid(s, "end")
        w = num(kid(s, "width")[1])
        net = kid(s, "net")[1].t
        layer = kid(s, "layer")[1].t if kid(s, "layer") else "F.Cu"
        segs.append((num(st[1]), num(st[2]), num(en[1]), num(en[2]), w, net, layer))
    vias = []
    for v in kids(board, "via"):
        at = kid(v, "at")
        size = num(kid(v, "size")[1]) / 2
        net = kid(v, "net")[1].t if kid(v, "net") else "GND"
        vias.append((num(at[1]), num(at[2]), size, net))
    for x1, y1, x2, y2, w, net, layer in segs:
        for r, n, px, py, pw, ph, pnet in pads:
            if pnet == net:
                continue
            ptype, lnames = pad_layer.get((r, n), ("thru_hole", {"*.Cu"}))
            # A back-side spoke does not meet an F.Cu-only SMT pad. Through-hole
            # barrels (layers "*.Cu") still count.
            on_layer = ptype == "thru_hole" or "*.Cu" in lnames or layer in lnames
            if not on_layer:
                continue
            # conservative radius
            rad = math.hypot(pw, ph)
            d = seg_point_dist(x1, y1, x2, y2, px, py)
            if d < rad + w / 2 + CLEARANCE - 0.05:
                # filter to things that are actually close, skip the flood of
                # conservative hits more than 0.6 mm of extra slop
                if d < max(pw, ph) + w / 2 + CLEARANCE:
                    problems.append(
                        f"track {net}@{layer} w={w} vs pad {r}/{n}({pnet}) d={d:.2f} at ({px:.2f},{py:.2f})"
                    )
        for vx, vy, vr, vnet in vias:
            if vnet == net:
                continue
            d = seg_point_dist(x1, y1, x2, y2, vx, vy)
            if d < vr + w / 2 + CLEARANCE:
                problems.append(f"track {net} w={w} vs via {vnet} d={d:.2f} at ({vx:.2f},{vy:.2f})")
    def orient(ax, ay, bx, by, cx, cy):
        return (by - ay) * (cx - bx) - (bx - ax) * (cy - by)

    def segs_cross(a, b):
        ax, ay, bx, by = a
        cx, cy, dx, dy = b
        o1 = orient(ax, ay, bx, by, cx, cy)
        o2 = orient(ax, ay, bx, by, dx, dy)
        o3 = orient(cx, cy, dx, dy, ax, ay)
        o4 = orient(cx, cy, dx, dy, bx, by)
        return o1 * o2 < 0 and o3 * o4 < 0

    for i in range(len(segs)):
        x1, y1, x2, y2, w1, n1, lay1 = segs[i]
        for j in range(i + 1, len(segs)):
            x3, y3, x4, y4, w2, n2, lay2 = segs[j]
            if n1 == n2 or lay1 != lay2:
                continue
            if segs_cross((x1, y1, x2, y2), (x3, y3, x4, y4)):
                problems.append(f"cross {n1}@{lay1} w={w1} ({x1:.1f},{y1:.1f})-({x2:.1f},{y2:.1f}) vs {n2}")
            else:
                # parallel clearance, sample endpoints
                for px, py in ((x3, y3), (x4, y4)):
                    d = seg_point_dist(x1, y1, x2, y2, px, py)
                    if d < w1 / 2 + w2 / 2 + CLEARANCE and d > 0.01:
                        problems.append(f"near {n1}/{n2}@{lay1} d={d:.2f} at ({px:.1f},{py:.1f})")
                        break
    # edge clearance of copper pads
    L, R, T, B = BOARD_L, 265.05 + DX_SHIFT, BOARD_T, BOARD_B
    for r, n, x, y, w, h, net in pads:
        if x - w < L + 0.3 or x + w > R - 0.3 or y - h < T + 0.3 or y + h > B - 0.3:
            problems.append(f"edge pad {r}/{n} at ({x:.2f},{y:.2f}) half {w:.2f}x{h:.2f}")
    return problems


def render(board, path):
    pads = list(iter_pads(board))
    segs = []
    for s in kids(board, "segment"):
        st, en = kid(s, "start"), kid(s, "end")
        net = kid(s, "net")[1].t
        layer = kid(s, "layer")[1].t if kid(s, "layer") else "F.Cu"
        segs.append((num(st[1]), num(st[2]), num(en[1]), num(en[2]), net, layer))
    fps = []
    for fp in kids(board, "footprint"):
        x, y, ang, _ = placement(fp)
        fps.append((prop(fp, "Reference"), x, y))
    xs = [4, 446]
    ys = [50, 145]
    scale = 7
    m = 20

    def X(x):
        return int((x - xs[0]) * scale) + m

    def Y(y):
        return int((y - ys[0]) * scale) + m

    w = X(xs[1]) + m
    h = Y(ys[1]) + m
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        # PPM fallback
        img = [[[255, 255, 255] for _ in range(w)] for _ in range(h)]

        def dot(x, y, rgb):
            if 0 <= x < w and 0 <= y < h:
                img[y][x] = rgb

        def line(x1, y1, x2, y2, rgb):
            steps = int(max(abs(x2 - x1), abs(y2 - y1), 1))
            for i in range(steps + 1):
                t = i / steps
                dot(int(x1 + (x2 - x1) * t), int(y1 + (y2 - y1) * t), rgb)

        for x1, y1, x2, y2, net, layer in segs:
            col = (220, 40, 40) if net == "+5V" else (180, 80, 0) if net in ("VIN", "VIN_F", "PACK", "PACK_IN", "BUCK5") else (40, 90, 200) if net.startswith("SMA") else (20, 140, 70) if net == "GND" and layer == "B.Cu" else (0, 0, 0)
            line(X(x1), Y(y1), X(x2), Y(y2), col)
        ppm = path.with_suffix(".ppm")
        with ppm.open("w") as f:
            f.write(f"P3\n{w} {h}\n255\n")
            for row in img:
                f.write(" ".join(f"{p[0]} {p[1]} {p[2]}" for p in row) + "\n")
        os.system(f"sips -s format png {ppm} --out {path} >/dev/null")
        return
    im = Image.new("RGB", (w, h), "white")
    dr = ImageDraw.Draw(im)
    dr.rectangle([X(BOARD_L), Y(BOARD_T), X(265.05 + DX_SHIFT), Y(BOARD_B)], outline=(0, 120, 0))
    for x1, y1, x2, y2, net, layer in segs:
        col = (200, 30, 30) if net == "+5V" else (180, 80, 0) if net in ("VIN", "VIN_F", "PACK", "PACK_IN", "BUCK5") else (30, 80, 180) if net.startswith("SMA") else (20, 130, 60) if net == "GND" and layer == "B.Cu" else (0, 0, 0)
        width = 3 if net == "+5V" or (net == "GND" and layer == "B.Cu") else 1
        dr.line([(X(x1), Y(y1)), (X(x2), Y(y2))], fill=col, width=width)
    for r, n, x, y, pw, ph, net in pads:
        col = (255, 180, 180) if net == "+5V" else (180, 180, 255) if net == "GND" else (220, 220, 220)
        dr.rectangle([X(x - pw), Y(y - ph), X(x + pw), Y(y + ph)], outline=col)
    for ref, x, y in fps:
        if ref and (ref.startswith("H") or ref.startswith("J") or ref.startswith("D") or ref.startswith("F") or ref.startswith("C3")):
            dr.text((X(x), Y(y)), ref, fill=(0, 0, 0))
    im.save(path)


def write_bom(board):
    rows = []
    for fp in kids(board, "footprint"):
        ref = prop(fp, "Reference")
        val = prop(fp, "Value")
        fpname = fp[1].t
        x, y, ang, _ = placement(fp)
        rows.append((ref, val, fpname, x, y, ang))
    rows.sort(key=lambda r: (r[0] or "",))
    prod = DEST_DIR / "production"
    prod.mkdir(parents=True, exist_ok=True)
    lines = ["Designator,Value,Footprint,X_mm,Y_mm,Rotation"]
    for ref, val, fpname, x, y, ang in rows:
        lines.append(f'{ref},{val},{fpname},{x:.3f},{y:.3f},{ang:.1f}')
    (prod / "positions.csv").write_text("\n".join(lines) + "\n")
    groups = {}
    for ref, val, fpname, *_ in rows:
        groups.setdefault((val, fpname), []).append(ref)
    bl = ["Value,Footprint,Quantity,Designators"]
    for (val, fpname), refs in sorted(groups.items(), key=lambda kv: kv[0][0] or ""):
        bl.append(f'{val},{fpname},{len(refs)},"{" ".join(refs)}"')
    (prod / "bom.csv").write_text("\n".join(bl) + "\n")


def copy_project():
    src_dir = SRC.parent
    for name in ("fp-lib-table", "sym-lib-table"):
        shutil.copy(src_dir / name, DEST_DIR / name)
    pro = (src_dir / "PacketHog-V2.kicad_pro").read_text()
    pro = pro.replace("PacketHog-V2", "PacketHog-20")
    (DEST_DIR / "PacketHog-20.kicad_pro").write_text(pro)
    sch = (src_dir / "PacketHog-V2.kicad_sch").read_text()
    sch = sch.replace('(project "PacketHog-V2"', '(project "PacketHog-20"')
    note = """\t(text "PacketHog-20 PCB is the routed 20-node board. This sheet is the original 10-node drawing and is not the netlist. Do not update the PCB from this schematic."
\t\t(exclude_from_sim no)
\t\t(at 20 12 0)
\t\t(effects
\t\t\t(font
\t\t\t\t(size 2.0 2.0)
\t\t\t)
\t\t\t(justify left top)
\t\t)
\t\t(uuid "%s")
\t)
""" % new_uuid()
    sch = sch.replace("\t(sheet_instances", note + "\t(sheet_instances", 1)
    (DEST_DIR / "PacketHog-20.kicad_sch").write_text(sch)
    prl = src_dir / "PacketHog-V2.kicad_prl"
    if prl.exists():
        shutil.copy(prl, DEST_DIR / "PacketHog-20.kicad_prl")


def fix_usb_hole_clearance(board):
    """Shorten the USB-C GND lands on the end next to the locating pegs.

    The GCT USB4105 land is 1.15 mm long and clears its own Ø0.65 pegs by
    0.194 mm. The board rule is 0.25 mm. Pull that end back 0.07 mm and
    leave the other end on the datasheet coordinate. A1/B12 share one land
    and A12/B1 share the other.
    """
    for fp in kids(board, "footprint"):
        if prop(fp, "Reference") != "J21":
            continue
        found = []
        for pad in kids(fp, "pad"):
            if pad[1].t not in ("A1", "A12", "B1", "B12"):
                continue
            at = kid(pad, "at")
            size = kid(pad, "size")
            # Local Y is the long axis. The pegs sit at local y=-2.605.
            atom_num(at, 2, -3.715)
            atom_num(size, 2, 1.08)
            found.append(pad[1].t)
        if sorted(found) != ["A1", "A12", "B1", "B12"]:
            raise RuntimeError(f"J21 GND pads not all adjusted: {found}")
        return
    raise RuntimeError("J21 missing")


def main():
    print("parsing", SRC)
    board = parse(SRC.read_text())
    fps = {prop(fp, "Reference"): fp for fp in kids(board, "footprint")}
    templates = [fps[r] for r in TEMPLATE_REFS]
    template_segs = []
    for s in kids(board, "segment"):
        net = kid(s, "net")[1].t
        if net in ("SMA2", "SMA7"):
            template_segs.append(s)
    template_vias = []
    for v in kids(board, "via"):
        x = num(kid(v, "at")[1])
        if 120.0 <= x <= 156.0:
            template_vias.append(v)
    fan = fps["FAN1"]
    c1 = fps["C1"]
    print(f"template fps {len(templates)} sma segs {len(template_segs)} vias {len(template_vias)}")

    clones = clone_columns(board, templates, template_segs, template_vias)
    rename_existing(board)

    # shift original geometry, except the left mounting holes and the edge
    for item in list(board):
        if not isinstance(item, list):
            continue
        h = head(item)
        if h == "footprint":
            ref = prop(item, "Reference")
            # after rename, left holes are still MH1/MH2
            if ref in ("MH1", "MH2"):
                continue
            shift_x_fields(item, DX_SHIFT)
        elif h in ("segment", "via", "gr_poly", "gr_text", "gr_circle", "dimension"):
            shift_x_fields(item, DX_SHIFT)
        elif is_edge(item):
            continue
        elif h == "zone":
            continue
        elif h == "group":
            continue

    move_mounting_holes(board)
    retitle_silkscreen(board)
    update_title(board)
    fix_usb_hole_clearance(board)

    # insert clones (already at final coordinates)
    # footprint clones and graphic clones are mixed; append all
    for c in clones:
        board.append(c)

    tracks, labels = add_power(board, fan, c1)
    for t in tracks:
        board.append(t)
    for lb in labels:
        board.append(lb)
    b_tracks, b_labels = add_battery(board)
    for t in b_tracks:
        board.append(t)
    for lb in b_labels:
        board.append(lb)
    for lb in add_node_labels(board):
        board.append(lb)
    for item in rebuild_outline(board):
        board.append(item)
    gnd_tracks, gnd_vias = add_gnd_return(board)
    for v in gnd_vias:
        board.append(v)
    for t in gnd_tracks:
        board.append(t)

    problems = check(board)
    real = [p for p in problems if "J21/" not in p]
    print(f"clearance notes: {len(problems)} ({len(real)} besides the V2 USB fanout)")
    for p in real[:80]:
        print(" ", p)
    if len(real) > 80:
        print(f"  ... {len(real) - 80} more")

    refs = sorted(prop(fp, "Reference") for fp in kids(board, "footprint"))
    print("footprints", len(refs))
    print("headers", sum(1 for r in refs if r.startswith("H")))
    print("sma", [r for r in refs if r.startswith("J")])

    DEST_DIR.mkdir(parents=True, exist_ok=True)
    text = emit(board) + "\n"
    DEST_PCB.write_text(text)
    print("wrote", DEST_PCB, "bytes", DEST_PCB.stat().st_size)
    write_bom(board)
    copy_project()
    png = Path("/tmp/packethog20.png")
    render(board, png)
    print("render", png)
    # reparse to confirm the printer is valid sexpr
    parse(text)
    print("reparse ok")
    return len(real)


if __name__ == "__main__":
    raise SystemExit(main())
