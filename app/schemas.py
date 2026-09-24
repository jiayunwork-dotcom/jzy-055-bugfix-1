"""HTTP 请求/响应的数据结构。

这里只描述接口形状；领域校验（元件类型、取值、接地、时间参数等）
全部在 netlist.py / transient.py 中以带错误码的 CircuitError 完成。
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ElementSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    type: str
    nodes: Optional[list[str]] = None
    value: Optional[float] = None
    initial: Optional[float] = None


class NetlistSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    elements: list[ElementSpec]


class DcRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    netlist: NetlistSpec


class TransientRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    netlist: NetlistSpec
    dt: Optional[float] = None
    tstop: Optional[float] = None


class DcResponse(BaseModel):
    success: bool
    node_voltages: dict[str, float]
    voltage_source_currents: dict[str, float]
    inductor_currents: dict[str, float]


class TransientResponse(BaseModel):
    success: bool
    integration: str
    dt: float
    tstop: float
    steps: int
    time: list[float]
    node_voltages: dict[str, list[float]]
    voltage_source_currents: dict[str, list[float]]
    inductor_currents: dict[str, list[float]]
