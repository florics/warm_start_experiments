"""Shared transparent compression helpers for LP, BAS and EBF files.

Reading supports plain files, gzip (.gz), and ZIP (.zip). ZIP archives must
contain exactly one non-directory member. Writing supports plain files and
.gzip only; ZIP writing is deliberately not supported.
"""
from __future__ import annotations

from contextlib import contextmanager
import gzip
import io
from pathlib import Path
import shutil
import tempfile
import zipfile


class CompressionIOError(ValueError):
    pass


def compression_suffix(path: str | Path) -> str:
    suffix = Path(path).suffix.lower()
    return suffix if suffix in {".gz", ".zip"} else ""


def logical_path(path: str | Path) -> Path:
    path = Path(path)
    if compression_suffix(path):
        return path.with_suffix("")
    return path


def logical_suffix(path: str | Path) -> str:
    return logical_path(path).suffix.lower()


def has_logical_suffix(path: str | Path, suffix: str) -> bool:
    """Return whether an input represents the requested logical file type.

    For ZIP input, the archive name itself does not need to contain the logical
    extension: ``model.zip`` containing exactly one ``model.lp`` member is
    accepted just like ``model.lp.zip``.
    """
    path = Path(path)
    wanted = suffix.lower()
    if path.suffix.lower() == ".zip" and path.is_file():
        try:
            with zipfile.ZipFile(path, "r") as zf:
                member = _single_zip_member(zf, path)
                return Path(member).suffix.lower() == wanted
        except (OSError, zipfile.BadZipFile, CompressionIOError):
            return False
    return logical_suffix(path) == wanted


def validate_input_suffix(path: str | Path, suffix: str) -> None:
    if not has_logical_suffix(path, suffix):
        raise ValueError(
            f"Expected {suffix}, {suffix}.gz, or a single-member .zip containing {suffix}; got: {path}"
        )


def validate_output_suffix(path: str | Path, suffix: str) -> None:
    path = Path(path)
    if path.suffix.lower() == ".zip":
        raise ValueError("ZIP output is not supported; use plain or .gz output")
    if not has_logical_suffix(path, suffix):
        raise ValueError(f"Expected {suffix} or {suffix}.gz output, got: {path}")


def _single_zip_member(zf: zipfile.ZipFile, archive: Path) -> str:
    members = [info.filename for info in zf.infolist() if not info.is_dir()]
    if len(members) != 1:
        raise CompressionIOError(
            f"ZIP archive must contain exactly one file, got {len(members)}: {archive}"
        )
    return members[0]


@contextmanager
def open_text_read(path: str | Path, *, encoding: str = "utf-8-sig"):
    """Open a text file for reading, transparently handling .gz/.zip."""
    path = Path(path)
    comp = compression_suffix(path)
    if comp == ".gz":
        with gzip.open(path, "rt", encoding=encoding, newline="") as f:
            yield f
        return
    if comp == ".zip":
        with zipfile.ZipFile(path, "r") as zf:
            member = _single_zip_member(zf, path)
            with zf.open(member, "r") as raw:
                with io.TextIOWrapper(raw, encoding=encoding, newline="") as f:
                    yield f
        return
    with path.open("r", encoding=encoding, newline="") as f:
        yield f


@contextmanager
def open_text_write(path: str | Path, *, encoding: str = "utf-8", newline: str = ""):
    """Open a text file for writing. Plain and .gz are supported."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    comp = compression_suffix(path)
    if comp == ".zip":
        raise CompressionIOError("ZIP output is not supported; use .gz")
    if comp == ".gz":
        with gzip.open(path, "wt", encoding=encoding, newline=newline) as f:
            yield f
        return
    with path.open("w", encoding=encoding, newline=newline) as f:
        yield f


@contextmanager
def materialize_input(path: str | Path, *, expected_suffix: str | None = None):
    """Yield a real uncompressed path suitable for solver file APIs.

    Plain inputs are yielded directly. Compressed files are decompressed into
    a temporary file with the logical suffix so solvers still recognize the
    format from the filename.
    """
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    if expected_suffix is not None:
        validate_input_suffix(path, expected_suffix)
    comp = compression_suffix(path)
    if not comp:
        yield path
        return

    suffix = logical_suffix(path) or (expected_suffix or "")
    with tempfile.TemporaryDirectory(prefix="basis_tools_input_") as td:
        target = Path(td) / f"materialized{suffix}"
        if comp == ".gz":
            with gzip.open(path, "rb") as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
        else:
            with zipfile.ZipFile(path, "r") as zf:
                member = _single_zip_member(zf, path)
                if expected_suffix and Path(member).suffix.lower() != expected_suffix.lower():
                    raise CompressionIOError(
                        f"ZIP member {member!r} does not end in {expected_suffix}"
                    )
                with zf.open(member, "r") as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
        yield target


@contextmanager
def materialize_output(path: str | Path, *, expected_suffix: str | None = None):
    """Yield an uncompressed output path for solver APIs, gzip afterwards."""
    path = Path(path).expanduser().resolve()
    if expected_suffix is not None:
        validate_output_suffix(path, expected_suffix)
    path.parent.mkdir(parents=True, exist_ok=True)
    comp = compression_suffix(path)
    if comp == ".zip":
        raise CompressionIOError("ZIP output is not supported; use .gz")
    if comp != ".gz":
        yield path
        return

    suffix = logical_suffix(path) or (expected_suffix or "")
    with tempfile.TemporaryDirectory(prefix="basis_tools_output_") as td:
        temporary = Path(td) / f"solver_output{suffix}"
        yield temporary
        if not temporary.is_file():
            raise RuntimeError(
                f"Solver writer returned without creating temporary output {temporary}"
            )
        with temporary.open("rb") as src, gzip.open(path, "wb") as dst:
            shutil.copyfileobj(src, dst)


def output_path(base: str | Path, *, compress: bool) -> Path:
    path = Path(base)
    if compress and path.suffix.lower() != ".gz":
        return Path(str(path) + ".gz")
    return path
