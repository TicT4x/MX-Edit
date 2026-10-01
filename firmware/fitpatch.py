#!/usr/bin/env python3
"""Replace one image's data blob in a HeadRush FIT Update.img, byte-for-byte
preserving everything else (header layout, property order, strings block).
Only the target 'data' property, its length field, its sha1 'value' and the
FDT header size/offset fields change."""
import hashlib, struct, sys

FDT_BEGIN_NODE, FDT_END_NODE, FDT_PROP, FDT_NOP, FDT_END = 1, 2, 3, 4, 9

def align4(n): return (n + 3) & ~3

def parse(raw):
    hdr = struct.unpack('>10I', raw[:40])
    magic, totalsize, off_struct, off_strings, off_rsv, ver, lcv, bootcpu, size_strings, size_struct = hdr
    assert magic == 0xd00dfeed
    strings = raw[off_strings:off_strings + size_strings]
    def sname(o): return strings[o:strings.index(b'\0', o)].decode()
    props = []  # (path, name, token_offset, data_offset, length)
    path = []
    p = off_struct
    end = off_struct + size_struct
    while p < end:
        tok, = struct.unpack('>I', raw[p:p+4]); tokoff = p; p += 4
        if tok == FDT_BEGIN_NODE:
            e = raw.index(b'\0', p); path.append(raw[p:e].decode()); p = align4(e + 1)
        elif tok == FDT_END_NODE:
            path.pop()
        elif tok == FDT_PROP:
            ln, no = struct.unpack('>II', raw[p:p+8]); p += 8
            props.append(('/'.join(path), sname(no), tokoff, p, ln)); p = align4(p + ln)
        elif tok == FDT_NOP:
            pass
        elif tok == FDT_END:
            break
        else:
            raise ValueError('bad token %d at %d' % (tok, tokoff))
    return hdr, props

def get(props, path, name):
    m = [x for x in props if x[0] == path and x[1] == name]
    assert len(m) == 1, (path, name, m)
    return m[0]

def replace_image(raw, image, newdata):
    hdr, props = parse(raw)
    magic, totalsize, off_struct, off_strings, off_rsv, ver, lcv, bootcpu, size_strings, size_struct = hdr
    assert off_struct < off_strings, 'unexpected layout'
    base = '/images/' + image
    _, _, _, doff, dlen = get(props, base, 'data')
    _, _, _, hoff, hlen = get(props, base + '/hash', 'value')
    _, _, _, aoff, alen = get(props, base + '/hash', 'algo')
    assert raw[aoff:aoff+alen].rstrip(b'\0') == b'sha1' and hlen == 20
    assert hoff > doff  # hash node follows data inside the image node
    old_padded = align4(dlen)
    new_padded = align4(len(newdata))
    delta = new_padded - old_padded
    digest = hashlib.sha1(newdata).digest()
    out = bytearray()
    out += raw[:doff - 8]
    out += struct.pack('>I', len(newdata))
    out += raw[doff - 4:doff]  # nameoff unchanged
    out += newdata + b'\0' * (new_padded - len(newdata))
    tail = bytearray(raw[doff + old_padded:])
    rel = hoff - (doff + old_padded)
    tail[rel:rel + 20] = digest
    out += tail
    out = bytearray(out)
    struct.pack_into('>I', out, 4, totalsize + delta)
    struct.pack_into('>I', out, 12, off_strings + delta)
    struct.pack_into('>I', out, 36, size_struct + delta)
    if off_rsv > doff:
        struct.pack_into('>I', out, 16, off_rsv + delta)
    return bytes(out)

def extract(raw, image):
    _, props = parse(raw)
    _, _, _, doff, dlen = get(props, '/images/' + image, 'data')
    return raw[doff:doff + dlen]

def verify(raw):
    _, props = parse(raw)
    ok = True
    for (path, name, _, doff, dlen) in props:
        if name == 'data' and path.startswith('/images/'):
            _, _, _, hoff, _ = get(props, path + '/hash', 'value')
            good = hashlib.sha1(raw[doff:doff+dlen]).digest() == raw[hoff:hoff+20]
            print('  %-24s %10d bytes  sha1 %s' % (path, dlen, 'OK' if good else 'FALSCH'))
            ok &= good
    assert struct.unpack('>I', raw[4:8])[0] == len(raw), 'totalsize mismatch'
    return ok

if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'selftest':
        raw = open(sys.argv[2], 'rb').read()
        same = replace_image(raw, 'rootfs', extract(raw, 'rootfs'))
        print('roundtrip identisch:', same == raw)
        test = replace_image(raw, 'rootfs', extract(raw, 'rootfs') + b'xyz')
        print('geaenderte Laenge verifiziert:', verify(test))
    elif cmd == 'extract':
        open(sys.argv[4], 'wb').write(extract(open(sys.argv[2], 'rb').read(), sys.argv[3]))
    elif cmd == 'replace':
        raw = open(sys.argv[2], 'rb').read()
        new = replace_image(raw, sys.argv[3], open(sys.argv[4], 'rb').read())
        assert verify(new)
        open(sys.argv[5], 'wb').write(new)
    elif cmd == 'verify':
        print('OK' if verify(open(sys.argv[2], 'rb').read()) else 'FEHLER')
