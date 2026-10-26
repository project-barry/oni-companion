"""Decode the PNGs with the stdlib only and compare every pixel with the raw data the encoder was given."""
import struct, sys, zlib, os

def decode(path):
    d = open(path, 'rb').read()
    assert d[:8] == b'\x89PNG\r\n\x1a\n', 'signature'
    pos, idat, ihdr = 8, b'', None
    seen = []
    while pos < len(d):
        n, = struct.unpack('>I', d[pos:pos + 4]); t = d[pos + 4:pos + 8]; body = d[pos + 8:pos + 8 + n]
        crc, = struct.unpack('>I', d[pos + 8 + n:pos + 12 + n])
        assert zlib.crc32(t + body) & 0xffffffff == crc, 'crc ' + t.decode()
        seen.append(t)
        if t == b'IHDR': ihdr = struct.unpack('>IIBBBBB', body)
        if t == b'IDAT': idat += body
        pos += 12 + n
    assert seen[0] == b'IHDR' and seen[-1] == b'IEND'
    w, h, bd, ct, _, _, il = ihdr
    assert (bd, ct, il) == (8, 6, 0)
    raw = zlib.decompress(idat)   # also checks the Adler-32
    stride = w * 4
    assert len(raw) == (stride + 1) * h
    out = bytearray()
    prev = bytearray(stride)
    for y in range(h):
        f = raw[y * (stride + 1)]; row = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        assert f == 1
        for i in range(4, stride): row[i] = (row[i] + row[i - 4]) & 255
        out += row
    return w, h, bytes(out)

dir = sys.argv[1]
bad = 0
for name in ('t1', 't2', 't3', 't4'):
    w, h, px = decode(os.path.join(dir, name + '.png'))
    want = open(os.path.join(dir, name + '.rgba'), 'rb').read()
    ok = px == want
    print(name, w, 'x', h, 'size', os.path.getsize(os.path.join(dir, name + '.png')), 'pixels equal' if ok else 'MISMATCH')
    bad += not ok
sys.exit(1 if bad else 0)
