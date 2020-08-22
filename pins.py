"""
Takes a Project Trellis config file and iodb.json and attempts to work out
the pin assignment.
"""

import re
import json
import argparse
from natsort import natsorted


def load_iodb(dbpath, package):
    with open(dbpath) as f:
        iodb = json.load(f)
    packages = iodb["packages"]
    if package not in packages:
        raise RuntimeError(
            f"Package {package} not found, try {list(packages.keys())}")
    return packages[package]


def load_config(path):
    tiles = {}
    loc = None
    name = None
    with open(path) as f:
        for line in f:
            if line.startswith(".tile "):
                match = re.search(r"R(\d+)C(\d+):([A-Z0-9_]*)$", line)
                row = int(match.group(1))
                col = int(match.group(2))
                name = match.group(3)
                loc = (row, col)
                if loc not in tiles:
                    tiles[loc] = {}
                tiles[loc][name] = {}
            elif line.startswith("enum: "):
                key, value = line.split()[1:]
                tiles[loc][name][key] = value.strip()
    return tiles


def get_base_type(tiles, row, col, name, pio):
    if (row, col) in tiles and name in tiles[(row, col)]:
        tile = tiles[(row, col)][name]
        return tile.get(f'{pio}.BASE_TYPE')


def reduce_base_types(types):
    bidi = any(t.startswith("BIDIR_") for t in types if t)
    inp = any(t.startswith("INPUT_") for t in types if t)
    out = any(t.startswith("OUTPUT_") for t in types if t)
    modes = sorted(list(set("_".join(t.split("_")[1:]) for t in types if t)))
    if bidi or (inp and out):
        return "bidi", modes
    elif inp:
        return "input", modes
    elif out:
        return "output", modes
    else:
        return None


def top_pin(tiles, row, col, pio):
    # Top pins are defined in PIOT0, PIOT1, PICT0, PICT1.
    return reduce_base_types([
        get_base_type(tiles, row, col, "PIOT0", f"PIO{pio}"),
        get_base_type(tiles, row, col+1, "PIOT1", f"PIO{pio}"),
        get_base_type(tiles, row+1, col, "PICT0", f"PIO{pio}"),
        get_base_type(tiles, row+1, col+1, "PICT1", f"PIO{pio}"),
    ])


def btm_pin(tiles, row, col, pio):
    # Bottom pins are defined in PICB0 and PICB1.
    # Sometimes EFBx_PICBy or SPICB0.
    return reduce_base_types([
        get_base_type(tiles, row, col, "PICB0", f"PIO{pio}"),
        get_base_type(tiles, row, col, "SPICB0", f"PIO{pio}"),
        get_base_type(tiles, row, col, "EFB0_PICB0", f"PIO{pio}"),
        get_base_type(tiles, row, col, "EFB2_PICB0", f"PIO{pio}"),
        get_base_type(tiles, row, col+1, "PICB1", f"PIO{pio}"),
        get_base_type(tiles, row, col+1, "EFB1_PICB1", f"PIO{pio}"),
        get_base_type(tiles, row, col+1, "EFB3_PICB1", f"PIO{pio}"),
    ])


def left_pin(tiles, row, col, pio):
    # Left pins are defined in PICL0, PICL1, PICL2.
    # Sometimes PICL2 is in MIB_CIB_LR.
    # Sometimes PICLx is shared with DQSy.
    return reduce_base_types([
        get_base_type(tiles, row, col, "PICL0", f"PIO{pio}"),
        get_base_type(tiles, row, col, "PICL0_DQS2", f"PIO{pio}"),
        get_base_type(tiles, row+1, col, "PICL1", f"PIO{pio}"),
        get_base_type(tiles, row+1, col, "PICL1_DQS0", f"PIO{pio}"),
        get_base_type(tiles, row+1, col, "PICL1_DQS3", f"PIO{pio}"),
        get_base_type(tiles, row+2, col, "PICL2", f"PIO{pio}"),
        get_base_type(tiles, row+2, col, "PICL2_DQS1", f"PIO{pio}"),
        get_base_type(tiles, row+2, col, "MIB_CIB_LR", f"PIO{pio}"),
    ])


def right_pin(tiles, row, col, pio):
    # Right pins are defined in PICR0, PICR1, PICR2
    return reduce_base_types([
        get_base_type(tiles, row, col, "PICR0", f"PIO{pio}"),
        get_base_type(tiles, row, col, "PICR0_DQS2", f"PIO{pio}"),
        get_base_type(tiles, row+1, col, "PICR1", f"PIO{pio}"),
        get_base_type(tiles, row+1, col, "PICR1_DQS0", f"PIO{pio}"),
        get_base_type(tiles, row+1, col, "PICR1_DQS3", f"PIO{pio}"),
        get_base_type(tiles, row+2, col, "PICR2", f"PIO{pio}"),
        get_base_type(tiles, row+2, col, "PICR2_DQS1", f"PIO{pio}"),
        get_base_type(tiles, row+2, col, "MIB_CIB_LR", f"PIO{pio}"),
        get_base_type(tiles, row+2, col, "MIB_CIB_LR_A", f"PIO{pio}"),
    ])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("config", help="Path to .config file to read")
    parser.add_argument("--package", default="CABGA256",
                        help="Footprint to use, default CABGA256")
    parser.add_argument(
        "--dbpath",
        default="/usr/share/trellis/database/ECP5/LFE5U-25F/iodb.json",
        help="Path to database file, default is LFE5U-25F")
    args = parser.parse_args()

    iodb = load_iodb(args.dbpath, args.package)
    tiles = load_config(args.config)

    max_row = max(p['row'] for p in iodb.values())
    max_col = max(p['col'] for p in iodb.values())

    pins = {}
    inputs = []
    outputs = []
    bidis = []

    for pin in natsorted(iodb):
        pinrow = iodb[pin]['row']
        pincol = iodb[pin]['col']
        pinpio = iodb[pin]['pio']
        io = None
        if pinrow == 0:
            # Top pin, look at PIOT0, PIOT1, PICT0, PICT1
            io = top_pin(tiles, pinrow, pincol, pinpio)
        elif pinrow == max_row:
            # Bottom pin, look at PICB0, PICB1
            io = btm_pin(tiles, pinrow, pincol, pinpio)
        elif pincol == 0:
            # Left pin, look at PICL0/1/2
            io = left_pin(tiles, pinrow, pincol, pinpio)
        elif pincol == max_col:
            # Right pin, look at PICR0/1/2
            io = right_pin(tiles, pinrow, pincol, pinpio)
        else:
            # Unhandled
            raise RuntimeError(f"Unhandled pin location {pin}")

        if io:
            pins[pin] = io
            print(f"{pin} {io[0]} {','.join(io[1])}")

            if io[0] == "input":
                inputs.append(pin)
            elif io[0] == "output":
                outputs.append(pin)
            elif io[0] == "bidi":
                bidis.append(pin)

        else:
            print(f"{pin} unused")

    print("Inputs:", inputs)
    print("Outputs:", outputs)
    print("Bidis:", bidis)


if __name__ == "__main__":
    main()
