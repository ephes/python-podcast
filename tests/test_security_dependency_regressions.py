"""Exercise real dependency boundaries needed by the October security stack."""

import base64
import bz2
import zlib
from io import BytesIO

import nbformat
import pytest
from django.core.files.images import ImageFile
from nbconvert import MarkdownExporter
from nbconvert.writers import FilesWriter
from PIL import Image, ImageOps
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView
from wagtail.images import get_image_model
from wagtail.models import Collection


@pytest.mark.parametrize("format_name", ["JPEG", "PNG", "WEBP", "TIFF", "GIF"])
def test_image_decode_and_thumbnail_round_trip(format_name):
    original = Image.new("RGB", (24, 16), (40, 80, 120))
    encoded = BytesIO()
    original.save(encoded, format=format_name)
    encoded.seek(0)
    with Image.open(encoded) as decoded:
        decoded.load()
        assert decoded.size == (24, 16)
        decoded.thumbnail((12, 12))
        assert decoded.size == (12, 8)
        thumbnail = BytesIO()
        decoded.convert("RGB").save(thumbnail, format="JPEG")
    with Image.open(BytesIO(thumbnail.getvalue())) as decoded_thumbnail:
        decoded_thumbnail.load()
        assert decoded_thumbnail.size == (12, 8)


def test_exif_orientation_is_applied_and_removed():
    original = Image.new("RGB", (24, 16), "red")
    exif = Image.Exif()
    exif[274] = 6  # Rotate 90 degrees clockwise.
    encoded = BytesIO()
    original.save(encoded, format="JPEG", exif=exif)
    with Image.open(BytesIO(encoded.getvalue())) as decoded:
        oriented = ImageOps.exif_transpose(decoded)
        assert oriented.size == (16, 24)
        assert 274 not in oriented.getexif()


@pytest.mark.django_db
def test_wagtail_willow_can_generate_a_cover_rendition():
    if not Collection.objects.exists():
        Collection.add_root(name="Root")
    encoded = BytesIO()
    Image.new("RGB", (24, 16), "red").save(encoded, format="JPEG")
    image = get_image_model().objects.create(
        title="Security stack rendition", file=ImageFile(BytesIO(encoded.getvalue()), name="security-stack.jpg")
    )
    rendition = image.get_rendition("fill-8x8|format-jpeg")
    assert (rendition.width, rendition.height) == (8, 8)
    with rendition.file.open("rb") as file, Image.open(file) as decoded:
        decoded.load()
        assert decoded.size == (8, 8)


class EchoJSON(APIView):
    authentication_classes = []
    permission_classes = []
    parser_classes = [JSONParser]

    def post(self, request):
        return Response(request.data)


@pytest.mark.parametrize("encoding,compress", [("bz2_codec", bz2.compress), ("zlib_codec", zlib.compress)])
def test_json_request_rejects_compressed_codec(encoding, compress):
    # Small harmless payload adapted from GHSA-3547-9m27-7rxg, not a memory bomb.
    request = APIRequestFactory().post(
        "/echo/", compress(b'{"text":"harmless"}'), content_type=f"application/json; charset={encoding}"
    )
    response = EchoJSON.as_view()(request)
    assert response.status_code == 400
    assert "Unsupported charset" in str(response.data["detail"])
    assert encoding in str(response.data["detail"])


@pytest.mark.parametrize(
    "body,charset,status",
    [(b'{"ok":true}', "utf-8", 200), ('{"ok":true}'.encode("utf-16"), "utf-16", 200), (b"{broken", "utf-8", 400)],
)
def test_json_request_text_charset_and_malformed_body(body, charset, status):
    request = APIRequestFactory().post("/echo/", body, content_type=f"application/json; charset={charset}")
    response = EchoJSON.as_view()(request)
    assert response.status_code == status
    if status == 200:
        assert response.data == {"ok": True}


def test_notebook_image_output_cannot_escape_export_directory(tmp_path):
    # GHSA-pjvx-prjx-h659: output metadata must not select a parent filename.
    image = BytesIO()
    Image.new("RGB", (1, 1), "red").save(image, format="PNG")
    output = nbformat.v4.new_output(
        "display_data",
        data={"image/png": base64.b64encode(image.getvalue()).decode()},
        metadata={"filename": "../escaped.png"},
    )
    notebook = nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell(outputs=[output])])
    text, resources = MarkdownExporter().from_notebook_node(notebook)
    build = tmp_path / "export"
    FilesWriter(build_directory=str(build)).write(text, resources, notebook_name="safe")
    assert not (tmp_path / "escaped.png").exists()
    assert (build / "escaped.png").read_bytes() == image.getvalue()
