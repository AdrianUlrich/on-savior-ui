"""File operations on save folders: rename, delete, archive.

These are the only functions in the package that write to the saves folder.
Each one validates that its target really is a save directly inside the saves
root, works through a temporary file where it can, and leaves the original
untouched if anything fails.

The game stores a save's name in three places — the folder name, the
``<name>.zip`` filename, and ``strName`` in both the outer and the zipped copy
of ``saveInfo.json`` — so renaming has to rewrite the archive. Members are
copied through a fresh handle and the result is CRC-checked before it replaces
the original.
"""

from __future__ import annotations

import re
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .catalog import SaveRef, read_ref

#: Rejected outright: path separators, NTFS-illegal characters, control codes.
_BAD_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_STRNAME = re.compile(rb'("strName"\s*:\s*)"(?:[^"\\]|\\.)*"')


class ManageError(RuntimeError):
    """A save operation was refused or failed."""


def validate_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise ManageError("name cannot be empty")
    if len(cleaned) > 100:
        raise ManageError("name is too long (100 characters max)")
    if _BAD_NAME.search(cleaned):
        raise ManageError(r'name cannot contain < > : " / \ | ? * or control characters')
    if cleaned in (".", "..") or cleaned.endswith("."):
        raise ManageError("name cannot be a path fragment")
    return cleaned


def _check_save(root: Path, ref: SaveRef) -> Path:
    folder = ref.folder.resolve()
    if folder.parent != root.resolve():
        raise ManageError(f"{ref.name} is not directly inside {root}")
    if not (folder / "saveInfo.json").is_file():
        raise ManageError(f"{ref.name} has no saveInfo.json — refusing to touch it")
    return folder


def _patch_strname(blob: bytes, new_name: str) -> bytes:
    """Replace the first ``strName`` value, leaving the rest byte-for-byte."""
    escaped = new_name.replace("\\", "\\\\").replace('"', '\\"')
    replacement = rb'\1"' + escaped.encode("utf-8") + b'"'
    patched, count = _STRNAME.subn(replacement, blob, count=1)
    if not count:
        raise ManageError("saveInfo.json has no strName field")
    return patched


def rename(root: Path, ref: SaveRef, new_name: str) -> SaveRef:
    """Rename a save so the game still loads it. Returns the updated ref."""
    new_name = validate_name(new_name)
    folder = _check_save(root, ref)
    if new_name == ref.name:
        return ref

    target = root / new_name
    if target.exists():
        raise ManageError(f"a save named {new_name!r} already exists")

    old_zip = folder / f"{ref.name}.zip"
    if old_zip.is_file():
        tmp_zip = folder / f".{new_name}.rename.zip"
        try:
            with zipfile.ZipFile(old_zip) as src:
                members = src.infolist()
                with zipfile.ZipFile(
                    tmp_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=1
                ) as dst:
                    for member in members:
                        data = src.read(member)
                        if member.filename == "saveInfo.json":
                            data = _patch_strname(data, new_name)
                        info = zipfile.ZipInfo(member.filename, member.date_time)
                        info.compress_type = member.compress_type
                        info.external_attr = member.external_attr
                        dst.writestr(info, data)
            with zipfile.ZipFile(tmp_zip) as check:
                if check.testzip() is not None or len(check.infolist()) != len(members):
                    raise ManageError("rewritten archive failed its integrity check")
            tmp_zip.replace(old_zip)
        except ManageError:
            tmp_zip.unlink(missing_ok=True)
            raise
        except Exception as exc:
            tmp_zip.unlink(missing_ok=True)
            raise ManageError(f"could not rewrite {old_zip.name}: {exc}") from exc

    meta = folder / "saveInfo.json"
    meta.write_bytes(_patch_strname(meta.read_bytes(), new_name))

    folder.rename(target)
    moved_zip = target / f"{ref.name}.zip"
    if moved_zip.is_file():
        moved_zip.rename(target / f"{new_name}.zip")

    updated = read_ref(target)
    if updated is None:
        raise ManageError(f"{new_name} is unreadable after renaming")
    return updated


@dataclass
class Removal:
    name: str
    freed_bytes: int
    trashed_to: str | None = None

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "freed_bytes": self.freed_bytes,
            "trashed_to": self.trashed_to,
        }


def delete(root: Path, ref: SaveRef, trash_dir: Path | None = None) -> Removal:
    """Delete a save, or move it aside when a trash folder is configured."""
    folder = _check_save(root, ref)
    freed = ref.size_bytes
    if trash_dir is not None:
        trash_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = trash_dir / f"{ref.name} ({stamp})"
        shutil.move(str(folder), str(target))
        return Removal(name=ref.name, freed_bytes=freed, trashed_to=str(target))
    shutil.rmtree(folder)
    return Removal(name=ref.name, freed_bytes=freed)


def archive(root: Path, ref: SaveRef, dest_dir: Path) -> Path:
    """Copy a save folder into ``dest_dir``, keeping its name unique."""
    folder = _check_save(root, ref)
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / ref.name
    if target.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = dest_dir / f"{ref.name} ({stamp})"
    shutil.copytree(folder, target)
    return target
