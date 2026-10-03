"""
ui/web_settings_page.py – Web Access settings dialog page (QR code pairing, device revocation,
network binding, OPDS keys, auto-off, and security options).
"""
from __future__ import annotations

import io
import logging
import socket
from typing import Any
import psutil

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFrame, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMessageBox, QPushButton, QRadioButton, QScrollArea, QSpinBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from booklib.db.repository import Repository
from booklib.services import get_service_manager
from booklib_web.security import hash_password

logger = logging.getLogger(__name__)


def get_private_ip_addresses() -> list[str]:
    """Discover local private IPv4 addresses (192.168.x.x, 10.x.x.x, 172.16-31.x.x)."""
    addrs: list[str] = ["127.0.0.1"]
    try:
        for iface, snics in psutil.net_if_addrs().items():
            for snic in snics:
                if snic.family == socket.AF_INET:
                    ip = snic.address
                    if ip.startswith(("192.168.", "10.", "172.")) and not ip.startswith("127."):
                        if ip not in addrs:
                            addrs.append(ip)
    except Exception as exc:
        logger.warning("Could not enumerate network interfaces: %s", exc)
    return addrs


class WebSettingsPage(QWidget):
    """Web access settings page."""

    def __init__(self, repo: Repository, parent=None) -> None:
        super().__init__(parent)
        self._repo = repo
        self._sm = get_service_manager()
        self._setup_ui()
        self._load_settings()
        self._refresh_device_list()

    def _setup_ui(self) -> None:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # ── 1. Server Mode ────────────────────────────────────────────────────
        mode_box = QGroupBox("Server Status & Mode")
        mode_layout = QVBoxLayout(mode_box)

        self._status_lbl = QLabel("Server: <b>Stopped</b>")
        mode_layout.addWidget(self._status_lbl)

        mode_row = QHBoxLayout()
        self._mode_group = QButtonGroup(self)
        self._rb_off = QRadioButton("Off")
        self._rb_local = QRadioButton("This computer only (127.0.0.1)")
        self._rb_network = QRadioButton("Devices on my local network")
        self._mode_group.addButton(self._rb_off, 0)
        self._mode_group.addButton(self._rb_local, 1)
        self._mode_group.addButton(self._rb_network, 2)
        mode_row.addWidget(self._rb_off)
        mode_row.addWidget(self._rb_local)
        mode_row.addWidget(self._rb_network)
        mode_row.addStretch()
        mode_layout.addLayout(mode_row)

        net_row = QHBoxLayout()
        net_row.addWidget(QLabel("Network address:"))
        self._ip_combo = QComboBox()
        for ip in get_private_ip_addresses():
            self._ip_combo.addItem(ip)
        net_row.addWidget(self._ip_combo)

        net_row.addWidget(QLabel("Port:"))
        self._port_spin = QSpinBox()
        self._port_spin.setRange(1024, 65535)
        self._port_spin.setValue(8765)
        net_row.addWidget(self._port_spin)

        net_row.addWidget(QLabel("Auto-off:"))
        self._auto_off_combo = QComboBox()
        self._auto_off_combo.addItem("4 hours", 240)
        self._auto_off_combo.addItem("1 hour", 60)
        self._auto_off_combo.addItem("24 hours", 1440)
        self._auto_off_combo.addItem("Until turned off", 0)
        net_row.addWidget(self._auto_off_combo)
        net_row.addStretch()
        mode_layout.addLayout(net_row)

        btn_row = QHBoxLayout()
        self._btn_toggle_server = QPushButton("Start Web Server")
        self._btn_toggle_server.setStyleSheet("font-weight: bold; padding: 6px 14px;")
        self._btn_toggle_server.clicked.connect(self._on_toggle_server)
        btn_row.addWidget(self._btn_toggle_server)

        self._btn_check_conn = QPushButton("Check from this computer")
        self._btn_check_conn.clicked.connect(self._on_check_connection)
        btn_row.addWidget(self._btn_check_conn)
        btn_row.addStretch()
        mode_layout.addLayout(btn_row)

        layout.addWidget(mode_box)

        # ── 2. Security & Permissions ─────────────────────────────────────────
        sec_box = QGroupBox("Security & Permissions")
        sec_layout = QVBoxLayout(sec_box)

        pwd_row = QHBoxLayout()
        self._pwd_status_lbl = QLabel("Password: Not set")
        pwd_row.addWidget(self._pwd_status_lbl, stretch=1)
        self._btn_set_pwd = QPushButton("Set Password…")
        self._btn_set_pwd.clicked.connect(self._on_set_password)
        pwd_row.addWidget(self._btn_set_pwd)
        sec_layout.addLayout(pwd_row)

        self._cb_allow_changes = QCheckBox("Allow remote devices to edit status, ratings, and notes")
        sec_layout.addWidget(self._cb_allow_changes)

        self._cb_allow_cloud = QCheckBox("Allow web server to download cloud books on demand")
        sec_layout.addWidget(self._cb_allow_cloud)

        layout.addWidget(sec_box)

        # ── 3. Device Pairing (QR Code) ───────────────────────────────────────
        pair_box = QGroupBox("Pair a Mobile Device")
        pair_layout = QHBoxLayout(pair_box)

        self._qr_label = QLabel()
        self._qr_label.setFixedSize(160, 160)
        self._qr_label.setStyleSheet("border: 1px dashed var(--border-color); background: white;")
        self._qr_label.setAlignment(Qt.AlignCenter)
        pair_layout.addWidget(self._qr_label)

        qr_info_layout = QVBoxLayout()
        qr_info_layout.addWidget(QLabel("<b>Scan QR code with your phone or tablet:</b>"))
        self._pair_url_lbl = QLabel("Start the server to generate pairing code.")
        self._pair_url_lbl.setWordWrap(True)
        self._pair_url_lbl.setStyleSheet("font-size: 11px; color: palette(window-text);")
        qr_info_layout.addWidget(self._pair_url_lbl)

        self._btn_gen_qr = QPushButton("Generate New Pairing Code")
        self._btn_gen_qr.clicked.connect(self._on_generate_pairing_qr)
        qr_info_layout.addWidget(self._btn_gen_qr)
        qr_info_layout.addStretch()
        pair_layout.addLayout(qr_info_layout)

        layout.addWidget(pair_box)

        # ── 4. Paired Devices Table ───────────────────────────────────────────
        dev_box = QGroupBox("Paired Devices")
        dev_layout = QVBoxLayout(dev_box)
        self._dev_table = QTableWidget(0, 4)
        self._dev_table.setHorizontalHeaderLabels(["Name", "Last Seen", "Last IP", "Actions"])
        self._dev_table.horizontalHeader().setStretchLastSection(True)
        self._dev_table.setFixedHeight(140)
        dev_layout.addWidget(self._dev_table)
        layout.addWidget(dev_box)

        # ── 5. OPDS Key ───────────────────────────────────────────────────────
        opds_box = QGroupBox("OPDS eReader Access")
        opds_layout = QVBoxLayout(opds_box)
        opds_row = QHBoxLayout()
        opds_row.addWidget(QLabel("OPDS Key:"))
        self._opds_key_lbl = QLabel("••••••••")
        opds_row.addWidget(self._opds_key_lbl, stretch=1)

        self._btn_show_opds = QPushButton("Show Key")
        self._btn_show_opds.clicked.connect(self._on_toggle_show_opds)
        opds_row.addWidget(self._btn_show_opds)

        self._btn_regen_opds = QPushButton("Regenerate")
        self._btn_regen_opds.clicked.connect(self._on_regenerate_opds)
        opds_row.addWidget(self._btn_regen_opds)
        opds_layout.addLayout(opds_row)

        opds_info = QLabel("Use username <b>booklib</b> and your OPDS key in reading apps (e.g. Moon+ Reader, FBReader, Marvin).")
        opds_info.setStyleSheet("font-size: 11px; color: palette(window-text);")
        opds_layout.addWidget(opds_info)
        layout.addWidget(opds_box)

        layout.addStretch()

    # ── State & Config Management ─────────────────────────────────────────────

    def _load_settings(self) -> None:
        has_pwd = bool(self._repo.get_app_meta("web.password_hash"))
        self._pwd_status_lbl.setText("Password: Configured" if has_pwd else "Password: Not set (Open)")

        self._cb_allow_changes.setChecked(self._repo.get_app_meta("web.allow_changes", "0") == "1")
        self._cb_allow_cloud.setChecked(self._repo.get_app_meta("web.allow_cloud", "0") == "1")

        self._cb_allow_changes.toggled.connect(lambda c: self._repo.set_app_meta("web.allow_changes", "1" if c else "0"))
        self._cb_allow_cloud.toggled.connect(lambda c: self._repo.set_app_meta("web.allow_cloud", "1" if c else "0"))

        self._update_server_status_ui()

    def _update_server_status_ui(self) -> None:
        running = self._sm.is_web_server_running()
        if running:
            self._status_lbl.setText("<span style='color:#16a34a; font-weight:bold;'>● Server Running</span>")
            self._btn_toggle_server.setText("Stop Web Server")
            self._btn_toggle_server.setStyleSheet("background-color: #ef4444; color: white; font-weight:bold;")
        else:
            self._status_lbl.setText("<span style='color:#64748b; font-weight:bold;'>○ Server Stopped</span>")
            self._btn_toggle_server.setText("Start Web Server")
            self._btn_toggle_server.setStyleSheet("background-color: #3b82f6; color: white; font-weight:bold;")

    def _on_toggle_server(self) -> None:
        if self._sm.is_web_server_running():
            self._sm.stop_web_server()
            self._update_server_status_ui()
            self._pair_url_lbl.setText("Server stopped.")
            self._qr_label.clear()
        else:
            host = self._ip_combo.currentText().strip() or "127.0.0.1"
            port = self._port_spin.value()
            from booklib.config import DB_PATH
            ok = self._sm.start_web_server(host=host, port=port, db_path=str(DB_PATH))
            if ok:
                self._update_server_status_ui()
                self._on_generate_pairing_qr()
            else:
                QMessageBox.warning(self, "Error", "Could not start web server.")

    def _on_check_connection(self) -> None:
        import urllib.request
        port = self._port_spin.value()
        url = f"http://127.0.0.1:{port}/"
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                QMessageBox.information(
                    self, "Connection Test",
                    f"Server responded with HTTP status {resp.status} on port {port}."
                )
        except Exception as exc:
            QMessageBox.warning(
                self, "Connection Test Failed",
                f"Could not reach server at {url}.\nReason: {exc}"
            )

    def _on_set_password(self) -> None:
        pwd, ok = QInputDialog.getText(self, "Set Web Password", "Enter access password (min. 6 characters):", QLineEdit.Password)
        if ok:
            if len(pwd.strip()) < 6:
                QMessageBox.warning(self, "Error", "Password must be at least 6 characters.")
                return
            h, s = hash_password(pwd.strip())
            self._repo.set_app_meta("web.password_hash", h)
            self._repo.set_app_meta("web.password_salt", s)
            self._pwd_status_lbl.setText("Password: Configured")
            QMessageBox.information(self, "Password Set", "Web access password updated successfully.")

    def _on_generate_pairing_qr(self) -> None:
        """Generate one-time code and display QR code."""
        import qrcode
        host = self._ip_combo.currentText().strip() or "127.0.0.1"
        port = self._port_spin.value()

        code = "PAIRCODE"
        if self._sm._web_server_thread and hasattr(self._sm._web_server_thread, "_app"):
            app = self._sm._web_server_thread._app
            mgr = app.config.get("BOOKLIB_PAIRING_MGR")
            if mgr:
                code = mgr.create_code(ttl_seconds=300)

        pair_url = f"http://{host}:{port}/pair?code={code}"
        self._pair_url_lbl.setText(f"<b>URL:</b> {pair_url}<br><i>Valid for 5 minutes</i>")

        # Generate QR image
        qr = qrcode.QRCode(box_size=4, border=1)
        qr.add_data(pair_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        px = QPixmap()
        px.loadFromData(buffer.getvalue())
        self._qr_label.setPixmap(px.scaled(150, 150, Qt.KeepAspectRatio))

    def _refresh_device_list(self) -> None:
        devices = self._repo.list_web_devices()
        self._dev_table.setRowCount(len(devices))
        for row, dev in enumerate(devices):
            self._dev_table.setItem(row, 0, QTableWidgetItem(dev["name"]))
            self._dev_table.setItem(row, 1, QTableWidgetItem(dev["last_seen_at"] or "—"))
            self._dev_table.setItem(row, 2, QTableWidgetItem(dev["last_ip"] or "—"))

            if dev["revoked_at"]:
                btn = QLabel("Revoked")
                btn.setStyleSheet("color: var(--text-muted); font-size: 11px;")
                self._dev_table.setCellWidget(row, 3, btn)
            else:
                btn = QPushButton("Revoke")
                btn.setStyleSheet("font-size: 11px; color: #ef4444;")
                btn.clicked.connect(lambda _, did=dev["id"]: self._on_revoke_device(did))
                self._dev_table.setCellWidget(row, 3, btn)

    def _on_revoke_device(self, device_id: int) -> None:
        self._repo.revoke_web_device(device_id)
        self._refresh_device_list()

    def _on_toggle_show_opds(self) -> None:
        import secrets
        key = self._repo.get_app_meta("web.opds_key")
        if not key:
            key = secrets.token_hex(8)
            self._repo.set_app_meta("web.opds_key", key)

        if self._btn_show_opds.text() == "Show Key":
            self._opds_key_lbl.setText(f"<code>{key}</code>")
            self._btn_show_opds.setText("Hide Key")
        else:
            self._opds_key_lbl.setText("••••••••")
            self._btn_show_opds.setText("Show Key")

    def _on_regenerate_opds(self) -> None:
        import secrets
        key = secrets.token_hex(8)
        self._repo.set_app_meta("web.opds_key", key)
        self._opds_key_lbl.setText(f"<code>{key}</code>")
        self._btn_show_opds.setText("Hide Key")
        QMessageBox.information(self, "OPDS Key", f"New OPDS key generated: {key}")
