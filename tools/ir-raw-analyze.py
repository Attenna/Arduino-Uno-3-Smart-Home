# -*- coding: utf-8 -*-
"""解析 IR RAW 抓取日志（tick=50µs），还原美的 RN02G(X) 帧结构。

输入：抓取固件输出 RAW|len=..|ticks=v1,v2,... （首项为占位 0，跳过）
输出：每帧拆分为段(segment)，每段打印 header / 位序列 / 字节十六进制。
用法: py -3 tools/ir-raw-analyze.py <logfile> [--max N]
"""
import sys
import re

TICK_US = 50
HEADER_MARK_MIN = 3500   # µs
HEADER_MARK_MAX = 6000
HEADER_SPACE_MIN = 3500
HEADER_SPACE_MAX = 6000
GAP_US = 2500           # 段间空隙阈值（大于此视为段分隔）
BIT_MARK_MIN = 300
BIT_MARK_MAX = 900
ZERO_SPACE_MAX = 1100   # 短间隔 = 0
ONE_SPACE_MIN = 1200    # 长间隔 = 1


def parse_line(line):
    m = re.match(r'RAW\|len=(\d+)\|ovf=(\d+)\|proto=(\d+)\|ticks=(.*)$', line.strip())
    if not m:
        return None
    ticks = [int(x) for x in m.group(4).split(',')]
    return int(m.group(1)), m.group(2) == '1', ticks


def split_segments(us_list):
    """按 mark/space 对切分，返回 segment 列表（每段为 [mark, space, ...] µs）。
    段间空隙判据：space ≥ GAP_US 且 下一对的 mark ≥ 3000µs（新头部）。"""
    # 组成 (mark, space) 对；末尾可能残留单个 mark（stop 位）
    pairs = [(us_list[i], us_list[i + 1]) for i in range(0, len(us_list) - 1, 2)]
    tail = [us_list[-1]] if len(us_list) % 2 else []
    segs, cur = [], []
    for idx, (mk, sp) in enumerate(pairs):
        nxt = pairs[idx + 1][0] if idx + 1 < len(pairs) else None
        if sp >= GAP_US and nxt is not None and nxt >= HEADER_MARK_MIN - 1000:
            if cur:
                segs.append(cur)
            cur = []  # 下一对 (nxt, header_space) 将作为新段的头部
        else:
            cur.extend((mk, sp))
    if tail:
        cur.extend(tail)
    if cur:
        segs.append(cur)
    return segs


def decode_segment(seg):
    """segment: [mark,space,mark,space,...]。去掉 header(mark,space)，剩余 bit 对。"""
    if len(seg) < 4:
        return None, None
    hm, hs = seg[0], seg[1]
    bits = []
    rest = seg[2:]
    for k in range(0, len(rest) - 1, 2):
        mark, space = rest[k], rest[k + 1]
        if BIT_MARK_MIN <= mark <= BIT_MARK_MAX and space <= ZERO_SPACE_MAX:
            bits.append(0)
        elif BIT_MARK_MIN <= mark <= BIT_MARK_MAX and space >= ONE_SPACE_MIN:
            bits.append(1)
        else:
            break
    return (hm, hs), bits


def main():
    path = sys.argv[1]
    compact = any(a == '--compact' for a in sys.argv)
    maxn = None
    for a in sys.argv[2:]:
        if a.startswith('--max'):
            maxn = int(a.split('=')[1])
    frames = 0
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            r = parse_line(line)
            if r is None:
                continue
            frames += 1
            if maxn and frames > maxn:
                break
            rawlen, ovf, ticks = r
            us = [t * TICK_US for t in ticks[1:]]  # 跳过占位首项
            segs = split_segments(us)
            if compact:
                hexes = []
                for si, seg in enumerate(segs):
                    hdr, bits = decode_segment(seg)
                    if bits and len(bits) >= 48:
                        payload = bits[:48]  # 只取前 48bit（帧负载），忽略尾部噪声
                        b = int(''.join(map(str, payload)), 2).to_bytes(6, 'big')
                        hexes.append(b.hex().upper())
                print(f'FRAME#{frames}: {" ".join(hexes)}')
                continue
            print(f'FRAME#{frames} len={rawlen} ovf={ovf} segs={len(segs)}')
            for si, seg in enumerate(segs):
                hdr, bits = decode_segment(seg)
                if hdr is None:
                    print(f'  seg{si}: <{len(seg)} 项，不足>')
                    continue
                print(f'  seg{si}: hdr={hdr[0]}us/{hdr[1]}us nbits={len(bits)}')
                if bits:
                    # 分段打印（16 位一组）
                    for g in range(0, len(bits), 16):
                        chunk = bits[g:g + 16]
                        hexes = ' '.join('%02X' % int(''.join(map(str, chunk[b:b + 8])), 2)
                                         for b in range(0, len(chunk) - 7, 8))
                        print(f'    bits[{g}:{g + len(chunk)}] = {"".join(map(str, chunk))}  hex: {hexes}')
            print()


if __name__ == '__main__':
    main()
