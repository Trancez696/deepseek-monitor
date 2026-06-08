"""界面样式模块。

把样式集中放在这里，主界面文件会更容易阅读。
"""


APP_STYLE = """
QWidget {
    color: #f2fffb;
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 14px;
}

QFrame#glassCard {
    background-color: rgba(255, 255, 255, 0.12);
    border: 1px solid rgba(255, 255, 255, 0.20);
    border-radius: 18px;
}

QFrame#smallCard,
QFrame#modelCard,
QFrame#chartCard {
    background-color: rgba(255, 255, 255, 0.10);
    border: 1px solid rgba(255, 255, 255, 0.16);
    border-radius: 14px;
}

QLabel#titleLabel {
    color: #ffffff;
    font-size: 21px;
    font-weight: 700;
}

QLabel#subtitleLabel {
    color: rgba(242, 255, 251, 0.68);
    font-size: 12px;
}

QLabel#mutedLabel {
    color: rgba(242, 255, 251, 0.72);
    font-size: 12px;
}

QLabel#sourceLabel {
    color: rgba(242, 255, 251, 0.66);
    font-size: 12px;
}

QLabel#statusPill {
    background-color: rgba(74, 222, 190, 0.18);
    border: 1px solid rgba(125, 255, 229, 0.32);
    border-radius: 9px;
    color: #dffef7;
    padding: 3px 8px;
    font-size: 12px;
    font-weight: 700;
}

QLabel#warningPill {
    background-color: rgba(250, 204, 21, 0.14);
    border: 1px solid rgba(250, 204, 21, 0.34);
    border-radius: 9px;
    color: #facc15;
    padding: 3px 8px;
    font-size: 12px;
    font-weight: 700;
}

QLabel#balanceValue {
    color: #ffffff;
    font-size: 38px;
    font-weight: 800;
}

QLabel#sectionValue {
    color: #ffffff;
    font-size: 20px;
    font-weight: 700;
}

QPushButton#iconButton {
    background-color: rgba(255, 255, 255, 0.14);
    border: 1px solid rgba(255, 255, 255, 0.20);
    border-radius: 15px;
    color: #ffffff;
    min-width: 30px;
    max-width: 30px;
    min-height: 30px;
    max-height: 30px;
}

QPushButton#iconButton:hover {
    background-color: rgba(255, 255, 255, 0.24);
}

QPushButton#primaryButton {
    background-color: rgba(74, 222, 190, 0.22);
    border: 1px solid rgba(125, 255, 229, 0.36);
    border-radius: 12px;
    color: #ffffff;
    min-width: 92px;
    min-height: 32px;
    padding: 7px 12px;
    font-weight: 700;
}

QPushButton#primaryButton:hover {
    background-color: rgba(74, 222, 190, 0.32);
}

QPushButton#smallActionButton {
    background-color: rgba(74, 222, 190, 0.18);
    border: 1px solid rgba(125, 255, 229, 0.34);
    border-radius: 10px;
    color: #ffffff;
    min-width: 64px;
    max-width: 64px;
    min-height: 30px;
    max-height: 30px;
    padding: 0;
    font-size: 13px;
    font-weight: 700;
}

QPushButton#smallActionButton:hover {
    background-color: rgba(74, 222, 190, 0.28);
}

QPushButton#loginActionButton {
    background-color: rgba(74, 222, 190, 0.18);
    border: 1px solid rgba(125, 255, 229, 0.34);
    border-radius: 12px;
    color: #ffffff;
    min-width: 118px;
    max-width: 118px;
    min-height: 32px;
    max-height: 32px;
    padding: 0;
    font-size: 13px;
    font-weight: 700;
}

QPushButton#loginActionButton:hover {
    background-color: rgba(74, 222, 190, 0.28);
}

QProgressBar {
    background-color: rgba(255, 255, 255, 0.14);
    border: none;
    border-radius: 5px;
    min-height: 10px;
    max-height: 10px;
}

QProgressBar::chunk {
    background-color: #4adebe;
    border-radius: 5px;
}

QLineEdit,
QComboBox,
QDoubleSpinBox {
    background-color: rgba(255, 255, 255, 0.12);
    border: 1px solid rgba(255, 255, 255, 0.20);
    border-radius: 8px;
    color: #ffffff;
    padding: 7px 9px;
}

QCheckBox {
    spacing: 8px;
}
"""
