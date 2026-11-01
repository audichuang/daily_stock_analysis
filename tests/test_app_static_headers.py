# -*- coding: utf-8 -*-
"""Response compression and cache headers set up by ``api.app.create_app``.

Covers GZip for large responses, SSE streams staying uncompressed (so they
are never buffered), long-lived caching for content-hashed assets only,
no-store for index.html, and the one-hour stock index cache.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from api import app as app_module
from api.app import create_app

_LARGE_JS = "console.log('ok');\n" * 200  # ~3.8KB, above the 1KB gzip threshold
_IMMUTABLE = "public, max-age=31536000, immutable"


def _build_static_dir(tmp_path: Path) -> Path:
    static_dir = tmp_path / "static"
    assets_dir = static_dir / "assets"
    assets_dir.mkdir(parents=True)
    (assets_dir / "index-AbC12345.js").write_text(_LARGE_JS, encoding="utf-8")
    (assets_dir / "index-AbC12345.css").write_text("body{color:#fff}", encoding="utf-8")
    (assets_dir / "logo.js").write_text("// logo", encoding="utf-8")
    (static_dir / "index.html").write_text(
        "<!doctype html><html><head>"
        '<script type="module" crossorigin src="/assets/index-AbC12345.js"></script>'
        '<link rel="stylesheet" crossorigin href="/assets/index-AbC12345.css">'
        '</head><body><div id="root"></div></body></html>',
        encoding="utf-8",
    )
    return static_dir


def test_large_asset_is_gzipped_when_client_accepts_it(tmp_path: Path) -> None:
    client = TestClient(create_app(static_dir=_build_static_dir(tmp_path)))

    response = client.get(
        "/assets/index-AbC12345.js",
        headers={"Accept-Encoding": "gzip"},
    )

    assert response.status_code == 200
    assert response.headers.get("content-encoding") == "gzip"
    # httpx transparently decodes, so the body must round-trip intact.
    assert response.text == _LARGE_JS


def test_event_stream_response_is_not_compressed(tmp_path: Path) -> None:
    # No index.html here, so the SPA catch-all is not registered and the
    # probe route below is reachable.
    app = create_app(static_dir=tmp_path / "no-frontend")
    chunk = "data: " + ("x" * 2048) + "\n\n"

    async def _events():
        yield chunk
        yield chunk

    @app.get("/__test__/sse")
    async def _sse() -> StreamingResponse:
        return StreamingResponse(_events(), media_type="text/event-stream")

    client = TestClient(app)
    response = client.get("/__test__/sse", headers={"Accept-Encoding": "gzip"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "content-encoding" not in response.headers
    assert response.text == chunk * 2


def test_hashed_assets_are_immutable_but_unhashed_are_not(tmp_path: Path) -> None:
    client = TestClient(create_app(static_dir=_build_static_dir(tmp_path)))

    hashed_js = client.get("/assets/index-AbC12345.js")
    hashed_css = client.get("/assets/index-AbC12345.css")
    plain_js = client.get("/assets/logo.js")

    assert hashed_js.status_code == 200
    assert hashed_js.headers["cache-control"] == _IMMUTABLE
    assert hashed_css.headers["cache-control"] == _IMMUTABLE

    assert plain_js.status_code == 200
    assert "immutable" not in plain_js.headers.get("cache-control", "")


def test_index_html_remains_no_store(tmp_path: Path) -> None:
    client = TestClient(create_app(static_dir=_build_static_dir(tmp_path)))

    for path in ("/", "/index.html", "/analysis/history"):
        response = client.get(path, headers={"Accept-Encoding": "gzip"})
        assert response.status_code == 200
        assert response.headers["cache-control"] == (
            "no-store, no-cache, must-revalidate, max-age=0"
        )


def test_stock_index_is_cached_for_one_hour(tmp_path: Path) -> None:
    static_dir = _build_static_dir(tmp_path)
    index_path = static_dir / "stocks.index.json"
    index_path.write_text(
        json.dumps([["2330.TW", "2330", "台積電", "taijidian", "tjd", [], "TW", "stock", True, 100]],
                   ensure_ascii=False),
        encoding="utf-8",
    )
    missing_cache = tmp_path / "cache" / "stocks.index.json"
    missing_bundled = tmp_path / "bundled" / "stocks.index.json"

    client = TestClient(create_app(static_dir=static_dir))
    with patch.object(app_module, "get_remote_stock_index_cache_path", return_value=missing_cache), \
         patch.object(app_module, "_bundled_stock_index_path", return_value=missing_bundled), \
         patch.object(app_module, "_schedule_stock_index_background_refresh"):
        response = client.get("/stocks.index.json")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=3600"
