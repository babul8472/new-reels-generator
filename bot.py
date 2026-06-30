#!/usr/bin/env python3
"""
Premium Video Generation Automation Bot
Telegram (Interactive) → Storyboard (NVIDIA) → WhatsApp Web Meta AI Images → NVIDIA Magpie-TTS → Ken Burns Slideshow → Silence Removal → Background Music Ducking → Telegram reply
"""

import os
import re
import sys
import time
import json
import shutil
import asyncio
import logging
import subprocess
import urllib.request
import urllib.parse
import base64
import wave
from pathlib import Path
from datetime import datetime

# ─── CONFIG ────────────────────────────────────────────────────────────────____
TELEGRAM_TOKEN   = "8854182279:AAG9RffZJqSB6GMUQarplzhbVci3qSMurXU"
NVIDIA_API_KEY   = "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"
NVIDIA_BASE_URL  = "https://integrate.api.nvidia.com/v1"
NVIDIA_MODEL     = "qwen/qwen3.5-122b-a10b"

# Output folder
OUTPUT_DIR       = Path("./video_output")
OUTPUT_DIR.mkdir(exist_ok=True)

# Session directory path for WhatsApp Web
SESSION_DIR = Path(__file__).parent / "whatsapp_session"

# Voice mappings for edge-tts (Fallback)
VOICE_MAPPING_EDGE = {
    ("english", "male"): "en-US-GuyNeural",
    ("english", "female"): "en-US-AriaNeural",
    ("hindi", "male"): "hi-IN-MadhurNeural",
    ("hindi", "female"): "hi-IN-SwaraNeural",
    ("hinglish", "male"): "hi-IN-MadhurNeural",
    ("hinglish", "female"): "hi-IN-SwaraNeural",
}

# Voice mappings for NVIDIA Magpie-TTS
VOICE_MAPPING_NVIDIA = {
    ("english", "male"): ("EN-US.Jason", "en-US"),
    ("english", "female"): ("EN-US.Aria", "en-US"),
    ("hindi", "male"): ("HI-IN.Jason", "hi-IN"),
    ("hindi", "female"): ("HI-IN.Aria", "hi-IN"),
    ("hinglish", "male"): ("HI-IN.Jason", "hi-IN"),
    ("hinglish", "female"): ("HI-IN.Aria", "hi-IN"),
}

# User state storage for interactive Telegram flow
USER_STATES = {}

# Logging
class FlushingStreamHandler(logging.StreamHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except AttributeError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[FlushingStreamHandler(sys.stdout)]
)
log = logging.getLogger(__name__)

# ─── DEPENDENCIES CHECK ─────────────────────────────────────────────────────────
def check_dependencies():
    """Check and install required packages."""
    required = {
        "openai":        "openai",
        "gtts":          "gTTS",
        "playwright":    "playwright",
        "requests":      "requests",
        "edge_tts":      "edge-tts",
        "riva.client":   "nvidia-riva-client",
    }
    missing = []
    for mod, pkg in required.items():
        try:
            if "." in mod:
                parts = mod.split(".")
                parent = __import__(parts[0])
                for part in parts[1:]:
                    getattr(parent, part)
            else:
                __import__(mod)
        except (ImportError, AttributeError):
            missing.append(pkg)

    if missing:
        log.info(f"Installing missing packages: {missing}")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet"] + missing)
        log.info("Installing playwright browsers...")
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])

# ─── ASYNC SUBPROCESS RUNNER ───────────────────────────────────────────────────
async def async_run_command(cmd: list) -> str:
    """Run a shell command asynchronously without blocking the event loop."""
    cmd_str = [str(x) for x in cmd]
    process = await asyncio.create_subprocess_exec(
        *cmd_str,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise subprocess.CalledProcessError(
            returncode=process.returncode,
            cmd=cmd_str,
            output=stdout,
            stderr=stderr
        )
    return stdout.decode("utf-8", errors="ignore")

# ─── JSON PARSER ────────────────────────────────────────────────────────────────
def clean_and_parse_json(text: str) -> dict:
    """Clean and parse JSON from text, handling markdown code blocks and trailing commas."""
    start_obj = text.find("{")
    start_arr = text.find("[")
    
    if start_obj != -1 and (start_arr == -1 or start_obj < start_arr):
        start = start_obj
        end = text.rfind("}")
    elif start_arr != -1:
        start = start_arr
        end = text.rfind("]")
    else:
        raise ValueError("No JSON object or array found in response.")
        
    json_str = text[start:end+1]
    json_str = re.sub(r"//.*", "", json_str)
    json_str = re.sub(r",\s*(?=[\]}])", "", json_str)
    
    return json.loads(json_str)

# ─── STEP 1 & 2: SCRIPT & STORYBOARD GENERATION ─────────────────────────────────
async def generate_script_and_storyboard(topic: str, duration: float, language: str, tone: str, ratio: str) -> tuple[str, list]:
    """
    Generate the storyboard JSON directly in a single LLM call.
    """
    from openai import AsyncOpenAI

    client = AsyncOpenAI(base_url=NVIDIA_BASE_URL, api_key=NVIDIA_API_KEY)
    target_words = int(duration * 2.5) # e.g. 150 words

    ratio_suffix = ", vertical, 9:16 aspect ratio" if ratio == "9:16" else ", widescreen, 16:9 aspect ratio"

    log.info(f"Generating storyboard in a single call for topic: '{topic}' (Target words: {target_words})")

    storyboard_prompt = (
        f"You are a professional video director and scriptwriter. Write a highly engaging, viral video storyboard about the topic: '{topic}' in JSON format.\n\n"
        f"Rules:\n"
        f"1. Break the script into short narration chunks (6-8 words each in {language}). "
        f"The TOTAL word count across ALL narration chunks combined MUST be between 150-170 words — "
        f"not more, not less. Calculate the number of chunks needed based on this target "
        f"(roughly {target_words}//7 chunks). The narration must form ONE continuous, "
        f"logically connected story — no topic jumps, no unrelated facts mixed in mid-script.\n"
        f"2. For each chunk, write a matching 'image_prompt' ALWAYS in English.\n"
        f"   CRITICAL FILTER-SAFETY RULE: The 'image_prompt' must NEVER contain any people, human "
        f"characters, faces, hands, or body parts. Instead, represent the narration using beautiful "
        f"nature landscapes, symbolic objects, conceptual metaphors, architecture, or abstract art. "
        f"For example, instead of a person meditating, describe a peaceful zen garden; instead of "
        f"people talking, describe a warm campfire; instead of hands clasped, describe interlocking "
        f"puzzle pieces. This is to guarantee the prompt never triggers AI content filters.\n"
        f"   NAMED PUBLIC FIGURE RULE: If the narration mentions a real, named public figure "
        f"(historical, political, royal, celebrity, etc.), the 'image_prompt' must NEVER include "
        f"their actual name or any direct visual identifier of their real face/likeness. Instead, "
        f"represent them through symbolic objects associated with their role, era, or story — "
        f"e.g. instead of naming a king, describe his crown and throne; instead of naming a queen, "
        f"describe her signature jewelry or attire draped over a chair; instead of a specific "
        f"president, describe the architecture of their office or a symbolic object tied to their "
        f"era. The goal is to visually evoke who they are through context and symbolism alone, "
        f"never through their name or face.\n"
        f"3. Every image prompt must be a highly detailed, cinematic description of the subject, "
        f"environment, setting, lighting, mood, colors, camera angle, composition, and art style.\n"
        f"   DYNAMIC VISUAL STYLE RULE: First, analyze the topic and determine the best matching visual style "
        f"(art style, color palette, lighting, mood) for this specific content type. Describe this style in the "
        f"'selected_visual_style' field of the JSON. Then, ensure every single 'image_prompt' in the 'scenes' list "
        f"shares and incorporates this exact consistent visual style so the final video feels visually cohesive.\n"
        f"4. The first chunk's narration must be a hook question directly related to the topic "
        f"(not generic). The final chunk's narration must always be a call-to-action telling the "
        f"viewer to comment and subscribe.\n"
        f"5. CRITICAL: Every single 'image_prompt' MUST end with the exact phrase: \"{ratio_suffix}\".\n"
        f"6. Output ONLY a valid JSON object with keys 'selected_visual_style' and 'scenes'. "
        f"Do not add any other text, explanation, or markdown formatting.\n\n"
        f"Format:\n"
        f"{{\n"
        f"  \"selected_visual_style\": \"[Art style, color palette, lighting, mood matching the topic]\",\n"
        f"  \"scenes\": [\n"
        f"    {{\n"
        f"      \"id\": 1,\n"
        f"      \"narration\": \"[Max 6-8 words in {language}]\",\n"
        f"      \"image_prompt\": \"[Detailed visual description in English sharing the selected style]{ratio_suffix}\"\n"
        f"    }}\n"
        f"  ]\n"
        f"}}"
    )

    completion = await client.chat.completions.create(
        model=NVIDIA_MODEL,
        messages=[
            {"role": "system", "content": "You are a professional video director and storyboard generator. You output ONLY valid JSON objects without any markdown or extra text."},
            {"role": "user", "content": storyboard_prompt}
        ],
        temperature=0.4,
        max_tokens=3000
    )
    
    content = completion.choices[0].message.content
    if not content:
        finish_reason = completion.choices[0].finish_reason if completion.choices else "unknown"
        log.error(f"NVIDIA LLM returned empty content. Finish reason: {finish_reason}")
        raise Exception(f"NVIDIA LLM returned a blank response (API error or safety block. Reason: {finish_reason}). Please try again or use a different topic.")
        
    storyboard_text = content.strip()
    
    try:
        parsed_json = clean_and_parse_json(storyboard_text)
        if isinstance(parsed_json, dict) and "scenes" in parsed_json:
            storyboard_list = parsed_json["scenes"]
            visual_style = parsed_json.get("selected_visual_style", "cinematic, photorealistic")
            log.info(f"LLM Selected Visual Style: {visual_style}")
        elif isinstance(parsed_json, list):
            storyboard_list = parsed_json
        else:
            raise ValueError("Unexpected JSON structure")
    except Exception as e:
        log.error(f"Failed to parse storyboard JSON. Raw response: {storyboard_text}")
        raise Exception(f"Failed to generate a valid storyboard JSON: {e}")

    # Reconstruct full script text from chunks
    narrations = [scene["narration"] for scene in storyboard_list]
    script_text = " ".join(narrations)
    
    log.info(f"Storyboard JSON generated successfully with {len(storyboard_list)} scenes.")
    log.info(f"Reconstructed Script ({len(script_text.split())} words): {script_text}")
    
    return script_text, storyboard_list

# ─── STEP 3: WHATSAPP META AI IMAGE GENERATION ──────────────────────────────────
async def launch_browser(p, headless=True):
    """Launch a persistent browser context using Playwright's bundled Chromium."""
    SESSION_DIR.mkdir(exist_ok=True)
    
    lock_file = SESSION_DIR / "SingletonLock"
    if lock_file.exists():
        try:
            lock_file.unlink()
        except Exception:
            pass
            
    log.info("Launching persistent bundled Chromium...")
    context = await p.chromium.launch_persistent_context(
        user_data_dir=str(SESSION_DIR),
        headless=headless,
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 800},
        ignore_default_args=["--enable-automation"] if not headless else None,
    )
    return context

async def login_whatsapp():
    """Launch a headed persistent browser for WhatsApp Web login."""
    from playwright.async_api import async_playwright
    log.info("Launching headed persistent browser for WhatsApp Web login...")
    async with async_playwright() as p:
        context = await launch_browser(p, headless=False)
        page = await context.new_page()
        
        log.info("Navigating to WhatsApp Web...")
        await page.goto("https://web.whatsapp.com/", wait_until="commit", timeout=120000)
        
        log.info("=" * 60)
        log.info(" PLEASE SCAN THE QR CODE ON THE OPENED BROWSER WINDOW (IF NOT LOGGED IN).")
        log.info(" ONCE YOU ARE LOGGED IN AND SEE YOUR CHATS:")
        log.info(" PRESS [ENTER] IN THIS CONSOLE WINDOW TO CLOSE THE BROWSER.")
        log.info("=" * 60)
        
        await asyncio.get_event_loop().run_in_executor(None, input, "Press [Enter] here after logging in...")
        
        await context.close()
        log.info("WhatsApp session saved successfully.")

async def rewrite_prompt_for_safety(prompt: str) -> str:
    """Ask Qwen to rewrite the prompt to be safe and avoid AI content filters."""
    from openai import AsyncOpenAI
    try:
        client = AsyncOpenAI(base_url=NVIDIA_BASE_URL, api_key=NVIDIA_API_KEY)
        system_msg = (
            "You are an AI prompt safety expert. Your task is to rewrite the given image prompt to make it extremely safe, simple, and ensure it does NOT trigger AI content filters.\n"
            "Guidelines:\n"
            "- Focus on beautiful scenery, landscapes, objects, or abstract art.\n"
            "- Remove any references to groups of people, specific body parts, or potentially sensitive situations.\n"
            "- Keep the style description (cinematic, colors, aspect ratio) intact.\n"
            "- Output ONLY the rewritten prompt string. No explanations."
        )
        completion = await client.chat.completions.create(
            model=NVIDIA_MODEL,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": f"Rewrite this prompt: {prompt}"}
            ],
            temperature=0.3,
            max_tokens=200
        )
        rewritten = completion.choices[0].message.content.strip()
        if rewritten:
            return rewritten
    except Exception as e:
        log.error(f"Failed to rewrite prompt for safety: {e}")
    
    # Simple fallback: strip common triggering words manually
    safe_prompt = prompt
    safe_prompt = re.sub(r"\b(group of people|people|person|man|woman|child|children|boy|girl|crowd)\b", "scenery", safe_prompt, flags=re.IGNORECASE)
    return safe_prompt

async def generate_images_whatsapp(prompts: list, out_dir: Path) -> list:
    """
    Uses Playwright to generate images via WhatsApp Web.
    Falls back to Picsum placeholder images if WhatsApp is not logged in or fails.
    """
    image_paths = []
    
    use_fallback = False
    if not SESSION_DIR.exists() or not any(SESSION_DIR.iterdir()):
        log.warning("WhatsApp session not found. Please run with --login-whatsapp first. Falling back to Picsum...")
        use_fallback = True
        
    if not use_fallback:
        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as p:
                log.info("Launching persistent browser for WhatsApp Web...")
                context = await launch_browser(p, headless=True)
                page = await context.new_page()
                
                log.info("Navigating to WhatsApp Web...")
                await page.goto("https://web.whatsapp.com/", wait_until="commit", timeout=120000)
                
                log.info("Waiting for WhatsApp Web to load...")
                try:
                    await page.wait_for_selector('div[contenteditable="true"], span[title="Meta AI"]', timeout=120000)
                except Exception:
                    log.error("Failed to load WhatsApp Web (timeout). The session might have expired. Using Picsum fallback...")
                    use_fallback = True
                    await context.close()
                    
                if not use_fallback:
                    meta_ai_chat = page.locator('span[title="Meta AI"], span:has-text("Meta AI")').first
                    if await meta_ai_chat.is_visible():
                        log.info("Found Meta AI chat directly in the chat list. Clicking it...")
                        await meta_ai_chat.click()
                    else:
                        log.info("Meta AI chat not immediately visible. Searching for it...")
                        search_box = await page.wait_for_selector('div[contenteditable="true"]', timeout=15000)
                        await search_box.click()
                        await search_box.fill("Meta AI")
                        await page.keyboard.press("Enter")
                        await asyncio.sleep(3)
                        
                        meta_ai_chat = page.locator('span[title="Meta AI"], span:has-text("Meta AI")').first
                        if not meta_ai_chat:
                            log.error("Meta AI chat not found after search. Using Picsum placeholders...")
                            use_fallback = True
                        else:
                            await meta_ai_chat.click()
                            
                    if not use_fallback:
                        log.info("Opened Meta AI chat successfully.")
                        await asyncio.sleep(2)
                        
                        chat_panel_selector = 'div[data-testid="conversation-panel-messages"], div.copyable-area'
                        
                        # Get the initial last image src once before the loop starts
                        last_img_el = page.locator(f'{chat_panel_selector} img').last
                        last_src_before = None
                        if await last_img_el.count() > 0:
                            last_src_before = await last_img_el.get_attribute("src")
                        log.info(f"Initial last image src before generation: {last_src_before[:50] if last_src_before else 'None'}")
                        
                        for idx, prompt in enumerate(prompts):
                            image_path = out_dir / f"scene{idx+1:02d}.png"
                            log.info(f"Generating image {idx+1}/{len(prompts)}: {prompt[:60]}...")
                            
                            success = False
                            current_prompt = prompt
                            for attempt in range(3):
                                if attempt > 0:
                                    log.info(f"  Attempting with rewritten safety prompt...")
                                    current_prompt = await rewrite_prompt_for_safety(prompt)
                                    log.info(f"  New prompt: {current_prompt[:60]}...")
                                    
                                log.info(f"  Attempt {attempt+1}/3...")
                                try:
                                    log.info(f"  Last image src before: {last_src_before[:50] if last_src_before else 'None'}")
                                    
                                    input_box = await page.wait_for_selector('div[contenteditable="true"][data-tab="10"], div[title="Type a message"]', timeout=15000)
                                    await input_box.click()
                                    await input_box.fill(f"imagine {current_prompt}")
                                    await page.keyboard.press("Enter")
                                    log.info("  Sent prompt to Meta AI.")
                                    
                                    new_image_el = None
                                    src = None
                                    filter_triggered = False
                                    for poll in range(45):
                                        await asyncio.sleep(2)
                                        
                                        # Check if Meta AI sent a text rejection message
                                        try:
                                            last_msgs = page.locator('div.message-in')
                                            count = await last_msgs.count()
                                            if count > 0:
                                                for i in range(max(0, count - 2), count):
                                                    msg_text = await last_msgs.nth(i).inner_text()
                                                    if any(k in msg_text.lower() for k in ["couldn't generate", "content filter", "policy", "safety guidelines", "can't generate", "sensitive"]):
                                                        log.warning(f"  [Content Filter Triggered] Meta AI rejected the prompt: '{msg_text[:120]}...'")
                                                        filter_triggered = True
                                                        break
                                        except Exception:
                                            pass
                                            
                                        if filter_triggered:
                                            break
                                            
                                        current_last_img = page.locator(f'{chat_panel_selector} img').last
                                        if await current_last_img.count() > 0:
                                            current_src = await current_last_img.get_attribute("src")
                                            if current_src and current_src != last_src_before and current_src.startswith("blob:"):
                                                new_image_el = current_last_img
                                                src = current_src
                                                break
                                                
                                    if filter_triggered or not new_image_el or not src:
                                        log.warning(f"  Failed to get image on attempt {attempt+1} (Filter triggered: {filter_triggered}).")
                                        continue
                                        
                                    log.info(f"  Downloading high-res image from src: {src[:50]}...")
                                    base64_data = await page.evaluate("""async (url) => {
                                        const response = await fetch(url);
                                        const blob = await response.blob();
                                        return new Promise((resolve) => {
                                            const reader = new FileReader();
                                            reader.onloadend = () => resolve(reader.result.split(',')[1]);
                                            reader.readAsDataURL(blob);
                                        });
                                    }""", src)
                                    with open(image_path, "wb") as f:
                                        f.write(base64.b64decode(base64_data))
                                            
                                    image_paths.append(image_path)
                                    last_src_before = src
                                    success = True
                                    break
                                except Exception as e:
                                    log.error(f"  Error on attempt {attempt+1}: {e}")
                                    await asyncio.sleep(5)
                                    
                            if not success:
                                log.error(f"Failed to generate image for scene {idx+1}. Using Picsum placeholder...")
                                await download_picsum_placeholder(image_path, idx)
                                image_paths.append(image_path)
                                
                    await context.close()
        except Exception as e:
            log.error(f"Error during WhatsApp Web image generation: {e}")
            log.warning("Falling back to Picsum placeholders...")
            use_fallback = True
            
    if use_fallback:
        for idx, prompt in enumerate(prompts):
            image_path = out_dir / f"scene{idx+1:02d}.png"
            await download_picsum_placeholder(image_path, idx)
            image_paths.append(image_path)
            
    return image_paths

def _download_picsum_placeholder_sync(image_path: Path, index: int):
    """Download a high-quality placeholder image from Picsum."""
    url = f"https://picsum.photos/1080/1920?random={index}"
    log.info(f"Downloading Picsum placeholder image: {url} -> {image_path}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as resp, open(image_path, "wb") as f:
            f.write(resp.read())
    except Exception as e:
        log.error(f"Failed to download Picsum placeholder: {e}")
        log.info("Creating a colored image using FFmpeg as fallback...")
        color = ["red", "blue", "green", "purple", "orange", "yellow"][index % 6]
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"color=c={color}:s=1080x1920:d=1",
            "-vframes", "1",
            str(image_path)
        ]
        subprocess.run(cmd, check=True, capture_output=True)

async def download_picsum_placeholder(image_path: Path, index: int):
    await asyncio.to_thread(_download_picsum_placeholder_sync, image_path, index)

# ─── STEP 4: VOICE GENERATION (TTS) ─────────────────────────────────────────────
async def generate_scene_voice_async(text: str, output_mp3: Path, output_wav: Path, language: str, gender: str, default_duration: float = 5.0) -> tuple[Path, float]:
    """Generate TTS WAV using edge-tts, falling back to gTTS."""
    clean_text = re.sub(r"[^a-zA-Z0-9\u0900-\u097F]", "", text)
    if not clean_text:
        log.info(f"No speakable text found for scene narration ('{text}'). Generating {default_duration}s of silence...")
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", "anullsrc=r=44100:cl=stereo",
            "-t", f"{default_duration:.3f}",
            "-acodec", "pcm_s16le",
            str(output_wav)
        ]
        await async_run_command(cmd)
        return output_wav, default_duration

    lang_clean = "hindi"
    gender_clean = "female"
    if "male" in gender.lower() and "female" not in gender.lower():
        gender_clean = "male"
        
    success = False
    
    # Use edge-tts directly (excellent neural voices)
    voice_edge = VOICE_MAPPING_EDGE.get((lang_clean, gender_clean), "hi-IN-SwaraNeural")
    log.info(f"Generating TTS using edge-tts (voice: {voice_edge}) for: '{text[:40]}...'")
    try:
        import edge_tts
        communicate = edge_tts.Communicate(text, voice_edge)
        await communicate.save(str(output_mp3))
        
        cmd_convert = [
            "ffmpeg", "-y",
            "-i", str(output_mp3),
            "-acodec", "pcm_s16le",
            "-ar", "44100",
            str(output_wav)
        ]
        await async_run_command(cmd_convert)
        success = True
    except Exception as e:
        log.error(f"edge-tts failed: {e}. Falling back to gTTS...")

    # Fallback to gTTS
    if not success:
        try:
            from gtts import gTTS
            tts = gTTS(text=text, lang="hi", slow=False)
            await asyncio.to_thread(tts.save, str(output_mp3))
            
            cmd_convert = [
                "ffmpeg", "-y",
                "-i", str(output_mp3),
                "-acodec", "pcm_s16le",
                "-ar", "44100",
                str(output_wav)
            ]
            await async_run_command(cmd_convert)
            success = True
        except Exception as e2:
            log.error(f"gTTS fallback failed: {e2}")

    # Absolute Fallback: Silence
    if not success:
        log.warning("All TTS options failed. Generating silence...")
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", "anullsrc=r=44100:cl=stereo",
            "-t", f"{default_duration:.3f}",
            "-acodec", "pcm_s16le",
            str(output_wav)
        ]
        await async_run_command(cmd)

    # Measure duration
    cmd_duration = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(output_wav)
    ]
    result = await async_run_command(cmd_duration)
    duration = float(result.strip())

    log.info(f"Voice generated. Duration: {duration:.2f}s")
    return output_wav, duration

async def concat_audio_files(audio_paths: list, output_path: Path):
    """Concatenate multiple audio files using FFmpeg's concat filter."""
    if len(audio_paths) == 1:
        shutil.copy(str(audio_paths[0]), str(output_path))
        return

    inputs = []
    filter_inputs = []
    for i, ap in enumerate(audio_paths):
        inputs.extend(["-i", str(ap)])
        filter_inputs.append(f"[{i}:a]")

    filter_complex = "".join(filter_inputs) + f"concat=n={len(audio_paths)}:v=0:a=1[a]"

    cmd = [
        "ffmpeg", "-y"
    ] + inputs + [
        "-filter_complex", filter_complex,
        "-map", "[a]",
        str(output_path)
    ]

    await async_run_command(cmd)

# ─── STEP 5: VIDEO CLIP CREATION (KEN BURNS & FADES) ───────────────────────────
async def create_scene_video(image_path: Path, duration: float, output_path: Path, index: int, ratio: str = "9:16"):
    """Create a single scene video from an image with a smooth Ken Burns effect."""
    frames = int(duration * 30)

    if index % 2 == 0:
        zoom_expr = "min(zoom+0.0015,1.5)"
    else:
        zoom_expr = "max(1.5-0.0015*on,1.0)"

    if ratio == "16:9":
        size = "1920x1080"
        scale_filter = "scale=-1:2000"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"
    else:
        size = "1080x1920"
        scale_filter = "scale=2000:-1"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(image_path),
        "-vf", f"{scale_filter},zoompan=z='{zoom_expr}':x='{x_expr}':y='{y_expr}':d={frames}:s={size}:fps=30",
        "-t", f"{duration:.3f}",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        str(output_path)
    ]

    await async_run_command(cmd)

# ─── STEP 6: MERGE ALL SCENES ───────────────────────────────────────────────────
async def merge_scenes_with_crossfade(video_paths: list, durations: list, transition_duration: float, output_path: Path):
    """Merge video clips with a crossfade transition between them."""
    if len(video_paths) == 1:
        shutil.copy(str(video_paths[0]), str(output_path))
        return

    inputs = []
    for vp in video_paths:
        inputs.extend(["-i", str(vp)])

    filter_parts = []
    offset = durations[0] - transition_duration
    filter_parts.append(f"[0:v][1:v]xfade=transition=fade:duration={transition_duration}:offset={offset:.3f}[v01]")
    current_out = "[v01]"

    accumulated_duration = durations[0] + durations[1] - transition_duration

    for i in range(2, len(video_paths)):
        offset = accumulated_duration - transition_duration
        next_out = f"[v0{i}]"
        filter_parts.append(f"{current_out}[{i}:v]xfade=transition=fade:duration={transition_duration}:offset={offset:.3f}{next_out}")
        current_out = next_out
        accumulated_duration = accumulated_duration + durations[i] - transition_duration

    filter_complex = ";".join(filter_parts)

    cmd = [
        "ffmpeg", "-y"
    ] + inputs + [
        "-filter_complex", filter_complex,
        "-map", current_out,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        str(output_path)
    ]

    await async_run_command(cmd)

# ─── STEP 7: REMOVE SILENCE (AUTO CUT) ──────────────────────────────────────────
async def detect_non_silent_intervals(audio_path: Path, noise_db: float = -30, min_silence_duration: float = 0.3) -> list:
    """Parse FFmpeg silencedetect output to find non-silent intervals."""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(audio_path),
        "-af", f"silencedetect=noise={noise_db}dB:d={min_silence_duration}",
        "-f", "null",
        "-"
    ]
    try:
        # We need stderr from async command
        cmd_str = [str(x) for x in cmd]
        process = await asyncio.create_subprocess_exec(
            *cmd_str,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr_bytes = await process.communicate()
        stderr = stderr_bytes.decode("utf-8", errors="ignore")
    except Exception as e:
        log.error(f"silencedetect error: {e}")
        return [(0.0, 30.0)]

    duration = 30.0
    duration_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", stderr)
    if duration_match:
        h, m, s = duration_match.groups()
        duration = int(h) * 3600 + int(m) * 60 + float(s)

    silence_starts = [float(x) for x in re.findall(r"silence_start:\s*(\d+\.?\d*)", stderr)]
    silence_ends = [float(x) for x in re.findall(r"silence_end:\s*(\d+\.?\d*)", stderr)]

    silence_intervals = []
    for i in range(min(len(silence_starts), len(silence_ends))):
        silence_intervals.append((silence_starts[i], silence_ends[i]))

    non_silent_intervals = []
    current_time = 0.0
    for start, end in silence_intervals:
        if start > current_time + 0.1:
            non_silent_intervals.append((current_time, start))
        current_time = end

    if current_time < duration - 0.1:
        non_silent_intervals.append((current_time, duration))

    if not non_silent_intervals:
        non_silent_intervals.append((0.0, duration))

    return non_silent_intervals

async def cut_silence(video_path: Path, intervals: list, output_path: Path):
    """Cut silent parts from the video and audio using trim and concat."""
    filter_parts = []
    concat_parts = []
    for i, (start, end) in enumerate(intervals):
        filter_parts.append(f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}];")
        filter_parts.append(f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}];")
        concat_parts.append(f"[v{i}][a{i}]")

    filter_complex = "".join(filter_parts) + "".join(concat_parts) + f"concat=n={len(intervals)}:v=1:a=1[vout][aout]"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", "[aout]",
        "-c:v", "libx264",
        "-c:a", "aac",
        str(output_path)
    ]

    await async_run_command(cmd)

# ─── STEP 8: BACKGROUND MUSIC ──────────────────────────────────────────────────
def _download_bg_music_sync(url: str, bg_music_path: Path):
    """Download background music synchronously."""
    try:
        urllib.request.urlretrieve(url, str(bg_music_path))
    except Exception as e:
        log.error(f"Failed to download bg music: {e}")
        # Create silent file
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", "anullsrc=r=44100:cl=stereo",
            "-t", "60",
            "-c:a", "libmp3lame",
            str(bg_music_path)
        ]
        subprocess.run(cmd, check=True, capture_output=True)

async def ensure_bg_music(project_dir: Path) -> Path:
    """Download a default background music track if missing, or generate silent fallback."""
    bg_music_path = project_dir / "bg_music.mp3"
    if not bg_music_path.exists():
        url = "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3"
        log.info(f"Downloading default background music from {url}...")
        await asyncio.to_thread(_download_bg_music_sync, url, bg_music_path)
    return bg_music_path

async def generate_sfx(output_path: Path, index: int):
    """Generate a random transition sound effect using FFmpeg (whoosh, ding, or chime)."""
    sfx_type = index % 3
    if sfx_type == 0:
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", "anoisesrc=d=0.5:c=white:r=44100",
            "-af", "afade=t=in:ss=0:d=0.2,afade=t=out:st=0.2:d=0.3,volume=0.25",
            "-ac", "2",
            str(output_path)
        ]
    elif sfx_type == 1:
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", "sine=f=880:d=0.5",
            "-af", "afade=t=out:st=0.1:d=0.4,volume=0.15",
            "-ac", "2",
            "-ar", "44100",
            str(output_path)
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", "sine=f=1000:d=0.5",
            "-f", "lavfi",
            "-i", "sine=f=1200:d=0.5",
            "-filter_complex", "[0:a][1:a]amix=inputs=2[mixed];[mixed]afade=t=out:st=0.1:d=0.4,volume=0.12[a]",
            "-map", "[a]",
            "-ac", "2",
            "-ar", "44100",
            str(output_path)
        ]
    await async_run_command(cmd)

# ─── PIPELINE ORCHESTRATION ─────────────────────────────────────────────────────
async def run_pipeline(topic: str, duration: float, language: str, tone: str, gender: str, ratio: str, job_dir: Path) -> Path:
    """Runs the entire 9-step video generation pipeline and returns final.mp4 path."""
    # Step 1 & 2: Generate Storyboard
    script_text, storyboard = await generate_script_and_storyboard(topic, duration, language, tone, ratio)
    
    script_file = job_dir / "script.txt"
    script_file.write_text(script_text, encoding="utf-8")
    log.info(f"Saved script to {script_file}")
    
    storyboard_file = job_dir / "storyboard.json"
    storyboard_file.write_text(json.dumps(storyboard, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"Saved storyboard to {storyboard_file}")
    
    # Step 3: Image Generation (WhatsApp Meta AI)
    prompts = [scene["image_prompt"] for scene in storyboard]
    
    images_dir = job_dir / "images"
    images_dir.mkdir(exist_ok=True)
    
    image_paths = await generate_images_whatsapp(prompts, images_dir)
    
    # Step 4: Voice Generation
    voice_dir = job_dir / "voice"
    voice_dir.mkdir(exist_ok=True)
    
    scene_audio_paths = []
    scene_durations = []
    
    for idx, scene in enumerate(storyboard):
        scene_mp3 = voice_dir / f"scene{idx+1:02d}.mp3"
        scene_wav = voice_dir / f"scene{idx+1:02d}.wav"
        wav_path, scene_dur = await generate_scene_voice_async(
            scene["narration"], scene_mp3, scene_wav, language, gender, duration / len(storyboard)
        )
        scene_audio_paths.append(wav_path)
        scene_durations.append(scene_dur)
        
    voice_wav_path = job_dir / "voice.wav"
    await concat_audio_files(scene_audio_paths, voice_wav_path)
    
    # Step 5: Video Creation (Slideshow scenes)
    clips_dir = job_dir / "clips"
    clips_dir.mkdir(exist_ok=True)
    
    scene_video_paths = []
    for idx, scene in enumerate(storyboard):
        clip_path = clips_dir / f"scene{idx+1:02d}.mp4"
        clip_duration = scene_durations[idx] + 0.5
        await create_scene_video(image_paths[idx], clip_duration, clip_path, idx, ratio)
        scene_video_paths.append(clip_path)
        
    # Step 6: Merge All Scenes
    merged_video_path = job_dir / "merged_scenes.mp4"
    clip_durations_for_merge = [d + 0.5 for d in scene_durations]
    await merge_scenes_with_crossfade(scene_video_paths, clip_durations_for_merge, 0.5, merged_video_path)
    
    # Overlay the voiceover
    video_path = job_dir / "video.mp4"
    cmd_overlay = [
        "ffmpeg", "-y",
        "-i", str(merged_video_path),
        "-i", str(voice_wav_path),
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        str(video_path)
    ]
    await async_run_command(cmd_overlay)
    
    # Step 7: Remove Silence
    non_silent_intervals = await detect_non_silent_intervals(voice_wav_path)
    clean_video_path = job_dir / "clean_video.mp4"
    await cut_silence(video_path, non_silent_intervals, clean_video_path)
    
    # Step 8: Add Background Music & Transition Sound Effects
    bg_music_path = await ensure_bg_music(Path(__file__).parent)
    final_audio_path = job_dir / "final_audio.mp3"
    
    transition_offsets = []
    current_offset = 0.0
    for dur in scene_durations[:-1]:
        current_offset += dur
        transition_offsets.append(current_offset)
        
    sfx_dir = job_dir / "sfx"
    sfx_dir.mkdir(exist_ok=True)
    sfx_paths = []
    for idx, offset in enumerate(transition_offsets):
        sfx_path = sfx_dir / f"sfx_{idx+1}.wav"
        await generate_sfx(sfx_path, idx)
        sfx_paths.append(sfx_path)
        
    filter_parts = []
    sfx_labels = []
    for idx, offset in enumerate(transition_offsets):
        input_idx = 2 + idx
        offset_ms = int(offset * 1000)
        label = f"[sfx_del{idx}]"
        filter_parts.append(f"[{input_idx}:a]adelay={offset_ms}|{offset_ms}{label}")
        sfx_labels.append(label)
        
    if sfx_labels:
        filter_parts.append(f"{''.join(sfx_labels)}amix=inputs={len(sfx_labels)}:normalize=0[sfx_mixed]")
        sfx_mix_label = "[sfx_mixed]"
    else:
        filter_parts.append("anullsrc=r=44100:cl=stereo:d=0.1[sfx_mixed]")
        sfx_mix_label = "[sfx_mixed]"
        
    filter_parts.append("[0:a]volume=1.0[voice]")
    filter_parts.append("[1:a]volume=0.15[bg]")
    filter_parts.append("[bg][voice]sidechaincompress=threshold=0.1:ratio=20:attack=100:release=500[ducked]")
    filter_parts.append(f"[voice][ducked]{sfx_mix_label}amix=inputs=3:duration=first[a]")
    
    filter_complex_str = ";".join(filter_parts)
    
    inputs = [
        "-i", str(clean_video_path),
        "-i", str(bg_music_path)
    ]
    for sp in sfx_paths:
        inputs.extend(["-i", str(sp)])
        
    cmd_duck = [
        "ffmpeg", "-y"
    ] + inputs + [
        "-filter_complex", filter_complex_str,
        "-map", "[a]",
        "-c:a", "libmp3lame",
        str(final_audio_path)
    ]
    await async_run_command(cmd_duck)
    
    # Step 9: Final Render
    final_video_path = job_dir / "final.mp4"
    cmd_final = [
        "ffmpeg", "-y",
        "-i", str(clean_video_path),
        "-i", str(final_audio_path),
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        str(final_video_path)
    ]
    await async_run_command(cmd_final)
    
    return final_video_path

# ─── TELEGRAM BOT (NON-BLOCKING ASYNC) ──────────────────────────────────────────
def _get_updates_sync(offset=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?timeout=30"
    if offset:
        url += f"&offset={offset}"
    try:
        with urllib.request.urlopen(url, timeout=35) as r:
            return json.loads(r.read())
    except Exception as e:
        log.error(f"getUpdates error: {e}")
        return {"ok": False, "result": []}

async def get_updates(offset=None):
    return await asyncio.to_thread(_get_updates_sync, offset)

def _send_message_sync(chat_id, text, keyboard=None):
    payload_data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if keyboard:
        payload_data["reply_markup"] = {"inline_keyboard": keyboard}
        
    payload = json.dumps(payload_data).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except Exception as e:
        log.error(f"sendMessage error: {e}")
        return {"ok": False}

async def send_message(chat_id, text, keyboard=None):
    return await asyncio.to_thread(_send_message_sync, chat_id, text, keyboard)

def _edit_message_sync(chat_id, message_id, text, keyboard=None):
    payload_data = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if keyboard:
        payload_data["reply_markup"] = {"inline_keyboard": keyboard}
        
    payload = json.dumps(payload_data).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except Exception as e:
        log.error(f"editMessageText error: {e}")
        return {"ok": False}

async def edit_message(chat_id, message_id, text, keyboard=None):
    return await asyncio.to_thread(_edit_message_sync, chat_id, message_id, text, keyboard)

def _answer_callback_query_sync(callback_query_id):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery?callback_query_id={callback_query_id}"
    try:
        with urllib.request.urlopen(url) as r:
            return json.loads(r.read())
    except Exception:
        return {"ok": False}

async def answer_callback_query(callback_query_id):
    return await asyncio.to_thread(_answer_callback_query_sync, callback_query_id)

def _delete_message_sync(chat_id, message_id):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteMessage?chat_id={chat_id}&message_id={message_id}"
    try:
        with urllib.request.urlopen(url) as r:
            return json.loads(r.read())
    except Exception:
        return {"ok": False}

async def delete_message(chat_id, message_id):
    if message_id:
        return await asyncio.to_thread(_delete_message_sync, chat_id, message_id)

def _send_video_sync(chat_id, video_path, caption=""):
    import requests
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
    log.info(f"Uploading video {video_path.name} ({video_path.stat().st_size / (1024*1024):.2f} MB) to Telegram...")
    try:
        with open(video_path, "rb") as vf:
            resp = requests.post(url, data={"chat_id": chat_id, "caption": caption}, files={"video": vf}, timeout=360)
        return resp.json()
    except Exception as e:
        log.error(f"sendVideo error: {e}")
        return {"ok": False, "description": str(e)}

async def send_video(chat_id, video_path, caption=""):
    return await asyncio.to_thread(_send_video_sync, chat_id, video_path, caption)

# ─── INTERACTIVE STATE MACHINE ──────────────────────────────────────────────────
async def start_interactive_flow(chat_id: int):
    """Start the multi-step interactive video configuration flow."""
    USER_STATES[chat_id] = {
        "state": "WAITING_FOR_TOPIC"
    }
    await send_message(chat_id, "🎬 Let's generate a premium video!\n\n✍️ Please reply to this message with your **Topic** (e.g., <i>The future of space travel</i>):")

async def handle_user_message(chat_id: int, text: str, user_msg_id: int = None):
    """Handle text messages during the interactive flow."""
    state_data = USER_STATES.get(chat_id)
    if not state_data or state_data["state"] != "WAITING_FOR_TOPIC":
        await start_interactive_flow(chat_id)
        return

    topic = text.strip()
    import random
    gender = random.choice(["male", "female"])
    
    job_data = {
        "topic": topic,
        "duration": 60.0,
        "ratio": "9:16",
        "language": "hindi",
        "tone": "dramatic",
        "gender": gender
    }

    # Send starting status as a new message at the bottom
    msg = await send_message(
        chat_id,
        f"🎬 <b>Starting 10-Step Video Generation:</b>\n"
        f"Topic: <i>{topic}</i>\n"
        f"Duration: <i>60s</i>\n"
        f"Aspect Ratio: <i>Vertical (9:16)</i>\n"
        f"Language: <i>Hindi (Pure)</i>\n"
        f"Voice Gender: <i>{gender.capitalize()}</i>\n\n"
        f"🚀 Generating script and storyboard..."
    )
    new_message_id = msg["result"]["message_id"] if msg.get("ok") else None
    
    USER_STATES.pop(chat_id, None)
    
    asyncio.create_task(run_job_pipeline(chat_id, job_data, new_message_id))

async def handle_callback_query(chat_id: int, query_id: str, data: str):
    """Callback query stub in case old buttons are clicked."""
    await answer_callback_query(query_id)

async def run_job_pipeline(chat_id: int, data: dict, message_id: int):
    """Orchestrates the background video generation pipeline job."""
    topic = data["topic"]
    duration = data["duration"]
    language = data["language"]
    tone = data["tone"]
    gender = data["gender"]
    ratio = data["ratio"]

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    job_dir = OUTPUT_DIR / f"job_{ts}"
    job_dir.mkdir(exist_ok=True)

    try:
        final_video = await run_pipeline(topic, duration, language, tone, gender, ratio, job_dir)
        
        await edit_message(
            chat_id,
            message_id,
            f"🎬 <b>Generation Complete!</b>\n"
            f"Topic: <i>{topic}</i>\n"
            f"Duration: <i>{duration}s</i>\n"
            f"Aspect Ratio: <i>{ratio}</i>\n\n"
            f"📤 Uploading final video to Telegram..."
        )
        
        result = await send_video(chat_id, final_video, caption=f"🎬 {topic}\n\nGenerated by AI Video Bot")
        
        if result.get("ok"):
            await edit_message(
                chat_id,
                message_id,
                f"✅ <b>Success!</b> Your video is ready.\n"
                f"Topic: <i>{topic}</i>\n"
                f"Aspect Ratio: <i>{ratio}</i>\n"
                f"Duration: <i>{duration}s</i>"
            )
            # Delete the job directory on successful upload to save disk space
            try:
                await asyncio.sleep(1)
                shutil.rmtree(job_dir)
                log.info(f"Deleted job directory: {job_dir}")
            except Exception as e:
                log.error(f"Failed to delete job directory {job_dir}: {e}")
        else:
            await edit_message(
                chat_id,
                message_id,
                f"⚠️ Video ready locally at:\n<code>{final_video}</code>\n"
                f"Telegram upload failed: {result.get('description')}"
            )
            
    except Exception as e:
        log.exception(f"Error handling topic '{topic}': {e}")
        await edit_message(
            chat_id,
            message_id,
            f"❌ <b>Error:</b> {str(e)}"
        )

# ─── BOT LOOP ───────────────────────────────────────────────────────────────────
async def run_bot():
    log.info("=" * 50)
    log.info("  INTERACTIVE VIDEO BOT STARTED — waiting for Telegram messages")
    log.info("=" * 50)
    offset = None

    while True:
        updates = await get_updates(offset)
        if not updates.get("ok"):
            await asyncio.sleep(5)
            continue

        for update in updates.get("result", []):
            offset = update["update_id"] + 1

            if "callback_query" in update:
                cb = update["callback_query"]
                query_id = cb["id"]
                chat_id = cb["message"]["chat"]["id"]
                data = cb["data"]
                
                await handle_callback_query(chat_id, query_id, data)
                continue

            msg = update.get("message") or update.get("edited_message")
            if not msg:
                continue

            chat_id = msg["chat"]["id"]
            text    = msg.get("text", "").strip()

            if not text:
                continue

            if text.lower() in ("/start", "/help"):
                USER_STATES.pop(chat_id, None)
                await start_interactive_flow(chat_id)
                continue

            await handle_user_message(chat_id, text, msg["message_id"])

        await asyncio.sleep(1)

# ─── ENTRY POINT ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    check_dependencies()

    # Verify FFmpeg
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        log.info("FFmpeg: OK")
    except (subprocess.CalledProcessError, FileNotFoundError):
        log.error("FFmpeg not found! Please install FFmpeg and ensure it is in the system PATH.")
        sys.exit(1)

    if len(sys.argv) > 1:
        if sys.argv[1] == "--login-whatsapp":
            asyncio.run(login_whatsapp())
        elif sys.argv[1] == "--test-pipeline" and len(sys.argv) > 2:
            test_topic = sys.argv[2]
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            test_dir = OUTPUT_DIR / f"test_{ts}"
            test_dir.mkdir(exist_ok=True)
            log.info(f"Running pipeline test for topic: '{test_topic}'...")
            try:
                final_path = asyncio.run(run_pipeline(test_topic, 30.0, "english", "dramatic", "female", "9:16", test_dir))
                log.info(f"SUCCESS! Test video created at: {final_path}")
            except Exception as e:
                log.exception(f"Pipeline test failed: {e}")
        else:
            print("Usage:")
            print("  python bot.py                    - Run Telegram bot")
            print("  python bot.py --login-whatsapp   - Log in to WhatsApp Web")
            print("  python bot.py --test-pipeline \"Topic\" - Test pipeline locally")
    else:
        asyncio.run(run_bot())
