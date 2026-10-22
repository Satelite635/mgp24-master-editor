"""Oodle decompression for MotoGP 25+ paks, through an Oodle DLL (Windows only): oo2core_*_win64.dll or
FModel's oodle-data-shared.dll.

Oodle is closed source, so there is no Python decoder: the DLL `oo2core_*_win64.dll` is loaded with ctypes.
It is searched next to the tool, below the game folder, and in FModel's folders (FModel downloads it)."""
import ctypes, glob, os, sys

_dll = None
_tried = []


def _candidates(hint_dirs):
    here = os.path.dirname(os.path.abspath(__file__))
    env = os.environ.get("MGP_OODLE_DLL")
    if env:
        yield env
    exe = os.path.dirname(os.path.abspath(sys.executable))         # the .exe build's own folder
    pats = [os.path.join(here, "oo2core_*_win64.dll"), os.path.join(exe, "oo2core_*_win64.dll")]
    for d in hint_dirs:                                    # e.g. the Paks folder: walk up to the game folder
        d = os.path.abspath(d)
        for _ in range(4):
            pats += [os.path.join(d, "oo2core_*_win64.dll"), os.path.join(d, "*", "Binaries", "Win64", "oo2core_*_win64.dll"),
                     os.path.join(d, "Engine", "Binaries", "ThirdParty", "Oodle", "*", "oo2core_*_win64.dll")]
            d = os.path.dirname(d)
    for base in (os.environ.get("APPDATA"), os.environ.get("LOCALAPPDATA"), os.path.expanduser("~/Documents"),
                 os.path.expanduser("~/Downloads"), os.path.expanduser("~/Desktop")):
        if base:
            pats += [os.path.join(base, "FModel", "oo2core_*_win64.dll"), os.path.join(base, "FModel", "*", "oo2core_*_win64.dll"),
                     os.path.join(base, "FModel", "Output", ".data", "oo2core_*_win64.dll")]
    for p in pats:                                         # FModel now ships Epic's oodle-data-shared.dll (same API)
        for q in (p, p.replace("oo2core_*_win64.dll", "oodle-data-shared.dll")):
            for f in sorted(glob.glob(q), reverse=True):
                yield f


def load(hint_dirs=()):
    """The loaded DLL; raises OSError with the places searched when it is not found."""
    global _dll
    if _dll:
        return _dll
    _tried.clear()
    for f in _candidates(hint_dirs):
        _tried.append(f)
        try:
            lib = ctypes.WinDLL(f) if os.name == "nt" else ctypes.CDLL(f)
        except OSError:
            continue
        fn = lib.OodleLZ_Decompress
        fn.restype = ctypes.c_int64
        fn.argtypes = [ctypes.c_void_p, ctypes.c_int64, ctypes.c_void_p, ctypes.c_int64, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                       ctypes.c_void_p, ctypes.c_int64, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64, ctypes.c_int]
        _dll = lib
        return lib
    raise OSError("Oodle DLL not found (oodle-data-shared.dll or oo2core_9_win64.dll). Copy it next to the tool "
                  "(FModel has one) and start the tool again.")


def decompress(data, raw_size, hint_dirs=()):
    fn = load(hint_dirs).OodleLZ_Decompress
    out = ctypes.create_string_buffer(raw_size)
    n = fn(data, len(data), out, raw_size, 1, 0, 0, None, 0, None, None, None, 0, 3)
    if n != raw_size:
        raise ValueError("Oodle decompression failed (%d of %d bytes)" % (n, raw_size))
    return out.raw
