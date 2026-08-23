#!/usr/bin/env python
"""Convert 2048-byte ISO sectors to PlayStation MODE2/2352 sectors."""

import argparse
import struct

verbose = False
sync = bytes([0x00, 0xff, 0xff, 0xff, 0xff, 0xff,
              0xff, 0xff, 0xff, 0xff, 0xff, 0x00])
subheader = bytes([0x00, 0x00, 0x08, 0x00,  0x00, 0x00, 0x08, 0x00])

def bcd(i):
    return int(i % 10) + 16 * (int(i / 10) % 10)


def convert_iso_to_bin(source, destination, *, calculate_edc=False):
    calculator = None
    if calculate_edc:
        import crc

        config = crc.Configuration(
            width=32,
            polynomial=0x8001801b,
            init_value=0x00,
            final_xor_value=0x00,
            reverse_input=True,
            reverse_output=True,
        )
        calculator = crc.Calculator(config, optimized=True)

    address = bytearray(4)
    minute, second, frame = 0, 2, 0
    with open(source, "rb") as input_file, open(destination, "wb") as output_file:
        for data in iter(lambda: input_file.read(2048), b""):
            if len(data) != 2048:
                raise ValueError("ISO size is not a multiple of 2048")
            output_file.write(sync)
            struct.pack_into(
                "<BBBB",
                address,
                0,
                bcd(minute),
                bcd(second),
                bcd(frame),
                2,
            )
            output_file.write(address)
            output_file.write(subheader)
            output_file.write(data)
            checksum = calculator.checksum(subheader + data) if calculator else 0
            output_file.write(struct.pack("<I", checksum))
            output_file.write(bytes(276))
            frame += 1
            if frame == 75:
                frame = 0
                second += 1
                if second == 60:
                    second = 0
                    minute += 1

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', action='store_true', help='Verbose')
    parser.add_argument('--edc', action='store_true', help='Generate ErrorCorrectionCode')
    parser.add_argument('iso', help='Iso image')
    parser.add_argument('basename', help='Name of output file(s)')
    args = parser.parse_args()

    verbose = args.v
    convert_iso_to_bin(
        args.iso,
        args.basename + ".bin",
        calculate_edc=args.edc,
    )
    print('Wrote:', args.basename + '.bin')
    with open(args.basename + '.cue', "w") as o:
        o.write('FILE "' + args.basename + '.bin' + '" BINARY\n')
        o.write('  TRACK 01 MODE2/2352\n')
        o.write('    INDEX 01 00:00:00\n')
    print('Wrote:', args.basename + '.cue')
