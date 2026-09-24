"""瞬态分析：定步长隐式积分 + 储能元件伴随模型。

积分方法全程固定为 **后向欧拉（Backward Euler）**，不混用其他格式。
对连接在 a、b 之间、电压 v = v(a)-v(b)、电流正方向 a→b 的储能元件：

- 电容 C：i_{n+1} = C/dt · (v_{n+1} − v_n)
  → 伴随电导 Geq = C/dt，并联等效电流源（从 b 流向 a，大小 Geq·v_n）；
- 电感 L：i_{n+1} = i_n + dt/L · v_{n+1}
  → 伴随电导 Geq = dt/L，并联等效电流源（从 a 流向 b，大小 i_n）。

每推进一步，把电容、电感按上式离散成等效电导并联等效电流源，
再解一次修正节点方程并记录该时刻各节点电压。

t=0 时刻用初始条件直接求解：电容换成电压为 v0 的电压源、电感换成电流为
i0 的电流源，保证时间序列第一个点与初始条件严格自洽、不突跳。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .errors import CircuitError, ErrorCode
from .mna import MnaBuilder, MnaSolution
from .netlist import Circuit

MAX_STEPS = 20_000  # 步数硬上限，防止失控

INTEGRATION_METHOD = "backward_euler"


@dataclass
class TransientResult:
    dt: float
    tstop: float
    time: list[float]                            # 含 t=0，长度 = 步数 + 1
    node_voltages: dict[str, list[float]]        # 每个节点一条曲线（含接地节点）
    voltage_source_currents: dict[str, list[float]]
    inductor_currents: dict[str, list[float]]


def run_transient(circuit: Circuit, dt: float | None, tstop: float | None) -> TransientResult:
    """从 t=0 按定步长 dt 推进到不超过 tstop 的最后一个整步。"""
    if dt is None or not math.isfinite(dt) or dt <= 0:
        raise CircuitError(ErrorCode.INVALID_TIME_PARAMS, "时间步长 dt 必须是正的有限数值")
    if tstop is None or not math.isfinite(tstop) or tstop < dt:
        raise CircuitError(ErrorCode.INVALID_TIME_PARAMS, "终止时间 tstop 必须不小于一个步长 dt")
    n_steps = int(math.floor(tstop / dt + 1e-9))  # 小容差吸收浮点除法误差
    if n_steps > MAX_STEPS:
        raise CircuitError(
            ErrorCode.TOO_MANY_STEPS,
            f"需要 {n_steps} 步，超过上限 {MAX_STEPS}；请增大 dt 或减小 tstop",
        )

    times: list[float] = []
    node_series: dict[str, list[float]] = {n: [] for n in (*circuit.nodes, circuit.ground)}
    vs_series: dict[str, list[float]] = {vs.name: [] for vs in circuit.voltage_sources}
    ind_series: dict[str, list[float]] = {ind.name: [] for ind in circuit.inductors}

    def record(t: float, sol: MnaSolution, ind_currents: dict[str, float]) -> None:
        times.append(t)
        for node, series in node_series.items():
            series.append(sol.node_voltages[node])
        for name, series in vs_series.items():
            series.append(sol.branch_currents[name])
        for name, series in ind_series.items():
            series.append(ind_currents[name])

    def stamp_static(builder: MnaBuilder) -> None:
        """电阻与独立源：每一步都相同的静态部分。"""
        for r in circuit.resistors:
            builder.add_conductance(r.a, r.b, 1.0 / r.resistance)
        for cs in circuit.current_sources:
            builder.add_current_source(cs.a, cs.b, cs.current)
        for vs in circuit.voltage_sources:
            builder.add_voltage_source(vs.name, vs.a, vs.b, vs.voltage)

    # --- t = 0：电容 → v0 电压源，电感 → i0 电流源，直接解出与初始条件自洽的起点 ---
    builder = MnaBuilder(circuit.nodes, circuit.ground)
    stamp_static(builder)
    for c in circuit.capacitors:
        builder.add_voltage_source(c.name, c.a, c.b, c.v0)
    for ind in circuit.inductors:
        builder.add_current_source(ind.a, ind.b, ind.i0)
    sol = builder.solve()
    cap_v = {c.name: c.v0 for c in circuit.capacitors}
    ind_i = {ind.name: ind.i0 for ind in circuit.inductors}
    record(0.0, sol, ind_i)

    # --- 后向欧拉步进 ---
    for k in range(1, n_steps + 1):
        builder = MnaBuilder(circuit.nodes, circuit.ground)
        stamp_static(builder)
        for c in circuit.capacitors:
            geq = c.capacitance / dt
            builder.add_conductance(c.a, c.b, geq)
            # 历史电流源必须挂在电容自己的两端之间（b → a：注入 a、从 b 抽出），
            # 与伴随电导构成完整的诺顿等效。若错挂到地，b 端 KCL 会丢掉抽出项，
            # 只有 b 恰好是地时才碰巧正确——浮空电容的稳态就会被解错。
            builder.add_current_source(c.b, c.a, geq * cap_v[c.name])
        for ind in circuit.inductors:
            geq = dt / ind.inductance
            builder.add_conductance(ind.a, ind.b, geq)
            builder.add_current_source(ind.a, ind.b, ind_i[ind.name])  # 等效源：a → b
        sol = builder.solve()
        for c in circuit.capacitors:
            cap_v[c.name] = sol.voltage(c.a) - sol.voltage(c.b)
        for ind in circuit.inductors:
            geq = dt / ind.inductance
            ind_i[ind.name] = geq * (sol.voltage(ind.a) - sol.voltage(ind.b)) + ind_i[ind.name]
        record(k * dt, sol, ind_i)

    return TransientResult(
        dt=dt,
        tstop=tstop,
        time=times,
        node_voltages=node_series,
        voltage_source_currents=vs_series,
        inductor_currents=ind_series,
    )
