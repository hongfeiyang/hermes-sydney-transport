"""The sole bounded ZIP archive grammar for TfNSW adapters."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ....models.errors import DomainError

type ArchiveSource = bytes | Path


class ArchiveSpec(BaseModel):
    """Declarative limits for one trusted archive shape."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    required_files: frozenset[str] = Field(min_length=1, max_length=20)
    max_uncompressed_bytes: Mapping[str, int]
    max_compression_ratio: int = Field(ge=1, le=1_000)
    max_files: int = Field(default=128, ge=1, le=1_000)

    @model_validator(mode="after")
    def every_required_file_has_a_limit(self) -> ArchiveSpec:
        if self.required_files != self.max_uncompressed_bytes.keys():
            raise ValueError("every required archive file needs exactly one size limit")
        return self


@contextmanager
def open_archive(source: ArchiveSource, spec: ArchiveSpec) -> Iterator[zipfile.ZipFile]:
    """Open and validate a ZIP before any table parser sees its contents."""

    archive: zipfile.ZipFile | None = None
    try:
        archive = zipfile.ZipFile(
            io.BytesIO(source) if isinstance(source, bytes) else source
        )
        _validate(archive, spec)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        if archive is not None:
            archive.close()
        raise DomainError(
            "static_data_invalid",
            f"TfNSW returned an invalid or unsafe archive: {exc}",
        ) from exc
    try:
        yield archive
    finally:
        archive.close()


@contextmanager
def open_text_table(archive: zipfile.ZipFile, name: str) -> Iterator[io.TextIOWrapper]:
    """Expose one UTF-8 table while containing archive/decompression failures."""

    try:
        with (
            archive.open(name) as binary,
            io.TextIOWrapper(binary, encoding="utf-8-sig", newline="") as text,
        ):
            yield text
    except (KeyError, OSError, RuntimeError, UnicodeError, zipfile.BadZipFile) as exc:
        raise DomainError(
            "static_data_invalid", f"TfNSW archive table {name} could not be read."
        ) from exc


def _validate(archive: zipfile.ZipFile, spec: ArchiveSpec) -> None:
    infos = archive.infolist()
    if len(infos) > spec.max_files:
        raise ValueError("archive contains too many files")
    by_name: dict[str, list[zipfile.ZipInfo]] = {}
    for item in infos:
        if item.filename.startswith("/") or ".." in Path(item.filename).parts:
            raise ValueError("archive contains an unsafe path")
        by_name.setdefault(item.filename, []).append(item)
    if not spec.required_files.issubset(by_name):
        raise ValueError("archive is missing required files")
    for name in spec.required_files:
        matches = by_name[name]
        if len(matches) != 1:
            raise ValueError(f"archive contains duplicate {name}")
        item = matches[0]
        if item.file_size > spec.max_uncompressed_bytes[name]:
            raise ValueError(f"{name} exceeds expanded-size limit")
        if item.file_size / max(item.compress_size, 1) > spec.max_compression_ratio:
            raise ValueError(f"{name} has an unsafe compression ratio")
