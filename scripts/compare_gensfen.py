#!/usr/bin/env python3
"""Compare two gensfen output files (PackedSfenValue, 40 bytes/record)."""

import argparse
import struct
import sys
import numpy as np
from pathlib import Path


RECORD_SIZE = 40
# PackedSfenValue layout (little-endian):
#   sfen:        32 bytes (PackedSfen)
#   score:       int16    (2 bytes)
#   move:        uint16   (2 bytes)
#   gamePly:     uint16   (2 bytes)
#   game_result: int8     (1 byte)
#   flags:       uint8    (1 byte) — last_position:1, entering_king:1
STRUCT_FMT = "<32s h H H b B"


def read_records(path: Path):
    data = path.read_bytes()
    n = len(data) // RECORD_SIZE
    if len(data) % RECORD_SIZE != 0:
        print(f"WARNING: {path} size {len(data)} not a multiple of {RECORD_SIZE}", file=sys.stderr)
    records = []
    for i in range(n):
        chunk = data[i * RECORD_SIZE : (i + 1) * RECORD_SIZE]
        sfen, score, move, ply, result, flags = struct.unpack(STRUCT_FMT, chunk)
        records.append({
            "score": score,
            "move": move,
            "gamePly": ply,
            "game_result": result,
            "last_position": flags & 1,
            "entering_king": (flags >> 1) & 1,
        })
    return records


def stats(arr, label):
    a = np.array(arr)
    return (
        f"  {label:20s}: n={len(a):>8d}  "
        f"mean={a.mean():>10.2f}  std={a.std():>10.2f}  "
        f"min={a.min():>8d}  q25={np.percentile(a,25):>8.0f}  "
        f"med={np.median(a):>8.0f}  q75={np.percentile(a,75):>8.0f}  "
        f"max={a.max():>8d}"
    )


def histogram(arr, label, bins):
    a = np.array(arr)
    counts, edges = np.histogram(a, bins=bins)
    lines = [f"  {label} histogram:"]
    for i, c in enumerate(counts):
        if c > 0:
            lines.append(f"    [{edges[i]:>8.0f}, {edges[i+1]:>8.0f}): {c:>8d}")
    return "\n".join(lines)


def report(name, records):
    scores = [r["score"] for r in records]
    plies = [r["gamePly"] for r in records]
    results = [r["game_result"] for r in records]
    last_pos = sum(r["last_position"] for r in records)
    entering = sum(r["entering_king"] for r in records)

    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    print(f"  Records: {len(records)}")
    print(f"  Games (last_position=1): {last_pos}")
    print(f"  Entering king: {entering}")
    print(stats(scores, "score"))
    print(stats(plies, "gamePly"))
    print(f"  game_result:  win={results.count(1)}  loss={results.count(-1)}  draw={results.count(0)}")
    print(histogram(scores, "score", bins=[-32001, -30000, -10000, -3000, -1000, 0, 1000, 3000, 10000, 30000, 32001]))
    print(histogram(plies, "gamePly", bins=list(range(0, 401, 40))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file_a", type=Path, help="First gensfen output (e.g. V8.50)")
    parser.add_argument("file_b", type=Path, help="Second gensfen output (e.g. tanuki-)")
    args = parser.parse_args()

    recs_a = read_records(args.file_a)
    recs_b = read_records(args.file_b)

    report(str(args.file_a), recs_a)
    report(str(args.file_b), recs_b)

    print(f"\n{'='*60}")
    print(f"  Comparison")
    print(f"{'='*60}")
    sa = np.array([r["score"] for r in recs_a])
    sb = np.array([r["score"] for r in recs_b])
    pa = np.array([r["gamePly"] for r in recs_a])
    pb = np.array([r["gamePly"] for r in recs_b])

    print(f"  score mean diff:   {abs(sa.mean() - sb.mean()):.2f}")
    print(f"  score std diff:    {abs(sa.std() - sb.std()):.2f}")
    print(f"  gamePly mean diff: {abs(pa.mean() - pb.mean()):.2f}")
    print(f"  gamePly std diff:  {abs(pa.std() - pb.std()):.2f}")

    ra = [r["game_result"] for r in recs_a]
    rb = [r["game_result"] for r in recs_b]
    print(f"  game_result win%:  A={ra.count(1)/len(ra)*100:.1f}%  B={rb.count(1)/len(rb)*100:.1f}%")
    print(f"  game_result loss%: A={ra.count(-1)/len(ra)*100:.1f}%  B={rb.count(-1)/len(rb)*100:.1f}%")
    print(f"  game_result draw%: A={ra.count(0)/len(ra)*100:.1f}%  B={rb.count(0)/len(rb)*100:.1f}%")


if __name__ == "__main__":
    main()
