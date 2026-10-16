"""Loudest input wins, per frequency band, per frame.

The library's nearest rule picks a winner for every single time-frequency cell. Where two
models disagree around the edge of a sound, that decision flips bin by bin, and every flip
brings the other model's phase with it - audible as a tear along the seam. Deciding once per
band per frame keeps a band's audio whole for that moment: the same idea, far fewer switches.

The length is preserved: the inverse transform is handed the input's own sample count, which
is the step the UVR path leaves out (it comes back 743 samples short on a real song).
"""

import numpy as np
import librosa

N_FFT = 2048
HOP = 1024

# Octave-ish edges, low to high. The top band runs to Nyquist, so the whole spectrum is covered
# whatever the sample rate.
BAND_EDGES = (20, 40, 80, 160, 320, 640, 1280, 2560, 5120, 10240, 20480)


def bands(freqs, rate):
    """The bin indices of each band, as a list, so a decision can be made per band."""
    edges = [edge for edge in BAND_EDGES if edge < rate / 2] + [rate / 2]
    out = []
    for low, high in zip(edges, edges[1:]):
        idx = np.flatnonzero((freqs >= low) & (freqs < high))
        if idx.size:
            out.append(idx)
    return out


def blend(waveforms, rate, loudest=True, n_fft=N_FFT, hop=HOP):
    """Blend ``[(channels, samples), ...]`` at ``rate``, returning one array of the same shape.

    ``loudest`` picks which way the band decision goes: True takes the louder input per band,
    False the quieter one. One input is the same as no blending at all, and is returned
    untouched.
    """
    if len(waveforms) == 1:
        return waveforms[0]

    length = max(wave.shape[-1] for wave in waveforms)
    waves = [wave if wave.shape[-1] == length
             else np.pad(wave, ((0, 0), (0, length - wave.shape[-1])))
             for wave in waveforms]
    channels = waves[0].shape[0]

    specs = np.stack([
        np.stack([librosa.stft(np.asfortranarray(wave[ch]), n_fft=n_fft, hop_length=hop)
                  for ch in range(channels)])
        for wave in waves
    ])                                             # (inputs, channels, bins, frames)

    # Both channels decide together, so a band cannot be taken from one input on the left and
    # another on the right - that would widen or tilt the stereo image at every switch.
    power = (np.abs(specs) ** 2).sum(axis=1)       # (inputs, bins, frames)

    freqs = librosa.fft_frequencies(sr=rate, n_fft=n_fft)
    out = np.zeros_like(specs[0])
    for band in bands(freqs, rate):
        band_power = power[:, band, :].sum(axis=1)         # (inputs, frames)
        decide = np.argmax if loudest else np.argmin
        pick = decide(band_power, axis=0)                  # (frames,) the chosen input
        chosen = np.take_along_axis(specs[:, :, band, :],
                                    pick.reshape(1, 1, 1, -1), axis=0)
        out[:, band, :] = chosen[0]

    return np.stack([librosa.istft(out[ch], hop_length=hop, length=length)
                     for ch in range(channels)])
