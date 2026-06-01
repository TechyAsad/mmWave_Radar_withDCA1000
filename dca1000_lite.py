#!/usr/bin/env python3

import argparse
import os
import socket
import struct
import time


PC_IP = "192.168.33.30"
DCA_IP = "192.168.33.180"

CFG_PORT = 4096
DATA_PORT = 4098

MAGIC_HEADER = 0xA55A
MAGIC_FOOTER = 0xEEAA

CMD_RESET_FPGA = 0x01
CMD_CONFIG_FPGA = 0x03
CMD_RECORD_START = 0x05
CMD_RECORD_STOP = 0x06
CMD_SYSTEM_CONNECTION = 0x09
CMD_CONFIG_PACKET_DELAY = 0x0B
CMD_READ_FPGA_VERSION = 0x0E


def build_cmd(cmd, payload=b""):
    return (
        struct.pack("<HHH", MAGIC_HEADER, cmd, len(payload))
        + payload
        + struct.pack("<H", MAGIC_FOOTER)
    )


def parse_status(reply):
    if len(reply) < 8:
        raise RuntimeError(f"short reply: {reply.hex()}")

    header, cmd, status, footer = struct.unpack_from("<HHHH", reply, 0)

    if header != MAGIC_HEADER or footer != MAGIC_FOOTER:
        raise RuntimeError(f"bad reply: {reply.hex()}")

    return cmd, status


class DCA1000Lite:
    def __init__(self, pc_ip=PC_IP, dca_ip=DCA_IP, cfg_port=CFG_PORT, timeout=2.0):
        self.pc_ip = pc_ip
        self.dca_ip = dca_ip
        self.cfg_port = cfg_port

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((pc_ip, cfg_port))
        self.sock.settimeout(timeout)

    def close(self):
        self.sock.close()

    def send(self, cmd, payload=b"", expect_success=True):
        pkt = build_cmd(cmd, payload)
        self.sock.sendto(pkt, (self.dca_ip, self.cfg_port))

        reply, _ = self.sock.recvfrom(2048)
        rcmd, status = parse_status(reply)

        if rcmd != cmd:
            raise RuntimeError(f"wrong reply cmd: got 0x{rcmd:02x}, expected 0x{cmd:02x}")

        if expect_success and status != 0:
            raise RuntimeError(f"cmd 0x{cmd:02x} failed, status={status}, reply={reply.hex()}")

        return status, reply

    def read_fpga_version(self):
        status, _ = self.send(CMD_READ_FPGA_VERSION, expect_success=False)
        major = status & 0x7F
        minor = (status >> 7) & 0x7F
        playback = bool(status & 0x4000)
        print(f"fpga_version: major={major}, minor={minor}, playback={playback}")

    def system_connection(self):
        self.send(CMD_SYSTEM_CONNECTION)
        print("system_connection: ok")

    def reset_fpga(self):
        self.send(CMD_RESET_FPGA)
        print("reset_fpga: ok")

    def config_fpga(self, lvds_mode=2, data_format_mode=3):
        payload = struct.pack(
            "<BBBBBB",
            1,                 # raw data logging
            lvds_mode,         # 2 = 2-lane, 1 = 4-lane
            1,                 # LVDS capture
            2,                 # ethernet stream
            data_format_mode,  # 3 = 16-bit
            30,                # timer seconds
        )
        self.send(CMD_CONFIG_FPGA, payload)
        print("config_fpga: ok")

    def config_packet_delay(self, packet_size=1472, delay_us=5):
        payload = struct.pack("<HHH", packet_size, delay_us, 0)
        self.send(CMD_CONFIG_PACKET_DELAY, payload)
        print(f"config_packet_delay: ok packet_size={packet_size} delay_us={delay_us}")

    def start_record(self):
        self.send(CMD_RECORD_START)
        print("start_record: ok")

    def stop_record(self):
        self.send(CMD_RECORD_STOP)
        print("stop_record: ok")


def open_data_socket(pc_ip=PC_IP, data_port=DATA_PORT, rcvbuf_mb=64):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, rcvbuf_mb * 1024 * 1024)
    sock.bind((pc_ip, data_port))
    sock.settimeout(0.5)   # 👈 ADD THIS
    return sock


def open_packet_dump(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    f = open(path, "wb")

    # File format:
    # magic: 8 bytes = b"DCAUDP1\0"
    # repeated records:
    #   uint64 little-endian timestamp_ns
    #   uint32 little-endian packet_length
    #   packet_length bytes raw UDP payload
    f.write(b"DCAUDP1\0")
    return f


def live_capture(args):
    data_sock = open_data_socket(args.pc_ip, args.data_port, args.rcvbuf_mb)
    dca = DCA1000Lite(args.pc_ip, args.dca_ip, args.cfg_port)

    dump_file = None
    if args.out:
        dump_file = open_packet_dump(args.out)
        print(f"saving raw UDP packets to: {args.out}")

    try:
        dca.read_fpga_version()
        dca.system_connection()
        dca.reset_fpga()
        time.sleep(0.2)
        dca.config_fpga(lvds_mode=args.lvds_mode, data_format_mode=args.data_format_mode)
        dca.config_packet_delay(packet_size=args.packet_size, delay_us=args.delay_us)
        dca.start_record()

        print("\nNow press Trigger Frame in mmWave Studio.")
        print("Listening for UDP ADC packets on port", args.data_port)
        print("Ctrl+C stops DCA recording cleanly.\n")

        buf = bytearray(4096)
        view = memoryview(buf)

        count = 0
        lost = 0
        last_seq = None
        total_udp_bytes = 0
        t0 = time.time()

        while True:
            try:
                nbytes, _ = data_sock.recvfrom_into(view)
            except socket.timeout:
                continue   # allows Ctrl+C to be processed
            
            now_ns = time.time_ns()

            if dump_file:
                dump_file.write(struct.pack("<QI", now_ns, nbytes))
                dump_file.write(view[:nbytes])

            if nbytes >= 10:
                seq = struct.unpack_from("<I", view, 0)[0]

                if last_seq is not None:
                    expected = last_seq + 1
                    if seq != expected and seq > expected:
                        lost += seq - expected

                last_seq = seq

            count += 1
            total_udp_bytes += nbytes

            if count % args.print_every == 0:
                if dump_file:
                    dump_file.flush()

                dt = max(time.time() - t0, 1e-9)
                mb = total_udp_bytes / (1024 * 1024)
                print(
                    f"pkts={count} "
                    f"last_seq={last_seq} "
                    f"lost={lost} "
                    f"rate={count/dt:.1f} pkt/s "
                    f"data={mb:.2f} MiB "
                    f"last_size={nbytes}"
                )

            if args.max_packets and count >= args.max_packets:
                print(f"max_packets reached: {args.max_packets}")
                break

    except KeyboardInterrupt:
        print("\nCtrl+C received.")

    finally:
        print("Stopping DCA1000...")
        try:
            dca.stop_record()
        except Exception as e:
            print("stop failed:", e)

        if dump_file:
            dump_file.flush()
            os.fsync(dump_file.fileno())
            dump_file.close()
            print(f"saved: {args.out}")

        dca.close()
        data_sock.close()


def control_only(args):
    dca = DCA1000Lite(args.pc_ip, args.dca_ip, args.cfg_port)
    try:
        if args.cmd == "stop":
            dca.stop_record()
        elif args.cmd == "start":
            dca.start_record()
        elif args.cmd == "init":
            dca.read_fpga_version()
            dca.system_connection()
            dca.reset_fpga()
            time.sleep(0.2)
            dca.config_fpga(lvds_mode=args.lvds_mode, data_format_mode=args.data_format_mode)
            dca.config_packet_delay(packet_size=args.packet_size, delay_us=args.delay_us)
    finally:
        dca.close()


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_common(x):
        x.add_argument("--pc-ip", default=PC_IP)
        x.add_argument("--dca-ip", default=DCA_IP)
        x.add_argument("--cfg-port", type=int, default=CFG_PORT)
        x.add_argument("--data-port", type=int, default=DATA_PORT)
        x.add_argument("--lvds-mode", type=int, default=2)
        x.add_argument("--data-format-mode", type=int, default=3)
        x.add_argument("--packet-size", type=int, default=1472)
        x.add_argument("--delay-us", type=int, default=5)

    x = sub.add_parser("live")
    add_common(x)
    x.add_argument("--rcvbuf-mb", type=int, default=64)
    x.add_argument("--print-every", type=int, default=1000)
    x.add_argument("--out", default=None, help="save raw UDP packets to this file")
    x.add_argument("--max-packets", type=int, default=0, help="stop after N packets; 0 = unlimited")

    for name in ["init", "start", "stop"]:
        y = sub.add_parser(name)
        add_common(y)

    args = p.parse_args()

    if args.cmd == "live":
        live_capture(args)
    else:
        control_only(args)


if __name__ == "__main__":
    main()
