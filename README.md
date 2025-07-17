# bt-tether-multi

This is a custom Pwnagotchi plugin for Bluetooth tethering with multiple fallback phones and WAN verification.

## Features

- Rotates through multiple configured phones when internet is unavailable
- Pings both `8.8.8.8` and `1.1.1.1` to confirm WAN access
- Prioritizes phones based on the order in the configuration
- Prevents rapid looping with retry delay
- Displays current connection status in the UI

## Security Audit

This plugin was scanned with Bandit to detect common Python security issues. Only low-severity subprocess usage warnings (B404, B603, B607) were present and are explicitly excluded via the .bandit.yaml configuration file.
To re-run the scan:
    
   ```bash
   bandit -c .bandit.yaml plugins/bt-tether-multi.py
   ```
    
No high or medium severity issues were found.

## Installation

1. Place `bt-tether-multi.py` in the Pwnagotchi plugin directory:

   ```bash
   /usr/local/share/pwnagotchi/custom-plugins/bt-tether-multi.py
   ```

2. Edit `/etc/pwnagotchi/config.toml` and add:

   ```toml
   [main.plugins.bt-tether-multi]
   enabled = true
   phones = [
       { name = "PhoneA", mac = "00:11:22:33:44:55", ip = "192.168.44.45", type = "android" },
       { name = "PhoneB", mac = "AA:BB:CC:DD:EE:FF", ip = "192.168.44.146", type = "android" }
   ]

   main.custom_plugins = "/usr/local/share/pwnagotchi/custom-plugins/"
   ```

3. Restart Pwnagotchi or reload the plugin via webcfg.

## UI Display

The plugin shows the connection status at the top center of the screen:

- `B:<name>` — Connected to a known phone
- `...` — Trying to connect or rotating phones
- `X` — Disconnected
- `B:???` — Connected but phone not recognized
- `!` — Configuration or runtime error

## Notes

- Requires `nmcli` for connection management
- WAN is considered "up" if either `8.8.8.8` or `1.1.1.1` responds to a single ping
- Retry delay is enforced to reduce battery and system churn (default: 120 seconds)

## License

GPLv3

## Author

Plugin by [rivassec](https://github.com/rivassec)
