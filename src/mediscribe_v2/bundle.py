"""Recording bundles: move processed or part-reviewed recordings between machines.

A bundle is a zip that mirrors the data folder for one or more recordings:

    mediscribe-bundle.json          manifest (optional on import)
    input/<name>.<ext>              original audio (playback, resume, re-run)
    intermediate/<name>/...         stage files and the editor overlay
    output/<name>/...               transcript, canonical evidence, review history

Run the pipeline on one machine, export a bundle, import it on another machine,
and review there; export again to continue the review somewhere else. A zip of
a whole data folder (optionally inside one top folder) imports the same way.
Only the standard library is used, so the CLI runs without the scribe env.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import IO, Iterable

from . import __version__
from .common import write_pipeline_state

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = PROJECT_ROOT / "data"
BUNDLE_FORMAT = "mediscribe-bundle"
BUNDLE_VERSION = 1
MANIFEST_NAME = "mediscribe-bundle.json"
AUDIO_EXTENSIONS = (".wav", ".m4a", ".mp3", ".flac", ".aac", ".ogg", ".webm", ".mp4")
SESSION_ROOTS = ("intermediate", "output")
# Only the prepare stage reads it, and it is the largest file by far.
SKIPPED_SUFFIXES = ("_source_pcm.wav",)
MAX_BUNDLE_BYTES = 16 * 1024**3
INTERRUPTED_STATES = {"running", "queued"}
IGNORED_PARTS = {"__MACOSX", ".DS_Store"}


class BundleError(ValueError):
    pass


class BundleConflictError(BundleError):
    def __init__(self, names: list[str]):
        self.names = names
        super().__init__(f"These recordings already exist: {', '.join(names)}.")


def check_name(name: str) -> str:
    if (not name.strip() or name.startswith(".") or "/" in name or "\\" in name
            or "\x00" in name or name in {".", ".."}):
        raise BundleError(f"Invalid recording or file name in bundle: {name!r}.")
    return name


def find_input_audio(data_root: Path, name: str) -> list[Path]:
    """Every input audio file whose stem is ``name`` (the WebUI's matching rule)."""
    input_root = data_root / "input"
    if not input_root.exists():
        return []
    return sorted(path for path in input_root.rglob("*")
                  if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS and path.stem == name)


def processed_names(data_root: Path) -> list[str]:
    names: set[str] = set()
    for root in SESSION_ROOTS:
        folder = data_root / root
        if folder.exists():
            names.update(path.name for path in folder.iterdir()
                         if path.is_dir() and not path.name.startswith("."))
    return sorted(names)


def _session_files(data_root: Path, name: str) -> list[tuple[str, Path]]:
    files: list[tuple[str, Path]] = []
    audio = find_input_audio(data_root, name)
    if audio:
        files.append((f"input/{audio[0].name}", audio[0]))
    for root in SESSION_ROOTS:
        folder = data_root / root / name
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            if path.is_file() and not path.name.startswith(".") and not path.name.endswith(SKIPPED_SUFFIXES):
                files.append((f"{root}/{name}/{path.name}", path))
    return files


def _read_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def export_bundle(data_root: Path, names: Iterable[str], target: Path | IO[bytes]) -> dict:
    """Write the named recordings into a bundle zip; return its manifest."""
    data_root = Path(data_root)
    entries: list[tuple[str, Path]] = []
    sessions = []
    for name in dict.fromkeys(names):
        files = _session_files(data_root, check_name(name))
        if not files:
            raise BundleError(f"No files found for recording {name!r}.")
        entries.extend(files)
        intermediate = data_root / "intermediate" / name
        sessions.append({
            "name": name,
            "input": next((path.name for arcname, path in files if arcname.startswith("input/")), None),
            "finished": bool(_read_json(intermediate / f"{name}_editor.json").get("finished")),
            "state": _read_json(intermediate / f"{name}_pipeline_state.json").get("state"),
        })
    if not sessions:
        raise BundleError("Select at least one recording to export.")
    manifest = {
        "format": BUNDLE_FORMAT,
        "version": BUNDLE_VERSION,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "mediscribe_version": __version__,
        "sessions": sessions,
    }
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2))
        for arcname, path in entries:
            # Audio is already compressed or does not deflate well.
            compress = zipfile.ZIP_STORED if path.suffix.lower() in AUDIO_EXTENSIONS else zipfile.ZIP_DEFLATED
            archive.write(path, arcname, compress_type=compress)
    return manifest


@dataclass
class ImportPlan:
    manifest: dict
    # recording name -> [(zip member, destination relative to the data folder)]
    sessions: dict[str, list[tuple[zipfile.ZipInfo, PurePosixPath]]] = field(default_factory=dict)
    ignored: int = 0

    def has_input(self, name: str) -> bool:
        return any(dest.parts[0] == "input" for _info, dest in self.sessions[name])


def plan_import(archive: zipfile.ZipFile) -> ImportPlan:
    members = []
    for info in archive.infolist():
        if "\\" in info.filename or "\x00" in info.filename:
            raise BundleError(f"Unsafe path in bundle: {info.filename!r}.")
        path = PurePosixPath(info.filename)
        if path.is_absolute() or ".." in path.parts:
            raise BundleError(f"Unsafe path in bundle: {info.filename!r}.")
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise BundleError(f"Bundle holds a symbolic link: {info.filename!r}.")
        if info.is_dir() or IGNORED_PARTS & set(path.parts):
            continue
        members.append((info, path.parts))

    # Accept a zipped data folder or bundle folder: drop one shared top folder.
    tops = {parts[0] for _info, parts in members if len(parts) > 1}
    if (len(tops) == 1 and all(len(parts) > 1 for _info, parts in members)
            and not tops & {"input", *SESSION_ROOTS}):
        members = [(info, parts[1:]) for info, parts in members]

    plan = ImportPlan(manifest={})
    seen: set[tuple[str, ...]] = set()
    for info, parts in members:
        if parts in seen:
            raise BundleError(f"Bundle holds {'/'.join(parts)} twice.")
        seen.add(parts)
        if parts == (MANIFEST_NAME,):
            try:
                plan.manifest = json.loads(archive.read(info))
            except ValueError as exc:
                raise BundleError(f"Bundle manifest is not valid JSON: {exc}") from exc
            if not isinstance(plan.manifest, dict):
                raise BundleError("Bundle manifest is not a JSON object.")
            continue
        if len(parts) == 2 and parts[0] == "input" and PurePosixPath(parts[1]).suffix.lower() in AUDIO_EXTENSIONS:
            name = check_name(PurePosixPath(parts[1]).stem)
        elif len(parts) == 3 and parts[0] in SESSION_ROOTS and not parts[2].startswith("."):
            name = check_name(parts[1])
            check_name(parts[2])
        else:
            plan.ignored += 1
            continue
        plan.sessions.setdefault(name, []).append((info, PurePosixPath(*parts)))

    if plan.manifest:
        if plan.manifest.get("format") != BUNDLE_FORMAT:
            raise BundleError("This zip is not a Mediscribe bundle.")
        version = plan.manifest.get("version")
        if not isinstance(version, int) or version > BUNDLE_VERSION:
            raise BundleError("This bundle comes from a newer Mediscribe. Update Mediscribe to import it.")
    if not plan.sessions:
        raise BundleError("No recordings found. A bundle holds input/, intermediate/<name>/ "
                          "or output/<name>/ folders.")
    return plan


def remove_session(data_root: Path, name: str, *, input_audio: bool) -> None:
    for root in SESSION_ROOTS:
        folder = data_root / root / name
        if folder.is_dir() and not folder.is_symlink():
            shutil.rmtree(folder)
        elif folder.exists() or folder.is_symlink():
            folder.unlink()
    if input_audio:
        for path in find_input_audio(data_root, name):
            path.unlink()


def _reset_interrupted_state(data_root: Path, name: str) -> None:
    """A bundle made mid-run says "running"; here nothing runs it any more."""
    state_path = data_root / "intermediate" / name / f"{name}_pipeline_state.json"
    state = _read_json(state_path)
    if state.get("state") in INTERRUPTED_STATES:
        write_pipeline_state(state_path, state="awaiting_resume", reason="imported",
                             message="The pipeline had not finished when this bundle was made.",
                             resumable_step=state.get("resumable_step"))


def import_bundle(data_root: Path, source: Path | IO[bytes], *, replace: bool = False,
                  busy: Iterable[str] = (), max_bytes: int = MAX_BUNDLE_BYTES) -> dict:
    """Unpack a bundle into the data folder.

    A recording that already exists here is a conflict unless ``replace`` is
    set; replacing removes its working files and output, and its input audio
    when the bundle brings its own. Names in ``busy`` (being processed) are
    refused. Files are unpacked to a staging folder first, so a bad bundle
    leaves nothing behind.
    """
    data_root = Path(data_root)
    try:
        with zipfile.ZipFile(source) as archive:
            plan = plan_import(archive)
            names = sorted(plan.sessions)
            busy_names = sorted(set(names) & set(busy))
            if busy_names:
                raise BundleError(f"Wait for processing to finish: {', '.join(busy_names)}.")
            conflicts = [
                name for name in names
                if any((data_root / root / name).exists() for root in SESSION_ROOTS)
                or (plan.has_input(name) and find_input_audio(data_root, name))
            ]
            if conflicts and not replace:
                raise BundleConflictError(conflicts)
            total = sum(info.file_size for members in plan.sessions.values() for info, _dest in members)
            if total > max_bytes:
                raise BundleError(f"Bundle unpacks to {total / 1024**3:.1f} GiB; "
                                  f"the limit is {max_bytes / 1024**3:.0f} GiB.")
            data_root.mkdir(parents=True, exist_ok=True)
            if total > shutil.disk_usage(data_root).free:
                raise BundleError("Not enough disk space to unpack this bundle.")

            staging = data_root / f".bundle-import-{uuid.uuid4().hex}"
            try:
                for members in plan.sessions.values():
                    for info, dest in members:
                        target = staging.joinpath(*dest.parts)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(info) as reader, target.open("xb") as writer:
                            shutil.copyfileobj(reader, writer, 1024 * 1024)
                for name in names:
                    if name in conflicts:
                        remove_session(data_root, name, input_audio=plan.has_input(name))
                    for info, dest in plan.sessions[name]:
                        if dest.parts[0] == "input":
                            (data_root / "input").mkdir(parents=True, exist_ok=True)
                            shutil.move(staging / dest, data_root / dest)
                    for root in SESSION_ROOTS:
                        if (staging / root / name).is_dir():
                            (data_root / root).mkdir(parents=True, exist_ok=True)
                            shutil.move(staging / root / name, data_root / root / name)
                    _reset_interrupted_state(data_root, name)
            finally:
                shutil.rmtree(staging, ignore_errors=True)
    except zipfile.BadZipFile as exc:
        raise BundleError(f"Not a valid zip file: {exc}") from exc
    return {
        "sessions": names,
        "replaced": conflicts,
        "files": sum(len(members) for members in plan.sessions.values()),
        "bytes": total,
        "ignored": plan.ignored,
    }


def main(argv: list[str] | None = None) -> None:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data-root", type=Path, default=DATA_ROOT,
                        help="Folder that holds input/, intermediate/ and output/ (default: data/).")
    parser = argparse.ArgumentParser(
        description="Move processed or part-reviewed recordings between machines as zip bundles.")
    commands = parser.add_subparsers(dest="command", required=True)
    export_cmd = commands.add_parser("export", parents=[common], help="Write recordings into a bundle.")
    export_cmd.add_argument("names", nargs="*", help="Recording names (input audio file stems).")
    export_cmd.add_argument("--all", action="store_true", help="Export every processed recording.")
    export_cmd.add_argument("-o", "--output", type=Path, required=True, help="Bundle zip to write.")
    import_cmd = commands.add_parser("import", parents=[common], help="Unpack a bundle into the data folder.")
    import_cmd.add_argument("bundle", type=Path, help="Bundle zip to read.")
    import_cmd.add_argument("--replace", action="store_true",
                            help="Overwrite recordings that already exist here, review edits included.")
    args = parser.parse_args(argv)

    try:
        if args.command == "export":
            names = processed_names(args.data_root) if args.all else args.names
            partial = args.output.with_name(f".{args.output.name}.part")
            try:
                manifest = export_bundle(args.data_root, names, partial)
                partial.replace(args.output)
            finally:
                partial.unlink(missing_ok=True)
            print(f"Wrote {len(manifest['sessions'])} recording(s) to {args.output}")
        else:
            result = import_bundle(args.data_root, args.bundle, replace=args.replace)
            print(f"Imported {len(result['sessions'])} recording(s): {', '.join(result['sessions'])}")
            if result["replaced"]:
                print(f"Replaced: {', '.join(result['replaced'])}")
    except BundleConflictError as exc:
        sys.exit(f"{exc} Pass --replace to overwrite them.")
    except BundleError as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
