"""Port bike engine sounds (Wwise) from another game's extracted files into the open project.

A bike sound is a chain:  BikeAudio_* data asset -> two AkAudioEvent assets (engine / exhaust)
                          -> an AkAudioBank asset -> <bank>.bnk in WwiseAudio/SoundBanks/Windows.
Porting copies the whole chain, rebuilds the data assets in the *target* game's own layout (taking one of
its own BikeAudio assets as the template), checks that the bank can load there (Wwise version, plugins,
Init.bnk objects) and adds any bus/effect objects the target's Init.bnk lacks.
Nothing is written unless dry_run is False; writes go through the project's staging layer."""
import os
import re
import struct

import mgp_core as C
import uprops as U

AUDIO = "Content/assets/Audio"
BANK_DIR = AUDIO + "/WwiseAudio/SoundBanks/Windows"
BIND_DIR = AUDIO + "/Bindings/Bikes"
GAME_AUDIO = "/Game/assets/Audio/"
OWN = ("unsaved", "mod folder")          # origins we may overwrite (an earlier port of ours), never the game's paks


# ------------------------------------------------------------------ Wwise bank helpers
def wwise_id(name):
    """Wwise short id: FNV-1 (32 bit) of the lower-cased name."""
    h = 2166136261
    for ch in name.lower().encode("utf-8"):
        h = (h * 16777619) & 0xFFFFFFFF
        h ^= ch
    return h


_GAIN = 0.0


def sections(data):
    out, o = [], 0
    while o + 8 <= len(data):
        t = data[o:o + 4].decode("latin1")
        s = struct.unpack_from("<I", data, o + 4)[0]
        out.append([t, data[o + 8:o + 8 + s]])
        o += 8 + s
    return out


def join_sections(secs):
    return b"".join(t.encode("latin1") + struct.pack("<I", len(b)) + b for t, b in secs)


def bank_version(data):
    if data[:4] != b"BKHD":
        raise C.MgpError("not a Wwise bank (no BKHD header)")
    return struct.unpack_from("<I", data, 8)[0]


def hirc_objects(data):
    """[(type, id, body)] where body includes the leading 4-byte id."""
    for t, b in sections(data):
        if t == "HIRC":
            n = struct.unpack_from("<I", b, 0)[0]
            q, out = 4, []
            for _ in range(n):
                ty = b[q]
                ln = struct.unpack_from("<I", b, q + 1)[0]
                out.append((ty, struct.unpack_from("<I", b, q + 5)[0], b[q + 5:q + 5 + ln]))
                q += 5 + ln
            return out
    return []


def _node_bundle(ty, b):
    """(parentID, offset of the AkPropBundle count byte) for a Sound/container body."""
    q = 4
    if ty == 2:
        plugin = struct.unpack_from("<I", b, 4)[0]
        q = 18
        if plugin & 0xF == 2:
            q += 4 + struct.unpack_from("<I", b, q)[0]
    n = b[q + 1]
    e = q + 2 + (1 + 7 * n if n else 0)
    return struct.unpack_from("<I", b, e + 7)[0], e + 7 + 4 + 1


def apply_gain(bnk, db):
    """Add `db` to the Volume of every top-level Sound/container of the bank. Returns (bytes, n_changed)."""
    if not db:
        return bnk, 0
    secs = sections(bnk)
    changed = 0
    for sec in secs:
        if sec[0] != "HIRC":
            continue
        b = sec[1]
        n = struct.unpack_from("<I", b, 0)[0]
        items, q = [], 4
        for _ in range(n):
            ty = b[q]; ln = struct.unpack_from("<I", b, q + 1)[0]
            items.append([ty, bytearray(b[q + 5:q + 5 + ln])]); q += 5 + ln
        ids = {struct.unpack_from("<I", it[1], 0)[0] for it in items}
        for it in items:
            ty, body = it
            if ty not in (2, 5, 6, 7, 9):
                continue
            try:
                parent, pb = _node_bundle(ty, bytes(body))
            except Exception:
                continue
            if parent in ids or parent == 0 and ty != 2 and False:
                continue
            c = body[pb]
            pids = list(body[pb + 1:pb + 1 + c])
            if 0 in pids:
                o = pb + 1 + c + 4 * pids.index(0)
                struct.pack_into("<f", body, o, struct.unpack_from("<f", body, o)[0] + db)
            else:
                body[pb] = c + 1
                body[pb + 1:pb + 1] = b"\x00"
                o = pb + 1 + (c + 1)
                body[o:o] = struct.pack("<f", db)
            changed += 1
        out = struct.pack("<I", n)
        for ty, body in items:
            out += bytes([ty]) + struct.pack("<I", len(body)) + bytes(body)
        sec[1] = out
    return join_sections(secs), changed


def init_plugins(data):
    """{plugin id: name} from the INIT section (u32 id + zero-terminated name, repeated)."""
    for t, b in sections(data):
        if t == "INIT":
            n = struct.unpack_from("<I", b, 0)[0]
            q, out = 4, {}
            for _ in range(n):
                pid = struct.unpack_from("<I", b, q)[0]
                e = b.index(b"\0", q + 4)
                out[pid] = b[q + 4:e].decode("latin1")
                q = e + 1
            return out
    return {}


def bank_event_ids(objs):
    return {oid for t, oid, _ in objs if t == 4}


def bank_plugin_ids(objs):
    ids = set()
    for t, oid, b in objs:
        if t == 2 and len(b) >= 8:
            pid = struct.unpack_from("<I", b, 4)[0]
            if pid & 0xF in (2, 3):                    # 1 = codec (Vorbis...), 2 = source plugin, 3 = effect
                ids.add(pid)
        elif t in (16, 17) and len(b) >= 8:
            ids.add(struct.unpack_from("<I", b, 4)[0])
    return ids


def streamed_media(objs):
    out = set()
    for t, oid, b in objs:
        if t == 2 and len(b) >= 13 and b[8] != 0:      # stream type: 0 = in the bank, 1 = streamed, 2 = prefetched
            out.add(struct.unpack_from("<I", b, 9)[0])
    return out


def rename_bank(bnk, new_name):
    """Same bank under another name: the bank id in the header is the hash of the (lowercase) name."""
    secs = sections(bnk)
    if secs[0][0] != "BKHD":
        raise C.MgpError("not a Wwise bank")
    secs[0][1] = secs[0][1][:4] + struct.pack("<I", wwise_id(new_name)) + secs[0][1][8:]
    return join_sections(secs)


def init_needs(bank_objs, src_init, tgt_ids):
    """Objects of the source Init.bnk that `bank_objs` refer to (directly or through each other) but the target
    Init.bnk lacks. Returns objects in dependency order (dependencies first)."""
    src = {oid: (t, b) for t, oid, b in src_init}
    local = {oid for _, oid, _ in bank_objs}
    found, queue = [], []

    def scan(body):
        for i in range(4, len(body) - 3):
            v = struct.unpack_from("<I", body, i)[0]
            if v in src and v not in tgt_ids and v not in local and v not in found:
                found.append(v)
                queue.append(v)
    for _, _, b in bank_objs:
        scan(b)
    while queue:
        scan(src[queue.pop(0)][1])
    return [(src[v][0], v, src[v][1]) for v in reversed(found)]


def patch_init(init_data, extra):
    secs = sections(init_data)
    for s in secs:
        if s[0] == "HIRC":
            n = struct.unpack_from("<I", s[1], 0)[0]
            body = struct.pack("<I", n + len(extra)) + s[1][4:]
            for ty, oid, b in extra:
                body += bytes([ty]) + struct.pack("<I", len(b)) + b
            s[1] = body
    return join_sections(secs)


# ------------------------------------------------------------------ asset helpers
def pkg_rel(pkg):
    return C.game_to_rel(pkg)


def read_pair(src_read, stem):
    return src_read(stem + ".uasset"), src_read(stem + ".uexp")


def tree_of(ua, ux):
    return U.tree(U.Asset(ua, ux))


def refs_of(tree, cls=None):
    """{property name: package} for top-level object properties."""
    out = {}
    for p in tree["props"]:
        if p["type"] == "ObjectProperty" and p.get("ref") and (cls is None or p.get("ref_cls") == cls):
            out[p["name"]] = p["ref"]
    return out


def prop_obj(tree, name):
    """Object name of a top-level ObjectProperty ('/Game/x/Name.Name' -> 'Name')."""
    for p in tree["props"]:
        if p["name"] == name and p.get("value"):
            return obj_name(p["value"])
    return ""


def obj_name(tree_ref_value):
    return tree_ref_value.partition(".")[2] or tree_ref_value.rsplit("/", 1)[-1]


def signature(tree):
    def s(p):
        return (p["name"], p["type"], p.get("struct"), tuple(s(c) for c in p["children"]) if p.get("children") is not None else None)
    return (tree["cls"], tuple(s(p) for p in tree["props"] if p["name"] != "NativeClass"))


def count_nodes(tree):
    def c(p):
        return 1 + sum(c(x) for x in (p.get("children") or []))
    return sum(c(p) for p in tree["props"])


def rename_asset(ua_bytes, mapping):
    ua = C.UAsset(ua_bytes)
    for old, new in mapping.items():
        if old == new:
            continue
        texts = ua.texts()
        if texts.count(old) == 0:       # the game's name tables spell some folders differently (audio/Audio)
            hits = [t for t in texts if t.lower() == old.lower()]
            if len(hits) == 1:
                old = hits[0]
        if texts.count(old) != 1:
            raise C.MgpError("template layout is not what I expected: %r appears %d times" % (old, texts.count(old)))
        if new in texts:
            raise C.MgpError("name %r is already in the template" % new)
        ua.replace_name(texts.index(old), new)
    return ua.to_bytes()


class Source:
    """The other game's extracted files (a folder that contains Bindings/, Events/, Banks/, WwiseAudio/...)."""

    def __init__(self, path):
        self.root = find_audio_root(path)
        self.files = {}
        for d, _, fs in os.walk(self.root):
            for f in fs:
                p = os.path.join(d, f)
                self.files[os.path.relpath(p, self.root).replace(os.sep, "/").lower()] = p

    def has(self, rel):
        return rel.lower() in self.files

    def read(self, rel):
        p = self.files.get(rel.lower())
        if not p:
            raise C.MgpError("not found in the source folder: " + rel)
        with open(p, "rb") as f:
            return f.read()

    def pkg_stem(self, pkg):
        if not pkg.startswith(GAME_AUDIO):
            raise C.MgpError("outside the Audio folder: " + pkg)
        return pkg[len(GAME_AUDIO):]

    def read_pkg(self, pkg):
        stem = self.pkg_stem(pkg)
        return self.read(stem + ".uasset"), self.read(stem + ".uexp")

    def has_pkg(self, pkg):
        return pkg.startswith(GAME_AUDIO) and self.has(self.pkg_stem(pkg) + ".uasset")


def find_audio_root(path):
    path = (path or "").strip().strip('"')
    if not path or not os.path.isdir(path):
        raise C.MgpError("source folder does not exist: %r" % path)
    for depth_dir in _walk_dirs(path, 6):
        kids = {k.lower() for k in os.listdir(depth_dir)}
        if "bindings" in kids and ("events" in kids or "wwiseaudio" in kids):
            return depth_dir
    for depth_dir in _walk_dirs(path, 6):
        if os.path.basename(depth_dir).lower() == "audio":
            return depth_dir
    raise C.MgpError("no Audio folder found under %s (expected Bindings/, Events/, Banks/ and WwiseAudio/ inside it)" % path)


def _walk_dirs(top, depth):
    yield top
    if depth <= 0:
        return
    try:
        for k in sorted(os.listdir(top)):
            p = os.path.join(top, k)
            if os.path.isdir(p):
                yield from _walk_dirs(p, depth - 1)
    except OSError:
        return


# ------------------------------------------------------------------ scanning the source
def scan_source(P, path):
    S = Source(path)
    bikes = []
    for key, real in sorted(S.files.items()):
        if not (key.startswith("bindings/") and key.endswith(".uasset")):
            continue
        name = os.path.basename(real)[:-len(".uasset")]
        if not name.lower().startswith("bikeaudio_"):
            continue
        info = dict(name=name, pkg=GAME_AUDIO + os.path.relpath(real, S.root).replace(os.sep, "/")[:-len(".uasset")], notes=[])
        try:
            stem_real = real[:-len(".uasset")]
            with open(stem_real + ".uasset", "rb") as f1, open(stem_real + ".uexp", "rb") as f2:
                t = tree_of(f1.read(), f2.read())
            info["cls"] = t["cls"]
            refs = refs_of(t, "AkAudioEvent")
            info["engine"], info["exhaust"] = refs.get("EngineEvent", ""), refs.get("ExhaustEvent", "")
            info["other"] = {k: v for k, v in refs.items() if k not in ("EngineEvent", "ExhaustEvent")}
            banks = set()
            for ev in (info["engine"], info["exhaust"]):
                if ev and S.has_pkg(ev):
                    et = tree_of(*S.read_pkg(ev))
                    rb = refs_of(et, "AkAudioBank").get("RequiredBank")
                    if rb:
                        banks.add(rb)
            info["banks"] = sorted(banks)
            info["bnk_found"] = all(S.has("WwiseAudio/SoundBanks/Windows/%s.bnk" % b.rsplit("/", 1)[1]) for b in banks) and bool(banks)
        except Exception as e:
            info["error"] = "%s: %s" % (type(e).__name__, e)
        info["exists_in_target"] = P.src.origin(pkg_rel(info["pkg"]) + ".uasset") if info["pkg"].startswith("/Game/") else "?"
        bikes.append(info)
    return dict(root=S.root, bikes=bikes, has_init=S.has("WwiseAudio/SoundBanks/Windows/Init.bnk"))


# ------------------------------------------------------------------ planning / porting
class Target:
    """What the open project (mod folder + paks) already has."""

    def __init__(self, P):
        self.P = P
        rel = BANK_DIR + "/Init.bnk"
        if not P.src.exists(rel):
            raise C.MgpError("the target game has no Init.bnk at " + rel)
        self.init_rel = rel
        self.init = P.src.read(rel)
        self.version = bank_version(self.init)
        self.plugins = init_plugins(self.init)
        self.init_objs = hirc_objects(self.init)
        self.init_ids = {oid for _, oid, _ in self.init_objs}
        self.template = self._pick_template()

    def _pick_template(self):
        P, best = self.P, None
        for rel in P.src.find(BIND_DIR, ".uasset"):
            stem = rel[:-len(".uasset")]
            if not stem.rsplit("/", 1)[1].lower().startswith("bikeaudio_") or not P.src.exists(stem + ".uexp"):
                continue
            try:
                t = tree_of(*read_pair(P.src.read, stem))
                refs = refs_of(t, "AkAudioEvent")
                if "EngineEvent" not in refs or "ExhaustEvent" not in refs:
                    continue
                ev = {k: tree_of(*read_pair(P.src.read, pkg_rel(refs[k]))) for k in ("EngineEvent", "ExhaustEvent")}
                banks = {refs_of(e, "AkAudioBank").get("RequiredBank") for e in ev.values()}
                if len(banks) != 1 or None in banks:
                    continue
                bank = banks.pop()
                bt = tree_of(*read_pair(P.src.read, pkg_rel(bank)))
            except Exception:
                continue
            game = P.src.origin(stem + ".uasset") not in OWN
            key = (game, count_nodes(t))
            if best is None or key > best[0]:
                best = (key, dict(stem=stem, tree=t, refs=refs, events=ev, bank=bank, bank_tree=bt))
        if not best:
            raise C.MgpError("no existing BikeAudio asset with an engine and exhaust event found in the target to use as a template")
        return best[1]


def port(P, path, bike_names, dry_run=True, gain=0.0):
    global _GAIN
    _GAIN = float(gain or 0)
    S = Source(path)
    T = Target(P)
    tm = T.template
    src_init = hirc_objects(S.read("WwiseAudio/SoundBanks/Windows/Init.bnk")) if S.has("WwiseAudio/SoundBanks/Windows/Init.bnk") else None
    results, writes, init_extra = [], [], []
    seen_bnk, commons = {}, {}
    for name in bike_names:
        r = dict(bike=name, problems=[], warnings=[], actions=[], files=[])
        results.append(r)
        try:
            _plan_bike(P, S, T, tm, src_init, name, r, writes, init_extra, seen_bnk, commons)
        except C.MgpError as e:
            r["problems"].append(str(e))
        r["ok"] = not r["problems"]
    ok_names = {r["bike"] for r in results if r["ok"]}
    writes = [w for w in writes if w[0] in ok_names]
    for bn, c in commons.items():
        users = [u for u in sorted(c["users"]) if u in ok_names]
        if not users or not c["ok"]:
            continue
        for rel, data in c["writes"]:
            writes.append((users[0], rel, data))
        for evw in c["events"].values():
            for rel, data in evw:
                writes.append((users[0], rel, data))
        if c["init"]:
            init_extra.append((users[0], c["init"]))
    extra, have = [], set()
    for bike, objs in init_extra:
        if bike in ok_names:
            for o in objs:
                if o[1] not in have and o[1] not in T.init_ids:
                    have.add(o[1]); extra.append(o)
    init_info = dict(added=["0x%08x" % o[1] for o in extra])
    if extra:
        writes.append(("", T.init_rel, patch_init(T.init, extra)))
    written = []
    if not dry_run:
        for bike, rel, data in writes:
            dst = P.src.loose(rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(data)
            written.append(rel)
    for r in results:
        r["files"] = [rel for bike, rel, _ in writes if bike == r["bike"]]
    return dict(results=results, init=init_info, template=tm["stem"].rsplit("/", 1)[1], dry_run=dry_run,
                written=len(written), init_file=T.init_rel if extra else "")


def _guard_target(P, pkg, ext, what, r):
    """Refuse to replace anything the game itself ships (same name = same Wwise id)."""
    rel = pkg_rel(pkg) + ext
    if not P.src.exists(rel):
        return True
    origin = P.src.origin(rel)
    if origin in OWN:
        r["warnings"].append("%s already exists in your mod and will be overwritten" % what)
        return True
    r["problems"].append("%s already exists in the game (%s). Wwise ids come from names, so a copy would clash with it" % (what, origin))
    return False


def _plan_extras(P, S, T, tpl, src_init, name, bt, extra_port, r, commons):
    """Backfire/gear events the game does not have: ported together with the bank they live in, which is
    added under a new name (the game's own bank of that name has other events, so it cannot be replaced)."""
    out = {}
    for k, pkg in sorted(extra_port.items()):
        evname = pkg.rsplit("/", 1)[1]
        et = tree_of(*S.read_pkg(pkg))
        rb = refs_of(et, "AkAudioBank").get("RequiredBank")
        if not rb:
            r["warnings"].append("event %s has no RequiredBank; the template's %s is used instead" % (evname, k))
            continue
        bn = rb.rsplit("/", 1)[1]
        src_rel = "WwiseAudio/SoundBanks/Windows/%s.bnk" % bn
        if not S.has(src_rel):
            r["warnings"].append("%s.bnk (holds %s) is not in the source folder; the template's %s is used instead" % (bn, evname, k))
            continue
        nbn = "Ported_" + bn
        npkg_bank = rb.rsplit("/", 1)[0] + "/" + nbn
        c = commons.get(bn)
        if c is None:
            bnk = S.read(src_rel)
            c = commons[bn] = dict(writes=[], init=[], users=set(), events={}, name=nbn, pkg=npkg_bank, ok=True)
            if bank_version(bnk) != T.version:
                r["problems"].append("%s.bnk is Wwise version %d, the target uses %d" % (bn, bank_version(bnk), T.version))
                c["ok"] = False
            else:
                objs = hirc_objects(bnk)
                for pid in sorted(bank_plugin_ids(objs)):
                    if pid not in T.plugins:
                        r["problems"].append("%s.bnk needs the Wwise plugin 0x%x which the target game does not have" % (bn, pid))
                if src_init is not None:
                    need = init_needs(objs, src_init, T.init_ids)
                    if need:
                        c["init"] = need
                ok = _guard_target(P, npkg_bank, ".uasset", "bank asset " + nbn, r)
                brel = BANK_DIR + "/%s.bnk" % nbn
                if P.src.exists(brel) and P.src.origin(brel) not in OWN:
                    r["problems"].append("%s.bnk already exists in the game" % nbn)
                tbo = prop_obj(tpl["events"]["EngineEvent"], "RequiredBank")
                c["writes"] += [(pkg_rel(npkg_bank) + ".uasset", rename_asset(P.src.read(pkg_rel(tpl["bank"]) + ".uasset"), {tpl["bank"]: npkg_bank, tbo: nbn})),
                                (pkg_rel(npkg_bank) + ".uexp", P.src.read(pkg_rel(tpl["bank"]) + ".uexp")),
                                (brel, rename_bank(bnk, nbn))]
        if not c["ok"]:
            continue
        c["users"].add(name)
        nobj = prop_obj(bt, k)
        if pkg not in c["events"]:
            if not _guard_target(P, pkg, ".uasset", "event " + evname, r):
                continue
            opkg, oobj = tpl["refs"]["EngineEvent"], prop_obj(tpl["tree"], "EngineEvent")
            tbo = prop_obj(tpl["events"]["EngineEvent"], "RequiredBank")
            ua = rename_asset(P.src.read(pkg_rel(opkg) + ".uasset"), {opkg: pkg, oobj: nobj, tpl["bank"]: c["pkg"], tbo: c["name"]})
            c["events"][pkg] = [(pkg_rel(pkg) + ".uasset", ua), (pkg_rel(pkg) + ".uexp", P.src.read(pkg_rel(opkg) + ".uexp"))]
        r["actions"].append("port %s %s via the new bank %s" % (k, evname, c["name"]))
        out[k] = (pkg, nobj)
    return out


def _plan_bike(P, S, T, tm, src_init, name, r, writes, init_extra, seen_bnk, commons):
    bike_pkg = None
    for key, real in S.files.items():
        if key.startswith("bindings/") and os.path.basename(real) == name + ".uasset":
            bike_pkg = GAME_AUDIO + os.path.relpath(real, S.root).replace(os.sep, "/")[:-len(".uasset")]
    if not bike_pkg:
        raise C.MgpError("%s not found in the source folder" % name)
    bt = tree_of(*S.read_pkg(bike_pkg))
    if bt["cls"] != tm["tree"]["cls"]:
        raise C.MgpError("the source asset is a %s but the target uses %s" % (bt["cls"], tm["tree"]["cls"]))
    refs = refs_of(bt, "AkAudioEvent")
    if "EngineEvent" not in refs or "ExhaustEvent" not in refs:
        raise C.MgpError("the source BikeAudio asset has no engine/exhaust event")
    extra_keep, extra_port = {}, {}
    for k in sorted(set(refs) - {"EngineEvent", "ExhaustEvent"}):
        if P.src.exists(pkg_rel(refs[k]) + ".uasset"):
            extra_keep[k] = refs[k]
        elif S.has_pkg(refs[k]):
            extra_port[k] = refs[k]
        else:
            r["warnings"].append("%s uses %s which is in neither MotoGP 24 nor the source folder; the template's %s is used instead" % (name, refs[k].rsplit("/", 1)[1], k))
    # source events and bank
    ev_trees, bank_pkgs = {}, set()
    for k in ("EngineEvent", "ExhaustEvent"):
        if not S.has_pkg(refs[k]):
            raise C.MgpError("event asset missing in the source folder: " + refs[k])
        ev_trees[k] = tree_of(*S.read_pkg(refs[k]))
        rb = refs_of(ev_trees[k], "AkAudioBank").get("RequiredBank")
        if not rb:
            raise C.MgpError("%s has no RequiredBank" % refs[k].rsplit("/", 1)[1])
        bank_pkgs.add(rb)
    if len(bank_pkgs) != 1:
        raise C.MgpError("the engine and exhaust events use different banks; not supported yet")
    bank_pkg = bank_pkgs.pop()
    bank_name = bank_pkg.rsplit("/", 1)[1]
    bnk_rel_src = "WwiseAudio/SoundBanks/Windows/%s.bnk" % bank_name
    if not S.has(bnk_rel_src):
        raise C.MgpError("bank file %s.bnk not found in the source folder (WwiseAudio/SoundBanks/Windows)" % bank_name)
    if S.has_pkg(bank_pkg):
        bank_tree = tree_of(*S.read_pkg(bank_pkg))
    else:                           # the bank asset is only a name + AutoLoad flag, so it can be built from the target's
        bank_tree = None
        r["warnings"].append("AkAudioBank asset %s was not in the source folder; it is created from the game's own" % bank_name)
    bnk = S.read(bnk_rel_src)

    # ---- is the bank able to load in the target?
    ver = bank_version(bnk)
    if ver != T.version:
        r["problems"].append("Wwise bank version %d, but the target game uses %d. It will not load (banks cannot be converted without the Wwise project)" % (ver, T.version))
    objs = hirc_objects(bnk)
    for pid in sorted(bank_plugin_ids(objs)):
        if pid not in T.plugins:
            r["problems"].append("the bank needs the Wwise plugin 0x%x which the target game does not have" % pid)
    ev_ids = bank_event_ids(objs)
    for k in ("EngineEvent", "ExhaustEvent"):
        en = prop_obj(bt, k)
        if wwise_id(en) not in ev_ids:
            r["warnings"].append("event %s is not inside %s.bnk (its Wwise id is missing); the sound may not play" % (en, bank_name))
    st = streamed_media(objs)
    if st:
        r["warnings"].append("%d streamed sound(s) (loose .wem files needed): %s" % (len(st), ", ".join(str(x) for x in sorted(st)[:6])))
        for wid in st:
            rel = "WwiseAudio/SoundBanks/Windows/%d.wem" % wid
            if S.has(rel):
                writes.append((name, BANK_DIR + "/%d.wem" % wid, S.read(rel)))
                r["actions"].append("copy %d.wem" % wid)
            else:
                r["warnings"].append("%d.wem not found next to the source bank" % wid)
    if src_init is not None:
        need = init_needs(objs, src_init, T.init_ids)
        if need:
            init_extra.append((name, need))
            r["actions"].append("add %d object(s) to Init.bnk: %s" % (len(need), ", ".join("0x%08x" % o[1] for o in need)))
    else:
        r["warnings"].append("no Init.bnk in the source folder, so missing buses/effects cannot be checked or copied")

    # ---- names / clashes
    ok = _guard_target(P, bike_pkg, ".uasset", "the BikeAudio asset " + name, r)
    for k in ("EngineEvent", "ExhaustEvent"):
        ok &= _guard_target(P, refs[k], ".uasset", "event " + refs[k].rsplit("/", 1)[1], r)
    ok &= _guard_target(P, bank_pkg, ".uasset", "bank asset " + bank_name, r)
    brel = BANK_DIR + "/%s.bnk" % bank_name
    if P.src.exists(brel):
        origin = P.src.origin(brel)
        if origin in OWN:
            r["warnings"].append("%s.bnk already exists in your mod and will be overwritten" % bank_name)
        elif P.src.read(brel) != bnk:
            r["problems"].append("%s.bnk already exists in the game (%s) and differs" % (bank_name, origin))
    prev = seen_bnk.get(bank_name)
    if prev and prev != name:
        r["warnings"].append("%s.bnk is shared with %s" % (bank_name, prev))
    seen_bnk[bank_name] = name
    tpl = tm
    extra_new = _plan_extras(P, S, T, tpl, src_init, name, bt, extra_port, r, commons)
    if r["problems"]:
        return

    # ---- build the assets in the target's layout
    new_names = {}
    for k in ("EngineEvent", "ExhaustEvent"):
        tref = tpl["refs"][k]
        new_names[k] = (refs[k], prop_obj(bt, k), tref, prop_obj(tpl["tree"], k))
    tstem = tpl["stem"]
    tua = P.src.read(tstem + ".uasset")
    tpkg = "/Game/" + tstem[len("Content/"):]
    mapping = {tpkg: bike_pkg, tpl["tree"]["name"]: bt["name"]}
    for k, (npkg, nobj, opkg, oobj) in new_names.items():
        mapping[opkg], mapping[oobj] = npkg, nobj
    tua_texts = {t.lower() for t in C.UAsset(tua).texts()}
    tvals = list(tpl["refs"].values())
    for k, npkg in list(extra_keep.items()) + [(k, v[0]) for k, v in extra_new.items()]:
        tref = tpl["refs"].get(k)
        if not tref or tref == npkg:
            continue
        nobj = prop_obj(bt, k)
        oobj = prop_obj(tpl["tree"], k)
        if tvals.count(tref) > 1 or npkg.lower() in tua_texts or nobj.lower() in tua_texts or npkg in mapping or tref in mapping:
            if k in extra_new:
                r["problems"].append("cannot place %s: the template layout shares or already uses that name" % npkg.rsplit("/", 1)[1])
            continue
        mapping[tref], mapping[oobj] = npkg, nobj
        r["actions"].append("%s -> %s" % (k, nobj))
    writes.append((name, pkg_rel(bike_pkg) + ".uasset", rename_asset(tua, mapping)))
    writes.append((name, pkg_rel(bike_pkg) + ".uexp", P.src.read(tstem + ".uexp")))
    r["actions"].append("rebuild %s in MotoGP 24's layout (template: %s)" % (name, tstem.rsplit("/", 1)[1]))

    bank_obj = prop_obj(ev_trees["EngineEvent"], "RequiredBank")
    tbank_obj = prop_obj(tpl["events"]["EngineEvent"], "RequiredBank")
    for k in ("EngineEvent", "ExhaustEvent"):
        npkg, nobj, opkg, oobj = new_names[k]
        s_ua, s_ux = S.read_pkg(npkg)
        if signature(ev_trees[k]) == signature(tpl["events"][k]):
            data_ua, data_ux = s_ua, s_ux
            r["actions"].append("copy event %s (same layout as the game's)" % nobj)
        else:
            data_ua = rename_asset(P.src.read(pkg_rel(opkg) + ".uasset"),
                                   {opkg: npkg, oobj: nobj, tpl["bank"]: bank_pkg, tbank_obj: bank_obj})
            data_ux = P.src.read(pkg_rel(opkg) + ".uexp")
            r["actions"].append("rebuild event %s in MotoGP 24's layout" % nobj)
        writes.append((name, pkg_rel(npkg) + ".uasset", data_ua))
        writes.append((name, pkg_rel(npkg) + ".uexp", data_ux))
    if bank_tree is not None and signature(bank_tree) == signature(tpl["bank_tree"]):
        s_ua, s_ux = S.read_pkg(bank_pkg)
        b_ua, b_ux = s_ua, s_ux
        r["actions"].append("copy bank asset %s" % bank_name)
    else:
        b_ua = rename_asset(P.src.read(pkg_rel(tpl["bank"]) + ".uasset"), {tpl["bank"]: bank_pkg, tbank_obj: bank_obj})
        b_ux = P.src.read(pkg_rel(tpl["bank"]) + ".uexp")
        r["actions"].append("rebuild bank asset %s in MotoGP 24's layout" % bank_name)
    writes.append((name, pkg_rel(bank_pkg) + ".uasset", b_ua))
    writes.append((name, pkg_rel(bank_pkg) + ".uexp", b_ux))
    if _GAIN:
        bnk, nch = apply_gain(bnk, _GAIN)
        r["actions"].append("gain %+g dB on %d top-level object(s) of %s.bnk" % (_GAIN, nch, bank_name))
    writes.append((name, brel, bnk))
    r["actions"].append("copy %s.bnk (%.1f MB)" % (bank_name, len(bnk) / 1048576))
    r["new_path"] = bike_pkg
