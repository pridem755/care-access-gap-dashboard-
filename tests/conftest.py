"""Shared test helpers."""
import struct
import zipfile

import pytest

SHAPEFILE_PARTS = (".shp", ".shx", ".dbf", ".prj")


def dbf_bytes(fields: list[tuple[str, int]], rows: list[list[str]], deleted=frozenset()) -> bytes:
    """Build a minimal dBASE III table with text fields; rows in `deleted` are flagged '*'."""
    header_len = 32 + 32 * len(fields) + 1
    record_len = 1 + sum(width for _, width in fields)
    header = struct.pack("<BBBBIHH20x", 3, 124, 1, 1, len(rows), header_len, record_len)
    descriptors = b"".join(
        name.encode().ljust(11, b"\0") + b"C" + bytes(4) + bytes([width, 0]) + bytes(14)
        for name, width in fields
    )
    records = b"".join(
        (b"*" if i in deleted else b" ")
        + b"".join(str(v).encode().ljust(w) for v, (_, w) in zip(row, fields))
        for i, row in enumerate(rows)
    )
    return header + descriptors + b"\r" + records + b"\x1a"


@pytest.fixture
def make_shapefile_zip():
    """Return a function that writes a shapefile ZIP with the given attribute rows."""
    def make(path, fields, rows, parts=SHAPEFILE_PARTS, deleted=frozenset()):
        with zipfile.ZipFile(path, "w") as archive:
            for ext in parts:
                content = dbf_bytes(fields, rows, deleted) if ext == ".dbf" else b"x"
                archive.writestr(f"cb_county{ext}", content)
        return path
    return make
