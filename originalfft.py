import struct
import numpy as np


def extract_adc_stream(filename):
    adc_bytes = bytearray()

    with open(filename, "rb") as f:
        # Skip file header
        magic = f.read(8)
        if magic != b"DCAUDP1\x00":
            raise ValueError("Invalid file")

        while True:
            # Read packet header
            ts = f.read(8)
            if len(ts) < 8:
                break

            packet_len = struct.unpack("<I", f.read(4))[0]

            payload = f.read(packet_len)
            if len(payload) < packet_len:
                break

            # Extract ADC payload (skip DCA1000 header)
            adc_payload = payload[10:]

            adc_bytes.extend(adc_payload)

    return np.frombuffer(adc_bytes, dtype=np.int16)


def to_complex(adc_int16):
    """
    Convert raw int16 ADC stream into complex samples.

    IMPORTANT (based on your data format):
    -------------------------------------
    The incoming data is NOT standard [I, Q, I, Q, ...].

    Instead, it is packed like:
        [I0, I1, Q0, Q1,  I2, I3, Q2, Q3, ...]

    So each group of 4 values contains:
        - 2 consecutive I samples
        - followed by 2 corresponding Q samples

    We must rearrange this into proper IQ pairs:
        (I0 + jQ0), (I1 + jQ1), ...

    This is the ONLY modification done.
    """

    # Ensure total length is divisible by 4 (required for this format)
    usable_len = (len(adc_int16) // 4) * 4  #divide and take whole number as result
    adc_int16 = adc_int16[:usable_len]

    # Step 1: Reshape into blocks of 4 → [I0 I1 Q0 Q1]
    data = adc_int16.reshape(-1, 4)

    # Step 2: Extract I and Q separately
    # I columns → first 2 values
    I = data[:, 0:2].reshape(-1)

    # Q columns → next 2 values
    Q = data[:, 2:4].reshape(-1)

    # Step 3: Form complex samples
    complex_samples = I + 1j * Q

    return complex_samples
    
NUM_RX = 4
NUM_SAMPLES = 256

def reshape_radar_cube(complex_samples):
    total_samples = len(complex_samples)

    samples_per_chirp = NUM_RX * NUM_SAMPLES

    num_chirps = total_samples // samples_per_chirp

    trimmed = complex_samples[:num_chirps * samples_per_chirp]

    cube = trimmed.reshape(num_chirps, NUM_RX, NUM_SAMPLES)
    print(f"There are {total_samples} samples in total. With {samples_per_chirp} samples per chirp and {num_chirps} total chirps")

    return cube
    
def range_fft(cube):
    window = np.hanning(cube.shape[2])

    windowed = cube * window

    fft_out = np.fft.fft(windowed, axis=2)

    return fft_out
    
import matplotlib.pyplot as plt

def plot_range_profile(fft_cube):
    rp0 = np.abs(fft_cube[0, 0, :])
    rp1 = np.abs(fft_cube[0, 1, :])
    rp2 = np.abs(fft_cube[0, 2, :])
    rp3 = np.abs(fft_cube[0, 3, :])

    num_bins0 = len(rp0) // 2 #First half of FFT → valid ranges ;Second half → mirror (negative frequencies)
    num_bins1 = len(rp1) // 2
    num_bins2 = len(rp2) // 2
    num_bins3 = len(rp3) // 2
    
    plt.subplot(2, 2, 1)
    plt.plot(ranges[:num_bins0], rp0[:num_bins0])
    plt.title("RX0")
    plt.xlabel("Range in metre")
    plt.ylabel("Magnitude")
    plt.grid()

    plt.subplot(2, 2, 2)
    plt.plot(ranges[:num_bins1], rp1[:num_bins1])
    plt.title("RX1")
    plt.xlabel("Range in metre")
    plt.ylabel("Magnitude")
    plt.grid()

    plt.subplot(2, 2, 3)
    plt.plot(ranges[:num_bins2], rp2[:num_bins2])
    plt.title("RX2")
    plt.xlabel("Range in metre")
    plt.ylabel("Magnitude")
    plt.grid()

    plt.subplot(2, 2, 4)
    plt.plot(ranges[:num_bins3], rp3[:num_bins3])
    plt.title("RX3")
    plt.xlabel("Range in metre")
    plt.ylabel("Magnitude")
    plt.grid()

    plt.tight_layout()
    plt.show()

import matplotlib
#matplotlib.use('Agg')

import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.animation import FFMpegWriter

def animate_line_mp4(fft_cube, ranges,name):
    fig, ax = plt.subplots()

    num_bins = fft_cube.shape[2] // 2

    # Find bins within 0–n meters
    max_range = 5 # meters
    valid_bins = np.where(ranges <= max_range)[0]
    max_bin = valid_bins[-1]

    #  Precompute global max ONLY for this region
    global_max = np.max(np.abs(fft_cube[:, 0, :max_bin]))

    line, = ax.plot(ranges[:max_bin], np.zeros(max_bin))

    #  Fix axes
    ax.set_xlim(0, max_range)
    ax.set_ylim(0, global_max * 1.2)

    ax.set_xlabel("Range (m)")
    ax.set_ylabel("Magnitude")

    def update(i):
        rp = np.abs(fft_cube[i, 0, :max_bin])
        line.set_ydata(rp)

        ax.set_title(f"Chirp {i}")
        return line,

    ani = animation.FuncAnimation(
        fig,
        update,
        frames=range(0, fft_cube.shape[0], 20)
    )

    writer = FFMpegWriter(fps=10)
    ani.save(name, writer=writer)

    plt.close(fig)
    
def plot_range_time_heatmap(fft_cube, ranges):
    num_chirps = fft_cube.shape[0]
    num_bins = fft_cube.shape[2] // 2

    # Limit to 0–n meters
    max_range = 3
    valid_bins = np.where(ranges <= max_range)[0]
    max_bin = valid_bins[-1]

    #  Build heatmap matrix
    heatmap = np.abs(fft_cube[:, 0, :max_bin])

    #  Optional: remove static clutter (VERY IMPORTANT)
    heatmap = heatmap - np.mean(heatmap, axis=0, keepdims=True)

    #  Convert to dB scale (better visualization)
    heatmap = 20 * np.log10(np.abs(heatmap) + 1e-6)

    #  Plot
    plt.figure(figsize=(10, 6))

    plt.imshow(
        heatmap,
        aspect='auto',
        extent=[0, max_range, 0, num_chirps],
        origin='lower'
    )

    plt.colorbar(label="Magnitude (dB)")
    plt.xlabel("Range (m)")
    plt.ylabel("Chirp Index (Time)")
    plt.title("Range-Time Heatmap")

    plt.tight_layout()
    plt.show()
    
adc_int16 = extract_adc_stream("may292nddata.dcaudp")

complex_samples = to_complex(adc_int16)

cube = reshape_radar_cube(complex_samples)

fft_cube = range_fft(cube)

c = 3e8

slope = 29.982e12       # Hz/s
ramp_time = 54e-6       # seconds, changed this to 60 us
B = slope * ramp_time
#range_res = c / (2 * B)

N = 256
fs = 10e6

range_res = (c * fs) / (2 * slope * N)

num_bins = fft_cube.shape[2]

ranges = np.arange(num_bins) * range_res

#plot_range_profile(fft_cube)
#print(len(complex_samples) / (NUM_RX * NUM_SAMPLES))

# CALL
animate_line_mp4(fft_cube, ranges,"vid_test_may292nddata.mp4")

#plot_range_time_heatmap(fft_cube, ranges)


