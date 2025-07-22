import logging
import shutil
import time
import re
import subprocess  # nosec
import pwnagotchi.plugins as plugins
import pwnagotchi.ui.fonts as fonts
from pwnagotchi.ui.components import LabeledValue
from pwnagotchi.ui.view import BLACK


class BTTetherMulti(plugins.Plugin):
    __author__ = "rivassec"
    __version__ = "1.2-secure"
    __license__ = "GPL3"
    __description__ = (
        "Bluetooth Tether plugin with multiple phone fallback and WAN check"
    )

    def __init__(self):
        self.ready = False
        self.options = {}
        self.phones = []
        self.status = "!"
        self.active_phone = None
        self.last_attempt = 0
        self.last_check = 0
        self.connecting = False
        self.retry_delay = 120
        self.failed_attempts = {}

        self.nmcli = shutil.which("nmcli")
        self.bluetoothctl = shutil.which("bluetoothctl")
        self.curl = shutil.which("curl")

    def on_loaded(self):
        logging.info("[BT-Tether-Multi] plugin loaded.")
        self.options = getattr(self, "options", {})
        self.phones = self.options.get("phones") or getattr(self, "phones", [])
        self._validate_phones()

    def on_config_changed(self, config):
        self.options = getattr(self, "options", {})
        self.phones = self.options.get("phones") or getattr(self, "phones", [])
        self._validate_phones()

    def _safe_run(self, cmd, **kwargs):
        try:
            subprocess.run(cmd, check=True, **kwargs)  # nosec
            return True
        except subprocess.CalledProcessError as e:
            logging.warning(f"[BT-Tether-Multi] Command failed: {' '.join(cmd)} - {e}")
            return False
        except Exception as e:
            logging.error(
                f"[BT-Tether-Multi] Unexpected error running {' '.join(cmd)}: {e}"
            )
            return False

    def _safe_call(self, cmd, **kwargs):
        try:
            return subprocess.call(cmd, **kwargs) == 0  # nosec
        except Exception as e:
            logging.error(f"[BT-Tether-Multi] Call failed: {' '.join(cmd)} - {e}")
            return False

    def _validate_phones(self):
        valid_phones = []
        for phone in self.phones:
            if not all(k in phone for k in ("name", "mac", "ip", "type")):
                logging.error(f"[BT-Tether-Multi] Invalid phone config: {phone}")
                continue
            try:
                phone["mac"] = self._sanitize_mac(phone["mac"])
                phone["name"] = self._sanitize_name(phone["name"])
                valid_phones.append(phone)
            except ValueError as e:
                logging.error(f"[BT-Tether-Multi] Phone validation failed: {e}")
        self.phones = valid_phones
        self.ready = bool(self.phones)
        if self.ready:
            logging.info(
                f"[BT-Tether-Multi] Validated phones: {[p['name'] for p in self.phones]}"
            )
        else:
            logging.error("[BT-Tether-Multi] No valid phones found.")

    def _sanitize_mac(self, mac):
        if re.match(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$", mac):
            return mac.lower()
        raise ValueError(f"Invalid MAC address: {mac}")

    def _sanitize_name(self, name):
        name = name.strip()
        if re.match(r"^[\w\s\-]{1,32}$", name):
            return name
        raise ValueError(f"Invalid phone name: {name}")

    def _connect_phone(self, phone):
        if self.connecting or not self.nmcli:
            return False

        phone_name = phone["name"] + " Network"
        ip = phone["ip"]
        mac = phone["mac"]
        phone_type = phone["type"].lower()
        gateway = {"android": "192.168.44.1", "ios": "172.20.10.1"}.get(phone_type)

        if not gateway:
            logging.error(f"[BT-Tether-Multi] Unsupported phone type: {phone_type}")
            return False

        self.connecting = True
        try:
            subprocess.run(
                [self.nmcli, "connection", "delete", phone_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )  # nosec

            if not self._safe_run(
                [
                    self.nmcli,
                    "connection",
                    "add",
                    "type",
                    "bluetooth",
                    "con-name",
                    phone_name,
                    "bluetooth.type",
                    "panu",
                    "bluetooth.bdaddr",
                    mac,
                    "ipv4.method",
                    "manual",
                    "ipv4.dns",
                    "8.8.8.8 1.1.1.1",
                    "ipv4.addresses",
                    f"{ip}/24",
                    "ipv4.gateway",
                    gateway,
                    "ipv4.route-metric",
                    "100",
                ]
            ):
                return False

            if not self._safe_run([self.nmcli, "connection", "up", phone_name]):
                return False

            if not self._check_wan():
                logging.warning(
                    f"[BT-Tether-Multi] No WAN after connecting to {phone_name}"
                )
                self._disconnect_active()
                self.last_attempt = time.time()
                self.failed_attempts[mac] = self.failed_attempts.get(mac, 0) + 1
                return False

            self.active_phone = phone
            self.failed_attempts[mac] = 0
            logging.info(f"[BT-Tether-Multi] Connected to {phone_name}")
            return True

        finally:
            self.connecting = False

    def _disconnect_active(self):
        if self.active_phone and self.nmcli:
            phone_name = self.active_phone["name"] + " Network"
            self._safe_run([self.nmcli, "connection", "down", phone_name])
            logging.info(f"[BT-Tether-Multi] Disconnected from {phone_name}")
            self.active_phone = None

    def _check_wan(self):
        if not self.curl:
            return False
        return self._safe_call(
            [self.curl, "-sSf", "--max-time", "3", "https://www.google.com"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def on_ready(self, agent):
        if not self.ready:
            return
        for phone in self.phones:
            mac = phone["mac"]
            if self.failed_attempts.get(mac, 0) >= 3:
                continue
            if self._connect_phone(phone):
                break

    def on_ui_setup(self, ui):
        with ui._lock:
            ui.add_element(
                "bluetooth",
                LabeledValue(
                    color=BLACK,
                    label="BT",
                    value=self.status,
                    position=(ui.width() / 2 - 10, 0),
                    label_font=fonts.Bold,
                    text_font=fonts.Small,
                ),
            )

    def on_ui_update(self, ui):
        if time.time() - self.last_attempt < self.retry_delay:
            return

        if not self.ready:
            self.status = "!"
            ui.set("bluetooth", self.status)
            return

        if not self.bluetoothctl:
            self.status = "X"
            ui.set("bluetooth", self.status)
            return

        try:
            result = subprocess.run(
                [self.bluetoothctl, "info"],
                capture_output=True,
                text=True,
                check=True,
            )  # nosec
            output = result.stdout

            if "Connected: yes" in output:
                for phone in self.phones:
                    if phone["mac"] in output.lower():
                        self.active_phone = phone
                        break

                if self.active_phone:
                    display_name = re.sub(
                        r"[^\w\-]", "", self.active_phone["name"].split()[0]
                    )
                    self.status = f"B:{display_name[:6]}"
                else:
                    self.status = "B:???"

                if time.time() - self.last_check > 120:
                    self.last_check = time.time()
                    if not self._check_wan():
                        logging.warning("[BT-Tether-Multi] WAN lost, rotating phones.")
                        self._disconnect_active()
                        self.status = "..."
                        self.last_attempt = time.time()
                        for phone in self.phones:
                            mac = phone["mac"]
                            if self.failed_attempts.get(mac, 0) >= 3:
                                continue
                            if self._connect_phone(phone):
                                break
            else:
                self.status = "X"
                if time.time() - self.last_attempt > self.retry_delay:
                    self.status = "..."
                    self.last_attempt = time.time()
                    for phone in self.phones:
                        mac = phone["mac"]
                        if self.failed_attempts.get(mac, 0) >= 3:
                            continue
                        if self._connect_phone(phone):
                            break

        except subprocess.CalledProcessError as e:
            logging.error(f"[BT-Tether-Multi] bluetoothctl failed: {e}")
            self.status = "!"
        except Exception as e:
            logging.error(f"[BT-Tether-Multi] UI update error: {e}")
            self.status = "!"

        ui.set("bluetooth", self.status)

    def on_unload(self, ui):
        with ui._lock:
            ui.remove_element("bluetooth")
        self._disconnect_active()
