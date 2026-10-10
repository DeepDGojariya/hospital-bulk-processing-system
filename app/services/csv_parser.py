"""Parse and validate an uploaded hospital CSV. Pure: no I/O, no HTTP."""

import csv
import io
from dataclasses import dataclass

from app.schemas import CsvError, HospitalRow

REQUIRED_COLUMNS = ("name", "address")
ALLOWED_COLUMNS = (*REQUIRED_COLUMNS, "phone")


@dataclass(frozen=True)
class ParsedCsv:
    rows: list[HospitalRow]
    errors: list[CsvError]
    total_rows: int

    @property
    def valid(self) -> bool:
        return not self.errors


def _file_error(message: str, total_rows: int = 0) -> ParsedCsv:
    return ParsedCsv(rows=[], errors=[CsvError(message=message)], total_rows=total_rows)


def _header_errors(header: list[str]) -> list[CsvError]:
    errors = [
        CsvError(field=column, message=f"Duplicate column: {column}")
        for column in dict.fromkeys(header)
        if header.count(column) > 1
    ]
    errors += [
        CsvError(field=column, message=f"Missing required column: {column}")
        for column in REQUIRED_COLUMNS
        if column not in header
    ]
    errors += [
        CsvError(field=column, message=f"Unknown column: {column}")
        for column in dict.fromkeys(header)
        if column not in ALLOWED_COLUMNS
    ]
    return errors


def _without_trailing_blanks(cells: list[str]) -> list[str]:
    """Drop empty cells at the end of a record; spreadsheets often export them."""
    end = len(cells)
    while end and not cells[end - 1].strip():
        end -= 1
    return cells[:end]


def parse_hospital_csv(content: bytes, max_rows: int) -> ParsedCsv:
    """Return validated rows, or every validation error found in the file."""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return _file_error("File must be UTF-8 encoded text")
    if "\x00" in text:
        return _file_error("File contains NUL bytes and is not a text CSV")

    try:
        records = [
            trimmed
            # strict: an unterminated quote is an error, not a field that
            # silently swallows the rest of the file.
            for record in csv.reader(io.StringIO(text, newline=""), strict=True)
            if (trimmed := _without_trailing_blanks(record))
        ]
    except csv.Error as exc:
        return _file_error(f"File is not valid CSV: {exc}")

    if not records:
        return _file_error("CSV file is empty")

    header = [cell.strip().lower() for cell in records[0]]
    data = records[1:]

    header_errors = _header_errors(header)
    if header_errors:
        return ParsedCsv(rows=[], errors=header_errors, total_rows=len(data))
    if not data:
        return _file_error("CSV has no data rows")
    if len(data) > max_rows:
        return _file_error(
            f"CSV has {len(data)} rows; the maximum is {max_rows}", total_rows=len(data)
        )

    rows: list[HospitalRow] = []
    errors: list[CsvError] = []
    for number, cells in enumerate(data, start=1):
        if len(cells) > len(header):
            errors.append(
                CsvError(
                    row=number,
                    message=f"Expected at most {len(header)} columns, found {len(cells)}",
                )
            )
            continue

        values = dict(zip(header, (cell.strip() for cell in cells), strict=False))
        missing = [column for column in REQUIRED_COLUMNS if not values.get(column)]
        errors += [
            CsvError(row=number, field=column, message=f"{column} is required")
            for column in missing
        ]
        if not missing:
            rows.append(
                HospitalRow(
                    row=number,
                    name=values["name"],
                    address=values["address"],
                    phone=values.get("phone") or None,
                )
            )

    return ParsedCsv(rows=[] if errors else rows, errors=errors, total_rows=len(data))
