# Sanskrit Voice Studio V2

A desktop Text-to-Speech (TTS) and Voice Conversion studio tailored for Sanskrit, Hindi, and mixed-language documents. It uses Microsoft Edge TTS neural voices with cross-script transliteration for authentic Sanskrit phonetics, and passes the output through a voice converter to match a custom target speaker.

---

## What This App Is Made For

1. **High-Fidelity Sanskrit & Hindi TTS**:
   Standard Hindi text-to-speech engines often mispronounce classical Sanskrit conjuncts (*saṃyuktākṣara*) and vowel lengths. Sanskrit Voice Studio solves this by transliterating Sanskrit into Dravidian scripts (Telugu, Kannada, or Malayalam) where phonetic correspondence is exceptionally close to classical Sanskrit, and synthesizing them using regional neural voices (e.g. `te-IN-MohanNeural`).

2. **Mixed-Language Support**:
   Supports documents containing both Sanskrit and Hindi seamlessly via inline tags:
   - `[SA]सर्वे भवन्तु सुखिनः[/SA]` for Sanskrit passages.
   - `[HI]सभी सुखी रहें[/HI]` for Hindi commentary or translation.

3. **Target Voice Conversion (Zero-Shot Cloning)**:
   Converts the generated multi-lingual speech into a custom speaker's voice using a target audio sample (`target_voice.wav`).

4. **Style & Prosody Matching (Optional)**:
   Extracts pitch (F0 via YIN algorithm) and pacing from a reference style audio recording to approximate the speaker's vocal pitch and tempo.

5. **Document Ingestion**:
   Directly loads `.txt` files or selectable `.pdf` documents (via PyMuPDF), cleans zero-width characters and whitespace, and chunks text into sentence-level synthesis blocks.

6. **Audio Export**:
   Exports final audio in uncompressed high-fidelity **WAV** (24 kHz) or compressed **MP3** (192 kbps).

---

## Architecture & Processing Pipeline

```
[Document (.pdf / .txt) or Direct Text]
                 │
                 ▼
     [Language Tag Parser]
       ├── [SA] Sanskrit Segments ──► [Indic Transliteration] ──► [Telugu/Kannada/Malayalam Script]
       └── [HI] Hindi Segments    ──► [Devanagari Script]
                 │
                 ▼
     [Edge TTS Neural Synthesis]
       ├── Sanskrit Voices (e.g., te-IN-MohanNeural, kn-IN-GaganNeural)
       └── Hindi Voices (hi-IN-SwaraNeural, hi-IN-MadhurNeural)
                 │
                 ▼
       [Chatterbox Voice Converter] (Transforms voice into your target speaker)
                 │
                 ▼
     [Style Adjustments (Optional)] (Pitch-shift & Time-stretch via Librosa)
                 │
                 ▼
     [Audio Stitching & Export] (.wav / .mp3)
```

---

## Prerequisites & Installation

### 1. Python Environment
Ensure Python 3.10 or higher is installed.

### 2. Core Dependencies
Install the required Python packages:

```bash
pip install soundfile edge-tts librosa numpy pymupdf indic-transliteration pydub torch
```

> **Note on Voice Conversion:**
> The app interfaces with a `chatterbox_vc` package for `VoiceConverter`. Ensure your local Chatterbox model package is installed in your Python environment.

### 3. Optional for MP3 Export
If exporting to MP3, ensure `ffmpeg` is installed and available in your system `PATH`. Alternatively, you can export directly as `.wav` without FFmpeg.

---

## How to Use the Application

### 1. Preparing Your Text

You can provide plain text or annotate mixed sections with tags:
```text
[SA]
ॐ असतो मा सद्गमय ।
तमसो मा ज्योतिर्गमय ।
मृत्योर्मा अमृतं गमय ॥
[/SA]

[HI]
हे प्रभु, मुझे असत्य से सत्य की ओर ले चलो।
अंधकार से प्रकाश की ओर ले चलो।
मृत्यु से अमरता की ओर ले चलो।
[/HI]
```

- In **Sanskrit only** mode: All untagged text is synthesized as Sanskrit.
- In **Hindi only** mode: All untagged text is synthesized as Hindi.
- In **Mixed** mode: Untagged text uses the selected default, and tagged blocks switch dynamically.

### 2. Preparing Reference Audio

- **Target Voice Sample**: A clean, dry recording of the speaker whose voice you want to emulate (WAV format recommended, 10–60 seconds, single speaker with minimal background noise).
- **Style Reference (Optional)**: If delivery style matching is checked, supply an audio clip (at least 1 second) representing the desired pitch and pace.

### 3. Running the Studio

Activate the virtual environment and run:

```powershell
.\.venv\Scripts\Activate.ps1
python song.py
```

Or run directly with the virtual environment interpreter:

```powershell
.\.venv\Scripts\python.exe song.py
```

### 4. Workflow in the Interface

1. **Load or Type Text**: Click **Browse** to select a PDF/TXT document or paste text directly into the text editor.
2. **Select Language Mode**: Choose between *Sanskrit only*, *Hindi only*, or *Mixed*.
3. **Choose Source Voice**: Select the neural source speaker (e.g., *Telugu male - Mohan*, *Hindi female - Swara*).
4. **Choose Target Voice**: Browse and select your target speaker audio recording.
5. **Configure Style Adjustments (Optional)**:
   - Check *Enable Delivery Style* to match pitch and pace.
   - Adjust *Pitch Influence* (0.0 to 1.0) and *Speed Factor* (0.75x to 1.25x).
6. **Output Destination**: By default, all generated audio files are automatically saved inside the dedicated **`output/`** folder (e.g. `output/output.wav`). You can also click **"Choose..."** to save to a specific name or location.
7. **Generate & Clean Up**: Click **"🎙️ Generate Audio"**. Once finished, click **"▶️ Play Audio"** to listen or **"📁 Open Output Folder"** to inspect your files. If you ever want to clean up your recordings, you can delete files inside `output/` (or the folder itself), and the studio will automatically recreate the folder for future generations.
