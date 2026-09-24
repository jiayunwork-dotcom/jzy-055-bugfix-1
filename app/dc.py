"""直流工作点分析。

元件模型与瞬态共用同一份定义（见 netlist.py 的符号约定）：
- 电容视为开路（不产生任何矩阵贡献）；
- 电感视为短路（以 0V 电压源建模，其支路电流即电感电流）；
- 初始条件不参与直流工作点求解，仅在瞬态 t=0 时使用。
"""

from __future__ import annotations

from dataclasses import dataclass

from .mna import MnaBuilder
from .netlist import Circuit


@dataclass(frozen=True)
class DcResult:
    node_voltages: dict[str, float]           # 各节点对地电位（含接地节点 0.0）
    voltage_source_currents: dict[str, float]  # 各电压源支路电流（正方向：从正极流入）
    inductor_currents: dict[str, float]        # 各电感电流（正方向：a→b）


def solve_dc(circuit: Circuit) -> DcResult:
    """组装并求解直流工作点，矩阵奇异时抛 CircuitError(MATRIX_SINGULAR)。"""
    builder = MnaBuilder(circuit.nodes, circuit.ground)
    for r in circuit.resistors:
        builder.add_conductance(r.a, r.b, 1.0 / r.resistance)
    for cs in circuit.current_sources:
        builder.add_current_source(cs.a, cs.b, cs.current)
    for vs in circuit.voltage_sources:
        builder.add_voltage_source(vs.name, vs.a, vs.b, vs.voltage)
    for ind in circuit.inductors:  # 直流稳态下电感相当于短路
        builder.add_voltage_source(ind.name, ind.a, ind.b, 0.0)

    sol = builder.solve()
    vs_names = {vs.name for vs in circuit.voltage_sources}
    return DcResult(
        node_voltages=sol.node_voltages,
        voltage_source_currents={k: v for k, v in sol.branch_currents.items() if k in vs_names},
        inductor_currents={k: v for k, v in sol.branch_currents.items() if k not in vs_names},
    )
