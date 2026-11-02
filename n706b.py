#!/usr/bin/env python3
import sys
import time
import argparse
import serial
import serial.tools.list_ports

def find_serial_port(default_port=None):
    """Automatically detect an available ttyUSB port if none is provided."""
    if default_port:
        return default_port
    
    ports = [p.device for p in serial.tools.list_ports.comports() if "ttyUSB" in p.device]
    if not ports:
        # Fallback to default Raspberry Pi USB serial port
        return "/dev/ttyUSB1"
    
    # Typically, the second port (ttyUSB1) serves as the AT command port
    for port in ports:
        if port.endswith("1"):
            return port
    return ports[0]

def send_at_command(ser, cmd, timeout=3.0, expect="OK"):
    """Send an AT command and verify the response."""
    full_cmd = (cmd + "\r\n").encode("utf-8")
    ser.reset_input_buffer()
    ser.write(full_cmd)
    
    start_time = time.time()
    response_lines = []
    
    while time.time() - start_time < timeout:
        if ser.in_waiting > 0:
            line = ser.readline().decode("utf-8", errors="replace").strip()
            if line:
                response_lines.append(line)
                if expect in line:
                    return True, response_lines
                if "ERROR" in line:
                    return False, response_lines
        time.sleep(0.05)
        
    return False, response_lines

def main():
    parser = argparse.ArgumentParser(description="Neoway N706 APN & USB-ECM Configuration Tool")
    parser.add_argument("apn", help="Target APN name (e.g., simplio.apn)")
    parser.add_argument("-p", "--port", default=None, help="Serial port (default: auto-detect or /dev/ttyUSB1)")
    parser.add_argument("-b", "--baud", default=115200, type=int, help="Baud rate (default: 115200)")
    args = parser.parse_args()

    port = find_serial_port(args.port)
    print(f"[*] Attempting to connect to serial port: {port} (Baudrate: {args.baud})")

    try:
        ser = serial.Serial(
            port=port,
            baudrate=args.baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=1.0
        )
    except Exception as e:
        print(f"[!] Failed to open serial port: {e}")
        sys.exit(1)

    print("[*] Synchronizing with module (AT)...")
    synced = False
    for _ in range(3):
        ok, _ = send_at_command(ser, "AT", timeout=1.0)
        if ok:
            synced = True
            break
        time.sleep(0.3)

    if not synced:
        print("[!] No response from module. Please verify port and power connection.")
        ser.close()
        sys.exit(1)

    # 1. Disable command echo
    send_at_command(ser, "ATE0", timeout=1.0)

    # 2. Check and configure USB ECM mode
    print("[1/5] Checking USB network mode (AT+NETSHAREMODE)...")
    ok, res = send_at_command(ser, "AT+NETSHAREMODE?", timeout=2.0)
    current_mode = None
    for line in res:
        if "+NETSHAREMODE:" in line:
            current_mode = line.split(":")[-1].strip()

    if current_mode != "1":
        print(f"[*] Configuring ECM mode (Current: {current_mode} -> Target: 1)...")
        ok, res = send_at_command(ser, "AT+NETSHAREMODE=1", timeout=3.0)
        if ok:
            print("[+] ECM mode successfully configured.")
        else:
            print(f"[!] Failed to configure ECM mode: {res}")
    else:
        print("[+] Already configured in ECM mode (1).")

    # 3. Configure APN via AT+CGDCONT
    print(f"[2/5] Setting APN to '{args.apn}' (AT+CGDCONT=1,\"IP\",\"{args.apn}\")...")
    ok, res = send_at_command(ser, f'AT+CGDCONT=1,"IP","{args.apn}"', timeout=3.0)
    if ok:
        print(f"[+] APN '{args.apn}' registered successfully.")
    else:
        print(f"[!] Failed to register APN: {res}")
        ser.close()
        sys.exit(1)

    # 4. Attach to network and activate PDP context
    print("[3/5] Attaching to packet service network (AT+CGATT=1)...")
    ok, _ = send_at_command(ser, "AT+CGATT=1", timeout=10.0)
    if ok:
        print("[+] Packet network attach successful.")
    else:
        print("[!] Warning: AT+CGATT=1 timed out or failed. Continuing...")

    print("[4/5] Activating PDP context (AT+CGACT=1,1)...")
    ok, res = send_at_command(ser, "AT+CGACT=1,1", timeout=30.0)
    if ok:
        print("[+] PDP context activated.")
    else:
        print(f"[!] PDP context activation failed or already active: {res}")

    # 5. Set NET_STATUS LED indication pattern
    print("[5/5] Setting NET_STATUS LED mode (AT+SIGNAL=11)...")
    ok, res = send_at_command(ser, "AT+SIGNAL=11", timeout=3.0)
    if ok:
        print("[+] AT+SIGNAL=11 configured successfully.")
    else:
        print(f"[!] Failed to configure AT+SIGNAL=11: {res}")

    ser.close()
    print("\n[SUCCESS] Configuration finished.")
    print("To bring up the ECM network interface (e.g. usb0), run:")
    print("  sudo ip link set usb0 up")
    print("  sudo udhcpc -i usb0   (or: sudo dhclient usb0)")

if __name__ == "__main__":
    main()