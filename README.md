# Radar Range FFT Pipeline (IWR1843 + DCA1000)

A complete Python-based radar signal processing pipeline for converting raw ADC data from TI IWR1843 mmWave radar + DCA1000 capture board into calibrated range profiles using FFT.

## Overview

Raw UDP ADC Data (.dcaudp) → Packet Parsing → IQ Reconstruction → Radar Cube Formation → Range FFT (Windowed) → Range Calibration → Visualization (MP4)

This project enables offline analysis of radar captures and forms the foundation for advanced processing like Doppler, CFAR, and AoA.

## System Architecture

- Radar Sensor: TI IWR1843BOOST  
- Capture Board: DCA1000EVM  
- Data Transfer: UDP over Ethernet (Port 4098)  
- Processing: Python (NumPy, Matplotlib)

## Input Data Format

### .dcaudp File Structure

[8B] Magic Header ("DCAUDP1\0")  
Repeat per packet:  
[8B] Timestamp (uint64)  
[4B] Packet Length (uint32)  
[N B] UDP Payload  

### UDP Payload

[4B] Sequence Number  
[6B] Byte Counter  
[N B] Raw ADC Data (int16)

### Why Packet-Based Storage?

- Detect dropped packets via sequence numbers  
- Ensure data continuity with byte counters  
- Preserve packet boundaries  
- Enable timestamp-based replay  

## IQ Reconstruction

Raw ADC data is not standard IQ interleaved.

Input pattern:  
[I₀ I₁ Q₀ Q₁] repeating

Conversion:

```python
data  = adc_int16.reshape(-1, 4)
I     = data[:, 0:2].reshape(-1)
Q     = data[:, 2:4].reshape(-1)
complex_samples = I + 1j * Q
```

## Radar Cube Formation

Structure: [chirps × RX antennas × samples] → [Nc × 4 × 256]

```python
cube = complex_samples.reshape(num_chirps, 4, 256)
```

## Range FFT Processing

Steps:

1. Apply Hanning window to reduce spectral leakage  
2. Perform FFT along fast-time axis  

```python
fft_cube = np.fft.fft(windowed, axis=2)
```

3. Keep first N/2 bins (positive frequencies only)

## Range Calibration

Incorrect formula:  
Δr = c / (2B)

Correct formula:  
Δr = (c × fs) / (2 × slope × N)

Where:
- c = 3×10^8 m/s  
- fs = ADC sampling rate  
- slope = chirp slope  
- N = FFT size  

Each FFT bin corresponds to one range step in meters.

## Visualization

Generates animated range profile (.mp4)

Features:
- Range axis in meters (calibrated)  
- Fixed amplitude scaling  
- Clutter removal (mean subtraction)  
- Frame skipping for smooth playback  

```python
ani = animation.FuncAnimation(...)
ani.save("output.mp4", writer=FFMpegWriter(fps=10))
```

## Achievements

- Custom .dcaudp parser  
- Correct IQ reconstruction ([I I Q Q] → complex)  
- Radar cube generation  
- Windowed Range FFT  
- Accurate range calibration  
- MP4 visualization output  

## Next Steps

- Doppler FFT: FFT across chirps for velocity estimation  

## Tech Stack

- Python  
- NumPy  
- Matplotlib  
- TI mmWave concepts  

## Notes

- Designed for offline ADC capture processing  
- Assumes 4 RX antennas and 256 samples per chirp  
- Easily adaptable to other configurations  


## License

MIT License (or your preferred license)
