import pytest
from PIL import Image

from app.engine.units import LengthUnit
from app.uploads.inspect import FileKind, UploadError, inspect_upload
from tests.uploads.fixtures import (
    blurred,
    dxf_bytes,
    encode,
    image_pdf,
    plan_image,
    rotated,
    text_pdf,
)

MB = 1_048_576


def inspect(filename: str, data: bytes, **kwargs):
    opts = {"max_bytes": 25 * MB, "max_pages": 50, "dwg_converter": None} | kwargs
    return inspect_upload(filename, data, **opts)


def codes(warnings) -> list[str]:
    return [w.code for w in warnings]


# --- PDF


def test_digital_pdf_multi_page_with_floor_guesses():
    result = inspect("plan.pdf", text_pdf(["GROUND FLOOR PLAN", "FIRST FLOOR PLAN", "SITE NOTES"]))
    assert result.kind == FileKind.PDF
    assert [p.floor_guess for p in result.pages] == ["Ground Floor", "First Floor", None]
    assert all(p.has_text for p in result.pages)
    assert all(p.thumbnail_png and p.thumbnail_png.startswith(b"\x89PNG") for p in result.pages)
    assert result.warnings == []


def test_scanned_pdf_warns_about_ocr_and_page_quality():
    result = inspect("scan.pdf", image_pdf([plan_image(), rotated(plan_image(), 4)]))
    assert codes(result.warnings) == ["no_text_layer"]
    assert "All pages" in result.warnings[0].message
    assert codes(result.pages[0].warnings) == []
    assert codes(result.pages[1].warnings) == ["skewed"]


def test_pdf_page_limit():
    with pytest.raises(UploadError, match="3 pages; the limit is 2"):
        inspect("plan.pdf", text_pdf(["a", "b", "c"]), max_pages=2)


def test_corrupt_pdf():
    with pytest.raises(UploadError, match="can't be opened"):
        inspect("plan.pdf", b"%PDF-1.4\nthis is not really a pdf")


# --- Images


def test_good_image_has_no_warnings():
    result = inspect("plan.png", encode(plan_image()))
    assert result.kind == FileKind.IMAGE
    assert result.content_type == "image/png"
    assert codes(result.pages[0].warnings) == []


@pytest.mark.parametrize(
    "image,expected",
    [
        (plan_image(700, 490), ["low_resolution"]),
        (blurred(plan_image(), 3), ["blurry"]),
        (rotated(plan_image(), -6), ["skewed"]),
        (Image.new("RGB", (1600, 1200), "white"), ["blank_or_faint"]),
    ],
)
def test_image_quality_warnings(image, expected):
    result = inspect("photo.jpg", encode(image, "JPEG"))
    assert codes(result.pages[0].warnings) == expected


def test_truncated_image_is_unreadable():
    data = encode(plan_image(), "PNG")
    with pytest.raises(UploadError, match="can't be opened"):
        inspect("plan.png", data[: len(data) // 2])


# --- DXF / DWG


def test_dxf_reads_units_text_and_draws_preview():
    result = inspect("plan.dxf", dxf_bytes())
    assert result.kind == FileKind.DXF
    assert result.detected_unit == LengthUnit.FT
    assert result.pages[0].has_text
    assert result.pages[0].thumbnail_png is not None
    assert result.warnings == []


def test_dxf_without_text_or_units_warns():
    result = inspect("plan.dxf", dxf_bytes(with_text=False, insunits=0))
    assert codes(result.warnings) == ["no_text", "units_unknown"]
    assert result.detected_unit is None


def test_dwg_without_converter_gives_guidance():
    with pytest.raises(UploadError, match="Export the drawing as DXF or PDF"):
        inspect("plan.dwg", b"AC1032" + b"\0" * 100)


# --- Validation


@pytest.mark.parametrize(
    "filename,data,status,message",
    [
        ("plan.docx", b"PK\x03\x04", 415, "not supported"),
        ("plan", b"%PDF-1.4", 415, "not supported"),
        ("plan.pdf", b"\x89PNG\r\n\x1a\n...", 415, "don't match its .pdf extension"),
        ("plan.png", b"%PDF-1.4", 415, "don't match its .png extension"),
        ("plan.dwg", b"not a dwg", 415, "don't match its .dwg extension"),
        ("plan.pdf", b"", 422, "empty"),
    ],
)
def test_type_validation(filename, data, status, message):
    with pytest.raises(UploadError, match=message) as exc:
        inspect(filename, data)
    assert exc.value.status_code == status


def test_size_limit():
    with pytest.raises(UploadError, match="limit is 1 MB") as exc:
        inspect("plan.pdf", b"%PDF-" + b"0" * (MB + 1), max_bytes=MB)
    assert exc.value.status_code == 413


def test_extension_is_case_insensitive():
    assert inspect("PLAN.PNG", encode(plan_image())).kind == FileKind.IMAGE
