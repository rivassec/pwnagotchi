import logging
import subprocess
import time
import pwnagotchi.plugins as plugins
import pwnagotchi.ui.fonts as fonts
from pwnagotchi.ui.components import LabeledValue
from pwnagotchi.ui.view import BLACK

class BTTetherMulti(plugins.Plugin):
    __author__ = "rivassec"
    __version__ = "1.0"
    __license__ = "GPL3"
    __description__ = "Bluetooth Tether plugin with multiple phone fallback and WAN check"

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

    def on_loaded(self):
        logging.info("[BT-Tether-Multi] plugin loaded.")
        self.options = getattr(self, "options", {})
        self.phones = self.options.get("phones", [])
        if not self.phones:
            logging.error("[BT-Tether-Multi] No phones found in config.")
            self.ready = False
        else:
            logging.info(f"[BT-Tether-Multi] Phones configured: {self.phones}")
            self.ready = True

    def on_config_changed(self, config):
        self.phones = self.options.get("phones", [])
        self.ready = bool(self.phones)

    def _connect_phone(self, phone):
        if self.connecting:
            return False
        self.connecting = True

        phone_name = phone["name"] + " Network"
        ip = phone["ip"]
        mac = phone["mac"]
        phone_type = phone["type"].lower()
        gateway = {"android": "192.168.44.1", "ios": "172.20.10.1"}.get(phone_type)

        if not gateway:
            logging.error(f"[BT-Tether-Multi] Unsupported phone type: {phone_type}")
            self.connecting = False
            return False

        try:
            subprocess.run(
                ["nmcli", "connection", "delete", phone_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            subprocess.run(
                [
                    "nmcli", "connection", "add",
                    "type", "bluetooth",
                    "con-name", phone_name,
                    "bluetooth.type", "panu",
                    "bluetooth.bdaddr", mac,
                    "ipv4.method", "manual",
                    "ipv4.dns", "8.8.8.8 1.1.1.1",
                    "ipv4.addresses", f"{ip}/24",
                    "ipv4.gateway", gateway,
                    "ipv4.route-metric", "100",
                ],
                check=True,
            )

            subprocess.run(["nmcli", "connection", "up", phone_name], check=True)
            self.active_phone = phone
            logging.info(f"[BT-Tether-Multi] Connected to {phone_name}")
            self.connecting = False

            if not self._check_wan():
                logging.warning(f"[BT-Tether-Multi] No WAN detected after {phone_name}")
                self._disconnect_active()
                self.last_attempt = time.time()
                return False

            return True

        except subprocess.CalledProcessError as e:
            logging.warning(f"[BT-Tether-Multi] Failed to connect to {phone_name}: {e}")
            self.connecting = False
            return False

    def _disconnect_active(self):
        if self.active_phone:
            phone_name = self.active_phone["name"] + " Network"
            try:
                subprocess.run(["nmcli", "connection", "down", phone_name], check=True)
                logging.info(f"[BT-Tether-Multi] Disconnected from {phone_name}")
            except subprocess.CalledProcessError as e:
                logging.error(f"[BT-Tether-Multi] Failed to disconnect: {e}")
            self.active_phone = None

    def _check_wan(self):
        try:
            for ip in ["8.8.8.8", "1.1.1.1"]:
                if subprocess.call(["ping", "-c", "1", "-W", "2", ip],
                                   stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL) == 0:
                    return True
        except Exception as e:
            logging.error(f"[BT-Tether-Multi] WAN check failed: {e}")
        return False

    def on_ready(self, agent):
        if not self.ready:
            return
        for phone in self.phones:
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

        try:
            status_output = subprocess.run(
                ["bluetoothctl", "info"],
                capture_output=True,
                text=True
            ).stdout

            if "Connected: yes" in status_output:
                for phone in self.phones:
                    if phone["mac"].lower() in status_output.lower():
                        self.active_phone = phone
                        break

                if self.active_phone:
                    display_name = self.active_phone["name"].split()[0]
                    self.status = f"B:{display_name[:6]}"
                else:
                    self.status = "B:???"

                if time.time() - self.last_check > 120:
                    self.last_check = time.time()
                    if not self._check_wan():
                        logging.warning("[BT-Tether-Multi] WAN lost. Rotating phones.")
                        self._disconnect_active()
                        self.status = "..."
                        self.last_attempt = time.time()
                        for phone in self.phones:
                            if self._connect_phone(phone):
                                break
            else:
                self.status = "X"
                if time.time() - self.last_attempt > self.retry_delay:
                    self.status = "..."
                    self.last_attempt = time.time()
                    for phone in self.phones:
                        if self._connect_phone(phone):
                            break

        except Exception as e:
            logging.error(f"[BT-Tether-Multi] Error in UI update: {e}")
            self.status = "!"

        ui.set("bluetooth", self.status)

    def on_unload(self, ui):
        with ui._lock:
            ui.remove_element("bluetooth")
        self._disconnect_active()
