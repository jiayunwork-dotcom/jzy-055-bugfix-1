"""修正节点分析（MNA）：矩阵组装与线性求解。

直流工作点与瞬态步进共用这一套组装原语，保证两种分析的元件方程一致：
- add_conductance：电导（电阻，以及储能元件的伴随电导）；
- add_current_source：独立电流源（以及伴随模型的等效电流源）；
- add_voltage_source：独立电压源（多引一个支路电流未知量，矩阵扩维）。

求解失败（矩阵奇异）时抛出带 MATRIX_SINGULAR 错误码的 CircuitError，
绝不返回 NaN 或无穷大。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .errors import CircuitError, ErrorCode


@dataclass(frozen=True)
class MnaSolution:
    node_voltages: dict[str, float]    # 含接地节点（恒为 0.0）
    branch_currents: dict[str, float]  # 各电压源支路电流，正方向：从正极流入电源

    def voltage(self, node: str) -> float:
        return self.node_voltages[node]


def _singular_error() -> CircuitError:
    return CircuitError(
        ErrorCode.MATRIX_SINGULAR,
        "系数矩阵奇异，无法求解：常见原因包括悬浮节点（某节点没有直流通路）、"
        "电压源/电感构成回路、或初始条件互相矛盾",
    )


class MnaBuilder:
    """逐步盖章（stamp）组装 MNA 方程 A·x = z 并求解。

    未知量排列：前 n 个为非地节点电压，后 m 个为电压源支路电流。
    """

    def __init__(self, nodes: tuple[str, ...] | list[str], ground: str):
        self._ground = ground
        self._nodes = list(nodes)
        self._index = {node: i for i, node in enumerate(self._nodes)}
        self._conductances: list[tuple[str, str, float]] = []
        self._current_sources: list[tuple[str, str, float]] = []
        self._voltage_sources: list[tuple[str, str, str, float]] = []

    def add_conductance(self, a: str, b: str, g: float) -> None:
        """在 a、b 之间并入电导 g（西门子）。"""
        self._conductances.append((a, b, g))

    def add_current_source(self, a: str, b: str, j: float) -> None:
        """电流源：电流 j 经源从 a 流向 b（向 b 注入、从 a 抽出）。"""
        self._current_sources.append((a, b, j))

    def add_voltage_source(self, name: str, a: str, b: str, e: float) -> None:
        """电压源：a 为正极、b 为负极，约束 v(a)-v(b)=e，支路电流正方向为从 a 流入。"""
        self._voltage_sources.append((name, a, b, e))

    def solve(self) -> MnaSolution:
        n = len(self._nodes)
        m = len(self._voltage_sources)
        size = n + m
        if size == 0:
            return MnaSolution(node_voltages={self._ground: 0.0}, branch_currents={})

        A = np.zeros((size, size))
        z = np.zeros(size)
        idx = self._index.get  # 接地节点不在索引中，返回 None

        for a, b, g in self._conductances:
            ia, ib = idx(a), idx(b)
            if ia is not None:
                A[ia, ia] += g
            if ib is not None:
                A[ib, ib] += g
            if ia is not None and ib is not None:
                A[ia, ib] -= g
                A[ib, ia] -= g

        for a, b, j in self._current_sources:
            ia, ib = idx(a), idx(b)
            if ia is not None:
                z[ia] -= j
            if ib is not None:
                z[ib] += j

        for k, (_name, a, b, e) in enumerate(self._voltage_sources):
            row = n + k
            ia, ib = idx(a), idx(b)
            if ia is not None:
                A[ia, row] += 1.0
                A[row, ia] += 1.0
            if ib is not None:
                A[ib, row] -= 1.0
                A[row, ib] -= 1.0
            z[row] = e

        try:
            x = np.linalg.solve(A, z)
        except np.linalg.LinAlgError as exc:
            raise _singular_error() from exc
        if not np.all(np.isfinite(x)):
            raise _singular_error()
        # 残差校验：近奇异矩阵可能不报错但解不可靠，一并判为奇异
        residual = A @ x - z
        scale = max(
            1.0,
            float(np.abs(z).max(initial=0.0)),
            float(np.abs(A).max(initial=0.0)) * float(np.abs(x).max(initial=0.0)),
        )
        if float(np.abs(residual).max(initial=0.0)) > 1e-6 * scale:
            raise _singular_error()

        node_voltages = {node: float(x[i]) for i, node in enumerate(self._nodes)}
        node_voltages[self._ground] = 0.0
        branch_currents = {
            name: float(x[n + k]) for k, (name, *_rest) in enumerate(self._voltage_sources)
        }
        return MnaSolution(node_voltages=node_voltages, branch_currents=branch_currents)
