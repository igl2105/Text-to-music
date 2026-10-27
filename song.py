
"""
Sanskrit Voice Studio V2
------------------------
Features:
- Read PDF or TXT files.
- Generate source speech using Edge TTS.
- Convert generated speech to a target voice using Chatterbox VC.
- Optional delivery-style matching, disabled by default.
- Export WAV or MP3.
- Sanskrit-only, Hindi-only, and mixed-language modes.

Mixed-language tags:
    [SA]सर्वे भवन्तु सुखिनः[/SA]
    [HI]सभी सुखी रहें[/HI]

Important:
Delivery-style matching is approximate. It adjusts global pitch and
pacing; it does not reproduce exact Vedic svara, melody, or prosody.

The Chatterbox VoiceConverter import and method signatures must match
the particular package/repository installed on your system.
"""

import asyncio
import os
import re
import tempfile
import threading
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

import numpy as np
import soundfile as sf

# Automatically expose FFmpeg to PATH for librosa/audioread/pydub (.m4a, .mp3, etc.)
try:
    import imageio_ffmpeg
    _ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    _ffmpeg_dir = os.path.dirname(_ffmpeg_exe)
    _target_ffmpeg = os.path.join(_ffmpeg_dir, "ffmpeg.exe")
    if not os.path.exists(_target_ffmpeg):
        import shutil
        shutil.copy2(_ffmpeg_exe, _target_ffmpeg)
    if _ffmpeg_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
except Exception:
    pass

SAMPLE_RATE = 24000

def ensure_wav_audio(input_path, temp_dir):
    """Ensure any audio format (.m4a, .mp3, .flac, etc.) is converted to WAV."""
    path = Path(input_path)
    if not path.is_file():
        raise RuntimeError(f"Audio file not found: {input_path}")
    if path.suffix.lower() == ".wav":
        return str(path)
    
    out_wav = os.path.join(temp_dir, f"{path.stem}_converted.wav")
    try:
        import librosa
        audio, sr = librosa.load(str(path), sr=SAMPLE_RATE, mono=True)
        sf.write(out_wav, audio, sr)
        return out_wav
    except Exception:
        # Fallback to direct ffmpeg command
        try:
            import imageio_ffmpeg
            import subprocess
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            subprocess.run(
                [ffmpeg_exe, "-y", "-i", str(path), "-ac", "1", "-ar", str(SAMPLE_RATE), out_wav],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            return out_wav
        except Exception as exc:
            raise RuntimeError(
                f"Could not read audio format of {path.name}: {exc}. Please select a WAV file."
            ) from exc

SOURCE_VOICES = {
    "Hindi female": ("hi-IN-SwaraNeural", "hindi"),
    "Hindi male": ("hi-IN-MadhurNeural", "hindi"),
    "Telugu female": ("te-IN-ShrutiNeural", "sanskrit"),
    "Telugu male": ("te-IN-MohanNeural", "sanskrit"),
    "Kannada female": ("kn-IN-SapnaNeural", "sanskrit"),
    "Kannada male": ("kn-IN-GaganNeural", "sanskrit"),
    "Malayalam female": ("ml-IN-SobhanaNeural", "sanskrit"),
    "Malayalam male": ("ml-IN-MidhunNeural", "sanskrit"),
}


def read_text_file(path):
    ext = Path(path).suffix.lower()

    if ext == ".pdf":
        try:
            import pymupdf
            doc = pymupdf.open(path)
        except ImportError:
            import fitz
            doc = fitz.open(path)

        try:
            text = "\n\n".join(page.get_text() for page in doc)
        finally:
            doc.close()

        if not text.strip():
            raise RuntimeError(
                "No selectable text found. This PDF may be scanned. "
                "Run OCR first."
            )
    else:
        with open(path, "r", encoding="utf-8-sig") as file:
            text = file.read()

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def parse_language_tags(text, default_language):
    """Parse optional Sanskrit and Hindi tags in mixed-language text."""
    pattern = re.compile(
        r"\[(SA|HI)\](.*?)\[/\1\]",
        flags=re.DOTALL | re.IGNORECASE,
    )

    segments = []
    position = 0

    for match in pattern.finditer(text):
        before = text[position:match.start()]

        if before.strip():
            segments.append((default_language, before.strip()))

        language = (
            "sanskrit"
            if match.group(1).upper() == "SA"
            else "hindi"
        )

        if match.group(2).strip():
            segments.append((language, match.group(2).strip()))

        position = match.end()

    tail = text[position:]

    if tail.strip():
        segments.append((default_language, tail.strip()))

    if not segments and text.strip():
        segments.append((default_language, text.strip()))

    return segments


def to_sanskrit_script(text, script_name):
    from indic_transliteration import sanscript

    return sanscript.transliterate(
        text,
        sanscript.DEVANAGARI,
        getattr(sanscript, script_name),
    )


def split_text(text, max_chars=180):
    """Split text into manageable speech chunks."""
    output = []

    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()

        if not paragraph:
            continue

        sentences = re.split(r"(?<=[.!?।॥])\s+", paragraph)
        current = ""

        for sentence in sentences:
            sentence = sentence.strip()

            if not sentence:
                continue

            while len(sentence) > max_chars:
                cut = sentence.rfind(" ", 0, max_chars)

                if cut < 1:
                    cut = max_chars

                if current:
                    output.append((current, False))
                    current = ""

                output.append((sentence[:cut].strip(), False))
                sentence = sentence[cut:].strip()

            if not sentence:
                continue

            if len(current) + len(sentence) + 1 <= max_chars:
                current = (current + " " + sentence).strip()
            else:
                if current:
                    output.append((current, False))

                current = sentence

        if current:
            output.append((current, True))

    return output


async def edge_synthesize(text, voice, output_path, rate_percent):
    import edge_tts

    rate = f"{rate_percent:+d}%"
    communicate = edge_tts.Communicate(
        text,
        voice,
        rate=rate,
    )
    await communicate.save(output_path)

    if (
        not os.path.isfile(output_path)
        or os.path.getsize(output_path) == 0
    ):
        raise RuntimeError("Source TTS produced an empty audio file.")


def estimate_reference_pitch(reference_path):
    """Estimate median voiced pitch in Hz from a style recording."""
    import librosa

    audio, sr = librosa.load(
        reference_path,
        sr=16000,
        mono=True,
    )

    if len(audio) < sr:
        raise RuntimeError(
            "The style recording must be at least one second long."
        )

    audio = audio[:sr * 30]

    f0 = librosa.yin(
        audio,
        fmin=65,
        fmax=500,
        sr=sr,
        frame_length=2048,
    )

    f0 = f0[np.isfinite(f0)]
    f0 = f0[(f0 >= 65) & (f0 <= 500)]

    if len(f0) < 5:
        raise RuntimeError(
            "Could not estimate pitch. Use a clear recording "
            "with one speaker."
        )

    return float(np.median(f0))


def apply_style_adjustments(
    audio,
    sr,
    target_pitch_hz,
    pitch_influence,
    speed_factor,
):
    """
    Approximate style matching by adjusting median pitch and speed.
    This does not copy the reference's exact intonation.
    """
    import librosa

    result = np.asarray(audio, dtype=np.float32)

    if result.size == 0:
        return result

    if target_pitch_hz and pitch_influence > 0:
        source_f0 = librosa.yin(
            result,
            fmin=65,
            fmax=500,
            sr=sr,
            frame_length=2048,
        )

        source_f0 = source_f0[np.isfinite(source_f0)]
        source_f0 = source_f0[
            (source_f0 >= 65) & (source_f0 <= 500)
        ]

        if len(source_f0) > 5:
            source_median = float(np.median(source_f0))

            semitones = 12.0 * np.log2(
                target_pitch_hz / source_median
            )
            semitones = float(np.clip(semitones, -5.0, 5.0))
            semitones *= float(pitch_influence)

            if abs(semitones) > 0.1:
                result = librosa.effects.pitch_shift(
                    y=result,
                    sr=sr,
                    n_steps=semitones,
                )

    speed_factor = float(np.clip(speed_factor, 0.75, 1.25))

    if abs(speed_factor - 1.0) > 0.01:
        result = librosa.effects.time_stretch(
            y=result,
            rate=speed_factor,
        )

    return np.asarray(result, dtype=np.float32)


DEFAULT_OUTPUT_DIR = os.path.abspath("output")
os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)


def save_audio(audio, sr, output_path):
    output_dir = os.path.dirname(os.path.abspath(output_path))
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    audio = np.asarray(audio, dtype=np.float32)
    audio = np.nan_to_num(audio)
    audio = np.clip(audio, -1.0, 1.0)

    if Path(output_path).suffix.lower() == ".mp3":
        try:
            from pydub import AudioSegment

            pcm = (audio * 32767).astype(np.int16)

            segment = AudioSegment(
                pcm.tobytes(),
                frame_rate=sr,
                sample_width=2,
                channels=1,
            )

            segment.export(
                output_path,
                format="mp3",
                bitrate="192k",
            )

            return output_path

        except Exception as exc:
            raise RuntimeError(
                "MP3 export failed. Install pydub and FFmpeg, "
                f"or choose WAV. Details: {exc}"
            ) from exc

    sf.write(output_path, audio, sr)
    return output_path


def run_pipeline(
    text,
    language_mode,
    source_voice_label,
    target_voice_path,
    style_reference_path,
    use_delivery_style,
    output_path,
    pitch_influence,
    speed_factor,
    rate_percent,
    status,
    use_voice_conversion=False,
):
    import librosa

    if not text.strip():
        raise RuntimeError("Enter text or load a document.")

    with tempfile.TemporaryDirectory(
        prefix="sanskrit_studio_v2_"
    ) as temp:
        converter = None
        if use_voice_conversion:
            if not target_voice_path or not os.path.isfile(target_voice_path):
                raise RuntimeError(
                    "Voice conversion is enabled, but no valid target voice recording was selected."
                )
            try:
                import torch
                try:
                    import perth
                    if getattr(perth, "PerthImplicitWatermarker", None) is None:
                        perth.PerthImplicitWatermarker = getattr(perth, "DummyWatermarker", None)
                except Exception:
                    pass

                try:
                    from chatterbox import ChatterboxVC
                    VCClass = ChatterboxVC
                except ImportError:
                    from chatterbox_vc import VoiceConverter
                    VCClass = VoiceConverter

                device = "cuda:0" if torch.cuda.is_available() else "cpu"
                status(f"Loading voice conversion model on {device}...")
                if hasattr(VCClass, "from_pretrained"):
                    converter = VCClass.from_pretrained(device)
                else:
                    converter = VCClass(device=device)

                # Ensure target voice is a clean WAV file (converts .m4a/.mp3 if needed)
                status("Preparing target voice recording...")
                wav_target = ensure_wav_audio(target_voice_path, temp)
                converter.set_target_voice(wav_target)
            except Exception as exc:
                err_text = str(exc) or repr(exc)
                raise RuntimeError(
                    f"Could not load voice conversion model: {err_text}"
                ) from exc

        # A style recording is required only when style mode is enabled.
        reference_pitch = None
        if use_delivery_style:
            if not style_reference_path or not os.path.isfile(style_reference_path):
                raise RuntimeError(
                    "Select a style recording or disable delivery style."
                )

            status("Analyzing style reference pitch...")
            wav_style = ensure_wav_audio(style_reference_path, temp)
            reference_pitch = estimate_reference_pitch(wav_style)

        default_language = (
            "sanskrit"
            if language_mode == "Sanskrit only"
            else "hindi"
        )

        segments = parse_language_tags(text, default_language)
        source_voice, source_kind = SOURCE_VOICES.get(
            source_voice_label,
            ("te-IN-MohanNeural", "sanskrit"),
        )

        if any(language == "sanskrit" for language, _ in segments):
            if source_kind != "sanskrit":
                source_voice = "te-IN-MohanNeural"
                script_name = "TELUGU"
            else:
                if source_voice_label.startswith("Telugu"):
                    script_name = "TELUGU"
                elif source_voice_label.startswith("Kannada"):
                    script_name = "KANNADA"
                else:
                    script_name = "MALAYALAM"
        else:
            script_name = "TELUGU"

        chunks = []
        for language, segment in segments:
            for chunk, paragraph_end in split_text(segment):
                chunks.append((language, chunk, paragraph_end))

        if not chunks:
            raise RuntimeError("No readable text chunks found.")

        all_audio = []
        total_chunks = len(chunks)
        for index, (language, chunk, paragraph_end) in enumerate(chunks, 1):
            status(f"Synthesizing chunk {index}/{total_chunks}...")
            tts_path = os.path.join(temp, f"chunk_{index}.wav")

            if language == "sanskrit":
                chunk_text = to_sanskrit_script(chunk, script_name)
                voice = source_voice
            else:
                chunk_text = chunk
                voice, _ = SOURCE_VOICES.get(
                    source_voice_label,
                    ("hi-IN-SwaraNeural", "hindi"),
                )
                if not voice.startswith("hi-"):
                    voice = "hi-IN-SwaraNeural"

            asyncio.run(
                edge_synthesize(chunk_text, voice, tts_path, rate_percent)
            )

            if converter is not None:
                status(f"Converting voice for chunk {index}/{total_chunks}...")
                try:
                    if hasattr(converter, "generate"):
                        converted = converter.generate(tts_path)
                    elif hasattr(converter, "convert"):
                        chunk_audio, _ = librosa.load(tts_path, sr=SAMPLE_RATE, mono=True)
                        converted = converter.convert(chunk_audio, SAMPLE_RATE)
                    elif callable(converter):
                        chunk_audio, _ = librosa.load(tts_path, sr=SAMPLE_RATE, mono=True)
                        converted = converter(chunk_audio, SAMPLE_RATE)
                    else:
                        converted, _ = librosa.load(tts_path, sr=SAMPLE_RATE, mono=True)

                    if hasattr(converted, "detach"):
                        converted = converted.detach().cpu().numpy()
                    elif hasattr(converted, "cpu"):
                        converted = converted.cpu().numpy()
                    if isinstance(converted, (list, tuple)):
                        converted = converted[0]
                    chunk_audio = np.asarray(converted, dtype=np.float32).flatten()
                except Exception as exc:
                    status(f"Voice conversion warning on chunk {index}: {exc}")
                    chunk_audio, _ = librosa.load(tts_path, sr=SAMPLE_RATE, mono=True)
            else:
                chunk_audio, _ = librosa.load(tts_path, sr=SAMPLE_RATE, mono=True)

            if use_delivery_style and reference_pitch:
                chunk_audio = apply_style_adjustments(
                    chunk_audio,
                    SAMPLE_RATE,
                    reference_pitch,
                    pitch_influence,
                    speed_factor,
                )

            all_audio.append(chunk_audio)

            pause_sec = 0.5 if paragraph_end else 0.2
            silence = np.zeros(int(SAMPLE_RATE * pause_sec), dtype=np.float32)
            all_audio.append(silence)

    if not all_audio:
        raise RuntimeError("No audio was generated.")

    status("Stitching audio segments...")
    full_audio = np.concatenate(all_audio)

    status(f"Saving audio to {Path(output_path).name}...")
    save_audio(full_audio, SAMPLE_RATE, output_path)
    status(f"Export complete: {Path(output_path).name}")


class SanskritStudioApp(tk.Tk):
    """Modern Tkinter GUI for Sanskrit Voice Studio V2."""

    def __init__(self):
        super().__init__()
        self.title("Sanskrit Voice Studio V2")
        self.geometry("860x820")
        self.minsize(780, 700)

        self._init_theme()
        self._build_ui()
        self.output_file = None

    def _init_theme(self):
        self.configure(bg="#F4F6F9")
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # Configure custom modern styles
        style.configure(".", font=("Segoe UI", 10), background="#F4F6F9")
        style.configure(
            "Header.TLabel",
            font=("Segoe UI Semibold", 16),
            background="#1E293B",
            foreground="#FFFFFF",
        )
        style.configure(
            "SubHeader.TLabel",
            font=("Segoe UI", 9),
            background="#1E293B",
            foreground="#94A3B8",
        )
        style.configure("Card.TLabelframe", background="#FFFFFF", relief="solid", borderwidth=1)
        style.configure(
            "Card.TLabelframe.Label",
            font=("Segoe UI Semibold", 10),
            background="#FFFFFF",
            foreground="#1E293B",
        )
        style.configure(
            "Primary.TButton",
            font=("Segoe UI Semibold", 10),
            padding=6,
        )
        style.configure(
            "Action.TButton",
            font=("Segoe UI Bold", 11),
            padding=8,
        )

    def _build_ui(self):
        # 1. Header Frame
        header = tk.Frame(self, bg="#1E293B", padx=20, pady=12)
        header.pack(fill="x", side="top")

        title_lbl = ttk.Label(
            header,
            text="Sanskrit Voice Studio V2",
            style="Header.TLabel",
        )
        title_lbl.pack(anchor="w")

        subtitle_lbl = ttk.Label(
            header,
            text="Neural Text-to-Speech & Cross-Script Voice Studio for Sanskrit & Hindi",
            style="SubHeader.TLabel",
        )
        subtitle_lbl.pack(anchor="w")

        # Main scrollable or padded container
        container = tk.Frame(self, bg="#F4F6F9", padx=16, pady=10)
        container.pack(fill="both", expand=True)

        # 2. Text Input Card
        text_card = ttk.LabelFrame(
            container,
            text=" 1. Input Text / Document ",
            style="Card.TLabelframe",
            padding=10,
        )
        text_card.pack(fill="both", expand=True, pady=(0, 8))

        # Toolbar above text box
        tb_frame = tk.Frame(text_card, bg="#FFFFFF")
        tb_frame.pack(fill="x", pady=(0, 6))

        load_btn = ttk.Button(
            tb_frame,
            text="📄 Load File (.pdf / .txt)",
            command=self._load_document,
        )
        load_btn.pack(side="left", padx=(0, 6))

        sa_tag_btn = ttk.Button(
            tb_frame,
            text="+ [SA] Tag",
            command=lambda: self._wrap_tag("SA"),
        )
        sa_tag_btn.pack(side="left", padx=3)

        hi_tag_btn = ttk.Button(
            tb_frame,
            text="+ [HI] Tag",
            command=lambda: self._wrap_tag("HI"),
        )
        hi_tag_btn.pack(side="left", padx=3)

        sample_btn = ttk.Button(
            tb_frame,
            text="✨ Load Sample Sloka",
            command=self._load_sample,
        )
        sample_btn.pack(side="left", padx=6)

        clear_btn = ttk.Button(
            tb_frame,
            text="Clear",
            command=lambda: self.text_area.delete("1.0", tk.END),
        )
        clear_btn.pack(side="right")

        # Text area
        text_frame = tk.Frame(text_card, bg="#FFFFFF")
        text_frame.pack(fill="both", expand=True)

        scrollbar = ttk.Scrollbar(text_frame, orient="vertical")
        self.text_area = tk.Text(
            text_frame,
            wrap="word",
            font=("Segoe UI", 10),
            yscrollcommand=scrollbar.set,
            height=7,
            relief="solid",
            bd=1,
        )
        scrollbar.config(command=self.text_area.yview)
        scrollbar.pack(side="right", fill="y")
        self.text_area.pack(side="left", fill="both", expand=True)

        # 3. Settings Card
        settings_card = ttk.LabelFrame(
            container,
            text=" 2. Voice & Audio Settings ",
            style="Card.TLabelframe",
            padding=10,
        )
        settings_card.pack(fill="x", pady=(0, 8))

        grid = tk.Frame(settings_card, bg="#FFFFFF")
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)
        grid.columnconfigure(3, weight=1)

        # Language Mode
        ttk.Label(grid, text="Language Mode:", background="#FFFFFF").grid(
            row=0, column=0, sticky="w", pady=4, padx=(0, 8)
        )
        self.lang_mode_var = tk.StringVar(value="Sanskrit only")
        lang_cb = ttk.Combobox(
            grid,
            textvariable=self.lang_mode_var,
            values=["Sanskrit only", "Hindi only", "Mixed language"],
            state="readonly",
            width=18,
        )
        lang_cb.grid(row=0, column=1, sticky="ew", pady=4, padx=(0, 16))

        # Source Voice
        ttk.Label(grid, text="Source Voice:", background="#FFFFFF").grid(
            row=0, column=2, sticky="w", pady=4, padx=(0, 8)
        )
        self.source_voice_var = tk.StringVar(value="Telugu male")
        voice_cb = ttk.Combobox(
            grid,
            textvariable=self.source_voice_var,
            values=list(SOURCE_VOICES.keys()),
            state="readonly",
            width=22,
        )
        voice_cb.grid(row=0, column=3, sticky="ew", pady=4)

        # Target Voice audio file (Chatterbox VC)
        ttk.Label(grid, text="Target Voice Audio:", background="#FFFFFF").grid(
            row=1, column=0, sticky="w", pady=4, padx=(0, 8)
        )
        self.target_voice_var = tk.StringVar()
        tv_entry = ttk.Entry(grid, textvariable=self.target_voice_var)
        tv_entry.grid(row=1, column=1, sticky="ew", pady=4, padx=(0, 4))
        tv_btn = ttk.Button(
            grid, text="Browse...", width=9, command=self._browse_target_voice
        )
        tv_btn.grid(row=1, column=2, sticky="w", pady=4, padx=(0, 16))

        self.use_vc_var = tk.BooleanVar(value=False)
        vc_chk = ttk.Checkbutton(
            grid,
            text="Enable Voice Conversion (Chatterbox VC)",
            variable=self.use_vc_var,
        )
        vc_chk.grid(row=1, column=3, sticky="w", pady=4)

        # Style Reference audio
        ttk.Label(grid, text="Style Audio Ref:", background="#FFFFFF").grid(
            row=2, column=0, sticky="w", pady=4, padx=(0, 8)
        )
        self.style_ref_var = tk.StringVar()
        sr_entry = ttk.Entry(grid, textvariable=self.style_ref_var)
        sr_entry.grid(row=2, column=1, sticky="ew", pady=4, padx=(0, 4))
        sr_btn = ttk.Button(
            grid, text="Browse...", width=9, command=self._browse_style_ref
        )
        sr_btn.grid(row=2, column=2, sticky="w", pady=4, padx=(0, 16))

        self.use_style_var = tk.BooleanVar(value=False)
        style_chk = ttk.Checkbutton(
            grid,
            text="Enable Delivery Style Matching",
            variable=self.use_style_var,
        )
        style_chk.grid(row=2, column=3, sticky="w", pady=4)

        # Sliders Row (Speech Rate, Pitch Influence, Speed Factor)
        sliders_frame = tk.Frame(settings_card, bg="#FFFFFF")
        sliders_frame.pack(fill="x", pady=(8, 0))
        sliders_frame.columnconfigure((0, 1, 2), weight=1)

        # Rate slider
        r_box = tk.LabelFrame(
            sliders_frame,
            text=" Speech Rate ",
            bg="#FFFFFF",
            font=("Segoe UI", 9),
        )
        r_box.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.rate_var = tk.IntVar(value=0)
        self.rate_lbl = ttk.Label(r_box, text="0%", background="#FFFFFF")
        self.rate_lbl.pack(anchor="e", padx=6)
        r_scale = ttk.Scale(
            r_box,
            from_=-50,
            to=50,
            variable=self.rate_var,
            orient="horizontal",
            command=lambda v: self.rate_lbl.config(text=f"{int(float(v)):+d}%"),
        )
        r_scale.pack(fill="x", padx=6, pady=(0, 4))

        # Pitch influence slider
        p_box = tk.LabelFrame(
            sliders_frame,
            text=" Pitch Influence ",
            bg="#FFFFFF",
            font=("Segoe UI", 9),
        )
        p_box.grid(row=0, column=1, sticky="ew", padx=3)
        self.pitch_var = tk.DoubleVar(value=0.5)
        self.pitch_lbl = ttk.Label(p_box, text="0.50", background="#FFFFFF")
        self.pitch_lbl.pack(anchor="e", padx=6)
        p_scale = ttk.Scale(
            p_box,
            from_=0.0,
            to=1.0,
            variable=self.pitch_var,
            orient="horizontal",
            command=lambda v: self.pitch_lbl.config(text=f"{float(v):.2f}"),
        )
        p_scale.pack(fill="x", padx=6, pady=(0, 4))

        # Speed factor slider
        s_box = tk.LabelFrame(
            sliders_frame,
            text=" Speed Factor ",
            bg="#FFFFFF",
            font=("Segoe UI", 9),
        )
        s_box.grid(row=0, column=2, sticky="ew", padx=(6, 0))
        self.speed_var = tk.DoubleVar(value=1.0)
        self.speed_lbl = ttk.Label(s_box, text="1.00x", background="#FFFFFF")
        self.speed_lbl.pack(anchor="e", padx=6)
        s_scale = ttk.Scale(
            s_box,
            from_=0.75,
            to=1.25,
            variable=self.speed_var,
            orient="horizontal",
            command=lambda v: self.speed_lbl.config(text=f"{float(v):.2f}x"),
        )
        s_scale.pack(fill="x", padx=6, pady=(0, 4))

        # 4. Output Destination Card
        out_card = ttk.LabelFrame(
            container,
            text=" 3. Output Destination ",
            style="Card.TLabelframe",
            padding=10,
        )
        out_card.pack(fill="x", pady=(0, 8))

        out_grid = tk.Frame(out_card, bg="#FFFFFF")
        out_grid.pack(fill="x")
        out_grid.columnconfigure(1, weight=1)

        ttk.Label(out_grid, text="Save File As:", background="#FFFFFF").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)
        default_out = os.path.join(DEFAULT_OUTPUT_DIR, "output.wav")
        self.out_path_var = tk.StringVar(value=default_out)
        out_entry = ttk.Entry(out_grid, textvariable=self.out_path_var)
        out_entry.grid(row=0, column=1, sticky="ew", padx=(0, 6))

        browse_out_btn = ttk.Button(
            out_grid, text="Choose...", width=10, command=self._browse_output
        )
        browse_out_btn.grid(row=0, column=2, sticky="w")

        # 5. Action, Progress & Playback Frame
        action_frame = tk.Frame(container, bg="#F4F6F9")
        action_frame.pack(fill="x", pady=4)

        self.gen_btn = ttk.Button(
            action_frame,
            text="🎙️ Generate Audio",
            style="Action.TButton",
            command=self._start_generation,
        )
        self.gen_btn.pack(side="left", padx=(0, 10))

        self.play_btn = ttk.Button(
            action_frame,
            text="▶️ Play Audio",
            command=self._play_output,
            state="disabled",
        )
        self.play_btn.pack(side="left", padx=(0, 6))

        self.folder_btn = ttk.Button(
            action_frame,
            text="📁 Open Output Folder",
            command=self._open_folder,
            state="normal",
        )
        self.folder_btn.pack(side="left")

        # Progress bar
        self.prog_bar = ttk.Progressbar(container, mode="indeterminate")
        self.prog_bar.pack(fill="x", pady=(8, 4))

        # Status Label
        self.status_var = tk.StringVar(value="Ready. Enter text and click Generate Audio.")
        self.status_lbl = ttk.Label(
            container,
            textvariable=self.status_var,
            font=("Segoe UI", 9, "italic"),
            foreground="#475569",
        )
        self.status_lbl.pack(anchor="w")

    def _wrap_tag(self, tag):
        try:
            sel_first = self.text_area.index("sel.first")
            sel_last = self.text_area.index("sel.last")
            selected = self.text_area.get(sel_first, sel_last)
            self.text_area.delete(sel_first, sel_last)
            self.text_area.insert(sel_first, f"[{tag}]{selected}[/{tag}]")
        except tk.TclError:
            self.text_area.insert(tk.INSERT, f"[{tag}][/{tag}]")

    def _load_sample(self):
        sample = (
            "[SA]\n"
            "सर्वे भवन्तु सुखिनः सर्वे सन्तु निरामयाः ।\n"
            "सर्वे भद्राणि पश्यन्तु मा कश्चिद्दुःखभाग्भवेत् ॥\n"
            "[/SA]\n\n"
            "[HI]\n"
            "सभी सुखी हों, सभी रोगमुक्त रहें, सभी मंगलमय घटनाओं के साक्षी बनें और किसी को भी दुःख न हो।\n"
            "[/HI]"
        )
        self.text_area.delete("1.0", tk.END)
        self.text_area.insert("1.0", sample)
        self.lang_mode_var.set("Mixed language")
        self.status_var.set("Sample loaded. Click Generate Audio to synthesize.")

    def _load_document(self):
        filetypes = [
            ("Supported files", "*.pdf;*.txt"),
            ("PDF Documents", "*.pdf"),
            ("Text Files", "*.txt"),
            ("All Files", "*.*"),
        ]
        path = filedialog.askopenfilename(
            title="Open Document", filetypes=filetypes
        )
        if not path:
            return
        try:
            content = read_text_file(path)
            self.text_area.delete("1.0", tk.END)
            self.text_area.insert("1.0", content)
            self.status_var.set(f"Loaded: {Path(path).name} ({len(content)} characters)")
        except Exception as exc:
            messagebox.showerror("Error Reading File", str(exc))

    def _browse_target_voice(self):
        path = filedialog.askopenfilename(
            title="Select Target Voice Recording",
            filetypes=[("Audio files", "*.wav;*.mp3;*.flac;*.m4a"), ("All Files", "*.*")],
        )
        if path:
            self.target_voice_var.set(path)
            self.use_vc_var.set(True)

    def _browse_style_ref(self):
        path = filedialog.askopenfilename(
            title="Select Style Reference Audio",
            filetypes=[("Audio files", "*.wav;*.mp3;*.flac;*.m4a"), ("All Files", "*.*")],
        )
        if path:
            self.style_ref_var.set(path)
            self.use_style_var.set(True)

    def _browse_output(self):
        os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)
        path = filedialog.asksaveasfilename(
            title="Save Output Audio",
            initialdir=DEFAULT_OUTPUT_DIR,
            initialfile="output.wav",
            defaultextension=".wav",
            filetypes=[("WAV Audio", "*.wav"), ("MP3 Audio", "*.mp3")],
        )
        if path:
            self.out_path_var.set(path)

    def _update_status(self, message):
        self.status_var.set(message)

    def _play_output(self):
        if self.output_file and os.path.isfile(self.output_file):
            try:
                os.startfile(self.output_file)
            except Exception as exc:
                messagebox.showerror("Playback Error", str(exc))

    def _open_folder(self):
        folder = DEFAULT_OUTPUT_DIR
        if self.output_file and os.path.isfile(self.output_file):
            folder = os.path.dirname(os.path.abspath(self.output_file))
        os.makedirs(folder, exist_ok=True)
        try:
            os.startfile(folder)
        except Exception as exc:
            messagebox.showerror("Error Opening Folder", str(exc))

    def _start_generation(self):
        text = self.text_area.get("1.0", tk.END).strip()
        if not text:
            messagebox.showwarning("Empty Text", "Please enter some text or load a file first.")
            return

        out_path = self.out_path_var.get().strip()
        if not out_path:
            out_path = os.path.join(DEFAULT_OUTPUT_DIR, "output.wav")
            self.out_path_var.set(out_path)

        if not os.path.dirname(out_path):
            out_path = os.path.join(DEFAULT_OUTPUT_DIR, out_path)
            self.out_path_var.set(out_path)

        # Prepare parameters
        lang_mode = self.lang_mode_var.get()
        source_voice = self.source_voice_var.get()
        target_voice = self.target_voice_var.get().strip()
        style_ref = self.style_ref_var.get().strip()
        use_style = self.use_style_var.get()
        use_vc = self.use_vc_var.get()
        if use_vc:
            try:
                import torch
                try:
                    from chatterbox import ChatterboxVC
                except ImportError:
                    from chatterbox_vc import VoiceConverter
            except ImportError:
                proceed = messagebox.askyesno(
                    "Chatterbox VC Not Installed",
                    "PyTorch / Chatterbox VC is not installed on your system.\n\n"
                    "Would you like to generate the audio directly using high-quality Microsoft Edge Neural TTS instead?"
                )
                if proceed:
                    use_vc = False
                    self.use_vc_var.set(False)
                else:
                    return

        rate_val = self.rate_var.get()
        pitch_val = self.pitch_var.get()
        speed_val = self.speed_var.get()

        # UI state during processing
        self.gen_btn.config(state="disabled")
        self.play_btn.config(state="disabled")
        self.folder_btn.config(state="disabled")
        self.prog_bar.start(10)
        self.status_var.set("Starting synthesis pipeline...")

        def worker():
            try:
                run_pipeline(
                    text=text,
                    language_mode=lang_mode,
                    source_voice_label=source_voice,
                    target_voice_path=target_voice,
                    style_reference_path=style_ref,
                    use_delivery_style=use_style,
                    output_path=out_path,
                    pitch_influence=pitch_val,
                    speed_factor=speed_val,
                    rate_percent=rate_val,
                    status=lambda msg: self.after(0, self._update_status, msg),
                    use_voice_conversion=use_vc,
                )
                self.output_file = out_path
                self.after(0, self._on_success)
            except Exception as exc:
                err_msg = str(exc)
                self.after(0, self._on_failure, err_msg)

        threading.Thread(target=worker, daemon=True).start()

    def _on_success(self):
        self.prog_bar.stop()
        self.gen_btn.config(state="normal")
        self.play_btn.config(state="normal")
        self.folder_btn.config(state="normal")
        self.status_var.set(f"Completed! Output saved to: {Path(self.output_file).name}")
        messagebox.showinfo(
            "Generation Complete",
            f"Successfully generated audio!\n\nSaved to:\n{self.output_file}",
        )

    def _on_failure(self, error_message):
        self.prog_bar.stop()
        self.gen_btn.config(state="normal")
        self.status_var.set(f"Failed: {error_message}")
        messagebox.showerror("Generation Error", error_message)


if __name__ == "__main__":
    app = SanskritStudioApp()
    app.mainloop()
