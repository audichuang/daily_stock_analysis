# -*- coding: utf-8 -*-
"""共用 validation handler 的回应契约：422、不外泄、不放大。

这个 handler 服务**所有**端点，所以它的错误回应形状是一条安全边界，不只是排障便利。
四件各自独立、都实际踩过或重现过的事：

1. `field_validator` 抛 `ValueError` 时必须回 422。pydantic 把原始 ValueError 物件
   放进 `ctx["error"]`，旧版直接塞进 `JSONResponse` 会序列化失败 → 被 general
   handler 接成 500。实际路径：`POST /api/v1/analysis/market-review` 传 `region=eu`，
   文件明写应回 4xx，实际回 500。
2. 回应不得回吐 `input`。`/api/v1/auth/login` 的 `password` 送成非字串时，
   旧版会在 422 里回吐明文密码。
3. 回应不得随输入放大。送 100,000 字元的非法值，旧版回应就是 100KB。
4. `ctx` 不得外流——它可能带任意物件，序列化行为不可控。

前端 `apps/dsa-web/src/api/error.ts::extractValidationDetail` 只读 `loc` 与 `msg`，
所以投影成 allowlist 不影响既有消费端。
"""
from typing import Dict

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field, create_model, field_validator

from api.middlewares.error_handler import add_error_handlers


def _build_app() -> FastAPI:
    app = FastAPI()
    add_error_handlers(app)

    class Payload(BaseModel):
        region: str = "ok"
        password: str = ""
        note: str = Field(default="", max_length=64)

        @field_validator("region")
        @classmethod
        def _reject(cls, value: str) -> str:
            if value != "ok":
                raise ValueError(f"region 包含非法值：{value}")
            return value

    @app.post("/probe")
    async def probe(payload: Payload):  # pragma: no cover - 只验错误路径
        return {"region": payload.region}

    return app


def _client() -> TestClient:
    return TestClient(_build_app(), raise_server_exceptions=False)


def test_value_error_from_field_validator_returns_422_not_500():
    response = _client().post("/probe", json={"region": "eu"})

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["error"] == "validation_error"
    # 保住 validator 的讯息——排障要靠它，投影不能把话也丢掉。
    assert isinstance(body["detail"], list) and body["detail"]
    assert "region 包含非法值：eu" in str(body["detail"])


def test_response_never_echoes_the_submitted_value():
    secret = "correct-horse-battery-staple"
    # 型别不符（送 list 给 str 栏位）是 pydantic 核心错误，会带 input；
    # `/api/v1/auth/login` 的 password 就是这个形状。
    response = _client().post("/probe", json={"password": [secret]})

    assert response.status_code == 422
    assert secret not in response.text
    assert "input" not in response.text


def test_response_does_not_amplify_with_input_size():
    oversized = "x" * 100_000
    response = _client().post("/probe", json={"region": oversized})

    assert response.status_code == 422
    # 旧版回应 ≈ 100KB（原样回吐）。新版只带 type/loc/msg，与输入大小无关。
    assert len(response.content) < 2_000, f"回应被输入放大到 {len(response.content)} bytes"
    assert oversized not in response.text


def test_detail_items_expose_only_the_allowlisted_fields():
    response = _client().post("/probe", json={"region": "eu"})

    body = response.json()
    for item in body["detail"]:
        assert set(item) == {"type", "loc", "msg"}, item
        assert isinstance(item["loc"], list)
        assert all(isinstance(segment, str) for segment in item["loc"])


def test_multiple_errors_are_capped():
    """真的造出 60 笔错误——旧版只造了 3 笔，拿掉实作的上限也照样绿。"""
    app = FastAPI()
    add_error_handlers(app)

    fields = {f"f{i}": (int, ...) for i in range(60)}
    Wide = create_model("Wide", **fields)

    @app.post("/wide")
    async def wide(body: Wide):  # pragma: no cover - 只验错误路径
        return {"ok": True}

    client = TestClient(app, raise_server_exceptions=False)
    response = client.post("/wide", json={f"f{i}": "not-an-int" for i in range(60)})

    assert response.status_code == 422
    assert len(response.json()["detail"]) == 20, "60 笔错误必须被截到上限"


def test_invalid_mapping_key_does_not_leak_through_loc():
    """`loc` 也承载使用者输入：mapping 栏位的非法 key 会被 pydantic 原样放进 loc。

    只截 `msg` 不截 `loc`，等于把回吐与放大的路径从值搬到键。
    """
    app = FastAPI()
    add_error_handlers(app)

    class Mapped(BaseModel):
        counts: Dict[int, int]

    @app.post("/mapped")
    async def mapped(body: Mapped):  # pragma: no cover - 只验错误路径
        return {"ok": True}

    oversized_key = "k" * 100_000
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post("/mapped", json={"counts": {oversized_key: 1}})

    assert response.status_code == 422
    assert oversized_key not in response.text
    assert len(response.content) < 2_000, f"回应被 loc 放大到 {len(response.content)} bytes"


def test_valid_payload_still_passes_through():
    response = _client().post("/probe", json={"region": "ok"})

    assert response.status_code == 200
    assert response.json() == {"region": "ok"}
