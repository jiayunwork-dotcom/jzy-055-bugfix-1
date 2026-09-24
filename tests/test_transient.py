"""瞬态：RC 充电末态与时间常数、初始条件自洽衔接、非法时间参数挡回。"""

import math

import pytest

from app.dc import solve_dc
from app.errors import CircuitError, ErrorCode
from app.netlist import parse_netlist
from app.transient import MAX_STEPS, run_transient

V, R, C = 5.0, 1000.0, 1e-6
TAU = R * C  # 1ms


def rc_netlist(v0: float = 0.0):
    elements = [
        {"name": "V1", "type": "voltage_source", "nodes": ["in", "0"], "value": V},
        {"name": "R1", "type": "resistor", "nodes": ["in", "out"], "value": R},
        {"name": "C1", "type": "capacitor", "nodes": ["out", "0"], "value": C},
    ]
    if v0:
        elements[2]["initial"] = v0
    return parse_netlist(elements)


def test_rc_final_voltage_approaches_source_voltage():
    res = run_transient(rc_netlist(), dt=1e-6, tstop=5e-3)  # dt=τ/1000，推 5τ
    v_end = res.node_voltages["out"][-1]
    exact = V * (1.0 - math.exp(-5.0))
    # 与指数规律 V(1−e^{−5}) 吻合（含后向欧拉离散误差，容差 1e-3）
    assert math.isclose(v_end, exact, rel_tol=1e-3)
    # 且确实逼近电源电压本身
    assert v_end > 0.99 * V


def test_rc_time_constant_matches_r_times_c():
    res = run_transient(rc_netlist(), dt=1e-6, tstop=5e-3)
    target = V * (1.0 - math.exp(-1.0))  # 63.21%
    series = res.node_voltages["out"]
    idx = next(i for i, v in enumerate(series) if v >= target)
    # 到达 63.2% 的时刻必须与时间常数 τ=R·C 对得上
    assert math.isclose(res.time[idx], TAU, rel_tol=1e-2)


def test_rc_zero_initial_condition_starts_at_zero():
    res = run_transient(rc_netlist(), dt=1e-5, tstop=1e-3)
    assert res.time[0] == 0.0
    assert res.node_voltages["out"][0] == 0.0


def test_capacitor_initial_condition_is_self_consistent():
    v0 = 2.0
    dt = 1e-6
    res = run_transient(rc_netlist(v0=v0), dt=dt, tstop=1e-3)
    out = res.node_voltages["out"]
    # t=0 必须严格等于初始电压，不能突跳
    assert math.isclose(out[0], v0, rel_tol=0.0, abs_tol=1e-12)
    # 第一个步进点必须与后向欧拉公式严格衔接
    v1_expected = (v0 + dt / TAU * V) / (1.0 + dt / TAU)
    assert math.isclose(out[1], v1_expected, rel_tol=1e-9)
    # 单步变化量受物理上限约束：不超过 (dt/τ)·|电源−初值|
    assert abs(out[1] - v0) <= (dt / TAU) * abs(V - v0) * 1.01
    # 整体仍朝电源电压单调逼近
    assert out[-1] > out[1] > out[0]


def test_inductor_initial_current_is_self_consistent():
    i0 = 2e-3
    inductance = 1e-3
    circuit = parse_netlist([
        {"name": "V1", "type": "voltage_source", "nodes": ["in", "0"], "value": V},
        {"name": "R1", "type": "resistor", "nodes": ["in", "out"], "value": R},
        {"name": "L1", "type": "inductor", "nodes": ["out", "0"], "value": inductance,
         "initial": i0},
    ])
    dt = 1e-8
    res = run_transient(circuit, dt=dt, tstop=1e-5)
    currents = res.inductor_currents["L1"]
    # t=0 必须严格等于初始电流
    assert math.isclose(currents[0], i0, rel_tol=0.0, abs_tol=1e-15)
    # 单步变化受 v/L·dt 约束，不能突跳
    assert abs(currents[1] - i0) <= (dt / inductance) * V * 1.01
    # 稳态趋向 V/R
    assert math.isclose(currents[-1], V / R, rel_tol=1e-2)


def floating_cap_netlist(v0: float = 0.0):
    """电容 C1 横跨 n1、n2 两个非地节点：两端都有确定直流通路，但都不接地。

    手算稳态：R1/R2 分压得 n1=2.5V，R3/R4 分压得 n2=3.75V，
    电容稳态电压 v(n2)-v(n1)=1.25V。
    """
    elements = [
        {"name": "V1", "type": "voltage_source", "nodes": ["in", "0"], "value": 5.0},
        {"name": "R1", "type": "resistor", "nodes": ["in", "n1"], "value": 1000.0},
        {"name": "R2", "type": "resistor", "nodes": ["n1", "0"], "value": 1000.0},
        {"name": "R3", "type": "resistor", "nodes": ["in", "n2"], "value": 1000.0},
        {"name": "R4", "type": "resistor", "nodes": ["n2", "0"], "value": 3000.0},
        {"name": "C1", "type": "capacitor", "nodes": ["n2", "n1"], "value": 1e-6},
    ]
    if v0:
        elements[-1]["initial"] = v0
    return parse_netlist(elements)


def test_floating_capacitor_steady_state_matches_dc_operating_point():
    """浮空电容（两端均不接地）：瞬态推到稳态必须与同网表直流工作点一致。"""
    circuit = floating_cap_netlist()
    dc = solve_dc(circuit)
    # 直流工作点本身先与手算核对：n1=2.5V、n2=3.75V
    assert math.isclose(dc.node_voltages["n1"], 2.5, rel_tol=1e-12)
    assert math.isclose(dc.node_voltages["n2"], 3.75, rel_tol=1e-12)

    # 电容看到的戴维南电阻 (1k||1k)+(1k||3k)=1.25kΩ，τ≈1.25ms；推 16τ 到稳态
    tr = run_transient(circuit, dt=1e-5, tstop=2e-2)
    n1_end = tr.node_voltages["n1"][-1]
    n2_end = tr.node_voltages["n2"][-1]
    assert math.isclose(n1_end, dc.node_voltages["n1"], abs_tol=1e-6)
    assert math.isclose(n2_end, dc.node_voltages["n2"], abs_tol=1e-6)
    # 浮空电容两端电压差收敛到两节点的直流电位差 3.75-2.5=1.25V
    assert math.isclose(n2_end - n1_end, 1.25, abs_tol=1e-6)

    # 起点自洽：v0=0 的电容在 t=0 相当于 0V 电压源，强制 v(n2)=v(n1)，
    # 与末态 2.5V/3.75V 明显不同——瞬态确实发生了演化，上面的断言不是空转
    assert math.isclose(tr.node_voltages["n2"][0], tr.node_voltages["n1"][0],
                        rel_tol=0.0, abs_tol=1e-12)


def test_floating_capacitor_initial_condition_self_consistent_and_same_steady_state():
    """浮空电容带非零初值：起点严格等于初值，稳态仍收敛到同一直流工作点。"""
    v0 = -0.5  # 初始 v(n2)-v(n1)
    circuit = floating_cap_netlist(v0=v0)
    dc = solve_dc(circuit)
    tr = run_transient(circuit, dt=1e-5, tstop=2e-2)
    # t=0 电容两端电压差必须严格等于初始条件，不突跳
    assert math.isclose(tr.node_voltages["n2"][0] - tr.node_voltages["n1"][0], v0,
                        rel_tol=0.0, abs_tol=1e-12)
    # 初始条件只影响过渡过程，不改变稳态：末态仍收敛到同一直流工作点
    assert math.isclose(tr.node_voltages["n1"][-1], dc.node_voltages["n1"], abs_tol=1e-6)
    assert math.isclose(tr.node_voltages["n2"][-1], dc.node_voltages["n2"], abs_tol=1e-6)


def test_time_series_shape_and_spacing():
    dt = 3e-4
    res = run_transient(rc_netlist(), dt=dt, tstop=1e-3)
    # tstop 不是 dt 整倍数时，最后一个点是不超过 tstop 的最后一个整步
    assert res.time == [0.0, dt, 2 * dt, 3 * dt]
    for series in res.node_voltages.values():
        assert len(series) == len(res.time)


def test_invalid_time_params_rejected():
    circuit = rc_netlist()
    bad = [(0.0, 1.0), (-1e-3, 1.0), (1e-3, 1e-4), (1e-3, 0.0), (None, 1.0), (1e-3, None)]
    for dt, tstop in bad:
        with pytest.raises(CircuitError) as excinfo:
            run_transient(circuit, dt=dt, tstop=tstop)
        assert excinfo.value.code == ErrorCode.INVALID_TIME_PARAMS


def test_too_many_steps_rejected():
    circuit = rc_netlist()
    with pytest.raises(CircuitError) as excinfo:
        run_transient(circuit, dt=1e-3, tstop=1e-3 * (MAX_STEPS + 1))
    assert excinfo.value.code == ErrorCode.TOO_MANY_STEPS
