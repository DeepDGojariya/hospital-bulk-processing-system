from app.services.csv_parser import parse_hospital_csv


def parse(text: str, max_rows: int = 20):
    return parse_hospital_csv(text.encode(), max_rows)


def messages(parsed) -> list[str]:
    return [error.message for error in parsed.errors]


def test_valid_file_returns_numbered_rows():
    parsed = parse("name,address,phone\nGeneral,1 Main St,555-1\nCity,2 Oak Ave,555-2\n")

    assert parsed.valid
    assert parsed.total_rows == 2
    assert [(r.row, r.name, r.address, r.phone) for r in parsed.rows] == [
        (1, "General", "1 Main St", "555-1"),
        (2, "City", "2 Oak Ave", "555-2"),
    ]


def test_phone_column_is_optional():
    parsed = parse("name,address\nGeneral,1 Main St\n")

    assert parsed.valid
    assert parsed.rows[0].phone is None


def test_empty_phone_becomes_none_and_short_rows_are_allowed():
    parsed = parse("name,address,phone\nGeneral,1 Main St,\nCity,2 Oak Ave\n")

    assert parsed.valid
    assert [r.phone for r in parsed.rows] == [None, None]


def test_header_is_trimmed_and_case_insensitive_and_values_are_trimmed():
    parsed = parse(" Name , ADDRESS ,Phone\n  General  , 1 Main St ,  555-1 \n")

    assert parsed.valid
    assert parsed.rows[0].name == "General"
    assert parsed.rows[0].address == "1 Main St"
    assert parsed.rows[0].phone == "555-1"


def test_blank_lines_are_skipped():
    parsed = parse("\nname,address\n\nGeneral,1 Main St\n , \nCity,2 Oak Ave\n\n")

    assert parsed.valid
    assert [r.row for r in parsed.rows] == [1, 2]


def test_excel_style_export_with_bom_crlf_and_quoted_commas():
    content = (
        b'\xef\xbb\xbfname,address,phone\r\n"St. Mary\'s, North","12 High St, Suite 4",555-1\r\n'
    )

    parsed = parse_hospital_csv(content, 20)

    assert parsed.valid
    assert parsed.rows[0].name == "St. Mary's, North"
    assert parsed.rows[0].address == "12 High St, Suite 4"


def test_empty_file_is_rejected():
    parsed = parse("")

    assert not parsed.valid
    assert messages(parsed) == ["CSV file is empty"]


def test_header_only_file_is_rejected():
    parsed = parse("name,address,phone\n")

    assert messages(parsed) == ["CSV has no data rows"]


def test_missing_required_column_is_rejected():
    parsed = parse("name,phone\nGeneral,555-1\n")

    assert messages(parsed) == ["Missing required column: address"]
    assert parsed.errors[0].field == "address"
    assert parsed.errors[0].row is None


def test_unknown_and_duplicate_columns_are_rejected():
    parsed = parse("name,address,name,email\nA,B,C,D\n")

    assert messages(parsed) == ["Duplicate column: name", "Unknown column: email"]


def test_semicolon_delimited_file_gets_a_clear_error():
    parsed = parse("name;address;phone\nGeneral;1 Main St;555-1\n")

    assert not parsed.valid
    assert "Missing required column: name" in messages(parsed)
    assert parsed.rows == []


def test_too_many_rows_is_rejected():
    body = "".join(f"H{i},{i} Main St\n" for i in range(21))

    parsed = parse("name,address\n" + body)

    assert messages(parsed) == ["CSV has 21 rows; the maximum is 20"]
    assert parsed.total_rows == 21


def test_exactly_max_rows_is_accepted():
    body = "".join(f"H{i},{i} Main St\n" for i in range(20))

    assert parse("name,address\n" + body).valid


def test_non_utf8_bytes_are_rejected():
    parsed = parse_hospital_csv(b"name,address\n\xff\xfe\x00bad\n", 20)

    assert messages(parsed) == ["File must be UTF-8 encoded text"]


def test_row_errors_are_all_reported_and_no_rows_returned():
    parsed = parse("name,address,phone\n,1 Main St,555\nCity,,\nOk,3 Elm St,\nA,B,C,D\n")

    assert [(e.row, e.field, e.message) for e in parsed.errors] == [
        (1, "name", "name is required"),
        (2, "address", "address is required"),
        (4, None, "Expected at most 3 columns, found 4"),
    ]
    assert parsed.rows == []
    assert parsed.total_rows == 4


def test_trailing_empty_columns_from_a_spreadsheet_export_are_ignored():
    parsed = parse("name,address,phone,,\nGeneral,1 Main St,555-1,,\nCity,2 Oak Ave,,,\n")

    assert parsed.valid
    assert [(r.name, r.phone) for r in parsed.rows] == [("General", "555-1"), ("City", None)]


def test_unterminated_quote_is_reported_as_invalid_csv():
    parsed = parse('name,address\n"General,1 Main St\nCity,2 Oak Ave\n')

    assert not parsed.valid
    assert messages(parsed)[0].startswith("File is not valid CSV")


def test_quote_character_inside_an_unquoted_value_is_kept():
    parsed = parse('name,address\nWard 5" North,1 Main St\n')

    assert parsed.valid
    assert parsed.rows[0].name == 'Ward 5" North'


def test_nul_bytes_are_rejected():
    parsed = parse_hospital_csv(b"name,address\nGen\x00eral,1 Main St\n", 20)

    assert messages(parsed) == ["File contains NUL bytes and is not a text CSV"]
