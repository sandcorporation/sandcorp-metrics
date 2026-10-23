"""`GET /m.js`: 스니펫을 루트 경로에서 낸다(파일은 정적 파일 `metrics/m.js`와 같은 것)."""

from functools import cache
from pathlib import Path

from django.http import HttpRequest, HttpResponse
from django.views.decorators.http import require_safe

SNIPPET = Path(__file__).resolve().parent / "static" / "metrics" / "m.js"


@cache
def snippet_bytes() -> bytes:
    return SNIPPET.read_bytes()


@require_safe
def snippet(request: HttpRequest) -> HttpResponse:
    response = HttpResponse(snippet_bytes(), content_type="application/javascript; charset=utf-8")
    response["Cache-Control"] = "public, max-age=86400"
    response["Access-Control-Allow-Origin"] = "*"
    return response
