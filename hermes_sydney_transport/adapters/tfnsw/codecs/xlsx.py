"""The sole bounded XLSX/XML grammar for TfNSW adapters."""

from __future__ import annotations

import re
import zipfile
from collections.abc import Iterator
from pathlib import Path
from xml.etree import ElementTree

from pydantic import BaseModel, ConfigDict, Field

from ....models.errors import DomainError

_SHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_COLUMN_RE = re.compile(r"^([A-Z]+)")


class XlsxSpec(BaseModel):
    """Declarative workbook shape and zip-bomb limits."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    sheet_path: str = Field(pattern=r"^xl/worksheets/[A-Za-z0-9_.-]+\.xml$")
    required_headers: frozenset[str] = Field(min_length=1, max_length=40)
    max_rows: int = Field(ge=1, le=100_000)
    max_field_chars: int = Field(default=8_192, ge=1, le=65_536)
    max_files: int = Field(default=64, ge=2, le=1_000)
    max_entry_bytes: int = Field(default=8 * 1024 * 1024, ge=1_024)
    max_compression_ratio: int = Field(default=200, ge=1, le=1_000)


def named_rows(path: Path, spec: XlsxSpec) -> Iterator[dict[str, str]]:
    """Yield rows keyed by validated header names rather than cell coordinates."""

    try:
        with zipfile.ZipFile(path) as archive:
            _validate(archive, spec)
            shared = _shared_strings(archive, spec.max_field_chars)
            raw_rows = _worksheet_rows(archive, spec.sheet_path, shared, spec)
            header = next(raw_rows)
            if not spec.required_headers.issubset(header.values()):
                raise ValueError("workbook headers are incomplete")
            by_name = {name: column for column, name in header.items()}
            for row in raw_rows:
                yield {
                    name: row[column]
                    for name, column in by_name.items()
                    if column in row
                }
    except (
        ElementTree.ParseError,
        IndexError,
        KeyError,
        OSError,
        StopIteration,
        ValueError,
        zipfile.BadZipFile,
    ) as exc:
        raise DomainError(
            "static_data_invalid", "TfNSW XLSX workbook is invalid."
        ) from exc


def _validate(archive: zipfile.ZipFile, spec: XlsxSpec) -> None:
    infos = archive.infolist()
    if len(infos) > spec.max_files:
        raise ValueError("workbook contains too many files")
    names = {item.filename for item in infos}
    if not {"xl/sharedStrings.xml", spec.sheet_path}.issubset(names):
        raise ValueError("workbook is missing required XML")
    for item in infos:
        if item.filename.startswith("/") or ".." in Path(item.filename).parts:
            raise ValueError("workbook contains an unsafe path")
        if item.file_size > spec.max_entry_bytes:
            raise ValueError("workbook entry is oversized")
        if item.file_size / max(item.compress_size, 1) > spec.max_compression_ratio:
            raise ValueError("workbook compression ratio is unsafe")


def _shared_strings(archive: zipfile.ZipFile, max_chars: int) -> tuple[str, ...]:
    root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    return tuple(
        "".join(node.text or "" for node in item.iter(f"{{{_SHEET_NS}}}t"))[:max_chars]
        for item in root.findall(f"{{{_SHEET_NS}}}si")
    )


def _worksheet_rows(
    archive: zipfile.ZipFile,
    name: str,
    shared: tuple[str, ...],
    spec: XlsxSpec,
) -> Iterator[dict[str, str]]:
    root = ElementTree.fromstring(archive.read(name))
    for index, row in enumerate(root.iter(f"{{{_SHEET_NS}}}row")):
        if index > spec.max_rows:
            raise ValueError("workbook row limit exceeded")
        values: dict[str, str] = {}
        for cell in row.findall(f"{{{_SHEET_NS}}}c"):
            match = _COLUMN_RE.match(cell.attrib.get("r", ""))
            value = cell.find(f"{{{_SHEET_NS}}}v")
            if match is None or value is None or value.text is None:
                continue
            text = value.text
            if cell.attrib.get("t") == "s":
                text = shared[int(text)]
            values[match.group(1)] = text[: spec.max_field_chars]
        yield values
