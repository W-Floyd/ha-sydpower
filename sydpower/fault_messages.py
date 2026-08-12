"""
English wording for fault messages the backend does not translate well.

Requesting the English locale still leaves 25 of the 42 fault messages in
Chinese: the backend's translations are incomplete. These overrides are applied
when reading, not when building the catalog, so refreshing the catalog cannot
silently lose them and the table stays auditable against its source.

Wording follows the English messages already present in the same fault group —
"Overload fault level 1" and "level 3" fix the phrasing of "level 2", and
"Low temperature when AFE charging" fixes its high-temperature counterpart.
"""

from __future__ import annotations

# Source string exactly as the backend returns it -> English wording.
FAULT_MESSAGE_OVERRIDES: dict[str, str] = {
    # AC FaultCode bit 3
    '过载故障等级2': 'Overload fault level 2',
    # AC FaultCode bit 9
    '市电电压异常': 'Abnormal mains voltage',
    # AC FaultCode bit 13
    '系统异常': 'System fault',
    # AC FaultCode bit 14
    '电池电压异常': 'Abnormal battery voltage',
    # BMS AFE Status bit 3
    'AFE放电2级过流': 'AFE discharge overcurrent level 2',
    # BMS AFE Status bit 4
    'AFE充电过流': 'AFE charge overcurrent',
    # BMS AFE Status bit 5
    'AFE输出短路': 'AFE output short circuit',
    # BMS AFE Status bit 9
    'AFE充电高温': 'High temperature when AFE charging',
    # BMS AFE Status bit 10 — not a translation: the backend's own English has a
    # typo here ("whtn"), and its counterpart on bit 9 reads "when".
    'Low temperature whtn AFE discharging': 'Low temperature when AFE discharging',
    # BMS AFE Status bit 11
    'AFE放电高温': 'High temperature when AFE discharging',
    # BMS USER Status bit 0
    '电池包放电高温': 'High temperature when battery pack discharging',
    # BMS USER Status bit 1
    '电池包放电低温': 'Low temperature when battery pack discharging',
    # BMS USER Status bit 2
    '电池包充电高温': 'High temperature when battery pack charging',
    # BMS USER Status bit 3
    '电池包充电低温': 'Low temperature when battery pack charging',
    # PV FaultCode bit 0
    'PV板温度异常': 'Abnormal PV board temperature',
    # PV FaultCode bit 1
    'DC 输入电压过高': 'DC input voltage too high',
    # PV FaultCode bit 2
    'DC 输入电流过高': 'DC input current too high',
    # PV FaultCode bit 3
    'DC 12V通道1和2过流': 'DC 12V channels 1 and 2 overcurrent',
    # PV FaultCode bit 4
    'DC 12V通道3过流': 'DC 12V channel 3 overcurrent',
    # PV FaultCode bit 5
    '电池电压过高故障': 'Battery overvoltage fault',
    # Panel FaultCode bit 0
    'USB1输出过流': 'USB1 output overcurrent',
    # Panel FaultCode bit 1
    'QC1输出过流': 'QC1 output overcurrent',
    # Panel FaultCode bit 3
    '12V DC输出过流': '12V DC output overcurrent',
    # Panel FaultCode bit 4
    '24V DC输出过流': '24V DC output overcurrent',
    # Panel FaultCode bit 18
    '无线充电故障': 'Wireless charging fault',
    # Panel FaultCode bit 20
    'PD3输出过流': 'PD3 output overcurrent',
}


def translate_fault(message: str) -> str:
    """Return the English wording for *message*, or the message unchanged."""
    return FAULT_MESSAGE_OVERRIDES.get(message, message)
