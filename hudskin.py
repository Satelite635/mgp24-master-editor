"""HUD re-skin: compare the widgets of two UMG Widget Blueprints (same game's own widget vs. one from another game)
and copy chosen look properties (colours, fonts, sizes, brushes) from the source into the target, in place.

Only same-size patches are made (numbers, colours, enums, object references the target already imports), so no
offsets or export sizes ever change. Layout (slots) is never touched."""
import re
import struct

import uprops as U
from mgp_core import MgpError

WIDGET_CLASSES = ("IgnitionTextBlock", "TextBlock", "Image", "Border", "ProgressBar", "RichTextBlock")
SKIP = ("Slot", "Slots", "Text", "bIsVariable", "bIsVolatile", "Visibility", "localizedText")


def group_of(path):
    p = path.lower()
    if p.startswith("font.outline") or "shadow" in p:
        return "shadow"
    if p.startswith("font."):
        return "font"
    if "color" in p or "tint" in p:
        return "color"
    if "resourceobject" in p:
        return "image"
    if any(x in p for x in ("margin", "imagesize", "justification", "padding", "textcase")):
        return "layout"
    return "other"


def _leaves(nodes, pre=""):
    for n in nodes:
        k = pre + n["name"]
        if n.get("children") is not None:
            yield from _leaves(n["children"], k + ".")
        else:
            yield k, n


def widgets(a):
    """{widget name: (class, {property path: node})} for the look-bearing widgets of an asset."""
    out = {}
    for i, e in enumerate(a.exports):
        if e["cls"] in WIDGET_CLASSES:
            try:
                ex = a.parse_export(i)
            except MgpError:
                continue
            out[e["name"]] = (e["cls"], {k: n for k, n in _leaves(ex["props"]) if k.split(".")[0] not in SKIP})
    return out


def _value(a, n):
    if n["type"] == "ObjectProperty":
        return n.get("value")
    if n["type"] in ("ByteProperty", "EnumProperty", "NameProperty") and not n.get("edit"):
        return n.get("value")
    return n.get("value")


def _import_index(a, pkg, obj):
    """Negative object index of an import with this package + object name, or None."""
    for i in range(len(a.imports)):
        if a.imports[i]["cls"] == "Package":
            continue
        p, o = a.object_ref(-(i + 1))
        if o == obj and p == pkg:
            return -(i + 1)
    return None


def _name_index(a, text):
    try:
        return a.names.index(text)
    except ValueError:
        return None


def classify(ta, tn, sa, sn):
    """-> (status, how). status: same | patch | needs-import | needs-name | different-type."""
    if tn["type"] != sn["type"]:
        return "different-type", None
    t = tn["type"]
    if t == "ObjectProperty":
        tv, sv = tn.get("value"), sn.get("value")
        if tv == sv:
            return "same", None
        idx = _import_index(ta, sn.get("ref") or "", sv.split(".")[-1] if sv else "") if sv else 0
        if sv == "" or sv is None:
            return "different-type", None
        return ("patch", ("obj", idx)) if idx is not None else ("needs-import", None)
    if tn.get("edit") and sn.get("edit"):
        if tn["value"] == sn["value"]:
            return "same", None
        return "patch", ("val", sn["value"])
    if t in ("ByteProperty", "EnumProperty", "NameProperty"):
        if tn.get("value") == sn.get("value"):
            return "same", None
        idx = _name_index(ta, sn.get("value"))
        return ("patch", ("name", idx)) if idx is not None else ("needs-name", None)
    return "same" if tn.get("value") == sn.get("value") else "different-type", None


def compare(ta, sa):
    """Rows for every widget present in both with the same class, plus lists of widgets only in one."""
    tw, sw = widgets(ta), widgets(sa)
    rows = []
    for name in sorted(set(tw) & set(sw)):
        tc, tp = tw[name]
        sc, sp = sw[name]
        if tc != sc:
            continue
        for path in sorted(set(tp) | set(sp)):
            if path not in tp or path not in sp:
                rows.append(dict(widget=name, cls=tc, path=path, group=group_of(path), status="only-in-source" if path in sp else "only-in-target",
                                 target=str(tp[path]["value"]) if path in tp else "", source=str(sp[path]["value"]) if path in sp else ""))
                continue
            st, how = classify(ta, tp[path], sa, sp[path])
            if st == "same":
                continue
            rows.append(dict(widget=name, cls=tc, path=path, group=group_of(path), status=st,
                             target=str(tp[path].get("value")), source=str(sp[path].get("value"))))
    return dict(rows=rows, only_target=sorted(set(tw) - set(sw)), only_source=sorted(set(sw) - set(tw)), common=len(set(tw) & set(sw)))


def apply(ta, sa, picks):
    """Patch ta.uexp in place for picks [(widget, path)]. Returns (applied, skipped[(widget,path,why)])."""
    tw, sw = widgets(ta), widgets(sa)
    applied, skipped = 0, []
    for name, path in picks:
        if name not in tw or name not in sw or path not in tw[name][1] or path not in sw[name][1]:
            skipped.append((name, path, "not in both"))
            continue
        tn, sn = tw[name][1][path], sw[name][1][path]
        st, how = classify(ta, tn, sa, sn)
        if st != "patch":
            skipped.append((name, path, st))
            continue
        kind, val = how
        u, off = ta.uexp, tn["off"]
        if kind == "obj":
            struct.pack_into("<i", u, off, val)
        elif kind == "name":
            struct.pack_into("<i", u, off, val)  # keep the name number as is
            struct.pack_into("<i", u, off + 4, struct.unpack_from("<i", sa.uexp, sn["off"] + 4)[0])
        else:
            e = tn["edit"]
            if e == "num":
                fmt = U.SIMPLE[tn["type"]][0] if tn["type"] in U.SIMPLE else "<B"
                struct.pack_into(fmt, u, off, float(val) if fmt in ("<f", "<d") else int(val))
            elif e == "bool":
                u[off] = 1 if val else 0
            elif e == "floats":
                struct.pack_into("<%df" % len(val), u, off, *val)
            elif e == "color8":
                r, g, b, al = val
                u[off:off + 4] = bytes([b, g, r, al])
        applied += 1
    return applied, skipped


# ---------------------------------------------------------------- show / hide widgets
_VIS = ("Visible", "Collapsed", "Hidden", "HitTestInvisible", "SelfHitTestInvisible")
_SKIP = ("Slot", "WidgetTree", "Function", "Class", "Blueprint", "Graph", "Default__", "Timeline", "Animation")
WARN_NAMES = re.compile(r"penal|warn|longlap|long_lap", re.I)


def visibility_list(a):
    """Widgets of a page/widget asset with their current Visibility ('' = not set, the class default applies)."""
    out = []
    for i, e in enumerate(a.exports):
        if any(k in e["cls"] or e["name"].startswith("Default__") for k in _SKIP) or e["name"] in ("WidgetTree",):
            continue
        cur = ""
        try:
            for p in a.parse_export(i)["props"]:
                if p["name"] == "Visibility":
                    cur = str(p.get("value", "")).split("::")[-1]
        except Exception:
            continue
        out.append(dict(i=i, name=e["name"], cls=e["cls"], vis=cur, warn=bool(WARN_NAMES.search(e["name"] + e["cls"]))))
    return out


def set_visibility(ua_bytes, ux_bytes, changes):
    """changes: {export name: one of _VIS}. Returns (uasset, uexp, done). Sets the Visibility property,
    adding it to the export when it is not there."""
    import struct
    import mgp_core as C
    ua = C.UAsset(ua_bytes)
    need = ["Visibility", "ByteProperty", "EnumProperty", "ESlateVisibility"] + ["ESlateVisibility::" + v for v in set(changes.values())]
    for n in need:
        if n not in ua.texts():
            if n == "ByteProperty" or n == "EnumProperty":
                pass
            ua.append_name(n)
    a = U.Asset(ua.to_bytes(), ux_bytes)
    ix = {n: k for k, n in enumerate(a.names)}
    # existing properties use EnumProperty (as in this game's assets)
    typ = "EnumProperty" if "EnumProperty" in ix else "ByteProperty"
    done = []
    for name, v in changes.items():
        if v not in _VIS:
            raise C.MgpError("unknown visibility " + v)
        hits = [i for i, e in enumerate(a.exports) if e["name"] == name and not name.startswith("Default__")]
        if not hits:
            continue
        i = hits[0]
        t = a.parse_export(i)
        val = struct.pack("<ii", ix["ESlateVisibility::" + v], 0)
        cur = [p for p in t["props"] if p["name"] == "Visibility"]
        if cur:
            if cur[0]["size"] == 8:
                a.uexp[cur[0]["off"]:cur[0]["off"] + 8] = val
                done.append(name)
            continue
        tag = (struct.pack("<ii", ix["Visibility"], 0) + struct.pack("<ii", ix[typ], 0) + struct.pack("<ii", 8, 0) +
               struct.pack("<ii", ix["ESlateVisibility"], 0) + b"\0" + val)
        at = t["end"] - 8                                    # the "None" terminator
        a.uexp[at:at] = tag
        d = len(tag)
        eo = a.ua._get("exportoff")
        S = C.UAsset.EXPORT_SIZE
        sz = struct.unpack_from("<q", a.ua.data, eo + i * S + 28)[0]
        struct.pack_into("<q", a.ua.data, eo + i * S + 28, sz + d)
        for j in range(i + 1, len(a.exports)):
            q = eo + j * S + 36
            struct.pack_into("<q", a.ua.data, q, struct.unpack_from("<q", a.ua.data, q)[0] + d)
        bulk = a.ua._get("bulk", "<q")
        if bulk:
            a.ua._set("bulk", bulk + d, "<q")
        a = U.Asset(a.ua.to_bytes(), bytes(a.uexp))          # refresh offsets
        done.append(name)
    return a.ua.to_bytes(), bytes(a.uexp), done


# ---------------------------------------------------------------- swap a widget's class
def retype_widget(ua_bytes, ux_bytes, donor_ua_bytes, from_cls, to_cls):
    """Make the widget(s) of class `from_cls` in this asset instances of `to_cls` (a widget class that exists
    in the donor asset, i.e. the game's own page). Only the asset's three import entries for that class are
    re-pointed (package, class, default object), so no export, offset or dependency list changes.
    Returns (uasset_bytes, uexp_bytes, [names of widgets changed])."""
    import struct
    import mgp_core as C
    t = U.Asset(ua_bytes, ux_bytes)
    d = U.Asset(donor_ua_bytes, b"")

    def trio(a, cls, what):
        c = [i for i, im in enumerate(a.imports) if im["name"] == cls and im["cls"] == "WidgetBlueprintGeneratedClass"]
        if len(c) != 1:
            raise MgpError("%s: expected one import of %s, found %d" % (what, cls, len(c)))
        c = c[0]
        outer = a.imports[c]["outer"]
        pk = -outer - 1
        df = [i for i, im in enumerate(a.imports) if im["name"] == "Default__" + cls and im["outer"] == outer]
        if len(df) != 1 or outer >= 0:
            raise MgpError("%s: cannot find the default object / package of %s" % (what, cls))
        extra = [i for i, im in enumerate(a.imports) if im["outer"] == outer and i not in (c, df[0])]
        return pk, c, df[0], extra

    tpk, tc, tdf, textra = trio(t, from_cls, "this page")
    dpk, dc, ddf, _ = trio(d, to_cls, "the game's page")
    if textra:
        raise MgpError("something else in this page also uses the %s package; not swapping" % from_cls)
    users = [e["name"] for e in t.exports if e["cls"] == from_cls]
    if not users:
        raise MgpError("no widget of class %s in this page" % from_cls)
    pkg_text = d.imports[dpk]["name"]
    ua = C.UAsset(ua_bytes)
    texts = ua.texts()
    def nm(s):
        return texts.index(s) if s in texts else ua.append_name(s)
    pk_i, cls_i, def_cls_i, def_name_i = nm(pkg_text), nm(to_cls), nm(to_cls), nm("Default__" + to_cls)
    io = ua._get("importoff")
    def rec(i):
        return list(struct.unpack_from("<iiiiiii", ua.data, io + i * 28))
    r = rec(tpk); r[5] = pk_i; struct.pack_into("<iiiiiii", ua.data, io + tpk * 28, *r)
    r = rec(tc); r[5] = cls_i; struct.pack_into("<iiiiiii", ua.data, io + tc * 28, *r)
    r = rec(tdf); r[0], r[2], r[5] = pk_i, def_cls_i, def_name_i; struct.pack_into("<iiiiiii", ua.data, io + tdf * 28, *r)
    out = ua.to_bytes()
    chk = U.Asset(out, ux_bytes)                              # must still parse, with the new class
    if not all(e["cls"] == to_cls for e in chk.exports if e["name"] in users):
        raise MgpError("the swap did not take effect")
    return out, bytes(ux_bytes), users


def swap_widget_types(ua_bytes, name_a, name_b):
    """Exchange the widget class of two exports (class, super, template and dependency fields), so each keeps its
    slot / position but shows the other's widget. Returns (uasset_bytes, class_now_at_a, class_now_at_b)."""
    import struct
    import mgp_core as C
    ua = C.UAsset(ua_bytes)
    eo, n, sz = ua._get("exportoff"), ua._get("exportcount"), ua.EXPORT_SIZE
    names = ua.texts()
    at = {}
    for i in range(n):
        idx = struct.unpack_from("<i", ua.data, eo + i * sz + 16)[0]
        if 0 <= idx < len(names):
            at.setdefault(names[idx], i)
    if name_a not in at or name_b not in at:
        raise MgpError("widgets %s / %s not both in this page" % (name_a, name_b))
    a, b = eo + at[name_a] * sz, eo + at[name_b] * sz
    for lo, hi in ((0, 12), (84, 104)):
        ta, tb = bytes(ua.data[a + lo:a + hi]), bytes(ua.data[b + lo:b + hi])
        ua.data[a + lo:a + hi], ua.data[b + lo:b + hi] = tb, ta
    return ua.to_bytes()


# ---------------------------------------------------------------- fonts
FONT_KEEP = re.compile(r"arialunicode|notosans|ttsupermolot", re.I)       # fallback (CJK) faces and the new faces: never touched


def font_faces(ua_bytes):
    """[(import index, face name)] for the FontFace imports of a Font asset ([] when it is not a Font)."""
    a = U.Asset(ua_bytes, b"")
    if not any(e["cls"] == "Font" for e in a.exports):
        return []
    return [(i, im["name"]) for i, im in enumerate(a.imports) if im["cls"] == "FontFace"]


def font_weight(*names):
    s = " ".join(names).lower()
    if re.search(r"black|bold|heavy", s):
        return "Bold"
    if re.search(r"light|thin", s):
        return "Light"
    return "Regular"


def retarget_font(ua_bytes, face_map):
    """face_map: {old FontFace name: new FontFace asset name (e.g. 'FF_TTSupermolotNeue-Bold_Mono')} - both live in
    /Game/assets/ui/Fonts. Re-points the asset's FontFace + package import records. Returns (uasset_bytes, [done names])."""
    import struct
    import mgp_core as C
    a = U.Asset(ua_bytes, b"")
    ua = C.UAsset(ua_bytes)
    texts = ua.texts()
    def nm(s):
        return texts.index(s) if s in texts else ua.append_name(s)

    jobs = []
    for i, im in enumerate(a.imports):
        if im["cls"] != "FontFace" or im["name"] not in face_map or im["outer"] >= 0:
            continue
        new = face_map[im["name"]]
        pk = -im["outer"] - 1
        pkg = a.imports[pk]["name"]
        newpkg = pkg.rsplit("/", 1)[0] + "/" + new
        jobs.append((im["name"], [(i, nm(new)), (pk, nm(newpkg))]))
    io = ua._get("importoff")                              # read after the names were appended (it moves)
    done = []
    for name, edits in jobs:
        for idx, ni in edits:
            rec = list(struct.unpack_from("<iiiiiii", ua.data, io + idx * 28))
            rec[5] = ni
            struct.pack_into("<iiiiiii", ua.data, io + idx * 28, *rec)
        done.append(name)
    return ua.to_bytes(), done
