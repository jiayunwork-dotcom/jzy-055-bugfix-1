"""HTTP 接口端到端行为：健康检查、算例、直流与瞬态的响应形状。"""

import math

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

DIVIDER = {
    "elements": [
        {"name": "V1", "type": "voltage_source", "nodes": ["in", "0"], "value": 5.0},
        {"name": "R1", "type": "resistor", "nodes": ["in", "out"], "value": 1000.0},
        {"name": "R2", "type": "resistor", "nodes": ["out", "0"], "value": 2000.0},
    ]
}

RC = {
    "elements": [
        {"name": "V1", "type": "voltage_source", "nodes": ["in", "0"], "value": 5.0},
        {"name": "R1", "type": "resistor", "nodes": ["in", "out"], "value": 1000.0},
        {"name": "C1", "type": "capacitor", "nodes": ["out", "0"], "value": 1e-6},
    ]
}


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_dc_endpoint_happy_path():
    resp = client.post("/api/dc", json={"netlist": DIVIDER})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert math.isclose(body["node_voltages"]["in"], 5.0, rel_tol=1e-12)
    assert math.isclose(body["node_voltages"]["out"], 10.0 / 3.0, rel_tol=1e-12)
    assert body["node_voltages"]["0"] == 0.0
    assert math.isclose(body["voltage_source_currents"]["V1"], -5.0 / 3000.0, rel_tol=1e-12)


def test_transient_endpoint_response_shape():
    resp = client.post("/api/transient", json={"netlist": RC, "dt": 1e-5, "tstop": 1e-3})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["integration"] == "backward_euler"
    assert body["steps"] == 100
    assert len(body["time"]) == body["steps"] + 1
    assert body["time"][0] == 0.0
    assert math.isclose(body["time"][-1], 1e-3, rel_tol=1e-9)
    for node in ("in", "out", "0"):
        assert len(body["node_voltages"][node]) == len(body["time"])
    assert body["node_voltages"]["in"][-1] == 5.0
    # 1ms = 1τ 处应约为 63.2% 的电源电压
    assert math.isclose(body["node_voltages"]["out"][-1], 5 * (1 - math.exp(-1)), rel_tol=2e-2)


def test_examples_available_and_hand_checkable():
    resp = client.get("/api/examples")
    assert resp.status_code == 200
    examples = resp.json()
    assert set(examples) >= {"voltage_divider", "rc_charge"}

    # 算例一：分压网络，直流解可笔算验证
    r = client.post("/api/dc", json={"netlist": examples["voltage_divider"]["netlist"]})
    assert r.status_code == 200
    assert math.isclose(r.json()["node_voltages"]["out"], 10.0 / 3.0, rel_tol=1e-9)

    # 算例二：RC 充电，瞬态末态逼近电源电压
    rc = examples["rc_charge"]
    r = client.post("/api/transient", json={
        "netlist": rc["netlist"],
        "dt": rc["suggested_dt"],
        "tstop": rc["suggested_tstop"],
    })
    assert r.status_code == 200
    v_end = r.json()["node_voltages"]["out"][-1]
    assert math.isclose(v_end, 5 * (1 - math.exp(-5)), rel_tol=1e-2)
    assert v_end > 0.99 * 5.0


def test_error_response_shape():
    resp = client.post("/api/dc", json={"netlist": {"elements": [
        {"name": "Q1", "type": "transistor", "nodes": ["a", "0"], "value": 1}]}})
    assert resp.status_code == 400
    body = resp.json()
    assert set(body) == {"code", "message"}
    assert body["code"] == "UNKNOWN_ELEMENT_TYPE"
