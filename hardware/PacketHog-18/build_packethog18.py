#!/usr/bin/env python3
"""Build PacketHog-18 from the PacketHog-V2 PCB.

10 XIAO sockets become 18 (2 rows x 9). The original layout shifts right by
four column pitches and four cloned columns fill the left side. The V2 USB-C
circuit is unchanged and cannot run 18 radios. J19's four GND lands are
0.07 mm shorter on the locating-peg end so they clear the 0.25 mm hole rule.
The left margin is a 5 V screw terminal, a 10 A fuse, and a P-channel
ideal-diode OR onto the +5 V buses.
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
DEST_DIR = ROOT / "hardware" / "PacketHog-18"
DEST_PCB = DEST_DIR / "PacketHog-18.kicad_pcb"

DX_SHIFT = 140.0  # 4 columns * 35 mm
COL_PITCH = 35.0
TEMPLATE_SMA_X = 135.0
NEW_SMA_X = [100.0, 135.0, 170.0, 205.0]  # final, pre-shift coordinates
BUS_TOP_Y = 97.0
BUS_BOT_Y = 124.5
# 1 oz external copper. The spine carries the whole array; the buses taper
# as columns tap off. 4.0 / 3.2 mm is the width that still clears the headers,
# C35, and the left board edge.
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
        return n + 4
    if 6 <= n <= 10:
        return n + 8
    return None


def rename_existing(board):
    """Single pass. Each field is rewritten from its current value once."""

    def map_ref(ref):
        if ref == "J11":
            return "J19"
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
        bot_n = i + 10
        cap_ids = {
            "top10": f"C{19 + i}",
            "top1": f"C{23 + i}",
            "bot10": f"C{27 + i}",
            "bot1": f"C{31 + i}",
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
        "J20",
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
    """External 5 V inlet sized for 18 nodes.

    J20 screw terminal -> F2 10 A fuse -> Q1 drain. Q1 is a P-channel with
    source on +5V. Q2 pulls the gate down only while VIN_F is present, so a
    USB-only rail cannot turn the FET on and the body diode stays reverse
    biased. This is not over-voltage protection: a VIN above 5 V still reaches
    the modules through the channel and the body diode.

    fan_fp is unused. The terminal is a library footprint, not a stretched FAN1.
    """
    del fan_fp
    taken = {prop(fp, "Reference") for fp in kids(board, "footprint")}
    for ref in ("J20", "F2", "Q1", "Q2", "R3", "R4", "R5", "R6", "D4", "C35"):
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
    set_prop(c35, "Reference", "C35")
    # y=128 clears MH2's courtyard. The gate parts sit above this courtyard.
    set_placement(c35, 80.5, 128.0, 0)
    parts.append(c35)
    for p in parts:
        board.append(p)

    tracks = []
    vin = find_pad(board, "J20", "2")
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
    top_end = min(top_end, 393.0)
    bot_end = min(bot_end, 386.0)
    print(f"+5V bus ends top x={top_end:.2f} bottom x={bot_end:.2f}")
    if top_end < 300 or bot_end < 300:
        raise RuntimeError("wide +5V bus was stopped short of the array")
    tracks += [seg(SPINE_X, BUS_TOP_Y, SPINE_X, BUS_BOT_Y, SPINE_W, "+5V")]
    tracks += [seg(SPINE_X, BUS_TOP_Y, top_end, BUS_TOP_Y, TOP_BUS_W, "+5V")]
    c_pos = find_pad(board, "C35", "1")
    c_neg = find_pad(board, "C35", "2")
    if c_pos[4] != "+5V":
        c_pos, c_neg = c_neg, c_pos
    # End cap of a 3.2 mm trace begun at the cap pad stays inside the board edge.
    tracks += [seg(c_pos[0], BUS_BOT_Y, bot_end, BUS_BOT_Y, BOT_BUS_W, "+5V")]
    tracks += [seg(c_pos[0], c_pos[1], c_pos[0], BUS_BOT_Y, 0.8, "+5V")]

    for i, sma_x in enumerate(NEW_SMA_X):
        top_n = i + 1
        bot_n = i + 10
        ptop = find_pad(board, f"H{top_n}B", "7")
        pbot = find_pad(board, f"H{bot_n}B", "7")
        tracks += [seg(ptop[0], ptop[1], ptop[0], BUS_TOP_Y, SPUR_W, "+5V")]
        tracks += [seg(pbot[0], pbot[1], pbot[0], BUS_BOT_Y, SPUR_W, "+5V")]
        for cref, by in (
            (f"C{19 + i}", BUS_TOP_Y),
            (f"C{23 + i}", BUS_TOP_Y),
            (f"C{27 + i}", BUS_BOT_Y),
            (f"C{31 + i}", BUS_BOT_Y),
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


def add_node_labels(board):
    labels = []
    for fp in kids(board, "footprint"):
        ref = prop(fp, "Reference") or ""
        if not ref.startswith("J"):
            continue
        # SMA connectors are the coaxial ones, not USB (J19) or the input (J12)
        name = fp[1].t
        if "SMA" not in name and "Coaxial" not in name and "BWSMA" not in name:
            # value or footprint name
            if "SMA" not in (prop(fp, "Value") or "") and "BWSMA" not in name:
                continue
        prefix, n, suffix = node_number_from_ref(ref)
        if prefix != "J" or suffix or n is None or n > 18:
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
    # left edge unchanged, right edge +140, corner radius 3 mm, same inset as V2
    L, R = 74.95, 265.05 + dxr
    T, B = 54.45, 140.55
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
    bus_x1 = 360.0
    if not pour_contains(board, 250, bus_y) or not pour_contains(board, 320, bus_y):
        raise RuntimeError("GND bus does not land in the shifted pour")
    # Lanes sit between pin columns. Bands sit between pin rows and the SMAs.
    lanes = (86.0, 110.0, 145.0, 180.0, 213.0)
    bands = (68.0, 82.0, 96.0, 126.0)
    cutoff = 225.0

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

    vias = []
    for fp in kids(board, "footprint"):
        if prop(fp, "Reference") != "C35":
            continue
        for pad in kids(fp, "pad"):
            cx, cy, _W, _H, netn, _num = pad_center_and_aabb(fp, pad)
            if netn == "GND":
                vias.append(via_at(cx, cy, "GND"))
                targets.append((cx, cy, "C35"))

    for v in kids(board, "via"):
        at = kid(v, "at")
        x, y = num(at[1]), num(at[2])
        net = kid(v, "net")[1].t if kid(v, "net") else "GND"
        if net == "GND" and x < cutoff:
            targets.append((x, y, "via"))

    def off_board(x1, y1, x2, y2, width):
        m = width / 2.0
        left, right, top, bot = 74.95, 405.05, 54.45, 140.55
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
            c[1] = A("PacketHog-18", True)
        elif isinstance(c, list) and head(c) == "date":
            c[1] = A("2026-11-14", True)
    tb.append([A("comment", False), A("1", False), A("18 XIAO ESP32-C5", True)])


def retitle_silkscreen(board):
    for c in board:
        if isinstance(c, list) and head(c) == "gr_text" and c[1].t == "V7":
            c[1] = A("18", True)
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
    L, R, T, B = 74.95, 265.05 + DX_SHIFT, 54.45, 140.55
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
    xs = [74, 406]
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
            col = (220, 40, 40) if net == "+5V" else (40, 90, 200) if net.startswith("SMA") else (20, 140, 70) if net == "GND" and layer == "B.Cu" else (0, 0, 0)
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
    dr.rectangle([X(74.95), Y(54.45), X(265.05 + DX_SHIFT), Y(140.55)], outline=(0, 120, 0))
    for x1, y1, x2, y2, net, layer in segs:
        col = (200, 30, 30) if net == "+5V" else (180, 80, 0) if net in ("VIN", "VIN_F") else (30, 80, 180) if net.startswith("SMA") else (20, 130, 60) if net == "GND" and layer == "B.Cu" else (0, 0, 0)
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
    pro = pro.replace("PacketHog-V2", "PacketHog-18")
    (DEST_DIR / "PacketHog-18.kicad_pro").write_text(pro)
    sch = (src_dir / "PacketHog-V2.kicad_sch").read_text()
    sch = sch.replace('(project "PacketHog-V2"', '(project "PacketHog-18"')
    note = """\t(text "PacketHog-18 PCB is the routed 18-node board. This sheet is the original 10-node drawing and is not the netlist. Do not update the PCB from this schematic."
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
    (DEST_DIR / "PacketHog-18.kicad_sch").write_text(sch)
    prl = src_dir / "PacketHog-V2.kicad_prl"
    if prl.exists():
        shutil.copy(prl, DEST_DIR / "PacketHog-18.kicad_prl")


def fix_usb_hole_clearance(board):
    """Shorten the USB-C GND lands on the end next to the locating pegs.

    The GCT USB4105 land is 1.15 mm long and clears its own Ø0.65 pegs by
    0.194 mm. The board rule is 0.25 mm. Pull that end back 0.07 mm and
    leave the other end on the datasheet coordinate. A1/B12 share one land
    and A12/B1 share the other.
    """
    for fp in kids(board, "footprint"):
        if prop(fp, "Reference") != "J19":
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
            raise RuntimeError(f"J19 GND pads not all adjusted: {found}")
        return
    raise RuntimeError("J19 missing")


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
    real = [p for p in problems if "J19/" not in p]
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
    png = Path("/tmp/packethog18.png")
    render(board, png)
    print("render", png)
    # reparse to confirm the printer is valid sexpr
    parse(text)
    print("reparse ok")
    return len(real)


if __name__ == "__main__":
    raise SystemExit(main())
