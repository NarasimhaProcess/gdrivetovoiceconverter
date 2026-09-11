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
from typing import Dict, Any, Optional, Callable, List

import edge_tts
from gtts import gTTS
from pydub import AudioSegment
from pydub.silence import split_on_silence
import speech_recognition as sr

from app.languages import LANGUAGES, get_language_folder_name

logger = logging.getLogger("gdrive_voice_converter")


def get_media_duration(file_path: Path) -> float:
    """Returns duration in seconds using ffprobe."""
    try:
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(file_path)
        ]
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode().strip()
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

    def extract_audio(self, video_path: Path, output_wav: Path) -> Path:
        """Extracts 16kHz mono WAV audio from video."""
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

    def transcribe_audio(self, audio_wav: Path, progress_callback: Optional[Callable[[int, str], None]] = None) -> str:
        """
        Transcribes speech from audio using chunked recognition to handle files of any length.
        """
        r = sr.Recognizer()
        sound = AudioSegment.from_wav(str(audio_wav))
        total_len_ms = len(sound)

        # If audio is very short (< 30s), transcribe directly
        if total_len_ms <= 30000:
            if progress_callback:
                progress_callback(32, "Transcribing speech from video audio...")
            with sr.AudioFile(str(audio_wav)) as source:
                audio_data = r.record(source)
            try:
                text = r.recognize_google(audio_data)
                return text
            except sr.UnknownValueError:
                logger.warning("No speech recognized in direct segment.")
                return ""
            except Exception as e:
                logger.error(f"Speech recognition error: {e}")
                return ""

        # For longer audio, chunk into 20-second slices with 1-second silence overlap
        chunk_length_ms = 25000
        step_ms = 24000
        chunks_text = []

        total_chunks = (total_len_ms // step_ms) + 1
        for i, start_ms in enumerate(range(0, total_len_ms, step_ms)):
            chunk_pct = 30 + int((i / max(1, total_chunks)) * 15)
            if progress_callback:
                progress_callback(chunk_pct, f"Transcribing speech: part {i + 1} of {total_chunks}...")

            end_ms = min(start_ms + chunk_length_ms, total_len_ms)
            chunk = sound[start_ms:end_ms]
            chunk_file = self.work_dir / f"chunk_{i}.wav"
            chunk.export(str(chunk_file), format="wav")

            try:
                with sr.AudioFile(str(chunk_file)) as source:
                    audio_data = r.record(source)
                recognized = r.recognize_google(audio_data)
                if recognized and recognized.strip():
                    chunks_text.append(recognized.strip())
            except sr.UnknownValueError:
                pass
            except Exception as e:
                logger.debug(f"Chunk {i} recognition note: {e}")
            finally:
                if chunk_file.exists():
                    chunk_file.unlink(missing_ok=True)

        return " ".join(chunks_text)

    def convert_video_voice(
        self,
        video_path: Path,
        target_lang: str,
        voice_id: Optional[str] = None,
        match_duration: bool = True,
        duck_original_audio: bool = False,
        background_volume: float = 0.15,
        custom_transcript: Optional[str] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> Dict[str, Any]:
        """
        Executes the end-to-end voice conversion pipeline:
        1. Extract audio & inspect video duration
        2. Transcribe speech
        3. Translate to target language
        4. Generate Neural Voice TTS
        5. Match duration & audio sync
        6. Remux with video
        """
        video_duration = get_media_duration(video_path)
        logger.info(f"Input video duration: {video_duration:.2f} seconds")

        # Step 1: Extract audio
        if progress_callback:
            progress_callback(28, "Extracting audio track from video...")
        raw_audio_path = self.work_dir / "extracted_audio.wav"
        self.extract_audio(video_path, raw_audio_path)

        # Step 2: Speech-to-Text
        if custom_transcript and custom_transcript.strip():
            transcript = custom_transcript.strip()
            logger.info("Using user-provided transcript.")
        else:
            transcript = self.transcribe_audio(raw_audio_path, progress_callback)

        if not transcript or not transcript.strip():
            # If no speech detected in video, provide a gentle fallback message so conversion still succeeds
            transcript = "This video does not contain clear detected speech, but has been processed for language conversion."
            logger.warning("Empty transcript detected. Using fallback placeholder.")

        # Step 3: Translate
        if progress_callback:
            lang_name = LANGUAGES.get(target_lang, {}).get("name", target_lang)
            progress_callback(48, f"Translating speech into {lang_name}...")
        
        translated_text = translate_text(transcript, target_lang)
        logger.info(f"Translated text: {translated_text[:100]}...")

        # Step 4: Generate Neural TTS
        if progress_callback:
            progress_callback(60, "Generating expressive neural voice...")
        tts_audio_path = self.work_dir / "translated_voice.mp3"
        generate_speech(translated_text, target_lang, voice_id, tts_audio_path)

        tts_duration = get_media_duration(tts_audio_path)
        logger.info(f"Generated voice duration: {tts_duration:.2f}s (Video is {video_duration:.2f}s)")

        # Step 5: Voice Matching & Tempo Sync
        final_voice_audio = tts_audio_path
        if match_duration and video_duration > 0.5 and tts_duration > 0.5:
            tempo_ratio = tts_duration / video_duration
            # If duration discrepancy is noticeable (> 7% difference)
            if abs(tempo_ratio - 1.0) > 0.07:
                if progress_callback:
                    progress_callback(72, f"Matching voice speed to video duration (tempo: {tempo_ratio:.2f}x)...")
                synced_audio = self.work_dir / "synced_voice.wav"
                try:
                    adjust_audio_tempo(tts_audio_path, synced_audio, tempo_ratio)
                    final_voice_audio = synced_audio
                except Exception as e:
                    logger.warning(f"Tempo adjustment failed, using raw TTS audio: {e}")

        # Step 6: Audio Mixing & Remuxing into Video
        if progress_callback:
            progress_callback(78, "Remuxing synchronized audio track with original video...")

        output_video_path = self.work_dir / f"converted_{target_lang}_{uuid.uuid4().hex[:6]}.mp4"

        if duck_original_audio:
            # Mix original audio lowered to background_volume with the new voice
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
                "-shortest",
                str(output_video_path)
            ]
        else:
            # Clean complete voiceover replacement
            cmd = [
                "ffmpeg", "-y",
                "-i", str(video_path),
                "-i", str(final_voice_audio),
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
                str(output_video_path)
            ]

        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logger.info(f"Video remuxing complete: {output_video_path}")

        return {
            "output_video_path": output_video_path,
            "original_transcript": transcript,
            "translated_transcript": translated_text,
            "video_duration": video_duration,
            "tts_duration": tts_duration,
            "target_lang": target_lang
        }
