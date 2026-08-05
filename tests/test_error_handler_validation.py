# -*- coding: utf-8 -*-
"""RequestValidationError 必须落成 422，即使 validator 抛的是 ValueError。

踩过：`pydantic` 把 `field_validator` 抛出的 `ValueError` 原样放进
`exc.errors()[i]["ctx"]["error"]`——那是**物件**不是字串。旧版 handler 直接把
`exc.errors()` 塞进 `JSONResponse`，序列化失败后被 general handler 接成 500，
于是任何走 `field_validator` 的欄位都拿不到该有的 422。

实际发现路径：`POST /api/v1/analysis/market-review` 传 `region=eu`（上游 v3.29
新增的 `region` 是这条链上第一个会抛 `ValueError` 的 validator），文件明写应回
4xx，实际回 500。这个测试盯的是 handler 本身，所以任何未来新增的 validator 都
被一起保护。
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, field_validator

from api.middlewares.error_handler import add_error_handlers


def _build_app() -> FastAPI:
    app = FastAPI()
    add_error_handlers(app)

    class Payload(BaseModel):
        region: str

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


def test_value_error_from_field_validator_returns_422_not_500():
    client = TestClient(_build_app(), raise_server_exceptions=False)

    response = client.post("/probe", json={"region": "eu"})

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["error"] == "validation_error"
    # detail 必须是可序列化的结构，且保住 validator 的讯息（排障要靠它）。
    assert isinstance(body["detail"], list) and body["detail"]
    assert "region 包含非法值：eu" in str(body["detail"])


def test_valid_payload_still_passes_through():
    client = TestClient(_build_app(), raise_server_exceptions=False)

    response = client.post("/probe", json={"region": "ok"})

    assert response.status_code == 200
    assert response.json() == {"region": "ok"}
