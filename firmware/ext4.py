#!/usr/bin/env python3
"""Minimaler ext4-Leser/-Schreiber in reinem Python - genau so viel, wie der Patcher fuer das
rootfs des MX5 braucht (ersetzt debugfs, damit die Firmware ohne Linux/WSL gebaut werden kann).

Kann: Dateien lesen, vorhandene regulaere Dateien neu schreiben (gleicher Inode, alte Bloecke
frei), neue regulaere Dateien in vorhandenen linearen Verzeichnissen anlegen, Modus/uid/gid
setzen. Haelt Bitmaps, Gruppendeskriptoren, Superblock und alle metadata_csum-Pruefsummen
(crc32c) aktuell. Kann NICHT: Journal, htree-Verzeichnisse, Extent-Baeume mit Tiefe > 0
schreiben, 64bit-Deskriptoren - in solchen Faellen bricht er mit einer Meldung ab, statt
etwas Falsches zu schreiben. Sicherungskopien von Superblock/Deskriptoren bleiben alt (wie bei
einem Kernel-Mount; e2fsck nimmt immer die primaeren)."""
import struct, time

# ---- crc32c (Castagnoli), roh wie ext4_chksum: ohne Vor-/Nachinvertierung ----
_T = []
for _i in range(256):
    _c = _i
    for _ in range(8):
        _c = (_c >> 1) ^ 0x82F63B78 if _c & 1 else _c >> 1
    _T.append(_c)


def crc32c(crc, data):
    t = _T
    for b in data:
        crc = t[(crc ^ b) & 0xFF] ^ (crc >> 8)
    return crc


INCOMPAT_EXTENTS, INCOMPAT_64BIT, INCOMPAT_CSUM_SEED = 0x40, 0x80, 0x2000
RO_COMPAT_METADATA_CSUM = 0x400
COMPAT_HAS_JOURNAL = 0x4
BG_INODE_UNINIT, BG_BLOCK_UNINIT = 0x1, 0x2
EXTENTS_FL, INDEX_FL, INLINE_DATA_FL = 0x80000, 0x1000, 0x10000000
EXT_MAGIC = 0xF30A
MAX_EXT_LEN = 32768


class Ext4Error(Exception):
    pass


class Ext4:
    def __init__(self, data):
        self.d = bytearray(data)
        sb = self.d[1024:2048]
        u32 = lambda o: struct.unpack_from("<I", sb, o)[0]
        u16 = lambda o: struct.unpack_from("<H", sb, o)[0]
        if u16(0x38) != 0xEF53:
            raise Ext4Error("kein ext4-Dateisystem")
        self.blocks_count = u32(0x04)
        self.first_data_block = u32(0x14)
        self.bs = 1024 << u32(0x18)
        self.bpg = u32(0x20)
        self.ipg = u32(0x28)
        self.first_ino = u32(0x54)
        self.inode_size = u16(0x58)
        self.compat, self.incompat, self.ro_compat = u32(0x5C), u32(0x60), u32(0x64)
        if self.incompat & INCOMPAT_64BIT:
            raise Ext4Error("64bit-Deskriptoren werden nicht unterstuetzt")
        if self.compat & COMPAT_HAS_JOURNAL:
            raise Ext4Error("Dateisystem mit Journal wird nicht unterstuetzt")
        self.desc_size = 32
        self.csum = bool(self.ro_compat & RO_COMPAT_METADATA_CSUM)
        if self.incompat & INCOMPAT_CSUM_SEED:
            self.seed = u32(0x270)
        else:
            self.seed = crc32c(0xFFFFFFFF, bytes(sb[0x68:0x78]))
        self.groups = (self.blocks_count - self.first_data_block + self.bpg - 1) // self.bpg
        self.gdt = (self.first_data_block + 1) * self.bs
        self.now = int(time.time())

    def check(self):
        """Prueft die vorhandenen Pruefsummen (Superblock, alle Deskriptoren) - Selbsttest der
        crc32c-Berechnung, bevor irgendetwas geschrieben wird."""
        if not self.csum:
            return
        sb = self.d[1024:2048]
        if crc32c(0xFFFFFFFF, sb[:0x3FC]) != struct.unpack_from("<I", sb, 0x3FC)[0]:
            raise Ext4Error("Superblock-Pruefsumme stimmt nicht")
        for g in range(self.groups):
            if self._gd_csum(g) != self._gd_get(g, 0x1E, "H"):
                raise Ext4Error("Deskriptor-Pruefsumme von Gruppe %d stimmt nicht" % g)

    # ---- Bloecke, Deskriptoren ----
    def block(self, n, count=1):
        return bytes(self.d[n * self.bs:(n + count) * self.bs])

    def _gd_off(self, g):
        return self.gdt + g * self.desc_size

    def _gd_get(self, g, off, fmt="I"):
        return struct.unpack_from("<" + fmt, self.d, self._gd_off(g) + off)[0]

    def _gd_set(self, g, off, fmt, v):
        struct.pack_into("<" + fmt, self.d, self._gd_off(g) + off, v)

    def _gd_csum(self, g):
        o = self._gd_off(g)
        desc = bytearray(self.d[o:o + self.desc_size])
        desc[0x1E:0x20] = b"\0\0"
        return crc32c(crc32c(self.seed, struct.pack("<I", g)), desc) & 0xFFFF

    def _group_blocks(self, g):
        return min(self.bpg, self.blocks_count - self.first_data_block - g * self.bpg)

    # ---- Inodes ----
    def _inode_off(self, n):
        g, idx = divmod(n - 1, self.ipg)
        return self._gd_get(g, 0x08) * self.bs + idx * self.inode_size

    def inode(self, n):
        o = self._inode_off(n)
        return bytes(self.d[o:o + self.inode_size])

    def _inode_csum(self, n, ino):
        ino = bytearray(ino)
        ino[0x7C:0x7E] = b"\0\0"
        if self.inode_size > 128:
            extra = struct.unpack_from("<H", ino, 0x80)[0]
            if extra >= 4:
                ino[0x82:0x84] = b"\0\0"
        gen = struct.unpack_from("<I", ino, 0x64)[0]
        c = crc32c(crc32c(self.seed, struct.pack("<I", n)), struct.pack("<I", gen))
        return crc32c(c, ino)

    def _put_inode(self, n, ino):
        ino = bytearray(ino)
        if self.csum:
            c = self._inode_csum(n, ino)
            struct.pack_into("<H", ino, 0x7C, c & 0xFFFF)
            if self.inode_size > 128 and struct.unpack_from("<H", ino, 0x80)[0] >= 4:
                struct.pack_into("<H", ino, 0x82, c >> 16)
        o = self._inode_off(n)
        self.d[o:o + self.inode_size] = ino

    @staticmethod
    def _size(ino):
        return struct.unpack_from("<I", ino, 4)[0] | (struct.unpack_from("<I", ino, 0x6C)[0] << 32)

    def _extents(self, iblock):
        magic, entries, _, depth = struct.unpack_from("<HHHH", iblock, 0)
        if magic != EXT_MAGIC:
            raise Ext4Error("kein Extent-Kopf")
        out = []
        for i in range(entries):
            e = iblock[12 + 12 * i:24 + 12 * i]
            if depth == 0:
                lblk, ln, hi, lo = struct.unpack("<IHHI", e)
                out.append((lblk, (hi << 32) | lo, ln if ln <= MAX_EXT_LEN else ln - MAX_EXT_LEN))
            else:
                lblk, lo, hi, _ = struct.unpack("<IIHH", e)
                out.extend(self._extents(self.block((hi << 32) | lo)))
        return out

    def _blockmap(self, iblock):
        """Klassische Blockzeiger (ext2/3-Stil, z. B. von libext2fs ohne Extents geschrieben,
        so legt das Werkzeug der NAM-Mod Dateien an). Liefert (Datenbloecke [(logisch,
        physisch, 1)], Zeigerbloecke [physisch])."""
        ptr = self.bs // 4
        data, meta = [], []

        def walk(blk, level, lblk):
            # level 0 = Datenblock; liefert die Zahl der abgedeckten logischen Bloecke
            span = ptr ** level
            if blk == 0:
                return span
            if level == 0:
                data.append((lblk, blk, 1))
                return 1
            meta.append(blk)
            ptrs = struct.unpack_from("<%dI" % ptr, self.d, blk * self.bs)
            for i, p in enumerate(ptrs):
                walk(p, level - 1, lblk + i * ptr ** (level - 1))
            return span

        slots = struct.unpack_from("<15I", iblock, 0)
        for i in range(12):
            walk(slots[i], 0, i)
        base = 12
        for level, p in ((1, slots[12]), (2, slots[13]), (3, slots[14])):
            walk(p, level, base)
            base += ptr ** level
        return data, meta

    def _data_runs(self, ino):
        """(Datenbloecke als Laeufe, Zeiger-/Indexbloecke) fuer Extent- und Blockzeiger-Inodes."""
        flags = struct.unpack_from("<I", ino, 0x20)[0]
        iblock = ino[0x28:0x28 + 60]
        if flags & EXTENTS_FL:
            if struct.unpack_from("<H", iblock, 6)[0] != 0:
                raise Ext4Error("Extent-Baum mit Tiefe > 0 wird nicht unterstuetzt")
            return self._extents(iblock), []
        data, meta = self._blockmap(iblock)
        return self._merge(data), meta

    def read(self, n):
        ino = self.inode(n)
        mode = struct.unpack_from("<H", ino, 0)[0]
        size = self._size(ino)
        flags = struct.unpack_from("<I", ino, 0x20)[0]
        iblock = ino[0x28:0x28 + 60]
        if (mode & 0xF000) == 0xA000 and size < 60:
            return mode, iblock[:size]
        if flags & INLINE_DATA_FL:
            return mode, iblock[:size]
        if flags & EXTENTS_FL:
            runs = self._extents(iblock)
        else:
            runs = self._merge(self._blockmap(iblock)[0])
        buf = bytearray(size)
        for lblk, pblk, ln in runs:
            start = lblk * self.bs
            chunk = self.block(pblk, ln)[:max(0, size - start)]
            buf[start:start + len(chunk)] = chunk
        return mode, bytes(buf)

    # ---- Verzeichnisse ----
    def _dir_blocks(self, n):
        ino = self.inode(n)
        flags = struct.unpack_from("<I", ino, 0x20)[0]
        if flags & INDEX_FL:
            raise Ext4Error("htree-Verzeichnis (Inode %d) wird nicht unterstuetzt" % n)
        return sorted(self._extents(ino[0x28:0x28 + 60]))

    def listdir(self, n):
        mode, data = self.read(n)
        if (mode & 0xF000) != 0x4000:
            raise Ext4Error("kein Verzeichnis")
        out, p = [], 0
        while p + 8 <= len(data):
            ino, rec_len, name_len, ftype = struct.unpack_from("<IHBB", data, p)
            if rec_len == 0:
                break
            if ino and ftype != 0xDE:
                out.append((data[p + 8:p + 8 + name_len].decode("utf-8", "replace"), ino, ftype))
            p += rec_len
        return out

    def lookup(self, path):
        n = 2
        for part in path.strip("/").split("/"):
            if not part:
                continue
            for name, ino, _ in self.listdir(n):
                if name == part:
                    n = ino
                    break
            else:
                raise FileNotFoundError(path)
        return n

    def exists(self, path):
        try:
            self.lookup(path)
            return True
        except FileNotFoundError:
            return False

    def cat(self, path):
        return self.read(self.lookup(path))[1]

    def _dir_csum(self, n, blk):
        if not self.csum:
            return
        o = blk * self.bs
        tail = o + self.bs - 12
        ino, rec_len, name_len, ft = struct.unpack_from("<IHBB", self.d, tail)
        if (ino, rec_len, name_len, ft) != (0, 12, 0, 0xDE):
            raise Ext4Error("Verzeichnisblock %d ohne Pruefsummen-Ende" % blk)
        gen = struct.unpack_from("<I", self.inode(n), 0x64)[0]
        c = crc32c(crc32c(self.seed, struct.pack("<I", n)), struct.pack("<I", gen))
        struct.pack_into("<I", self.d, tail + 8, crc32c(c, self.d[o:tail]))

    def _add_dirent(self, dir_ino, name, ino, ftype):
        raw = name.encode("utf-8")
        need = (8 + len(raw) + 3) & ~3
        end_limit = self.bs - (12 if self.csum else 0)
        for lblk, pblk, ln in self._dir_blocks(dir_ino):
            for b in range(pblk, pblk + ln):
                o, p = b * self.bs, 0
                while p < end_limit:
                    e_ino, rec_len, name_len, e_ft = struct.unpack_from("<IHBB", self.d, o + p)
                    if rec_len < 8:
                        raise Ext4Error("Verzeichnisblock %d ist beschaedigt" % b)
                    used = (8 + name_len + 3) & ~3 if e_ino else 0
                    if rec_len - used >= need:
                        if e_ino:     # vorhandenen Eintrag kuerzen, neuer kommt dahinter
                            struct.pack_into("<IHBB", self.d, o + p, e_ino, used, name_len, e_ft)
                            q, new_len = p + used, rec_len - used
                        else:
                            q, new_len = p, rec_len
                        struct.pack_into("<IHBB", self.d, o + q, ino, new_len, len(raw), ftype)
                        self.d[o + q + 8:o + q + 8 + len(raw)] = raw
                        self.d[o + q + 8 + len(raw):o + q + new_len] = bytes(new_len - 8 - len(raw))
                        self._dir_csum(dir_ino, b)
                        return
                    p += rec_len
        # kein Platz: Verzeichnis um einen Block verlaengern
        di = bytearray(self.inode(dir_ino))
        size = self._size(di)
        blk = self._alloc_blocks(1, near=self._dir_blocks(dir_ino)[-1][1])[0][0]
        o = blk * self.bs
        self.d[o:o + self.bs] = bytes(self.bs)
        struct.pack_into("<IHBB", self.d, o, ino, end_limit, len(raw), ftype)
        self.d[o + 8:o + 8 + len(raw)] = raw
        if self.csum:
            struct.pack_into("<IHBB", self.d, o + self.bs - 12, 0, 12, 0, 0xDE)
        exts = [(l, p, n) for l, p, n in self._dir_blocks(dir_ino)]
        exts.append((size // self.bs, blk, 1))
        self._set_extents(di, self._merge(exts))
        struct.pack_into("<I", di, 4, size + self.bs)
        blocks = struct.unpack_from("<I", di, 0x1C)[0] + self.bs // 512
        struct.pack_into("<I", di, 0x1C, blocks)
        self._put_inode(dir_ino, di)
        self._dir_csum(dir_ino, blk)

    def _touch_dir(self, dir_ino):
        di = bytearray(self.inode(dir_ino))
        struct.pack_into("<II", di, 0x0C, self.now, self.now)   # ctime, mtime
        self._put_inode(dir_ino, di)

    # ---- Bitmaps ----
    def _bitmap(self, g, inode=False):
        return self._gd_get(g, 0x04 if inode else 0x00) * self.bs

    def _bitmap_csum(self, g, inode=False):
        if not self.csum:
            return
        o = self._bitmap(g, inode)
        n = self.ipg // 8 if inode else self.bpg // 8
        self._gd_set(g, 0x1A if inode else 0x18, "H", crc32c(self.seed, self.d[o:o + n]) & 0xFFFF)

    def _gd_finish(self, g):
        if self.csum:
            self._gd_set(g, 0x1E, "H", self._gd_csum(g))

    def _sb_add(self, off, delta):
        v = struct.unpack_from("<I", self.d, 1024 + off)[0] + delta
        struct.pack_into("<I", self.d, 1024 + off, v)

    def _alloc_blocks(self, count, near=0):
        """Freie Bloecke belegen; liefert [(erster Block, Anzahl)] - moeglichst ein Stueck,
        hoechstens 4 (so viele Extents passen in den Inode)."""
        runs = []
        for g in range(self.groups):
            if self._gd_get(g, 0x12, "H") & BG_BLOCK_UNINIT:
                continue
            bm = self._bitmap(g)
            base = self.first_data_block + g * self.bpg
            run = None
            for i in range(self._group_blocks(g)):
                free = not (self.d[bm + (i >> 3)] >> (i & 7)) & 1
                if free:
                    if run is None:
                        run = [base + i, 0]
                    run[1] += 1
                elif run:
                    runs.append(tuple(run))
                    run = None
            if run:
                runs.append(tuple(run))
        # zuerst ein Stueck, das reicht (das naechste zu 'near'), sonst die groessten
        fit = [r for r in runs if r[1] >= count]
        if fit:
            chosen = [(min(fit, key=lambda r: abs(r[0] - near))[0], count)]
        else:
            chosen, left = [], count
            for start, ln in sorted(runs, key=lambda r: -r[1]):
                take = min(ln, left)
                chosen.append((start, take))
                left -= take
                if not left:
                    break
            if left:
                raise Ext4Error("nicht genug freie Bloecke")
        out = []
        for start, ln in chosen:
            while ln:                       # Extents sind hoechstens 32768 Bloecke lang
                part = min(ln, MAX_EXT_LEN)
                out.append((start, part))
                start, ln = start + part, ln - part
        if len(out) > 4:
            raise Ext4Error("Datei wuerde mehr als 4 Extents brauchen")
        for start, ln in out:
            self._mark_blocks(start, ln, True)
        return out

    def _mark_blocks(self, start, count, used):
        groups = set()
        for b in range(start, start + count):
            g, i = divmod(b - self.first_data_block, self.bpg)
            bm = self._bitmap(g)
            cur = (self.d[bm + (i >> 3)] >> (i & 7)) & 1
            if cur == used:
                raise Ext4Error("Block %d ist schon %s" % (b, "belegt" if used else "frei"))
            self.d[bm + (i >> 3)] ^= 1 << (i & 7)
            free = self._gd_get(g, 0x0C, "H")
            self._gd_set(g, 0x0C, "H", free - 1 if used else free + 1)
            groups.add(g)
        self._sb_add(0x0C, -count if used else count)
        for g in groups:
            self._bitmap_csum(g)
            self._gd_finish(g)

    def _alloc_inode(self, near_group):
        order = [near_group] + [g for g in range(self.groups) if g != near_group]
        for g in order:
            if self._gd_get(g, 0x12, "H") & BG_INODE_UNINIT:
                continue
            bm = self._bitmap(g, inode=True)
            for i in range(self.ipg):
                n = g * self.ipg + i + 1
                if n < self.first_ino:
                    continue
                if not (self.d[bm + (i >> 3)] >> (i & 7)) & 1:
                    self.d[bm + (i >> 3)] |= 1 << (i & 7)
                    self._gd_set(g, 0x0E, "H", self._gd_get(g, 0x0E, "H") - 1)
                    unused = self._gd_get(g, 0x1C, "H")
                    if i >= self.ipg - unused:
                        self._gd_set(g, 0x1C, "H", self.ipg - i - 1)
                    self._sb_add(0x10, -1)
                    self._bitmap_csum(g, inode=True)
                    self._gd_finish(g)
                    o = self._inode_off(n)
                    self.d[o:o + self.inode_size] = bytes(self.inode_size)
                    return n
        raise Ext4Error("kein freier Inode")

    # ---- Extents ----
    @staticmethod
    def _merge(exts):
        out = []
        for l, p, n in sorted(exts):
            if out and out[-1][0] + out[-1][2] == l and out[-1][1] + out[-1][2] == p \
                    and out[-1][2] + n <= MAX_EXT_LEN:
                out[-1] = (out[-1][0], out[-1][1], out[-1][2] + n)
            else:
                out.append((l, p, n))
        return out

    def _set_extents(self, ino, exts):
        if len(exts) > 4:
            raise Ext4Error("mehr als 4 Extents")
        ib = bytearray(60)
        struct.pack_into("<HHHHI", ib, 0, EXT_MAGIC, len(exts), 4, 0, 0)
        for i, (l, p, n) in enumerate(exts):
            struct.pack_into("<IHHI", ib, 12 + 12 * i, l, n, p >> 32, p & 0xFFFFFFFF)
        ino[0x28:0x28 + 60] = ib

    # ---- Schreiben ----
    def write_file(self, path, data, mode, uid=0, gid=0):
        """Regulaere Datei anlegen oder ersetzen (Inhalt, Modus z. B. 0o100755, Besitzer)."""
        parent, _, name = path.rstrip("/").rpartition("/")
        dir_ino = self.lookup(parent or "/")
        nblk = (len(data) + self.bs - 1) // self.bs
        try:
            n = self.lookup(path)
            new = False
        except FileNotFoundError:
            n, new = None, True
        if new:
            n = self._alloc_inode((dir_ino - 1) // self.ipg)
            ino = bytearray(self.inode_size)
            struct.pack_into("<H", ino, 0x1A, 1)                  # links
            struct.pack_into("<I", ino, 0x08, self.now)           # atime
            near = self._dir_blocks(dir_ino)[0][1]
        else:
            ino = bytearray(self.inode(n))
            m = struct.unpack_from("<H", ino, 0)[0]
            flags = struct.unpack_from("<I", ino, 0x20)[0]
            if (m & 0xF000) != 0x8000 or flags & INLINE_DATA_FL:
                raise Ext4Error("%s ist keine einfache Datei" % path)
            old, meta = self._data_runs(ino)       # die neue Datei bekommt immer Extents
            for _, p, ln in old:
                self._mark_blocks(p, ln, False)
            for p in meta:
                self._mark_blocks(p, 1, False)
            old_blocks = sum(ln for _, _, ln in old) + len(meta)
            # i_blocks enthaelt auch einen xattr-Block; nur den Datenanteil abziehen
            blocks = struct.unpack_from("<I", ino, 0x1C)[0] - old_blocks * (self.bs // 512)
            struct.pack_into("<I", ino, 0x1C, blocks)
            near = old[0][1] if old else 0
        runs = self._alloc_blocks(nblk, near=near) if nblk else []
        exts, l = [], 0
        for p, ln in runs:
            chunk = data[l * self.bs:(l + ln) * self.bs]
            self.d[p * self.bs:p * self.bs + len(chunk)] = chunk
            pad = ln * self.bs - len(chunk)
            if pad:
                self.d[p * self.bs + len(chunk):(p + ln) * self.bs] = bytes(pad)
            exts.append((l, p, ln))
            l += ln
        self._set_extents(ino, exts)
        struct.pack_into("<H", ino, 0x00, mode)
        struct.pack_into("<H", ino, 0x02, uid & 0xFFFF)
        struct.pack_into("<H", ino, 0x18, gid & 0xFFFF)
        struct.pack_into("<HH", ino, 0x78, uid >> 16, gid >> 16)
        struct.pack_into("<I", ino, 0x04, len(data) & 0xFFFFFFFF)
        struct.pack_into("<I", ino, 0x6C, len(data) >> 32)
        struct.pack_into("<II", ino, 0x0C, self.now, self.now)    # ctime, mtime
        flags = struct.unpack_from("<I", ino, 0x20)[0] | EXTENTS_FL
        struct.pack_into("<I", ino, 0x20, flags)
        blocks = struct.unpack_from("<I", ino, 0x1C)[0] + nblk * (self.bs // 512)
        struct.pack_into("<I", ino, 0x1C, blocks)
        self._put_inode(n, ino)
        if new:
            self._add_dirent(dir_ino, name, n, 1)
        self._touch_dir(dir_ino)

    def finish(self):
        """Superblock-Zeit und -Pruefsumme setzen; liefert das Image als bytes."""
        struct.pack_into("<I", self.d, 1024 + 0x30, self.now)      # s_wtime
        if self.csum:
            struct.pack_into("<I", self.d, 1024 + 0x3FC, crc32c(0xFFFFFFFF, self.d[1024:1024 + 0x3FC]))
        return bytes(self.d)
