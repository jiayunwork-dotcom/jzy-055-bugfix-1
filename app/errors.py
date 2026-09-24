"""统一错误类型与机器可读错误码。

所有可预期的非法情况（网表非法、矩阵奇异、参数越界）都以 CircuitError 抛出，
由 HTTP 层统一转换为 {"code": ..., "message": ...} 形式的错误响应。
"""

from __future__ import annotations


class ErrorCode:
    """机器可读错误码（字符串常量，随错误响应返回）。"""

    MALFORMED_REQUEST = "MALFORMED_REQUEST"          # 请求体不符合接口结构
    EMPTY_NETLIST = "EMPTY_NETLIST"                  # 网表没有任何元件
    UNKNOWN_ELEMENT_TYPE = "UNKNOWN_ELEMENT_TYPE"    # 不认识的元件类型
    MISSING_NODE = "MISSING_NODE"                    # 元件缺少必需的节点
    MISSING_VALUE = "MISSING_VALUE"                  # 元件缺少参数值
    INVALID_VALUE = "INVALID_VALUE"                  # 参数值非法（非有限、非正等）
    ZERO_RESISTANCE = "ZERO_RESISTANCE"              # 电阻取值为零
    UNSUPPORTED_INITIAL_CONDITION = "UNSUPPORTED_INITIAL_CONDITION"  # 非储能元件带初始条件
    DUPLICATE_ELEMENT = "DUPLICATE_ELEMENT"          # 元件重名
    NO_GROUND = "NO_GROUND"                          # 找不到接地参考节点
    AMBIGUOUS_GROUND = "AMBIGUOUS_GROUND"            # 同时出现 0 和 gnd 两个参考名
    VOLTAGE_SOURCE_LOOP = "VOLTAGE_SOURCE_LOOP"      # 理想电压源围成回路
    MATRIX_SINGULAR = "MATRIX_SINGULAR"              # 系数矩阵奇异，无法求解
    INVALID_TIME_PARAMS = "INVALID_TIME_PARAMS"      # dt / tstop 非法
    TOO_MANY_STEPS = "TOO_MANY_STEPS"                # 瞬态步数超过上限


class CircuitError(Exception):
    """网表/求解相关的可预期错误，携带机器可读错误码与人话说明。"""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")
