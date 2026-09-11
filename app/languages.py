"""
Language configurations for Indian Languages and Professional English.
Provides mappings for Google Translate codes and Edge Neural TTS voices.
"""

from typing import Dict, List, Any

LANGUAGES: Dict[str, Dict[str, Any]] = {
    # Professional English variants
    "en-IN": {
        "name": "Professional English (Indian Accent)",
        "native_name": "Indian English",
        "category": "English",
        "trans_code": "en",
        "default_voice": "en-IN-NeerjaExpressiveNeural",
        "voices": [
            {"id": "en-IN-NeerjaExpressiveNeural", "name": "Neerja (Expressive / Corporate)", "gender": "Female"},
            {"id": "en-IN-NeerjaNeural", "name": "Neerja (Professional)", "gender": "Female"},
            {"id": "en-IN-PrabhatNeural", "name": "Prabhat (Professional)", "gender": "Male"}
        ]
    },
    "en-US": {
        "name": "Professional English (US Accent)",
        "native_name": "American English",
        "category": "English",
        "trans_code": "en",
        "default_voice": "en-US-JennyNeural",
        "voices": [
            {"id": "en-US-JennyNeural", "name": "Jenny (Natural / Professional)", "gender": "Female"},
            {"id": "en-US-AriaNeural", "name": "Aria (News / Confident)", "gender": "Female"},
            {"id": "en-US-GuyNeural", "name": "Guy (Corporate / Clear)", "gender": "Male"},
            {"id": "en-US-ChristopherNeural", "name": "Christopher (Authoritative)", "gender": "Male"}
        ]
    },
    "en-GB": {
        "name": "Professional English (UK / British)",
        "native_name": "British English",
        "category": "English",
        "trans_code": "en",
        "default_voice": "en-GB-SoniaNeural",
        "voices": [
            {"id": "en-GB-SoniaNeural", "name": "Sonia (Professional British)", "gender": "Female"},
            {"id": "en-GB-RyanNeural", "name": "Ryan (Corporate British)", "gender": "Male"}
        ]
    },

    # Indian Languages
    "hi": {
        "name": "Hindi",
        "native_name": "हिन्दी",
        "category": "Indian",
        "trans_code": "hi",
        "default_voice": "hi-IN-SwaraNeural",
        "voices": [
            {"id": "hi-IN-SwaraNeural", "name": "Swara (Natural)", "gender": "Female"},
            {"id": "hi-IN-MadhurNeural", "name": "Madhur (Natural)", "gender": "Male"}
        ]
    },
    "te": {
        "name": "Telugu",
        "native_name": "తెలుగు",
        "category": "Indian",
        "trans_code": "te",
        "default_voice": "te-IN-ShrutiNeural",
        "voices": [
            {"id": "te-IN-ShrutiNeural", "name": "Shruti (Natural)", "gender": "Female"},
            {"id": "te-IN-MohanNeural", "name": "Mohan (Natural)", "gender": "Male"}
        ]
    },
    "ta": {
        "name": "Tamil",
        "native_name": "தமிழ்",
        "category": "Indian",
        "trans_code": "ta",
        "default_voice": "ta-IN-PallaviNeural",
        "voices": [
            {"id": "ta-IN-PallaviNeural", "name": "Pallavi (Natural)", "gender": "Female"},
            {"id": "ta-IN-ValluvarNeural", "name": "Valluvar (Natural)", "gender": "Male"}
        ]
    },
    "kn": {
        "name": "Kannada",
        "native_name": "ಕನ್ನಡ",
        "category": "Indian",
        "trans_code": "kn",
        "default_voice": "kn-IN-SapnaNeural",
        "voices": [
            {"id": "kn-IN-SapnaNeural", "name": "Sapna (Natural)", "gender": "Female"},
            {"id": "kn-IN-GaganNeural", "name": "Gagan (Natural)", "gender": "Male"}
        ]
    },
    "ml": {
        "name": "Malayalam",
        "native_name": "മലയാളം",
        "category": "Indian",
        "trans_code": "ml",
        "default_voice": "ml-IN-SobhanaNeural",
        "voices": [
            {"id": "ml-IN-SobhanaNeural", "name": "Sobhana (Natural)", "gender": "Female"},
            {"id": "ml-IN-MidhunNeural", "name": "Midhun (Natural)", "gender": "Male"}
        ]
    },
    "bn": {
        "name": "Bengali",
        "native_name": "বাংলা",
        "category": "Indian",
        "trans_code": "bn",
        "default_voice": "bn-IN-TanishaaNeural",
        "voices": [
            {"id": "bn-IN-TanishaaNeural", "name": "Tanishaa (Natural)", "gender": "Female"},
            {"id": "bn-IN-BashkarNeural", "name": "Bashkar (Natural)", "gender": "Male"}
        ]
    },
    "mr": {
        "name": "Marathi",
        "native_name": "मराठी",
        "category": "Indian",
        "trans_code": "mr",
        "default_voice": "mr-IN-AarohiNeural",
        "voices": [
            {"id": "mr-IN-AarohiNeural", "name": "Aarohi (Natural)", "gender": "Female"},
            {"id": "mr-IN-ManoharNeural", "name": "Manohar (Natural)", "gender": "Male"}
        ]
    },
    "gu": {
        "name": "Gujarati",
        "native_name": "ગુજરાતી",
        "category": "Indian",
        "trans_code": "gu",
        "default_voice": "gu-IN-DhwaniNeural",
        "voices": [
            {"id": "gu-IN-DhwaniNeural", "name": "Dhwani (Natural)", "gender": "Female"},
            {"id": "gu-IN-NiranjanNeural", "name": "Niranjan (Natural)", "gender": "Male"}
        ]
    },
    "pa": {
        "name": "Punjabi",
        "native_name": "ਪੰਜਾਬੀ",
        "category": "Indian",
        "trans_code": "pa",
        "default_voice": "pa-IN-OjasNeural",
        "voices": [
            {"id": "pa-IN-OjasNeural", "name": "Ojas (Natural)", "gender": "Female"},
            {"id": "pa-IN-GurpreetNeural", "name": "Gurpreet (Natural)", "gender": "Male"}
        ]
    },
    "ur": {
        "name": "Urdu",
        "native_name": "اردو",
        "category": "Indian",
        "trans_code": "ur",
        "default_voice": "ur-IN-GulNeural",
        "voices": [
            {"id": "ur-IN-GulNeural", "name": "Gul (Natural)", "gender": "Female"},
            {"id": "ur-IN-SalmanNeural", "name": "Salman (Natural)", "gender": "Male"}
        ]
    }
}

def get_languages_list() -> List[Dict[str, Any]]:
    result = []
    for code, info in LANGUAGES.items():
        result.append({
            "code": code,
            "name": info["name"],
            "native_name": info["native_name"],
            "category": info["category"],
            "default_voice": info["default_voice"],
            "voices": info["voices"]
        })
    return result

def get_language_folder_name(lang_code: str) -> str:
    """Returns clean folder name for Google Drive, e.g. 'Hindi', 'Telugu', 'Professional_English_Indian'"""
    if lang_code in LANGUAGES:
        name = LANGUAGES[lang_code]["name"]
        # Clean special chars for folder name
        name = name.replace("(", "").replace(")", "").replace("/", "_").strip()
        parts = [p.strip() for p in name.split() if p.strip()]
        return "_".join(parts)
    return lang_code.upper()
