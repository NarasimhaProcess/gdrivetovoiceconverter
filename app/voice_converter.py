"""
Video Voice Converter Core.
Handles audio extraction, speech transcription, language translation,
neural TTS synthesis, duration tempo matching, audio mixing/ducking, and video remuxing.
"""

import os
import re
import json
import uuid
import shutil
import asyncio
import logging
import subprocess
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Dict, Any, Optional, Callable, List, Tuple

try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
except Exception:
    pass

import edge_tts
from gtts import gTTS
from pydub import AudioSegment
from pydub.silence import split_on_silence, detect_nonsilent
import speech_recognition as sr

from app.languages import LANGUAGES, get_language_folder_name

logger = logging.getLogger("gdrive_voice_converter")

# Speech recognition language code mapping for BCP-47 recognition
SPEECH_RECOGNITION_LANG_MAP: Dict[str, str] = {
    "auto": "en-IN",
    "en-IN": "en-IN",
    "en-US": "en-US",
    "en-GB": "en-GB",
    "hi": "hi-IN",
    "hi-IN": "hi-IN",
    "te": "te-IN",
    "te-IN": "te-IN",
    "ta": "ta-IN",
    "ta-IN": "ta-IN",
    "kn": "kn-IN",
    "kn-IN": "kn-IN",
    "ml": "ml-IN",
    "ml-IN": "ml-IN",
    "bn": "bn-IN",
    "bn-IN": "bn-IN",
    "mr": "mr-IN",
    "mr-IN": "mr-IN",
    "gu": "gu-IN",
    "gu-IN": "gu-IN",
    "pa": "pa-IN",
    "pa-IN": "pa-IN",
    "ur": "ur-IN",
    "ur-IN": "ur-IN",
}


def get_candidate_languages(source_lang: Optional[str] = None, target_lang: Optional[str] = None) -> List[str]:
    """Builds prioritized candidate languages for speech recognition cascade."""
    candidates = []
    if source_lang and source_lang != "auto":
        code = SPEECH_RECOGNITION_LANG_MAP.get(source_lang, source_lang)
        if code not in candidates:
            candidates.append(code)

    # Primary cascade: en-IN (Indian English is predominant in tech/demos), en-US
    for l in ["en-IN", "en-US"]:
        if l not in candidates:
            candidates.append(l)

    # Add target language if recognized
    if target_lang and target_lang in SPEECH_RECOGNITION_LANG_MAP:
        t_code = SPEECH_RECOGNITION_LANG_MAP[target_lang]
        if t_code not in candidates:
            candidates.append(t_code)

    # Add major regional languages in cascade
    for l in ["te-IN", "hi-IN", "ta-IN", "kn-IN"]:
        if l not in candidates:
            candidates.append(l)

    return candidates


def detect_speech_intervals(sound: AudioSegment, min_silence_len: int = 400, silence_thresh: Optional[float] = None) -> List[Tuple[int, int]]:
    """
    Detects non-silent intervals where speech occurs in milliseconds.
    Adapts threshold dynamically to the audio's dynamic range.
    """
    if len(sound) == 0:
        return []

    if silence_thresh is None:
        silence_thresh = max(-50.0, min(-24.0, sound.dBFS - 8.0))

    intervals = detect_nonsilent(sound, min_silence_len=min_silence_len, silence_thresh=silence_thresh)

    if not intervals:
        silence_thresh = max(-55.0, sound.dBFS - 5.0)
        intervals = detect_nonsilent(sound, min_silence_len=min_silence_len, silence_thresh=silence_thresh)

    if not intervals:
        return []

    # Merge intervals that are very close (less than 650ms apart) and filter out tiny non-speech clicks (< 350ms)
    merged = []
    for start, end in intervals:
        if end - start < 350:
            continue
        if not merged:
            merged.append([start, end])
        else:
            prev_start, prev_end = merged[-1]
            if start - prev_end < 650:
                merged[-1][1] = end
            else:
                merged.append([start, end])

    return [(m[0], m[1]) for m in merged]


def transcribe_audio_segment(
    sound_segment: AudioSegment,
    work_dir: Path,
    candidate_langs: List[str]
) -> str:
    """
    Transcribes an individual audio segment using a prioritized multi-language cascade.
    """
    seg_id = uuid.uuid4().hex[:8]
    tmp_path = work_dir / f"seg_trans_{seg_id}.wav"
    sound_segment.export(str(tmp_path), format="wav")

    r = sr.Recognizer()
    r.dynamic_energy_threshold = True

    recognized_text = ""
    try:
        with sr.AudioFile(str(tmp_path)) as src:
            audio_data = r.record(src)
        for lang_code in candidate_langs:
            try:
                txt = r.recognize_google(audio_data, language=lang_code)
                if txt and txt.strip():
                    recognized_text = txt.strip()
                    break
            except Exception:
                continue
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)

    return recognized_text


def has_audio_stream(file_path: Path) -> bool:
    """Checks if media file contains at least one audio stream."""
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=index",
            "-of", "csv=p=0",
            str(file_path)
        ]
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()
        return bool(out)
    except Exception:
        return False


def get_media_duration(file_path: Path) -> float:
    """Returns duration in seconds using ffprobe, checking video stream first."""
    try:
        # Check video stream duration first
        cmd = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(file_path)
        ]
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()
        if out and out != "N/A":
            return float(out)
    except Exception:
        pass

    try:
        # Fallback to container format duration
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(file_path)
        ]
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()
        if out and out != "N/A":
            return float(out)
    except Exception as e:
        logger.warning(f"Could not determine duration for {file_path}: {e}")
    return 0.0


def translate_text(text: str, target_lang_code: str) -> str:
    """
    Translates text to target language using Google Translate endpoint with fallback.
    """
    if not text or not text.strip():
        return ""

    target_code = LANGUAGES.get(target_lang_code, {}).get("trans_code", target_lang_code)
    
    # Try primary direct Google Translate client API
    try:
        # Split text into chunks if it's very long
        chunks = [text[i:i + 1500] for i in range(0, len(text), 1500)]
        translated_chunks = []
        for chunk in chunks:
            url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={target_code}&dt=t&q=" + urllib.parse.quote(chunk)
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                translated_part = "".join([item[0] for item in data[0] if item and item[0]])
                translated_chunks.append(translated_part)
        return " ".join(translated_chunks)
    except Exception as e:
        logger.warning(f"Primary translation failed, trying fallback deep-translator: {e}")

    # Fallback to deep_translator
    try:
        from deep_translator import GoogleTranslator
        return GoogleTranslator(source="auto", target=target_code).translate(text)
    except Exception as e2:
        logger.error(f"Fallback translation also failed: {e2}")
        return text


async def generate_speech_edge(text: str, voice: str, output_path: Path, rate: str = "+0%", pitch: str = "+0Hz"):
    """Generates speech using Edge TTS neural voice."""
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await communicate.save(str(output_path))


def generate_speech(text: str, target_lang: str, voice_id: Optional[str], output_path: Path, speed_rate: str = "+0%") -> Path:
    """
    Synthesizes speech using Edge TTS (or gTTS fallback).
    """
    lang_info = LANGUAGES.get(target_lang, {})
    chosen_voice = voice_id or lang_info.get("default_voice", "en-US-JennyNeural")

    try:
        asyncio.run(generate_speech_edge(text, chosen_voice, output_path, rate=speed_rate))
        if output_path.exists() and output_path.stat().st_size > 500:
            return output_path
    except Exception as e:
        logger.warning(f"Edge TTS failed ({e}), falling back to gTTS...")

    # Fallback gTTS
    try:
        t_code = lang_info.get("trans_code", "en")
        tts = gTTS(text=text, lang=t_code, slow=False)
        tts.save(str(output_path))
        return output_path
    except Exception as e_fallback:
        logger.error(f"gTTS fallback failed: {e_fallback}")
        raise RuntimeError(f"Speech synthesis failed: {e_fallback}")


def adjust_audio_tempo(input_audio: Path, output_audio: Path, tempo_ratio: float) -> Path:
    """
    Adjusts audio tempo without pitch shift using ffmpeg atempo filter.
    atempo accepts values between 0.5 and 2.0.
    """
    # Clamp tempo between 0.7x and 1.4x for natural speech quality
    tempo_ratio = max(0.7, min(1.4, tempo_ratio))

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_audio),
        "-filter:a", f"atempo={tempo_ratio:.3f}",
        "-vn",
        str(output_audio)
    ]
    subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return output_audio


class VideoVoiceConverter:
    def __init__(self, work_dir: Path):
        self.work_dir = work_dir
        self.work_dir.mkdir(parents=True, exist_ok=True)

    def extract_audio(self, video_path: Path, output_wav: Path, duration: float = 1.0) -> Path:
        """Extracts 16kHz mono WAV audio from video, generating silence if no audio track exists."""
        if not has_audio_stream(video_path):
            logger.warning(f"Video {video_path} contains no audio stream. Creating silent audio placeholder.")
            dur = max(1.0, duration)
            cmd = [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
                "-t", f"{dur:.2f}",
                "-acodec", "pcm_s16le",
                str(output_wav)
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-i", str(video_path),
                "-vn",
                "-acodec", "pcm_s16le",
                "-ar", "16000",
                "-ac", "1",
                str(output_wav)
            ]
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return output_wav

    def transcribe_audio(
        self,
        audio_wav: Path,
        candidate_langs: Optional[List[str]] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> str:
        """
        Transcribes speech from audio using adaptive speech interval detection and multi-language cascade.
        """
        if candidate_langs is None:
            candidate_langs = ["en-IN", "en-US", "hi-IN", "te-IN"]

        sound = AudioSegment.from_wav(str(audio_wav))
        total_len_ms = len(sound)

        intervals = detect_speech_intervals(sound)
        if not intervals:
            if total_len_ms <= 20000:
                r = sr.Recognizer()
                with sr.AudioFile(str(audio_wav)) as src:
                    audio_data = r.record(src)
                for l in candidate_langs:
                    try:
                        return r.recognize_google(audio_data, language=l)
                    except Exception:
                        pass
                return ""
            intervals = [(s, min(s + 10000, total_len_ms)) for s in range(0, total_len_ms, 8000)]

        texts = []
        total = len(intervals)
        for i, (s, e) in enumerate(intervals):
            if progress_callback:
                progress_callback(30 + int((i / max(1, total)) * 16), f"Transcribing speech segment {i + 1} of {total}...")
            p_s = max(0, s - 200)
            p_e = min(total_len_ms, e + 200)
            seg_slice = sound[p_s:p_e]
            txt = transcribe_audio_segment(seg_slice, self.work_dir, candidate_langs)
            if txt and (not texts or texts[-1].lower() != txt.lower()):
                texts.append(txt)

        return " ".join(texts)

    def convert_video_voice(
        self,
        video_path: Path,
        target_lang: str,
        voice_id: Optional[str] = None,
        match_duration: bool = True,
        duck_original_audio: bool = False,
        background_volume: float = 0.15,
        custom_transcript: Optional[str] = None,
        source_lang: Optional[str] = "auto",
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> Dict[str, Any]:
        """
        Executes the end-to-end timeline-synchronized voice conversion pipeline:
        1. Extract audio & determine full video duration
        2. Detect speech segments with exact timestamps across the whole video
        3. Transcribe speech using multi-language cascade (Indian English, US English, Regional)
        4. Translate segments to target language
        5. Synthesize Neural TTS per segment and place at corresponding video timestamps
        6. Remux with video preserving 100% full duration and synchronized voice timing throughout
        """
        video_duration = get_media_duration(video_path)
        total_video_ms = max(1000, int(video_duration * 1000))
        logger.info(f"Input video duration: {video_duration:.2f} seconds ({total_video_ms} ms)")

        # Step 1: Extract audio
        if progress_callback:
            progress_callback(25, "Extracting audio track from video...")
        raw_audio_path = self.work_dir / "extracted_audio.wav"
        self.extract_audio(video_path, raw_audio_path, duration=video_duration)
        sound = AudioSegment.from_wav(str(raw_audio_path))
        sound_len_ms = len(sound)

        candidate_langs = get_candidate_languages(source_lang, target_lang)

        # Step 2: Speech Interval Detection & Transcription
        segments_to_process: List[Dict[str, Any]] = []

        if custom_transcript and custom_transcript.strip():
            logger.info("Using user-provided transcript.")
            user_text = custom_transcript.strip()
            sentences = [s.strip() for s in re.split(r'(?<=[.!?\n])\s+', user_text) if s.strip()]
            if not sentences:
                sentences = [user_text]

            detected_intervals = detect_speech_intervals(sound)
            if detected_intervals and len(detected_intervals) >= len(sentences):
                for idx, sentence in enumerate(sentences):
                    s_ms, e_ms = detected_intervals[idx]
                    segments_to_process.append({"start_ms": s_ms, "end_ms": e_ms, "text": sentence})
            else:
                step = total_video_ms / (len(sentences) + 0.5)
                for idx, sentence in enumerate(sentences):
                    s_ms = int(step * idx)
                    e_ms = int(s_ms + step * 0.8)
                    segments_to_process.append({"start_ms": s_ms, "end_ms": e_ms, "text": sentence})
        else:
            if progress_callback:
                progress_callback(28, "Analyzing speech timing and intervals across video...")
            intervals = detect_speech_intervals(sound)
            logger.info(f"Detected {len(intervals)} speech intervals across video audio.")

            total_intervals = len(intervals)
            for i, (start_ms, end_ms) in enumerate(intervals):
                pct = 28 + int((i / max(1, total_intervals)) * 20)
                if progress_callback:
                    progress_callback(pct, f"Transcribing speech segment {i + 1} of {total_intervals}...")
                p_start = max(0, start_ms - 200)
                p_end = min(sound_len_ms, end_ms + 200)
                seg_audio = sound[p_start:p_end]
                txt = transcribe_audio_segment(seg_audio, self.work_dir, candidate_langs)
                if txt and txt.strip():
                    segments_to_process.append({
                        "start_ms": p_start,
                        "end_ms": p_end,
                        "text": txt.strip()
                    })

            # Fallback if silence-based interval detection found no segments
            if not segments_to_process:
                logger.warning("No speech segments detected with silence detector; trying sliding window transcription...")
                step_ms = 8000
                chunk_ms = 10000
                for s_ms in range(0, sound_len_ms, step_ms):
                    seg_audio = sound[s_ms:min(s_ms + chunk_ms, sound_len_ms)]
                    txt = transcribe_audio_segment(seg_audio, self.work_dir, candidate_langs)
                    if txt and txt.strip():
                        if not segments_to_process or segments_to_process[-1]["text"].lower() != txt.strip().lower():
                            segments_to_process.append({
                                "start_ms": s_ms,
                                "end_ms": min(s_ms + chunk_ms, sound_len_ms),
                                "text": txt.strip()
                            })

            if not segments_to_process:
                logger.warning("No speech recognized in audio. Inserting placeholder segment.")
                segments_to_process.append({
                    "start_ms": 2000,
                    "end_ms": 7000,
                    "text": "This video has been processed for language conversion."
                })

        original_transcript = " ".join([s["text"] for s in segments_to_process])
        logger.info(f"Full original transcript ({len(segments_to_process)} segments): {original_transcript[:120]}...")

        # Step 3: Translate segments
        lang_name = LANGUAGES.get(target_lang, {}).get("name", target_lang)
        if progress_callback:
            progress_callback(50, f"Translating speech segments into {lang_name}...")

        for seg in segments_to_process:
            seg["translated_text"] = translate_text(seg["text"], target_lang)

        translated_transcript = " ".join([s["translated_text"] for s in segments_to_process])
        logger.info(f"Full translated transcript: {translated_transcript[:120]}...")

        # Step 4 & 5: Synthesize and Assemble Timeline Audio
        if progress_callback:
            progress_callback(60, f"Synthesizing neural voiceover synchronized with video timeline...")

        full_voice_audio = AudioSegment.silent(duration=total_video_ms)
        total_segs = len(segments_to_process)

        for i, seg in enumerate(segments_to_process):
            seg_pct = 60 + int((i / max(1, total_segs)) * 16)
            if progress_callback:
                progress_callback(seg_pct, f"Synthesizing voice: segment {i + 1} of {total_segs}...")

            seg_tts_path = self.work_dir / f"seg_{i}_{uuid.uuid4().hex[:6]}.mp3"
            generate_speech(seg["translated_text"], target_lang, voice_id, seg_tts_path)

            if not seg_tts_path.exists() or seg_tts_path.stat().st_size == 0:
                continue

            seg_sound = AudioSegment.from_file(str(seg_tts_path))
            seg_tts_path.unlink(missing_ok=True)

            # Available window before next speech segment
            if i + 1 < total_segs:
                next_start = segments_to_process[i + 1]["start_ms"]
                max_window_ms = max(500, next_start - seg["start_ms"] - 80)
            else:
                max_window_ms = max(500, total_video_ms - seg["start_ms"])

            # Adjust tempo if TTS exceeds available window
            if len(seg_sound) > max_window_ms and max_window_ms > 500 and match_duration:
                tempo_ratio = len(seg_sound) / max_window_ms
                if tempo_ratio > 1.05:
                    tmp_in = self.work_dir / f"tempo_in_{i}.wav"
                    tmp_out = self.work_dir / f"tempo_out_{i}.wav"
                    seg_sound.export(str(tmp_in), format="wav")
                    try:
                        adjust_audio_tempo(tmp_in, tmp_out, min(1.35, tempo_ratio))
                        seg_sound = AudioSegment.from_file(str(tmp_out))
                    except Exception as e:
                        logger.warning(f"Tempo adjustment note for segment {i}: {e}")
                    finally:
                        tmp_in.unlink(missing_ok=True)
                        tmp_out.unlink(missing_ok=True)

            pos = min(seg["start_ms"], max(0, total_video_ms - 200))
            full_voice_audio = full_voice_audio.overlay(seg_sound, position=pos)

        # Export assembled timeline audio
        final_voice_audio = self.work_dir / f"synced_voice_{target_lang}_{uuid.uuid4().hex[:6]}.wav"
        full_voice_audio.export(str(final_voice_audio), format="wav")
        voice_dur = len(full_voice_audio) / 1000.0
        logger.info(f"Assembled timeline voiceover duration: {voice_dur:.2f}s (Video is {video_duration:.2f}s)")

        # Step 6: Audio Mixing & Remuxing into Video
        if progress_callback:
            progress_callback(78, "Remuxing synchronized full-duration audio track with video...")

        output_video_path = self.work_dir / f"converted_{target_lang}_{uuid.uuid4().hex[:6]}.mp4"
        orig_has_audio = has_audio_stream(video_path)

        if duck_original_audio and orig_has_audio:
            filter_complex = (
                f"[0:a]volume={background_volume}[bg];"
                f"[1:a]volume=1.0[fg];"
                f"[bg][fg]amix=inputs=2:duration=first:dropout_transition=2[aout]"
            )
            cmd = [
                "ffmpeg", "-y",
                "-i", str(video_path),
                "-i", str(final_voice_audio),
                "-filter_complex", filter_complex,
                "-map", "0:v:0",
                "-map", "[aout]",
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-t", f"{video_duration:.3f}",
                "-movflags", "+faststart",
                str(output_video_path)
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-i", str(video_path),
                "-i", str(final_voice_audio),
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-t", f"{video_duration:.3f}",
                "-movflags", "+faststart",
                str(output_video_path)
            ]

        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        out_dur = get_media_duration(output_video_path)
        logger.info(f"Video remuxing complete: {output_video_path} (duration: {out_dur:.2f}s)")

        return {
            "output_video_path": output_video_path,
            "voice_audio_path": final_voice_audio,
            "original_transcript": original_transcript,
            "translated_transcript": translated_transcript,
            "video_duration": video_duration,
            "tts_duration": voice_dur,
            "target_lang": target_lang
        }
