# 电路仿真服务（netlist → 直流工作点 + 瞬态波形）

纯 HTTP 接口的电路计算服务：喂一份 JSON 网表进去，返回直流工作点，或沿时间轴推出一条
瞬态波形。没有画布、没有拖拽，所有电学计算都在服务端完成，并附带一套自动化测试独立检验。

## 快速开始

### Docker（运行时固定 Python 3.12）

```bash
docker build -t circuit-sim .
docker run --rm -p 8000:8000 circuit-sim
```

### 本地

```bash
pip install -r requirements-dev.txt   # 仅运行服务的话 requirements.txt 即可
uvicorn app.main:app --port 8000
pytest                                # 跑自动化测试
```

服务起来后，交互式接口文档在 `http://localhost:8000/docs`。

## 网表格式

网表是一组元件，每个元件有唯一名称、两个节点名和一个参数值：

```json
{
  "netlist": {
    "elements": [
      {"name": "V1", "type": "voltage_source", "nodes": ["in", "0"], "value": 5.0},
      {"name": "R1", "type": "resistor", "nodes": ["in", "out"], "value": 1000.0},
      {"name": "C1", "type": "capacitor", "nodes": ["out", "0"], "value": 1e-6, "initial": 0.0}
    ]
  }
}
```

| type（可缩写） | 参数 value | 可选 initial |
|---|---|---|
| `resistor`（r） | 电阻，欧姆（不允许为 0） | — |
| `capacitor`（c） | 电容，法拉（必须为正） | 初始电压 v(a)−v(b)，默认 0 |
| `inductor`（l） | 电感，亨利（必须为正） | 初始电流 a→b，默认 0 |
| `voltage_source`（v） | 电压，伏特 | — |
| `current_source`（i） | 电流，安培 | — |

**符号约定**（直流与瞬态共用同一份定义）：

- 每个元件连接两个节点 `[a, b]`；二端元件电压定义为 `v = v(a) − v(b)`，电流正方向为从 a 经元件流向 b；
- 电压源 a 为正极、b 为负极；其支路电流正方向为**从正极流入**（电源向外供电时为负值，与 SPICE 一致）；
- 电流源的电流经源从 a 流向 b（向 b 注入、从 a 抽出）；
- 整张网必须恰好有一个接地参考节点，名字叫 `"0"` 或 `"gnd"`，电位恒为零（两个名字同时出现会被拒绝）。

## 接口

### `POST /api/dc` — 直流工作点

收网表，返回各节点电位、各电压源支路电流、各电感电流：

```bash
curl -s localhost:8000/api/dc -H 'content-type: application/json' -d '{
  "netlist": {"elements": [
    {"name": "V1", "type": "voltage_source", "nodes": ["in", "0"], "value": 5.0},
    {"name": "R1", "type": "resistor", "nodes": ["in", "out"], "value": 1000.0},
    {"name": "R2", "type": "resistor", "nodes": ["out", "0"], "value": 2000.0}
  ]}}'
```

```json
{
  "success": true,
  "node_voltages": {"in": 5.0, "out": 3.3333333333333335, "0": 0.0},
  "voltage_source_currents": {"V1": -0.0016666666666666668},
  "inductor_currents": {}
}
```

直流工作点下电容当开路、电感当短路（以 0V 电压源建模，支路电流即电感电流）；
初始条件不参与直流求解，仅用于瞬态 t=0。

### `POST /api/transient` — 瞬态分析

收网表连同 `dt` 与 `tstop`，返回一条时间序列（含 t=0，每个时刻各节点电压，够直接画曲线）：

```bash
curl -s localhost:8000/api/transient -H 'content-type: application/json' -d '{
  "netlist": {"elements": [
    {"name": "V1", "type": "voltage_source", "nodes": ["in", "0"], "value": 5.0},
    {"name": "R1", "type": "resistor", "nodes": ["in", "out"], "value": 1000.0},
    {"name": "C1", "type": "capacitor", "nodes": ["out", "0"], "value": 1e-6}
  ]},
  "dt": 1e-5, "tstop": 5e-3
}'
```

```json
{
  "success": true,
  "integration": "backward_euler",
  "dt": 1e-5, "tstop": 0.005, "steps": 500,
  "time": [0.0, 1e-05, "..."],
  "node_voltages": {"in": [5.0, "..."], "out": [0.0, "..."], "0": [0.0, "..."]},
  "voltage_source_currents": {"V1": ["..."]},
  "inductor_currents": {}
}
```

`tstop` 不是 `dt` 整倍数时，最后一个时间点是不超过 `tstop` 的最后一个整步。

### `GET /api/examples` — 两个可手算核对的算例

返回分压网络与 RC 充电两份网表（含建议的 dt/tstop），可直接 POST 给上面两个接口。

### 错误响应

网表非法、矩阵奇异、参数越界一律返回 HTTP 400，带机器可读错误码和人话说明：

```json
{"code": "VOLTAGE_SOURCE_LOOP", "message": "电压源 V3 与其他电压源构成回路（或两端短接），KVL 约束冲突，方程组奇异"}
```

| code | 含义 |
|---|---|
| `MALFORMED_REQUEST` | 请求体不符合接口结构 |
| `EMPTY_NETLIST` | 网表没有任何元件 |
| `UNKNOWN_ELEMENT_TYPE` | 不认识的元件类型 |
| `MISSING_NODE` | 元件缺少必需的节点（必须恰好两个） |
| `MISSING_VALUE` | 元件缺少参数值 |
| `INVALID_VALUE` | 参数值非法（非有限数值、电容/电感非正等） |
| `ZERO_RESISTANCE` | 电阻取值为零 |
| `UNSUPPORTED_INITIAL_CONDITION` | 非储能元件带了初始条件 |
| `DUPLICATE_ELEMENT` | 元件重名 |
| `NO_GROUND` | 找不到接地参考节点 |
| `AMBIGUOUS_GROUND` | 同时出现 `0` 和 `gnd` 两个参考名 |
| `VOLTAGE_SOURCE_LOOP` | 理想电压源围成回路（解析阶段并查集检测） |
| `MATRIX_SINGULAR` | 系数矩阵奇异（悬浮节点、电感回路、初始条件矛盾等） |
| `INVALID_TIME_PARAMS` | dt 不为正，或 tstop 小于一个 dt |
| `TOO_MANY_STEPS` | 瞬态步数超过上限 20000 |

## 数值方法

**修正节点分析（MNA）**：电阻在导纳矩阵上贡献自己的电导；独立电流源把电流注入右端
向量；独立电压源多引一个支路电流未知量、把矩阵扩维。节点相对地的电位和每个电压源
支路的电流一起解出。线性方程组用 NumPy 稠密求解；奇异矩阵（如悬浮节点、电压源回路）
会被显式判错并报告，绝不返回 NaN 或无穷大。

**瞬态积分**：全程固定使用**后向欧拉（Backward Euler）**这一种定步长隐式格式，不混用
其他方法。每推进一步，储能元件离散为伴随模型（等效电导并联等效电流源），再解一次 MNA：

- 电容：`i_{n+1} = C/dt·(v_{n+1} − v_n)` → 电导 `C/dt` 并联电流源 `C/dt·v_n`（b→a）；
- 电感：`i_{n+1} = i_n + dt/L·v_{n+1}` → 电导 `dt/L` 并联电流源 `i_n`（a→b）。

t=0 时刻用初始条件直接求解（电容换成 v0 电压源、电感换成 i0 电流源），保证时间序列
第一个点与初始条件严格自洽、不突跳。直流与瞬态共用同一份元件定义与 MNA 组装原语，
测试里有一条"瞬态推到稳态 == 直流工作点"的一致性用例把这一点钉死。

## 算例（可手算核对）

1. **电阻串联分压**（`GET /api/examples` 里的 `voltage_divider`）：5V 电源、1kΩ/2kΩ 串联。
   手算 `V(out) = 5 × 2/3 ≈ 3.3333V`，回路电流 `5/3kΩ ≈ 1.6667mA`。
2. **RC 充电**（`rc_charge`）：5V 经 1kΩ 给 1µF 充电，零初始电压。`τ = R·C = 1ms`，
   `v(t) = 5(1 − e^{−t/τ})`：t=τ 时约 3.1594V（63.2%），t=5τ=5ms 时约 4.9663V，逼近电源电压。

## 目录结构

```
app/
  netlist.py     # 网表解析与合法性校验（元件定义与符号约定也在此）
  mna.py         # 修正节点分析：矩阵组装与线性求解
  dc.py          # 直流工作点（电容开路、电感短路）
  transient.py   # 瞬态时间步进与储能元件伴随模型（后向欧拉）
  schemas.py     # 请求/响应数据结构
  main.py        # HTTP 接口层（只做转发与封装）
  examples.py    # 算例加载
  examples/      # 两个手算可核对算例（JSON）
tests/           # 自动化测试（pytest）
Dockerfile       # Python 3.12 镜像，容器起来接口即可访问
```

## 测试覆盖

- 分压网络的直流解，各节点电位之比与手算分压比在数值误差内吻合；
- RC 充电从零初值出发，瞬态末端电压按指数规律逼近电源电压，到达 63.2% 的时刻与 τ=R·C 对得上；
- 电容初压非零时，t=0 严格等于初值、第一步与后向欧拉公式严格衔接、不突跳（电感初流同理）；
- 瞬态稳态与直流工作点互相一致（RC 与 RL 各一条）；
- 各类非法网表（未知元件类型、缺节点、无接地、零电阻、重名、电压源回路、悬浮节点、
  初始条件矛盾）与非法时间参数（dt≤0、tstop<dt、步数超上限）都被正确挡回。

## 限制

- 仅支持五种线性元件与独立源，不含非线性器件；
- 稠密矩阵求解，面向"手算可核对"规模的中小电路；
- 后向欧拉是一阶格式：定步长下精度随 dt 减小线性提升， unconditionally stable，
  但对快变波形需要足够小的 dt 才准确。
