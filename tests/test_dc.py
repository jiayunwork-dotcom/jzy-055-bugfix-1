"""直流工作点：分压比、电流源、电感短路、电容开路，以及与瞬态稳态的一致性。"""

import math

from app.dc import solve_dc
from app.netlist import parse_netlist
from app.transient import run_transient


def divider_netlist():
    return parse_netlist([
        {"name": "V1", "type": "voltage_source", "nodes": ["in", "0"], "value": 5.0},
        {"name": "R1", "type": "resistor", "nodes": ["in", "out"], "value": 1000.0},
        {"name": "R2", "type": "resistor", "nodes": ["out", "0"], "value": 2000.0},
    ])


def test_voltage_divider_ratio_matches_hand_calculation():
    res = solve_dc(divider_netlist())
    v_in = res.node_voltages["in"]
    v_out = res.node_voltages["out"]
    assert math.isclose(v_in, 5.0, rel_tol=0.0, abs_tol=1e-12)
    # 分压比必须与手算 R2/(R1+R2) = 2/3 在数值误差内吻合
    assert math.isclose(v_out / v_in, 2.0 / 3.0, rel_tol=1e-12)
    assert math.isclose(v_out, 10.0 / 3.0, rel_tol=1e-12)
    # 回路电流 5/3mA；电压源支路电流正方向为“流入正极”，供电故为负
    assert math.isclose(res.voltage_source_currents["V1"], -5.0 / 3000.0, rel_tol=1e-12)
    assert res.node_voltages["0"] == 0.0


def test_current_source_into_resistor():
    circuit = parse_netlist([
        {"name": "I1", "type": "current_source", "nodes": ["0", "n1"], "value": 0.001},
        {"name": "R1", "type": "resistor", "nodes": ["n1", "0"], "value": 1000.0},
    ])
    res = solve_dc(circuit)
    assert math.isclose(res.node_voltages["n1"], 1.0, rel_tol=1e-12)


def test_capacitor_is_open_in_dc():
    # 电容开路 → 无电流，out 经 R1 被拉到电源电压
    circuit = parse_netlist([
        {"name": "V1", "type": "voltage_source", "nodes": ["in", "0"], "value": 5.0},
        {"name": "R1", "type": "resistor", "nodes": ["in", "out"], "value": 1000.0},
        {"name": "C1", "type": "capacitor", "nodes": ["out", "0"], "value": 1e-6},
    ])
    res = solve_dc(circuit)
    assert math.isclose(res.node_voltages["out"], 5.0, rel_tol=1e-12)
    assert math.isclose(res.voltage_source_currents["V1"], 0.0, abs_tol=1e-12)


def test_inductor_is_short_in_dc():
    circuit = parse_netlist([
        {"name": "V1", "type": "voltage_source", "nodes": ["in", "0"], "value": 5.0},
        {"name": "R1", "type": "resistor", "nodes": ["in", "out"], "value": 1000.0},
        {"name": "L1", "type": "inductor", "nodes": ["out", "0"], "value": 1e-3},
    ])
    res = solve_dc(circuit)
    assert math.isclose(res.node_voltages["out"], 0.0, abs_tol=1e-12)
    assert math.isclose(res.inductor_currents["L1"], 5e-3, rel_tol=1e-12)


def test_transient_steady_state_matches_dc_operating_point():
    """同一套元件模型：瞬态推到稳态后必须与直流工作点一致。"""
    rc = parse_netlist([
        {"name": "V1", "type": "voltage_source", "nodes": ["in", "0"], "value": 5.0},
        {"name": "R1", "type": "resistor", "nodes": ["in", "out"], "value": 1000.0},
        {"name": "C1", "type": "capacitor", "nodes": ["out", "0"], "value": 1e-6},
    ])
    dc = solve_dc(rc)
    tr = run_transient(rc, dt=1e-5, tstop=2e-2)  # τ=1ms，推 20τ 到稳态
    assert math.isclose(tr.node_voltages["out"][-1], dc.node_voltages["out"], abs_tol=1e-6)
    assert math.isclose(tr.voltage_source_currents["V1"][-1],
                        dc.voltage_source_currents["V1"], abs_tol=1e-9)

    rl = parse_netlist([
        {"name": "V1", "type": "voltage_source", "nodes": ["in", "0"], "value": 5.0},
        {"name": "R1", "type": "resistor", "nodes": ["in", "out"], "value": 1000.0},
        {"name": "L1", "type": "inductor", "nodes": ["out", "0"], "value": 1e-3},
    ])
    dc2 = solve_dc(rl)
    tr2 = run_transient(rl, dt=1e-8, tstop=2e-5)  # τ=L/R=1µs，推 20τ 到稳态
    assert math.isclose(tr2.inductor_currents["L1"][-1],
                        dc2.inductor_currents["L1"], abs_tol=1e-9)
    assert math.isclose(tr2.node_voltages["out"][-1],
                        dc2.node_voltages["out"], abs_tol=1e-6)
