"""
Voice Cloner Engine for Google Drive to Voice Converter.
Provides:
1. Reference Voice Extraction & Speech Isolation (from uploaded audio or source video).
2. Voice Profile Acoustic Analysis (pitch F0 detection, gender identification, spectral balance).
3. Free & Instant Acoustic Voice Morphing (formant shifting, pitch matching, and EQ matching via DSP).
4. Generative AI Voice Cloning via ElevenLabs API (optional).
"""

import os
import wave
import struct
import math
import shutil
import logging
import asyncio
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Dict, Any, Tuple

try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
except Exception:
    pass

import requests
from pydub import AudioSegment
from pydub.silence import detect_nonsilent

from app.languages import LANGUAGES

logger = logging.getLogger("gdrive_voice_converter.cloner")


@dataclass
class VoiceProfile:
    f0: float  # Fundamental pitch in Hz
    gender: str  # "male" or "female"
    pitch_scale: float  # Scale factor relative to standard voice
    bass_gain_db: float  # Bass EQ adjustment (-6 to +6 dB)
    treble_gain_db: float  # Treble EQ adjustment (-6 to +6 dB)
    duration_sec: float
    source_name: str = "reference_audio"


def extract_reference_audio_from_video(
    video_path: Path,
    output_wav: Path,
    max_duration_sec: float = 30.0
) -> Optional[Path]:
    """
    Extracts the clearest vocal speech segment from an input video to use as a clone reference.
    """
    temp_wav = output_wav.with_suffix(".temp.wav")
    try:
        # Extract 16kHz mono audio from video
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            str(temp_wav)
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

        if not temp_wav.exists() or temp_wav.stat().st_size < 1000:
            return None

        sound = AudioSegment.from_wav(str(temp_wav))
        total_len = len(sound)

        # Detect non-silent speech intervals
        silence_thresh = max(-50.0, sound.dBFS - 10.0)
        intervals = detect_nonsilent(sound, min_silence_len=350, silence_thresh=silence_thresh)

        if intervals:
            # Find the longest continuous speech segment up to max_duration_sec
            best_seg = max(intervals, key=lambda iv: iv[1] - iv[0])
            start_ms = best_seg[0]
            end_ms = min(best_seg[1], start_ms + int(max_duration_sec * 1000))
            vocal_slice = sound[start_ms:end_ms]
        else:
            # Fallback to first N seconds
            vocal_slice = sound[:int(max_duration_sec * 1000)]

        # Ensure minimum 3 seconds for reliable pitch detection
        if len(vocal_slice) < 3000 and total_len >= 3000:
            vocal_slice = sound[:min(total_len, int(max_duration_sec * 1000))]

        vocal_slice.export(str(output_wav), format="wav")
        return output_wav

    except Exception as e:
        logger.warning(f"Failed to extract reference audio from video: {e}")
        return None
    finally:
        temp_wav.unlink(missing_ok=True)


def convert_to_clean_wav(input_path: Path, output_wav: Path) -> Path:
    """Converts any input audio file (mp3, m4a, ogg, etc.) to clean 16kHz mono WAV."""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        str(output_wav)
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return output_wav


def estimate_pitch_autocorr(wav_path: Path) -> Tuple[float, str]:
    """
    Estimates the speaker's fundamental frequency (F0) using autocorrelation.
    Returns (f0_hz, gender).
    """
    with wave.open(str(wav_path), "rb") as wf:
        sr = wf.getframerate()
        raw = wf.readframes(wf.getnframes())

    data = struct.unpack(f"<{len(raw)//2}h", raw)
    if len(data) == 0:
        return 130.0, "male"

    frame_size = int(0.04 * sr)  # 40ms window
    step = int(0.02 * sr)        # 20ms step
    min_lag = max(1, int(sr / 380))  # Up to 380 Hz
    max_lag = min(frame_size - 1, int(sr / 75))   # Down to 75 Hz

    pitches = []
    for start in range(0, len(data) - frame_size, step):
        frame = data[start:start + frame_size]
        energy = sum(s * s for s in frame)
        # Skip quiet/silent frames
        if energy < 1e7:
            continue

        best_corr = -1
        best_lag = -1
        for lag in range(min_lag, max_lag):
            corr = sum(frame[j] * frame[j + lag] for j in range(frame_size - lag))
            if corr > best_corr:
                best_corr = corr
                best_lag = lag

        if best_lag > 0:
            pitch = sr / best_lag
            if 70.0 <= pitch <= 400.0:
                pitches.append(pitch)

    if not pitches:
        return 135.0, "male"

    pitches.sort()
    median_f0 = pitches[len(pitches) // 2]
    gender = "female" if median_f0 >= 165.0 else "male"
    return median_f0, gender


def analyze_reference_voice(audio_path: Path) -> VoiceProfile:
    """
    Extracts acoustic profile of a voice sample:
    Pitch (F0), gender estimation, and spectral balance (EQ).
    """
    clean_wav = audio_path.with_suffix(".profile_clean.wav")
    try:
        convert_to_clean_wav(audio_path, clean_wav)
        sound = AudioSegment.from_wav(str(clean_wav))
        duration_sec = len(sound) / 1000.0

        f0, gender = estimate_pitch_autocorr(clean_wav)

        # Baseline pitches for Edge TTS voices
        base_f0 = 210.0 if gender == "female" else 125.0
        pitch_scale = max(0.75, min(1.35, f0 / base_f0))

        # Estimate rough spectral balance for EQ matching
        bass_gain = 0.0
        treble_gain = 0.0
        try:
            # Low frequencies (< 350 Hz) vs Mid-High (> 1500 Hz)
            low_pass = sound.low_pass_filter(350)
            high_pass = sound.high_pass_filter(1500)
            diff_low = low_pass.dBFS - sound.dBFS
            diff_high = high_pass.dBFS - sound.dBFS
            bass_gain = max(-4.0, min(4.0, (diff_low + 6.0) * 0.5))
            treble_gain = max(-4.0, min(4.0, (diff_high + 10.0) * 0.5))
        except Exception:
            pass

        profile = VoiceProfile(
            f0=f0,
            gender=gender,
            pitch_scale=pitch_scale,
            bass_gain_db=bass_gain,
            treble_gain_db=treble_gain,
            duration_sec=duration_sec,
            source_name=audio_path.name
        )
        logger.info(
            f"Voice Profile Analyzed: F0={f0:.1f}Hz, Gender={gender}, "
            f"PitchScale={pitch_scale:.2f}, Bass={bass_gain:+.1f}dB, Treble={treble_gain:+.1f}dB"
        )
        return profile

    except Exception as e:
        logger.error(f"Error analyzing voice sample: {e}")
        return VoiceProfile(
            f0=130.0,
            gender="male",
            pitch_scale=1.0,
            bass_gain_db=0.0,
            treble_gain_db=0.0,
            duration_sec=1.0
        )
    finally:
        clean_wav.unlink(missing_ok=True)


def get_best_base_voice(target_lang: str, gender: str) -> str:
    """Finds the best matching native neural voice for the specified language and gender."""
    lang_info = LANGUAGES.get(target_lang, {})
    voices = lang_info.get("voices", [])

    for v in voices:
        if v.get("gender", "").lower() == gender.lower():
            return v["id"]

    return lang_info.get("default_voice", "en-US-JennyNeural")


def clone_voice_elevenlabs(
    text: str,
    reference_audio_path: Path,
    output_path: Path,
    api_key: str,
    target_lang: Optional[str] = None
) -> bool:
    """
    Uses ElevenLabs Instant Voice Cloning API to clone reference audio and synthesize text.
    """
    try:
        headers = {"xi-api-key": api_key}
        
        # Step 1: Add/Clone Voice
        url_add_voice = "https://api.elevenlabs.io/v1/voices/add"
        with open(reference_audio_path, "rb") as f:
            files = [
                ("files", (reference_audio_path.name, f, "audio/mpeg"))
            ]
            data = {
                "name": f"Clone_{Path(reference_audio_path).stem[:12]}",
                "description": "DriveVoice AI Instant Voice Clone",
            }
            resp = requests.post(url_add_voice, headers=headers, data=data, files=files, timeout=30)

        if resp.status_code != 200:
            logger.warning(f"ElevenLabs Voice Add failed ({resp.status_code}): {resp.text}")
            return False

        voice_id = resp.json().get("voice_id")
        if not voice_id:
            return False

        # Step 2: Synthesize Text with Cloned Voice
        url_tts = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        tts_payload = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.50,
                "similarity_boost": 0.80,
                "style": 0.20,
                "use_speaker_boost": True
            }
        }
        tts_resp = requests.post(url_tts, headers={**headers, "Content-Type": "application/json"}, json=tts_payload, timeout=45)

        if tts_resp.status_code == 200:
            with open(output_path, "wb") as out_f:
                out_f.write(tts_resp.content)
            logger.info(f"ElevenLabs voice cloning successful for text length {len(text)}")
            return True
        else:
            logger.warning(f"ElevenLabs TTS failed ({tts_resp.status_code}): {tts_resp.text}")
            return False

    except Exception as e:
        logger.warning(f"ElevenLabs voice cloning error: {e}")
        return False


def apply_acoustic_voice_clone(
    input_tts_audio: Path,
    output_audio: Path,
    profile: VoiceProfile
) -> Path:
    """
    Applies high-resolution acoustic pitch-shifting, formant adaptation, and spectral EQ
    matching the reference voice profile.
    """
    p_scale = profile.pitch_scale
    filters = []

    # 1. Pitch & Formant adjustment via rubberband DSP
    # If rubberband pitch is close to 1.0 (within 3%), keep natural
    if abs(p_scale - 1.0) > 0.03:
        filters.append(f"rubberband=pitch={p_scale:.3f}:tempo=1.0:formant=shifted:pitchq=quality")

    # 2. Parametric EQ matching speaker's vocal resonance
    eq_parts = []
    if abs(profile.bass_gain_db) >= 0.5:
        eq_parts.append(f"equalizer=f=250:width_type=o:width=1.0:g={profile.bass_gain_db:.1f}")
    if abs(profile.treble_gain_db) >= 0.5:
        eq_parts.append(f"equalizer=f=3500:width_type=o:width=1.0:g={profile.treble_gain_db:.1f}")

    if eq_parts:
        filters.extend(eq_parts)

    filter_str = ",".join(filters) if filters else "anull"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_tts_audio),
        "-af", filter_str,
        str(output_audio)
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        if output_audio.exists() and output_audio.stat().st_size > 500:
            return output_audio
    except Exception as e:
        logger.warning(f"Acoustic morphing filter note ({e}), falling back to direct copy.")

    shutil.copy2(input_tts_audio, output_audio)
    return output_audio
