"""网表的解析与合法性校验。

输入是 JSON 风格的元件字典列表，输出是校验通过的 Circuit 对象。
所有非法情况在此阶段以 CircuitError 干净地抛出：绝不崩溃，也绝不静默丢弃元件。

符号约定（直流与瞬态共用同一份定义，保证两种分析不打架）：
- 每个元件连接两个节点 [a, b]；
- 二端元件电压定义为 v = v(a) - v(b)，电流正方向为从 a 经元件流向 b；
- 电压源 a 为正极、b 为负极；
- 电流源的电流经源从 a 流向 b（即向 b 注入、从 a 抽出）；
- 电容初始条件为 t=0 时的 v(a)-v(b)，电感初始条件为 t=0 时 a→b 的电流。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .errors import CircuitError, ErrorCode

GROUND_NAMES = ("0", "gnd")

_ELEMENT_TYPES = {
    "resistor": "resistor", "r": "resistor",
    "capacitor": "capacitor", "c": "capacitor",
    "inductor": "inductor", "l": "inductor",
    "voltage_source": "voltage_source", "v": "voltage_source",
    "current_source": "current_source", "i": "current_source",
}


@dataclass(frozen=True)
class Resistor:
    name: str
    a: str
    b: str
    resistance: float  # 欧姆


@dataclass(frozen=True)
class Capacitor:
    name: str
    a: str
    b: str
    capacitance: float  # 法拉
    v0: float = 0.0     # 初始电压 v(a)-v(b)，伏特


@dataclass(frozen=True)
class Inductor:
    name: str
    a: str
    b: str
    inductance: float  # 亨利
    i0: float = 0.0    # 初始电流 a→b，安培


@dataclass(frozen=True)
class VoltageSource:
    name: str
    a: str  # 正极
    b: str  # 负极
    voltage: float  # 伏特


@dataclass(frozen=True)
class CurrentSource:
    name: str
    a: str
    b: str
    current: float  # 安培，经源从 a 流向 b


@dataclass(frozen=True)
class Circuit:
    """校验通过的网表：元件按类型分组，节点按出现顺序排列。"""

    resistors: tuple[Resistor, ...]
    capacitors: tuple[Capacitor, ...]
    inductors: tuple[Inductor, ...]
    voltage_sources: tuple[VoltageSource, ...]
    current_sources: tuple[CurrentSource, ...]
    nodes: tuple[str, ...]  # 非地节点，按出现顺序
    ground: str             # 接地参考节点名（"0" 或 "gnd"）


def _is_finite_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def parse_netlist(elements: list[dict]) -> Circuit:
    """解析并校验元件字典列表，返回 Circuit；任何非法情况抛 CircuitError。"""
    if not elements:
        raise CircuitError(ErrorCode.EMPTY_NETLIST, "网表为空：至少需要一个元件")

    seen_names: set[str] = set()
    resistors: list[Resistor] = []
    capacitors: list[Capacitor] = []
    inductors: list[Inductor] = []
    voltage_sources: list[VoltageSource] = []
    current_sources: list[CurrentSource] = []
    node_order: list[str] = []
    node_seen: set[str] = set()

    def register(node: str) -> None:
        if node not in node_seen:
            node_seen.add(node)
            node_order.append(node)

    for raw in elements:
        name = raw.get("name")
        if not isinstance(name, str) or not name:
            raise CircuitError(ErrorCode.MALFORMED_REQUEST, "每个元件都必须有非空的名称 name")
        if name in seen_names:
            raise CircuitError(ErrorCode.DUPLICATE_ELEMENT, f"元件名 {name!r} 重复，名称必须唯一")
        seen_names.add(name)

        etype = raw.get("type")
        canonical = _ELEMENT_TYPES.get(etype.lower()) if isinstance(etype, str) else None
        if canonical is None:
            raise CircuitError(
                ErrorCode.UNKNOWN_ELEMENT_TYPE,
                f"元件 {name} 的类型 {etype!r} 无法识别；支持的类型："
                "resistor / capacitor / inductor / voltage_source / current_source",
            )

        nodes = raw.get("nodes")
        if (
            not isinstance(nodes, (list, tuple))
            or len(nodes) != 2
            or any(not isinstance(n, str) or not n for n in nodes)
        ):
            raise CircuitError(
                ErrorCode.MISSING_NODE,
                f"元件 {name} 必须恰好提供两个非空节点名，形如 \"nodes\": [\"a\", \"b\"]",
            )
        a, b = nodes

        value = raw.get("value")
        initial = raw.get("initial")

        def require_value() -> float:
            if value is None:
                raise CircuitError(ErrorCode.MISSING_VALUE, f"元件 {name} 缺少参数值 value")
            if not _is_finite_number(value):
                raise CircuitError(ErrorCode.INVALID_VALUE, f"元件 {name} 的参数值 {value!r} 不是有限数值")
            return float(value)

        def read_initial() -> float:
            if initial is None:
                return 0.0
            if not _is_finite_number(initial):
                raise CircuitError(ErrorCode.INVALID_VALUE, f"元件 {name} 的初始条件 {initial!r} 不是有限数值")
            return float(initial)

        def forbid_initial() -> None:
            if initial is not None:
                raise CircuitError(
                    ErrorCode.UNSUPPORTED_INITIAL_CONDITION,
                    f"元件 {name}（{canonical}）不支持初始条件，只有电容和电感可以带 initial",
                )

        if canonical == "resistor":
            v = require_value()
            forbid_initial()
            if v == 0.0:
                raise CircuitError(
                    ErrorCode.ZERO_RESISTANCE,
                    f"电阻 {name} 阻值为零，会使方程组奇异；如需理想短路请改用 0V 电压源",
                )
            resistors.append(Resistor(name, a, b, v))
        elif canonical == "capacitor":
            v = require_value()
            if v <= 0.0:
                raise CircuitError(ErrorCode.INVALID_VALUE, f"电容 {name} 的容值必须为正，得到 {v}")
            capacitors.append(Capacitor(name, a, b, v, read_initial()))
        elif canonical == "inductor":
            v = require_value()
            if v <= 0.0:
                raise CircuitError(ErrorCode.INVALID_VALUE, f"电感 {name} 的感值必须为正，得到 {v}")
            inductors.append(Inductor(name, a, b, v, read_initial()))
        elif canonical == "voltage_source":
            v = require_value()
            forbid_initial()
            voltage_sources.append(VoltageSource(name, a, b, v))
        else:  # current_source
            v = require_value()
            forbid_initial()
            current_sources.append(CurrentSource(name, a, b, v))

        register(a)
        register(b)

    grounds = [g for g in GROUND_NAMES if g in node_seen]
    if not grounds:
        raise CircuitError(
            ErrorCode.NO_GROUND,
            "网表中没有接地参考节点：必须恰好有一个名为 \"0\" 或 \"gnd\" 的节点",
        )
    if len(grounds) > 1:
        raise CircuitError(
            ErrorCode.AMBIGUOUS_GROUND,
            "网表同时使用了 \"0\" 和 \"gnd\" 两个节点名；接地参考必须唯一，请统一为其中一个",
        )
    ground = grounds[0]

    # 理想电压源回路检测：对电压源两端做并查集，若某源两端已被其他源连通则构成回路，
    # 对应 KVL 约束互相矛盾或冗余，MNA 矩阵必然奇异。
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for vs in voltage_sources:
        ra, rb = find(vs.a), find(vs.b)
        if ra == rb:
            raise CircuitError(
                ErrorCode.VOLTAGE_SOURCE_LOOP,
                f"电压源 {vs.name} 与其他电压源构成回路（或两端短接），KVL 约束冲突，方程组奇异",
            )
        parent[ra] = rb

    nodes = tuple(n for n in node_order if n != ground)
    return Circuit(
        resistors=tuple(resistors),
        capacitors=tuple(capacitors),
        inductors=tuple(inductors),
        voltage_sources=tuple(voltage_sources),
        current_sources=tuple(current_sources),
        nodes=nodes,
        ground=ground,
    )
