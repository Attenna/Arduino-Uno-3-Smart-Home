# -*- coding: utf-8 -*-
"""RN02G(X) 帧字段分析：对每个帧按 [A ~A B ~B C ~C] 结构拆分，
统计各字段取值分布，定位温度/模式/风速/功能字节。
用法: py -3 tools/ir-rn02g-analyze.py <logfile>
"""
import sys
import re
from collections import defaultdict

TICK_US = 50
GAP_US = 2500
HEADER_MARK_MIN = 3000
BIT_MARK_MAX = 900
ZERO_SPACE_MAX = 1100


def parse_line(line):
    m = re.match(r'RAW\|len=(\d+)\|ovf=(\d+)\|proto=(\d+)\|ticks=(.*)$', line.strip())
    if not m:
        return None
    return [int(x) for x in m.group(4).split(',')]


def split_segments(us):
    pairs = [(us[i], us[i + 1]) for i in range(0, len(us) - 1, 2)]
    segs, cur = [], []
    for idx, (mk, sp) in enumerate(pairs):
        nxt = pairs[idx + 1][0] if idx + 1 < len(pairs) else None
        if sp >= GAP_US and nxt is not None and nxt >= 3000:
            if cur:
                segs.append(cur)
            cur = []
        else:
            cur.extend((mk, sp))
    if cur:
        segs.append(cur)
    return segs


def decode_bits(seg):
    bits = []
    for k in range(2, len(seg) - 1, 2):  # 跳过 header
        mark, space = seg[k], seg[k + 1]
        if not (300 <= mark <= 900):
            break
        bits.append(0 if space <= ZERO_SPACE_MAX else 1)
    return bits


def main():
    path = sys.argv[1]
    frames = []
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            ticks = parse_line(line)
            if not ticks:
                continue
            us = [t * TICK_US for t in ticks[1:]]
            segs = split_segments(us)
            if not segs:
                continue
            bits = decode_bits(segs[0])
            if len(bits) != 48:
                continue
            by = int(''.join(map(str, bits)), 2).to_bytes(6, 'big')
            # 结构候选1: [A ~A B ~B C ~C]
            a, na, b, nb, c, nc = by
            # 温度帧字节5/6 不是补码对（如 7B/0B），b+nb != 255 是已知例外，不崩溃
            if not (a + na == 255):
                continue
            frames.append((a, b, c, nc, by.hex().upper(), b + nb != 255))
    print(f'有效帧数: {len(frames)}')

    print('\n=== A 字节分布 (帧号: A值) ===')
    a_map = defaultdict(list)
    for i, (a, b, c, nc, h, noncomp) in enumerate(frames, 1):
        a_map[a].append(i)
    for a, idxs in sorted(a_map.items()):
        print(f'  A=0x{a:02X}: 帧 {idxs}')

    print('\n=== 每帧完整表: #  A    B    C    ~C字段   hex  (B非补码=温度帧*) ===')
    prev = None
    for i, (a, b, c, nc, h, noncomp) in enumerate(frames, 1):
        mark = '' if h == prev else ' *'
        prev = h
        tag = '  <-- 温度帧' if noncomp else ''
        print(f'  #{i:3} {a:02X}   {b:02X}   {c:02X}    {nc:02X}      {h}{mark}{tag}')

    print('\n=== (A,B,C) 三元组去重 ===')
    seen = {}
    order = []
    for i, (a, b, c, nc, h, noncomp) in enumerate(frames, 1):
        key = (a, b, c)
        if key not in seen:
            seen[key] = (i, nc, noncomp)
            order.append(key)
    for key in order:
        i, nc, noncomp = seen[key]
        tag = ' [温度帧]' if noncomp else ''
        print(f'  首见于#{i}: A={key[0]:02X} B={key[1]:02X} C={key[2]:02X} nc={nc:02X}{tag}')


if __name__ == '__main__':
    main()
