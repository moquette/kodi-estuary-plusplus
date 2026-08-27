#!/usr/bin/env python3
"""Structural regression harness for skin.estuary8.

Compares the working tree against a git baseline and reports structural
regressions that XML well-formedness cannot see. Deleting a whole balanced
<control> leaves perfectly valid XML, so a parse check passes while a settings
window loses every focusable control. This tool counts and names what vanished.

Six checks, run in this order and reported worst first:

  1. control census        controls per file, broken down by type=
  2. control id census     every id="" on a control, per file
  3. reference integrity   include / $VAR / $EXP / <font> / <texture>
  4. font binding          every <filename> in Font.xml resolves to a real file
  5. font id inventory     the <name> list per fontset
  6. orphan hunt           nav targets that no longer exist anywhere

Everything is reported as a DELTA against the baseline. Pre-existing upstream
breakage is counted but does not fail the run; only new breakage does. That is
deliberate: a check that cries wolf about 300 inherited defects gets muted, and
a muted check is the same as no check.

Usage:
    python3 estuary8/tools/verify_skin.py
    python3 estuary8/tools/verify_skin.py --baseline HEAD
    python3 estuary8/tools/verify_skin.py --max 40 --json out.json

Exit codes: 0 clean, 1 regressions found, 2 tool error.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import struct
import subprocess
import sys
import tarfile
import xml.parsers.expat
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------

SKIN_SUBDIR = "estuary8/skin.estuary8"
DEFAULT_BASELINE = "cd28cb9"

# Kodi's own font directory. arial.ttf is bound by Font.xml and legitimately
# absent from the skin because it ships inside the application bundle. Calling
# that a broken fontset is a false positive that two earlier plans both made.
KODI_APP_CANDIDATES = [
    "~/Applications/Kodi22.app/Contents/Resources/Kodi",
    "/Applications/Kodi22.app/Contents/Resources/Kodi",
    "/Applications/Kodi.app/Contents/Resources/Kodi",
]

# Directories under the skin root that hold markup worth parsing.
PARSE_DIRS = ("xml", "shortcuts", "colors", "extras")

# Elements whose text is a texture path.
TEXTURE_TAGS = frozenset(
    t
    for t in [
        "texture",
        "bordertexture",
        "texturefocus",
        "texturenofocus",
        "texturebg",
        "midtexture",
        "lefttexture",
        "righttexture",
        "overlaytexture",
        "progresstexture",
        "texturesliderbar",
        "texturesliderbarfocus",
        "texturesliderbackground",
        "textureslidernib",
        "textureslidernibfocus",
        "textureradioonfocus",
        "textureradioonnofocus",
        "textureradioondisabled",
        "textureradioofffocus",
        "textureradiooffnofocus",
        "textureradiooffdisabled",
        "alttexturefocus",
        "alttexturenofocus",
        "texturecolormask",
        "texturecolordisabledmask",
        "textureup",
        "texturedown",
        "textureupfocus",
        "texturedownfocus",
        "textureupdisabled",
        "texturedowndisabled",
        "texturefocusdisabled",
    ]
)

NAV_TAGS = ("onleft", "onright", "onup", "ondown", "pagecontrol")

# A control the user can put a cursor on. A window that had some of these at
# baseline and has none now is dead: it renders, and nothing can be pressed.
FOCUSABLE_TYPES = frozenset(
    [
        "button",
        "radiobutton",
        "togglebutton",
        "list",
        "fixedlist",
        "wraplist",
        "panel",
        "edit",
        "slider",
        "sliderex",
        "spincontrol",
        "spincontrolex",
        "mover",
        "resize",
        "grouplist",
        "colorbutton",
        "gamecontroller",
        "gamecontrollerlist",
    ]
)

# xml/ files that Kodi's include loader references but that are generated at
# runtime rather than shipped. Missing on disk is normal.
GENERATED_INCLUDE_FILES = frozenset({"script-skinshortcuts-includes.xml"})


# --------------------------------------------------------------------------
# tiny XML tree with line numbers
# --------------------------------------------------------------------------


class Node:
    __slots__ = ("attrs", "children", "line", "tag", "text")

    def __init__(self, tag: str, attrs: dict, line: int) -> None:
        self.tag = tag
        self.attrs = attrs
        self.line = line
        self.text: list[str] = []
        self.children: list[Node] = []

    def value(self) -> str:
        return "".join(self.text).strip()

    def walk(self):
        stack = [self]
        while stack:
            n = stack.pop()
            yield n
            stack.extend(reversed(n.children))


_BARE_AMP = re.compile(rb"&(?!(?:[A-Za-z][A-Za-z0-9]*|#[0-9]+|#x[0-9A-Fa-f]+);)")


def parse_xml(data: bytes) -> tuple[Node | None, str | None]:
    """Parse to a Node tree. Returns (root, error).

    Kodi uses TinyXML, which tolerates a bare '&'. expat does not, and a
    handful of upstream files carry one. Normalise those so the check reports
    real structural damage rather than an inherited encoding wart.
    """
    data = _BARE_AMP.sub(b"&amp;", data.lstrip(b"\xef\xbb\xbf"))
    root: Node | None = None
    stack: list[Node] = []
    parser = xml.parsers.expat.ParserCreate()

    def start(name, attrs):
        nonlocal root
        node = Node(name, attrs, parser.CurrentLineNumber)
        if stack:
            stack[-1].children.append(node)
        elif root is None:
            root = node
        stack.append(node)

    def end(_name):
        stack.pop()

    def chars(text):
        if stack:
            stack[-1].text.append(text)

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = chars
    try:
        parser.Parse(data, True)
    except xml.parsers.expat.ExpatError as exc:
        return root, str(exc)
    return root, None


# --------------------------------------------------------------------------
# model
# --------------------------------------------------------------------------


@dataclass
class Ref:
    """A reference from markup to something that must resolve."""

    name: str
    file: str
    line: int

    def where(self) -> str:
        return f"{self.file}:{self.line}"


_BOLD_RE = re.compile(r"bold|black|heavy|semibold|extrabold", re.IGNORECASE)


@dataclass
class FontDef:
    """One <font> entry in Font.xml."""

    filename: str = ""
    style: str = ""
    size: str = ""
    line: int = 0

    @property
    def heavy(self) -> bool:
        """Heuristic: does this id render as a heavy weight?

        Kodi takes weight from two independent places, the face in <filename>
        and the synthetic <style>bold</style>. A thinning pass has to clear both
        or the id stays heavy, so both are folded into one signal here.
        """
        return bool(_BOLD_RE.search(self.filename) or _BOLD_RE.search(self.style))

    def summary(self) -> str:
        bits = [self.filename or "?"]
        if self.style:
            bits.append(f"style={self.style}")
        if self.size:
            bits.append(f"size={self.size}")
        return " ".join(bits)


@dataclass
class ControlRec:
    ctype: str
    cid: str
    file: str
    line: int


@dataclass
class FileRec:
    path: str
    root_tag: str = ""
    parse_error: str | None = None
    controls: list[ControlRec] = field(default_factory=list)
    include_defs: dict[str, int] = field(default_factory=dict)

    @property
    def n_controls(self) -> int:
        return len(self.controls)

    def type_counts(self) -> Counter:
        return Counter(c.ctype for c in self.controls)

    def ids(self) -> set[str]:
        return {c.cid for c in self.controls if c.cid}


@dataclass
class Model:
    label: str
    files: dict[str, FileRec] = field(default_factory=dict)
    # reference buckets
    include_refs: list[Ref] = field(default_factory=list)
    include_file_refs: list[Ref] = field(default_factory=list)
    var_refs: list[Ref] = field(default_factory=list)
    exp_refs: list[Ref] = field(default_factory=list)
    font_refs: list[Ref] = field(default_factory=list)
    texture_refs: list[Ref] = field(default_factory=list)
    nav_refs: list[Ref] = field(default_factory=list)
    hasfocus_refs: list[Ref] = field(default_factory=list)
    # definition tables
    include_defs: dict[str, str] = field(default_factory=dict)
    var_defs: dict[str, str] = field(default_factory=dict)
    exp_defs: dict[str, str] = field(default_factory=dict)
    fontsets: dict[str, dict[str, FontDef]] = field(default_factory=dict)
    font_files: list[tuple[str, str, int]] = field(default_factory=list)
    font_dupes: list[tuple[str, str, int]] = field(default_factory=list)
    # asset inventory
    asset_paths: set[str] = field(default_factory=set)
    xbt_entries: set[str] = field(default_factory=set)

    def all_control_ids(self) -> set[str]:
        out: set[str] = set()
        for f in self.files.values():
            out |= f.ids()
        return out

    def total_controls(self) -> int:
        return sum(f.n_controls for f in self.files.values())


# --------------------------------------------------------------------------
# extraction
# --------------------------------------------------------------------------

_VAR_RE = re.compile(r"\$VAR\[\s*([^\],]+)")
_EXP_RE = re.compile(r"\$EXP\[\s*([^\],]+)")
_HASFOCUS_RE = re.compile(r"Control\.HasFocus\(\s*(\d+)\s*\)")
_SETFOCUS_RE = re.compile(r"SetFocus\(\s*(\d+)", re.IGNORECASE)
_INT_RE = re.compile(r"^\d+$")


def _node_strings(node: Node):
    """Every string in a node that could carry a $VAR / Control.HasFocus."""
    yield from node.attrs.values()
    yield node.value()


def extract_file(path: str, data: bytes, model: Model) -> FileRec:
    rec = FileRec(path=path)
    root, err = parse_xml(data)
    rec.parse_error = err
    if root is None:
        model.files[path] = rec
        return rec
    rec.root_tag = root.tag
    is_font_file = Path(path).name.lower() == "font.xml"

    for node in root.walk():
        tag = node.tag
        _scan_free_text(node, path, model)

        if tag == "control":
            rec.controls.append(
                ControlRec(
                    ctype=node.attrs.get("type", "<untyped>"),
                    cid=node.attrs.get("id", ""),
                    file=path,
                    line=node.line,
                )
            )
        elif tag == "include":
            _scan_include(node, path, rec, model)
        elif tag == "variable" and "name" in node.attrs:
            model.var_defs.setdefault(node.attrs["name"], f"{path}:{node.line}")
        elif tag == "expression" and "name" in node.attrs:
            model.exp_defs.setdefault(node.attrs["name"], f"{path}:{node.line}")
        elif tag == "font" and not is_font_file:
            val = node.value()
            if val and "$" not in val:
                model.font_refs.append(Ref(val, path, node.line))
        elif tag == "param" and node.attrs.get("name") == "font":
            # <include content="X"><param name="font" value="font30_title"/></include>
            # feeding an include whose body is <font>$PARAM[font]</font>. Without
            # this, an id used only through a param looks unreferenced and would
            # be a tempting deletion during a slimming pass.
            val = node.attrs.get("value", "")
            if val and "$" not in val:
                model.font_refs.append(Ref(val, path, node.line))
        elif tag in TEXTURE_TAGS:
            val = node.value()
            if val:
                model.texture_refs.append(Ref(val, path, node.line))
        elif tag in NAV_TAGS:
            _scan_nav(node, path, model)

    if is_font_file:
        _scan_fontsets(root, path, model)

    model.files[path] = rec
    return rec


def _scan_free_text(node: Node, path: str, model: Model) -> None:
    for s in _node_strings(node):
        if not s:
            continue
        if "$VAR[" in s:
            for m in _VAR_RE.finditer(s):
                name = m.group(1).strip()
                if name and "$" not in name:
                    model.var_refs.append(Ref(name, path, node.line))
        if "$EXP[" in s:
            for m in _EXP_RE.finditer(s):
                name = m.group(1).strip()
                if name and "$" not in name:
                    model.exp_refs.append(Ref(name, path, node.line))
        if "Control.HasFocus(" in s:
            for m in _HASFOCUS_RE.finditer(s):
                model.hasfocus_refs.append(Ref(m.group(1), path, node.line))


def _scan_include(node: Node, path: str, rec: FileRec, model: Model) -> None:
    attrs, val = node.attrs, node.value()
    if "name" in attrs:
        rec.include_defs[attrs["name"]] = node.line
        model.include_defs.setdefault(attrs["name"], f"{path}:{node.line}")
        return
    if "file" in attrs:
        model.include_file_refs.append(Ref(attrs["file"], path, node.line))
    for candidate in (attrs.get("content"), val):
        if candidate and "$" not in candidate:
            model.include_refs.append(Ref(candidate.strip(), path, node.line))


def _scan_nav(node: Node, path: str, model: Model) -> None:
    val = node.value()
    if not val or "$" in val:
        return
    if _INT_RE.match(val):
        model.nav_refs.append(Ref(val, path, node.line))
        return
    for m in _SETFOCUS_RE.finditer(val):
        model.nav_refs.append(Ref(m.group(1), path, node.line))


def _scan_fontsets(root: Node, path: str, model: Model) -> None:
    for fontset in root.children:
        if fontset.tag != "fontset":
            continue
        set_id = fontset.attrs.get("id", "<unnamed>")
        table = model.fontsets.setdefault(set_id, {})
        for font in fontset.children:
            if font.tag != "font":
                continue
            name, fd = "", FontDef(line=font.line)
            for child in font.children:
                if child.tag == "name":
                    name = child.value()
                elif child.tag == "filename":
                    fd.filename = child.value()
                elif child.tag == "style":
                    fd.style = child.value()
                elif child.tag == "size":
                    fd.size = child.value()
            if name:
                if name in table:
                    model.font_dupes.append((f"{set_id}/{name}", path, font.line))
                table[name] = fd
            if fd.filename:
                model.font_files.append((fd.filename, path, font.line))


# --------------------------------------------------------------------------
# tree loaders
# --------------------------------------------------------------------------


def _run(cmd: list[str], repo: Path, binary: bool = False):
    out = subprocess.run(cmd, cwd=repo, capture_output=True, check=True)
    return out.stdout if binary else out.stdout.decode("utf-8", "replace")


def _wanted(rel: str) -> bool:
    return rel.endswith(".xml") and (rel.split("/", 1)[0] in PARSE_DIRS or "/" not in rel)


def load_working(skin_root: Path, label: str) -> Model:
    model = Model(label=label)
    for dirpath, dirnames, filenames in os.walk(skin_root):
        dirnames[:] = [d for d in dirnames if d != "language"]
        for fn in sorted(filenames):
            full = Path(dirpath) / fn
            rel = str(full.relative_to(skin_root))
            model.asset_paths.add(rel)
            if _wanted(rel):
                extract_file(rel, full.read_bytes(), model)
    xbt = skin_root / "media" / "Textures.xbt"
    if xbt.exists():
        model.xbt_entries = parse_xbt(xbt.read_bytes())
    return model


def load_baseline(repo: Path, ref: str, prefix: str) -> Model:
    model = Model(label=ref)
    sha = _run(["git", "rev-parse", ref], repo).strip()
    model.label = f"{ref} ({sha[:8]})"

    listing = _run(["git", "ls-tree", "-r", "--name-only", sha, "--", prefix], repo)
    for line in listing.splitlines():
        if line.startswith(prefix + "/"):
            model.asset_paths.add(line[len(prefix) + 1 :])

    blob = _run(["git", "archive", sha, "--", prefix], repo, binary=True)
    with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            rel = member.name[len(prefix) + 1 :]
            if _wanted(rel):
                fh = tar.extractfile(member)
                if fh:
                    extract_file(rel, fh.read(), model)
            elif rel == "media/Textures.xbt":
                fh = tar.extractfile(member)
                if fh:
                    model.xbt_entries = parse_xbt(fh.read())
    return model


def parse_xbt(data: bytes) -> set[str]:
    """Read the entry table of a Kodi XBT texture bundle.

    Layout: 'XBTF' + version byte + uint32 file count, then per file a
    256 byte NUL padded path, uint32 loop, uint32 frame count, and 40 bytes
    per frame. Entry names are stored LOWER CASED while the XML uses
    CamelCase, so callers must compare case insensitively.
    """
    if data[:4] != b"XBTF":
        return set()
    count = struct.unpack_from("<I", data, 5)[0]
    off, names = 9, set()
    try:
        for _ in range(count):
            path = data[off : off + 256].split(b"\x00")[0]
            off += 256
            _loop, nframes = struct.unpack_from("<II", data, off)
            off += 8 + nframes * 40
            names.add(path.decode("utf-8", "replace").lower())
    except struct.error:
        pass
    return names


# --------------------------------------------------------------------------
# findings
# --------------------------------------------------------------------------

SEVERITIES = ("FATAL", "REGRESSION", "ADVISORY", "INFO")


@dataclass
class Finding:
    severity: str
    check: str
    summary: str
    details: list[str] = field(default_factory=list)

    @property
    def fails(self) -> bool:
        return self.severity in ("FATAL", "REGRESSION")


class Report:
    def __init__(self) -> None:
        self.findings: list[Finding] = []

    def add(self, severity, check, summary, details=None) -> None:
        self.findings.append(Finding(severity, check, summary, list(details or [])))

    @property
    def failed(self) -> bool:
        return any(f.fails for f in self.findings)


# --------------------------------------------------------------------------
# check 1 + 2: control census and control id census
# --------------------------------------------------------------------------


def check_control_census(base: Model, cur: Model, rep: Report, cap: int) -> None:
    losses = []
    for path, brec in sorted(base.files.items()):
        crec = cur.files.get(path)
        if crec is None:
            losses.append((brec.n_controls, path, brec, None))
            continue
        if crec.n_controls < brec.n_controls:
            losses.append((brec.n_controls - crec.n_controls, path, brec, crec))

    losses.sort(reverse=True, key=lambda t: t[0])
    if losses:
        details = []
        for lost, path, brec, crec in losses[:cap]:
            if crec is None:
                details.append(f"{path}: FILE DELETED, {brec.n_controls} controls gone")
                continue
            bt, ct = brec.type_counts(), crec.type_counts()
            gone = [f"{t} x{bt[t] - ct.get(t, 0)}" for t in sorted(bt) if bt[t] > ct.get(t, 0)]
            details.append(
                f"{path}: {brec.n_controls} -> {crec.n_controls} controls "
                f"(-{lost}) [{', '.join(gone)}]"
            )
        if len(losses) > cap:
            details.append(f"... and {len(losses) - cap} more files")
        rep.add(
            "REGRESSION",
            "control census",
            f"{len(losses)} file(s) lost controls "
            f"({base.total_controls()} -> {cur.total_controls()} tree wide)",
            details,
        )
    else:
        rep.add(
            "INFO",
            "control census",
            f"no file lost a control ({base.total_controls()} -> {cur.total_controls()} tree wide)",
        )

    gains = [
        (crec.n_controls - base.files[p].n_controls, p)
        for p, crec in sorted(cur.files.items())
        if p in base.files and crec.n_controls > base.files[p].n_controls
    ]
    new_files = sorted(set(cur.files) - set(base.files))
    if gains or new_files:
        rep.add(
            "INFO",
            "control census",
            f"{len(gains)} file(s) gained controls, {len(new_files)} new file(s)",
            [f"{p}: +{n}" for n, p in sorted(gains, reverse=True)[:cap]]
            + [f"{p}: new file" for p in new_files[:cap]],
        )


def check_id_census(base: Model, cur: Model, rep: Report, cap: int) -> None:
    """Name every control id that vanished, per file, with its type and line.

    Deliberately independent of the control count. A control can be swapped for
    a different one, leaving the count flat while a focusable id disappears, and
    the count check alone would call that clean.
    """
    _check_focusability(base, cur, rep)

    rows, focus_rows = [], []
    for path, brec in sorted(base.files.items()):
        crec = cur.files.get(path)
        gone = brec.ids() - (crec.ids() if crec else set())
        if not gone:
            continue
        by_id = {c.cid: c for c in brec.controls if c.cid}
        rows.append(f"{path}: {len(gone)} control id(s) vanished")
        for cid in sorted(gone, key=lambda s: (len(s), s))[:cap]:
            c = by_id[cid]
            focusable = c.ctype in FOCUSABLE_TYPES
            mark = "  <-- FOCUSABLE" if focusable else ""
            rows.append(f"      id={cid} type={c.ctype} was at line {c.line}{mark}")
            if focusable:
                focus_rows.append(f"{path}:{c.line} id={cid} type={c.ctype}")

    if focus_rows:
        rep.add(
            "REGRESSION",
            "control id census",
            f"{len(focus_rows)} FOCUSABLE control id(s) vanished; anything that "
            f"navigated to them now has nowhere to go",
            focus_rows[:cap],
        )
    if rows:
        rep.add(
            "REGRESSION" if not focus_rows else "INFO",
            "control id census",
            f"control ids vanished from {sum(1 for r in rows if not r.startswith(' '))} file(s)",
            rows,
        )

    b_ids, c_ids = base.all_control_ids(), cur.all_control_ids()
    rep.add(
        "INFO",
        "control id census",
        f"{len(b_ids)} distinct control ids at baseline, {len(c_ids)} now, "
        f"{len(b_ids - c_ids)} gone tree wide, {len(c_ids - b_ids)} added",
    )


def _check_focusability(base: Model, cur: Model, rep: Report) -> None:
    """A window that loses every focusable control still parses, still renders,
    and cannot be used. This is the exact shape of the SkinSettings.xml failure
    that motivated this harness."""
    dead, thin = [], []
    for path, brec in sorted(base.files.items()):
        crec = cur.files.get(path)
        if crec is None or brec.root_tag != "window":
            continue
        had = sum(1 for c in brec.controls if c.ctype in FOCUSABLE_TYPES)
        has = sum(1 for c in crec.controls if c.ctype in FOCUSABLE_TYPES)
        if had and not has:
            dead.append(f"{path}: had {had} focusable control(s), now 0")
        elif had and has < had:
            thin.append((had - has, f"{path}: {had} -> {has} focusable control(s)"))
    if dead:
        rep.add(
            "FATAL",
            "focusability",
            f"{len(dead)} window(s) lost every focusable control",
            dead,
        )
    if thin:
        thin.sort(reverse=True)
        rep.add(
            "ADVISORY",
            "focusability",
            f"{len(thin)} window(s) lost some focusable controls",
            [t[1] for t in thin],
        )


# --------------------------------------------------------------------------
# check 3: reference integrity
# --------------------------------------------------------------------------


def _unresolved(refs: list[Ref], defined: set[str]) -> dict[str, list[Ref]]:
    out: dict[str, list[Ref]] = defaultdict(list)
    for r in refs:
        if r.name not in defined:
            out[r.name].append(r)
    return out


def _delta_report(
    rep: Report, check: str, noun: str, base_bad: dict, cur_bad: dict, cap: int
) -> None:
    new = sorted(set(cur_bad) - set(base_bad))
    old = sorted(set(cur_bad) & set(base_bad))
    if new:
        rep.add(
            "REGRESSION",
            check,
            f"{len(new)} {noun} became unresolvable",
            [
                f"{name}  <- {', '.join(r.where() for r in cur_bad[name][:4])}"
                + (f" (+{len(cur_bad[name]) - 4} more)" if len(cur_bad[name]) > 4 else "")
                for name in new[:cap]
            ],
        )
    if old:
        rep.add(
            "ADVISORY",
            check,
            f"{len(old)} {noun} unresolvable at baseline too (inherited, not ours)",
            [f"{n}  <- {cur_bad[n][0].where()}" for n in old[:cap]],
        )
    if not new and not old:
        rep.add("INFO", check, f"every {noun} resolves")


def check_references(base: Model, cur: Model, rep: Report, cap: int) -> None:
    for check, attr, defs_attr, noun in (
        ("include refs", "include_refs", "include_defs", "<include> name(s)"),
        ("variable refs", "var_refs", "var_defs", "$VAR[] name(s)"),
        ("expression refs", "exp_refs", "exp_defs", "$EXP[] name(s)"),
    ):
        bb = _unresolved(getattr(base, attr), set(getattr(base, defs_attr)))
        cb = _unresolved(getattr(cur, attr), set(getattr(cur, defs_attr)))
        _delta_report(rep, check, noun, bb, cb, cap)

    _check_include_files(base, cur, rep, cap)
    _check_font_refs(base, cur, rep, cap)
    _check_textures(base, cur, rep, cap)


def _check_include_files(base: Model, cur: Model, rep: Report, cap: int) -> None:
    def bad(m: Model):
        out = defaultdict(list)
        for r in m.include_file_refs:
            if r.name in GENERATED_INCLUDE_FILES:
                continue
            if f"xml/{r.name}" not in m.asset_paths:
                out[r.name].append(r)
        return out

    _delta_report(rep, "include file refs", "<include file=> target(s)", bad(base), bad(cur), cap)


def _font_ids(m: Model) -> set[str]:
    ids: set[str] = set()
    for table in m.fontsets.values():
        ids |= set(table)
    return ids


def _check_font_refs(base: Model, cur: Model, rep: Report, cap: int) -> None:
    """A <font> id that is not in Font.xml does not error. Kodi silently falls
    back to font13 for the lifetime of the skin, so nothing on screen says so."""
    bb = _unresolved(base.font_refs, _font_ids(base))
    cb = _unresolved(cur.font_refs, _font_ids(cur))
    _delta_report(rep, "font refs", "<font> id(s)", bb, cb, cap)

    _check_fontset_parity(base, cur, rep, cap)


def _check_fontset_parity(base: Model, cur: Model, rep: Report, cap: int) -> None:
    """An id defined in some fontsets but not others breaks only for users who
    switched fontset, which is why it survives every screenshot.

    Ids missing from EVERY fontset are excluded here; those are already the
    'font refs' finding above and reporting them twice makes the second one
    look like a different, larger problem than it is.
    """
    used = {r.name for r in cur.font_refs}
    everywhere = _font_ids(cur)
    partial = used & everywhere
    rows = []
    for set_id, table in sorted(cur.fontsets.items()):
        missing = sorted(partial - set(table))
        if not missing:
            continue
        was = sorted(partial - set(base.fontsets.get(set_id, {})))
        new = sorted(set(missing) - set(was))
        rows.append(
            f"fontset '{set_id}': {len(missing)} used id(s) absent ({len(new)} newly absent)"
        )
        rows.extend(f"      {n}{'  <-- NEW' if n in new else ''}" for n in missing[:cap])
    if rows:
        severity = "REGRESSION" if any("<-- NEW" in r for r in rows) else "ADVISORY"
        rep.add(
            severity,
            "fontset parity",
            "fontset(s) do not define every id the markup uses; those fall back "
            "to font13 when that fontset is selected",
            rows,
        )
    else:
        rep.add("INFO", "fontset parity", "every fontset defines every id the markup uses")


def _texture_candidates(val: str) -> list[str] | None:
    """Normalise a texture value to skin relative paths, or None if it cannot
    be checked statically."""
    v = val.strip().strip('"')
    if not v or v == "-" or "$" in v or v.startswith(("http://", "https://")):
        return None
    if v.startswith("special://skin/"):
        return [v[len("special://skin/") :]]
    if v.startswith("special://"):
        return None
    if "|" in v or v.endswith("/"):
        return None
    v = v.lstrip("./")
    return [f"media/{v}", v]


def _missing_textures(m: Model, kodi_media: set[str]) -> dict[str, list[Ref]]:
    lower_assets = {p.lower() for p in m.asset_paths}
    out: dict[str, list[Ref]] = defaultdict(list)
    for r in m.texture_refs:
        cands = _texture_candidates(r.name)
        if cands is None:
            continue
        if any(c.lower() in lower_assets for c in cands):
            continue
        # xbt entries are stored lower cased and relative to media/
        rel = cands[-1].lower()
        if rel in m.xbt_entries or rel in kodi_media:
            continue
        out[r.name].append(r)
    return out


def _check_textures(base: Model, cur: Model, rep: Report, cap: int) -> None:
    kodi_media = _kodi_media_index()
    bb = _missing_textures(base, kodi_media)
    cb = _missing_textures(cur, kodi_media)
    _delta_report(rep, "texture refs", "texture path(s)", bb, cb, cap)


def _kodi_app_root() -> Path | None:
    for c in KODI_APP_CANDIDATES:
        p = Path(c).expanduser()
        if p.is_dir():
            return p
    return None


def _kodi_media_index() -> set[str]:
    root = _kodi_app_root()
    if root is None:
        return set()
    media = root / "media"
    if not media.is_dir():
        return set()
    return {str(p.relative_to(media)).lower() for p in media.rglob("*") if p.is_file()}


# --------------------------------------------------------------------------
# check 4 + 5: font binding and font id inventory
# --------------------------------------------------------------------------


def check_font_binding(base: Model, cur: Model, rep: Report, cap: int) -> None:
    kodi_fonts = _kodi_font_index()
    kodi_root = _kodi_app_root()

    def bad(m: Model):
        lower_assets = {p.lower() for p in m.asset_paths}
        out = defaultdict(list)
        for fname, path, line in m.font_files:
            if not fname or "$" in fname:
                continue
            rel = f"fonts/{fname}".lower()
            if rel in lower_assets or fname.lower() in kodi_fonts:
                continue
            out[fname].append(Ref(fname, path, line))
        return out

    bb, cb = bad(base), bad(cur)
    _delta_report(rep, "font binding", "<filename> binding(s)", bb, cb, cap)
    if kodi_root is None:
        rep.add(
            "ADVISORY",
            "font binding",
            "Kodi application bundle not found; fonts that ship with Kodi "
            "(arial.ttf) cannot be distinguished from missing ones",
            [f"looked in: {', '.join(KODI_APP_CANDIDATES)}"],
        )


def _kodi_font_index() -> set[str]:
    root = _kodi_app_root()
    if root is None:
        return set()
    fonts = root / "media" / "Fonts"
    if not fonts.is_dir():
        return set()
    return {p.name.lower() for p in fonts.iterdir() if p.is_file()}


def check_font_inventory(base: Model, cur: Model, rep: Report, cap: int) -> None:
    lost_sets = sorted(set(base.fontsets) - set(cur.fontsets))
    if lost_sets:
        rep.add(
            "REGRESSION",
            "font inventory",
            f"{len(lost_sets)} fontset(s) removed",
            [f"fontset '{s}' ({len(base.fontsets[s])} ids) gone" for s in lost_sets],
        )

    used = {r.name for r in cur.font_refs}
    rows, dead_rows = [], []
    for set_id in sorted(base.fontsets):
        btab = base.fontsets[set_id]
        ctab = cur.fontsets.get(set_id)
        if ctab is None:
            continue
        gone = sorted(set(btab) - set(ctab))
        if not gone:
            continue
        still_used = [g for g in gone if g in used]
        rows.append(f"fontset '{set_id}': {len(btab)} -> {len(ctab)} ids (-{len(gone)})")
        rows.extend(f"      removed: {g}" for g in gone[:cap])
        if still_used:
            dead_rows.append(
                f"fontset '{set_id}': {len(still_used)} removed id(s) STILL REFERENCED "
                f"by markup, each silently falls back to font13"
            )
            dead_rows.extend(f"      {g}" for g in still_used[:cap])
    if dead_rows:
        rep.add("REGRESSION", "font inventory", "font ids removed while still in use", dead_rows)
    if rows:
        rep.add(
            "ADVISORY" if not dead_rows else "INFO",
            "font inventory",
            "font ids removed from fontset(s)",
            rows,
        )
    if not rows and not lost_sets:
        b = sum(len(t) for t in base.fontsets.values())
        c = sum(len(t) for t in cur.fontsets.values())
        rep.add(
            "INFO",
            "font inventory",
            f"no font id removed ({b} -> {c} ids across {len(cur.fontsets)} fontset(s))",
        )

    added = []
    for set_id, ctab in sorted(cur.fontsets.items()):
        btab = base.fontsets.get(set_id, {})
        new = sorted(set(ctab) - set(btab))
        if new:
            added.append(f"fontset '{set_id}': +{len(new)} id(s): {', '.join(new[:cap])}")
    changed = _changed_font_defs(base, cur, cap)
    if added or changed:
        rep.add("INFO", "font inventory", "font table changes", added + changed)


def _changed_font_defs(base: Model, cur: Model, cap: int) -> list[str]:
    out = []
    for set_id, ctab in sorted(cur.fontsets.items()):
        btab = base.fontsets.get(set_id, {})
        rebound = [
            f"      {n}: {btab[n].summary()} -> {ctab[n].summary()}"
            for n in sorted(set(btab) & set(ctab))
            if (btab[n].filename, btab[n].style, btab[n].size)
            != (ctab[n].filename, ctab[n].style, ctab[n].size)
        ]
        if rebound:
            out.append(f"fontset '{set_id}': {len(rebound)} id(s) redefined")
            out.extend(rebound[:cap])
    return out


def check_font_weight_parity(base: Model, cur: Model, rep: Report, cap: int) -> None:
    """Did a font id get thinned in one fontset but left heavy in the others?

    HEURISTIC, and labelled as one. Weight is inferred from the face name and
    the <style> tag, so a face whose name does not say 'bold' is invisible to
    it. It exists because a thinning pass naturally edits the Default fontset,
    which is the only one anyone looks at, while Arial, Arial Unicode MS and
    Economica keep the heavy binding. Nobody switches fontset during QA, so no
    screenshot ever shows it.
    """
    if len(cur.fontsets) < 2:
        return
    rows = []
    for fid in sorted(_font_ids(cur)):
        present = {s: t[fid] for s, t in cur.fontsets.items() if fid in t}
        if len(present) < 2:
            continue
        heavy = {s for s, fd in present.items() if fd.heavy}
        if not heavy or len(heavy) == len(present):
            continue  # consistent across every fontset that defines it
        # `present` is keyed by FONTSET id, so the membership test here is
        # `s in present`, not `fid in present`. It read `fid in present` until
        # 2026-08-08, which asked whether a font id was one of the fontset
        # NAMES: always false. `was` was therefore always empty, `newly` was
        # always true, and this check could only ever emit REGRESSION, never
        # the ADVISORY the code below plainly intends. MEASURED: comparing a
        # pristine checkout of HEAD against HEAD, a diff with nothing in it at
        # all, reported 18 ids "caused by the current change" with <-- NEW on
        # every one. A gate that is red on an empty diff blames whatever change
        # happens to be in flight, which is worse than no gate: it trains
        # everyone to run it with --accept.
        was = {s for s, t in base.fontsets.items() if fid in t and t[fid].heavy and s in present}
        newly = len(was) != len(heavy)
        rows.append(
            f"{fid}: heavy in {sorted(heavy)}, light in "
            f"{sorted(set(present) - heavy)}{'   <-- NEW' if newly else ''}"
        )
    if not rows:
        rep.add("INFO", "font weight parity", "every shared font id has a consistent weight")
        return
    new_rows = [r for r in rows if "<-- NEW" in r]
    rep.add(
        "REGRESSION" if new_rows else "ADVISORY",
        "font weight parity",
        f"{len(rows)} font id(s) have inconsistent weight across fontsets "
        f"({len(new_rows)} caused by the current change); heuristic, see docstring",
        rows[:cap],
    )


def check_font_dupes(base: Model, cur: Model, rep: Report, cap: int) -> None:
    """Two <font> entries with the same <name> in one fontset. The later wins
    and the earlier is dead markup, which is easy to create when merging."""
    new = [d for d in cur.font_dupes if d[0] not in {b[0] for b in base.font_dupes}]
    if new:
        rep.add(
            "REGRESSION",
            "font duplicates",
            f"{len(new)} duplicate <name> entrie(s) inside a fontset",
            [f"{key} redefined at {path}:{line}" for key, path, line in new[:cap]],
        )
    elif cur.font_dupes:
        rep.add(
            "ADVISORY",
            "font duplicates",
            f"{len(cur.font_dupes)} duplicate <name> entrie(s), inherited",
            [f"{k} at {p}:{n}" for k, p, n in cur.font_dupes[:cap]],
        )


# --------------------------------------------------------------------------
# check 6: orphan hunt in reverse
# --------------------------------------------------------------------------


def check_orphans(base: Model, cur: Model, rep: Report, cap: int) -> None:
    """Controls that point at a control id which no longer exists.

    Scope is TREE WIDE, not per file, and that is deliberate. The reference
    that the previous failure left behind (Includes.xml:47 -> button 6131) sits
    in a different file from the control it names, so a per-file check would
    have called it broken at baseline too and the delta would have hidden it.
    """
    b_ids, c_ids = base.all_control_ids(), cur.all_control_ids()

    def dangling(refs: list[Ref], ids: set[str]):
        out = defaultdict(list)
        for r in refs:
            if r.name not in ids:
                out[r.name].append(r)
        return out

    for check, attr in (("nav orphans", "nav_refs"), ("HasFocus orphans", "hasfocus_refs")):
        bb = dangling(getattr(base, attr), b_ids)
        cb = dangling(getattr(cur, attr), c_ids)
        new = sorted(set(cb) - set(bb), key=lambda s: (len(s), s))
        if new:
            details = []
            for cid in new[:cap]:
                owner = _who_defined(base, cid)
                details.append(
                    f"id {cid} referenced {len(cb[cid])}x but no longer exists "
                    f"(was defined at {owner})"
                )
                details.extend(f"      referenced from {r.where()}" for r in cb[cid][:6])
            rep.add(
                "REGRESSION",
                check,
                f"{len(new)} control id(s) newly dangling",
                details,
            )
        stale = sorted(set(cb) & set(bb))
        if stale:
            rep.add(
                "ADVISORY",
                check,
                f"{len(stale)} id(s) dangling at baseline too (inherited)",
                [f"id {s} <- {cb[s][0].where()}" for s in stale[:cap]],
            )
        if not new and not stale:
            rep.add("INFO", check, "every navigation target resolves")


def _who_defined(base: Model, cid: str) -> str:
    for path, rec in sorted(base.files.items()):
        for c in rec.controls:
            if c.cid == cid:
                return f"{path}:{c.line} type={c.ctype}"
    return "nowhere in the baseline either"


# --------------------------------------------------------------------------
# parse sanity (not one of the six, but free and it gates the rest)
# --------------------------------------------------------------------------


def check_parse(base: Model, cur: Model, rep: Report, cap: int) -> None:
    bad = [(p, r.parse_error) for p, r in sorted(cur.files.items()) if r.parse_error]
    if bad:
        rep.add(
            "FATAL",
            "xml parse",
            f"{len(bad)} file(s) do not parse; every other check below is unreliable for them",
            [f"{p}: {e}" for p, e in bad[:cap]],
        )
    else:
        rep.add("INFO", "xml parse", f"all {len(cur.files)} parsed files are well formed")
    gone = sorted(set(base.files) - set(cur.files))
    if gone:
        rep.add("REGRESSION", "xml parse", f"{len(gone)} markup file(s) deleted", gone[:cap])


# --------------------------------------------------------------------------
# output
# --------------------------------------------------------------------------

_ORDER = {s: i for i, s in enumerate(SEVERITIES)}


def render(rep: Report, base: Model, cur: Model, out) -> None:
    findings = sorted(rep.findings, key=lambda f: (_ORDER[f.severity], f.check))
    counts = Counter(f.severity for f in findings)
    print("=" * 78, file=out)
    print(f"skin structural verification   baseline {base.label}  ->  {cur.label}", file=out)
    print(
        f"  {len(cur.files)} markup files, {cur.total_controls()} controls, "
        f"{len(cur.all_control_ids())} distinct control ids",
        file=out,
    )
    print(
        "  " + "   ".join(f"{s}: {counts.get(s, 0)}" for s in SEVERITIES),
        file=out,
    )
    print("=" * 78, file=out)
    for f in findings:
        if f.severity == "INFO" and not f.details:
            print(f"\n[{f.severity:10}] {f.check}: {f.summary}", file=out)
            continue
        print(f"\n[{f.severity:10}] {f.check}: {f.summary}", file=out)
        for d in f.details:
            print(f"    {d}", file=out)
    print(
        "\n"
        + (
            "FAIL: structural regressions found" if rep.failed else "PASS: no structural regression"
        ),
        file=out,
    )


def dump_census(base: Model, cur: Model, out) -> None:
    """Per-file control census, biggest first, with the baseline delta."""
    print(f"{'file':52} {'ctrls':>6} {'delta':>6} {'focus':>6}  top types", file=out)
    print("-" * 110, file=out)
    rows = sorted(cur.files.items(), key=lambda kv: -kv[1].n_controls)
    for path, rec in rows:
        if not rec.n_controls:
            continue
        brec = base.files.get(path)
        delta = rec.n_controls - (brec.n_controls if brec else 0)
        focus = sum(1 for c in rec.controls if c.ctype in FOCUSABLE_TYPES)
        top = ", ".join(f"{t}:{n}" for t, n in rec.type_counts().most_common(4))
        flag = "" if delta == 0 else f"{delta:+d}"
        print(f"{path:52} {rec.n_controls:6} {flag:>6} {focus:6}  {top}", file=out)
    print("-" * 110, file=out)
    print(
        f"{'TOTAL':52} {cur.total_controls():6} {cur.total_controls() - base.total_controls():+6d}",
        file=out,
    )


def to_json(rep: Report, base: Model, cur: Model) -> dict:
    return {
        "baseline": base.label,
        "current": cur.label,
        "totals": {
            "files": len(cur.files),
            "controls": cur.total_controls(),
            "control_ids": len(cur.all_control_ids()),
            "baseline_controls": base.total_controls(),
        },
        "failed": rep.failed,
        "findings": [
            {
                "severity": f.severity,
                "check": f.check,
                "summary": f.summary,
                "details": f.details,
            }
            for f in rep.findings
        ],
    }


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--baseline", default=DEFAULT_BASELINE, help="git ref to compare against")
    ap.add_argument(
        "--skin", default=None, help=f"path to the skin root (default: repo/{SKIN_SUBDIR})"
    )
    ap.add_argument("--prefix", default=SKIN_SUBDIR, help="path of the skin inside the repo")
    ap.add_argument("--max", type=int, default=25, dest="cap", help="max example lines per finding")
    ap.add_argument("--json", default=None, help="also write findings as JSON here")
    ap.add_argument("--quiet", action="store_true", help="suppress INFO findings")
    ap.add_argument(
        "--accept",
        default="",
        help="comma separated check names to demote to ADVISORY, for findings "
        "that are a deliberate decision rather than a defect. The finding is "
        "still printed in full; it just stops failing the run. Example: "
        "--accept 'font weight parity'",
    )
    ap.add_argument(
        "--census",
        action="store_true",
        help="dump the per-file control census as a table and exit; useful "
        "before a slimming pass to see the shape of what you are about to cut",
    )
    args = ap.parse_args(argv)

    here = Path(__file__).resolve()
    try:
        repo = Path(_run(["git", "rev-parse", "--show-toplevel"], here.parent).strip())
    except subprocess.CalledProcessError:
        print("not inside a git repository", file=sys.stderr)
        return 2

    skin_root = Path(args.skin).resolve() if args.skin else repo / args.prefix
    if not skin_root.is_dir():
        print(f"skin root not found: {skin_root}", file=sys.stderr)
        return 2

    try:
        base = load_baseline(repo, args.baseline, args.prefix)
    except subprocess.CalledProcessError as exc:
        print(f"cannot read baseline {args.baseline}: {exc}", file=sys.stderr)
        return 2
    cur = load_working(skin_root, "working tree")

    if args.census:
        dump_census(base, cur, sys.stdout)
        return 0

    rep = Report()
    check_parse(base, cur, rep, args.cap)
    check_id_census(base, cur, rep, args.cap)
    check_control_census(base, cur, rep, args.cap)
    check_orphans(base, cur, rep, args.cap)
    check_references(base, cur, rep, args.cap)
    check_font_binding(base, cur, rep, args.cap)
    check_font_inventory(base, cur, rep, args.cap)
    check_font_dupes(base, cur, rep, args.cap)
    check_font_weight_parity(base, cur, rep, args.cap)

    accepted = {a.strip().lower() for a in args.accept.split(",") if a.strip()}
    for f in rep.findings:
        if f.check.lower() in accepted and f.fails:
            f.severity = "ADVISORY"
            f.summary += "   [ACCEPTED: deliberate, not failing the run]"

    if args.quiet:
        rep.findings = [f for f in rep.findings if f.severity != "INFO"]
    render(rep, base, cur, sys.stdout)
    if args.json:
        Path(args.json).write_text(json.dumps(to_json(rep, base, cur), indent=2))
    return 1 if rep.failed else 0


if __name__ == "__main__":
    sys.exit(main())
