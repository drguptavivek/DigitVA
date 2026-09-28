"""Read bounded CSV and XLSX import tables with the same cell validation."""

import csv
import io
import re
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile, ZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException


class TabularImportError(ValueError):
    """The uploaded table is malformed or contains unsafe values."""


def validate_xlsx(raw, *, max_rows, max_columns):
    """Reject oversized ZIP members and worksheet dimensions before workbook parsing.

    Limits bound decompression and row iteration for untrusted uploads. Malformed
    archives raise TabularImportError.
    """
    try:
        with ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) > 100 or sum(entry.file_size for entry in entries) > 50 * 1024 * 1024:
                raise TabularImportError("The XLSX workbook is too large or complex.")
            for entry in entries:
                if not re.fullmatch(r"xl/worksheets/sheet\d+\.xml", entry.filename):
                    continue
                with archive.open(entry) as sheet:
                    prefix = sheet.read(8192)
                dimension = re.search(rb'<dimension\s+ref="([A-Z]+\d+)(?::([A-Z]+\d+))?"', prefix)
                if dimension:
                    last = dimension.group(2) or dimension.group(1)
                    match = re.fullmatch(rb"([A-Z]+)(\d+)", last)
                    column = 0
                    for letter in match.group(1):
                        column = column * 26 + letter - ord("A") + 1
                    if int(match.group(2)) > max_rows * 2 + 1 or column > max_columns + 16:
                        raise TabularImportError("The XLSX worksheet dimensions exceed the import limit.")
    except (BadZipFile, OSError, EOFError, RuntimeError) as exc:
        raise TabularImportError("The XLSX workbook could not be read.") from exc


def _value(value, column, row_number):
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    value = value.strip()
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise TabularImportError(f"Row {row_number}: control characters are not allowed.")
    if value and value[0] in "=+-@":
        if column not in {"latitude", "longitude"} or not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", value):
            raise TabularImportError(f"Row {row_number}: formula-like values are not allowed.")
    return value or None


def parse_rows(raw_rows, expected_headers, *, max_rows, require_all=False):
    try:
        header = next(raw_rows)
    except StopIteration as exc:
        raise TabularImportError("The file is empty.") from exc
    names = [str(cell or "").strip().lower() for cell in header]
    while names and not names[-1]:
        names.pop()
    allowed = set(expected_headers)
    if (not names or len(names) != len(set(names)) or
            any(name not in allowed for name in names) or
            (require_all and set(names) != allowed)):
        raise TabularImportError("Headers must be: " + ",".join(expected_headers))
    rows = []
    for row_number, cells in enumerate(raw_rows, start=2):
        if row_number > max_rows * 2 + 1:
            raise TabularImportError(f"The file exceeds the {max_rows}-row limit.")
        cells = list(cells)
        if any(_value(cell, "", row_number) is not None for cell in cells[len(names):]):
            raise TabularImportError(f"Row {row_number}: unexpected populated column.")
        row = {name: _value(cells[index] if index < len(cells) else None, name, row_number)
               for index, name in enumerate(names)}
        if not any(value is not None for value in row.values()):
            continue
        row["_line_number"] = row_number
        rows.append(row)
        if len(rows) > max_rows:
            raise TabularImportError(f"The file exceeds the {max_rows}-row limit.")
    return rows


def parse_table(stream, filename, expected_headers, *, max_bytes, max_rows, require_all=False):
    """Parse the first worksheet or CSV; reject excess data and unsafe cells.

    The caller supplies the allowed headers and upload limits. Returns stripped
    rows with physical row numbers; malformed files raise TabularImportError.
    """
    raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise TabularImportError(f"The file exceeds the {max_bytes // (1024 * 1024)} MB limit.")
    if filename.lower().endswith(".xlsx"):
        try:
            validate_xlsx(raw, max_rows=max_rows, max_columns=len(expected_headers))
            workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=False)
            try:
                sheet = workbook.worksheets[0]
                if ((sheet.max_row or 0) > max_rows * 2 + 1 or
                        (sheet.max_column or 0) > len(expected_headers) + 16):
                    raise TabularImportError("The XLSX worksheet dimensions exceed the import limit.")
                return parse_rows(sheet.iter_rows(values_only=True), expected_headers,
                                  max_rows=max_rows, require_all=require_all)
            finally:
                workbook.close()
        except TabularImportError:
            raise
        except (OSError, ValueError, KeyError, IndexError, BadZipFile, InvalidFileException,
                ParseError) as exc:
            raise TabularImportError("The XLSX workbook could not be read.") from exc
    if not filename.lower().endswith(".csv"):
        raise TabularImportError("Upload a CSV or XLSX file.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode("cp1252")
        except UnicodeDecodeError as exc:
            raise TabularImportError("The CSV encoding could not be read.") from exc
    if text.startswith("sep=,\r\n") or text.startswith("sep=,\n"):
        text, delimiter = text.split("\n", 1)[1], ","
    elif text.startswith("sep=;\r\n") or text.startswith("sep=;\n"):
        text, delimiter = text.split("\n", 1)[1], ";"
    else:
        first = text.splitlines()[0] if text else ""
        delimiter = ";" if first.count(";") > first.count(",") else ","
    try:
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
        return parse_rows(iter(reader), expected_headers, max_rows=max_rows,
                          require_all=require_all)
    except csv.Error as exc:
        raise TabularImportError("The CSV file is malformed.") from exc
