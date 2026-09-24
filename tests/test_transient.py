"""瞬态：RC 充电末态与时间常数、初始条件自洽衔接、非法时间参数挡回。"""

import math

import pytest

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
