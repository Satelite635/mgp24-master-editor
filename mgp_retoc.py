"""retoc (https://github.com/trumank/retoc) as a helper for MotoGP 25: zen <-> legacy asset conversion.

UAssetGUI can't open zen (IoStore) assets, so for GP25 the editor extracts a legacy .uasset/.uexp with
`retoc to-legacy` and turns legacy files in the mod folder back into zen with `retoc to-zen` when packing."""
import os, shutil, subprocess, sys, tempfile

ENGINE = {"gp25": "UE5_5", "gp26": "UE5_7"}


class RetocError(Exception):
    pass


def find(configured=""):
    """Path of retoc(.exe): the configured one, next to the tool / its exe, or on PATH. '' if none."""
    if configured:
        return configured if os.path.isfile(configured) else ""
    name = "retoc.exe" if os.name == "nt" else "retoc"
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (here, os.path.dirname(os.path.abspath(sys.executable)), os.path.join(here, "retoc")):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
    return shutil.which("retoc") or ""


def _run(exe, args, log=None, timeout=1800):
    if not exe:
        raise RetocError("retoc not found: put retoc.exe next to the tool or set its path in Setup "
                         "(https://github.com/trumank/retoc/releases)")
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = 0x08000000                         # CREATE_NO_WINDOW
    try:
        r = subprocess.run([exe] + args, capture_output=True, text=True, errors="replace", timeout=timeout, **kw)
    except OSError as e:
        raise RetocError("could not start retoc (%s): %s" % (exe, e))
    except subprocess.TimeoutExpired:
        raise RetocError("retoc took longer than %d s and was stopped" % timeout)
    out = (r.stdout or "") + (r.stderr or "")
    if log:
        for line in out.splitlines()[-30:]:
            if line.strip() and "\r" not in line:
                log("retoc: " + line.strip())
    if r.returncode:
        raise RetocError("retoc failed (exit %d): %s" % (r.returncode, out.strip()[-600:]))
    return out


def _walk(root):
    out = {}
    for d, _, fs in os.walk(root):
        for f in fs:
            full = os.path.join(d, f)
            out[os.path.relpath(full, root).replace(os.sep, "/")] = full
    return out


UNKNOWN = b"/Engine/UnknownPackage"


def _unresolved(files):
    """Names of converted files whose imports retoc could not resolve (it writes /Engine/UnknownPackage)."""
    bad = []
    for rel, path in files.items():
        if rel.lower().endswith(".uasset"):
            with open(path, "rb") as f:
                if UNKNOWN in f.read():
                    bad.append(rel.rsplit("/", 1)[-1])
    return bad


def to_legacy(exe, paks_dir, aes_key, rels, log=None):
    """Convert the game's zen packages `rels` ('Content/x/Name' stems) to legacy files.
    -> (temp dir to delete, {'Content/x/Name.uasset': full path, '.uexp', '.ubulk' ...})."""
    tmp = tempfile.mkdtemp(prefix="mgp_legacy_")
    args = (["--aes-key", aes_key] if aes_key else []) + ["to-legacy", paks_dir, tmp, "--no-shaders", "--no-script-objects"]
    for r in rels:
        args += ["--filter", r + "."]                          # retoc matches a substring of the package's file path
    _run(exe, args, log)
    got = {}
    for rel, full in _walk(tmp).items():
        i = rel.find("Content/")
        if i >= 0 and any(rel[i:].startswith(r + ".") for r in rels):
            got[rel[i:]] = full
    bad = _unresolved(got)
    if bad:
        shutil.rmtree(tmp, ignore_errors=True)
        raise RetocError("retoc could not resolve some imports of %s (it wrote /Engine/UnknownPackage); the file would be "
                         "broken, so nothing was extracted. Is the Paks folder the game's full Paks folder?" % ", ".join(bad[:5]))
    return tmp, got


def to_zen(exe, project, files, game="gp25", log=None):
    """Legacy files {'Content/x/Name.uasset': path, '.uexp': path, ...} -> zen, via a temp retoc container.
    -> (temp dir to delete, path of the .utoc retoc wrote)."""
    tmp = tempfile.mkdtemp(prefix="mgp_zen_")
    src = os.path.join(tmp, "in")
    for rel, path in files.items():
        dst = os.path.join(src, project, *rel.split("/"))          # mount point ../../../ -> <project>/Content/...
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(path, dst)
    utoc = os.path.join(tmp, "out", "legacy_P.utoc")
    os.makedirs(os.path.dirname(utoc))
    _run(exe, ["to-zen", src, utoc, "--version", ENGINE.get(game, "UE5_5")], log)
    if not os.path.isfile(utoc):
        raise RetocError("retoc to-zen wrote no .utoc")
    bad = _unresolved(files)
    if bad:
        shutil.rmtree(tmp, ignore_errors=True)
        raise RetocError("%s import /Engine/UnknownPackage (an unresolved import from a bad conversion); "
                         "extract the asset again" % ", ".join(bad[:5]))
    return tmp, utoc
