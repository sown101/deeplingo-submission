import re
import logging
import time
from urllib.parse import parse_qs, urlparse
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound, VideoUnavailable
import requests

from app.modules.content.application.ports import SourceProviderError

logger = logging.getLogger(__name__)

_YOUTUBE_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be",
                            "www.youtu.be"})
_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")


class YouTubeService:
    """
    Simplified YouTube service for iframe-based video playback
    No video/audio download needed - just metadata and transcripts
    
    Features:
    - Extract video metadata (oEmbed API)
    - Get transcripts with auto-merging into sentences
    - Multi-language transcript support
    - Language detection
    """
    
    def extract_video_id(self, url: str) -> str:
        """The 11-character video id of a YouTube watch, short, embed or youtu.be URL; ValueError for anything else
        (another host, or an id that is not a YouTube id)."""
        text = (url or "").strip()
        parsed = urlparse(text if "://" in text else f"https://{text}")
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in ("http", "https") or host not in _YOUTUBE_HOSTS:
            raise ValueError("Invalid YouTube URL")
        parts = [part for part in parsed.path.split("/") if part]
        if host.endswith("youtu.be"):
            candidate = parts[0] if len(parts) == 1 else ""
        elif parts == ["watch"]:
            candidate = parse_qs(parsed.query).get("v", [""])[0]
        elif len(parts) == 2 and parts[0] in ("embed", "v", "shorts", "live"):
            candidate = parts[1]
        else:
            candidate = ""
        if not _VIDEO_ID.fullmatch(candidate):
            raise ValueError("Invalid YouTube URL")
        return candidate
    
    def get_video_metadata(self, url: str) -> dict:
        """
        Get video metadata using YouTube oEmbed API
        This is fast, reliable, and never gets blocked
        """
        try:
            video_id = self.extract_video_id(url)
            
            # Use oEmbed API - public, reliable, never blocked
            oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
            
            logger.info(f"🔵 Fetching metadata for video: {video_id}")
            
            response = requests.get(oembed_url, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            # Get additional info from thumbnail URL
            thumbnail_url = data.get('thumbnail_url', '')
            
            logger.info(f"✅ Got metadata: {data.get('title', 'Unknown')}")
            
            return {
                'id': video_id,
                'title': data.get('title', 'Unknown Title'),
                'thumbnail': thumbnail_url,
                'uploader': data.get('author_name', 'Unknown'),
                'uploader_url': data.get('author_url', ''),
                'duration': None,  # oEmbed doesn't provide duration
                'view_count': None,  # oEmbed doesn't provide view count
                'description': '',
                'iframe_url': f"https://www.youtube.com/embed/{video_id}",
                'watch_url': f"https://www.youtube.com/watch?v={video_id}",
            }
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                raise SourceProviderError("Video không tồn tại hoặc đã bị xóa.")
            elif e.response.status_code == 401:
                raise SourceProviderError("Video này ở chế độ riêng tư.")
            else:
                raise SourceProviderError(f"Không thể tải thông tin video: {str(e)}")
        except Exception as e:
            logger.error(f"❌ Error getting metadata: {e}")
            raise SourceProviderError("Link YouTube không hợp lệ hoặc video không khả dụng.")
    
    def _merge_transcript_segments(self, raw_segments: list, max_duration: float = 15.0) -> list:
        """
        Merge small segments into complete sentences
        
        YouTube auto-captions split text into tiny chunks (2-3 words each).
        This merges them into proper sentences for better AI analysis.
        
        Args:
            raw_segments: List of raw transcript segments
            max_duration: Max duration per merged sentence (seconds)
        
        Rules:
        1. Merge until we hit sentence-ending punctuation (. ! ?)
        2. Or until we reach ~15-20 words (reasonable sentence length)
        3. Or until duration exceeds max_duration
        4. Keep timing info (start from first segment, end from last)
        """
        if not raw_segments:
            return []
        
        merged = []
        current_sentence = {
            'texts': [],
            'start': None,
            'end': None,
            'sequence_start': None
        }
        
        sentence_enders = {'.', '!', '?', '...'}
        max_words_per_sentence = 20
        
        for i, segment in enumerate(raw_segments, start=1):
            text = segment.text.strip() if hasattr(segment, 'text') else segment.get('text', '').strip()
            
            if not text:
                continue
            
            # Initialize if first segment
            if current_sentence['start'] is None:
                current_sentence['start'] = segment.start if hasattr(segment, 'start') else segment.get('start', 0)
                current_sentence['sequence_start'] = i
            
            # Add text to current sentence
            current_sentence['texts'].append(text)
            current_sentence['end'] = (segment.start if hasattr(segment, 'start') else segment.get('start', 0)) + \
                                      (segment.duration if hasattr(segment, 'duration') else segment.get('duration', 0))
            
            # Check if we should end this sentence
            ends_with_punctuation = any(text.endswith(p) for p in sentence_enders)
            word_count = sum(len(t.split()) for t in current_sentence['texts'])
            duration = current_sentence['end'] - current_sentence['start']
            is_last_segment = (i == len(raw_segments))
            
            should_end = (
                ends_with_punctuation or 
                word_count >= max_words_per_sentence or
                duration >= max_duration or
                is_last_segment
            )
            
            if should_end:
                # Create merged segment
                merged_text = ' '.join(current_sentence['texts'])
                
                # Clean up text
                merged_text = re.sub(r'\s+', ' ', merged_text)  # Remove extra spaces
                merged_text = merged_text.strip()
                
                if merged_text:
                    merged.append({
                        'sequence_number': len(merged) + 1,
                        'start': current_sentence['start'],
                        'duration': current_sentence['end'] - current_sentence['start'],
                        'text': merged_text,
                        'original_segment_count': len(current_sentence['texts'])
                    })
                
                # Reset for next sentence
                current_sentence = {
                    'texts': [],
                    'start': None,
                    'end': None,
                    'sequence_start': None
                }
        
        logger.info(f"📝 Merged {len(raw_segments)} segments → {len(merged)} sentences")
        return merged
    
    
    def get_transcript_detailed(
        self, 
        video_id: str, 
        languages: list = None,
        max_duration: float = 15.0
    ) -> list:
        """
        Get detailed transcript with merged sentences
        
        Returns complete sentences instead of tiny word fragments
        
        Args:
            video_id: YouTube video ID
            languages: Preferred languages (default: ["en", "en-US", "en-GB"])
            max_duration: Max duration per sentence in seconds
        
        Returns:
            List of merged sentence objects with timing info
        """
        if languages is None:
            languages = ["en", "en-US", "en-GB"]
        
        try:
            logger.info(f"🔵 Fetching transcript for: {video_id}")
            logger.info(f"🌍 Preferred languages: {languages}")
            
            # Get raw transcript
            ytt_api = YouTubeTranscriptApi()
            fetched = ytt_api.fetch(video_id, languages=languages)
            raw_transcript = fetched.to_raw_data()   # list[dict]: {'text','start','duration'}
            
            # Convert to list if needed
            if not isinstance(raw_transcript, list):
                raw_transcript = list(raw_transcript)
            
            logger.info(f"📥 Got {len(raw_transcript)} raw segments")
            
            # Merge into complete sentences
            merged_segments = self._merge_transcript_segments(raw_transcript, max_duration)
            
            logger.info(f"✅ Created {len(merged_segments)} complete sentences")
            
            return merged_segments
            
        except TranscriptsDisabled:
            raise SourceProviderError("Video này không có phụ đề (transcripts bị tắt).")
        except NoTranscriptFound:
            raise SourceProviderError(f"Video này không có phụ đề cho ngôn ngữ: {', '.join(languages)}. Vui lòng chọn video khác.")
        except VideoUnavailable:
            raise SourceProviderError("Video không khả dụng hoặc đã bị xóa.")
        except Exception as e:
            logger.error("Transcript acquisition failed error_type=%s", type(e).__name__)
            raise SourceProviderError(f"Lỗi khi lấy transcript: {str(e)}")
    
    # ============================================
    # ⭐ NEW: Language Detection & Multi-language Support
    # ============================================
    
    def list_available_transcripts(self, video_id: str) -> list:
        """
        List all available transcript languages
        
        Returns:
            List of available transcripts with language info
        """
        try:
            ytt_api = YouTubeTranscriptApi()
            transcript_list = ytt_api.list(video_id)
            
            available = []
            for t in transcript_list:
                available.append({
                    "language": t.language,
                    "language_code": t.language_code,
                    "is_generated": t.is_generated,
                    "is_translatable": t.is_translatable,
                })
            return available
        except Exception as e:
            logger.error(f"Error listing transcripts: {e}")
            return []
    
    # Ngôn ngữ target của DeepLingo — ưu tiên theo thứ tự này
    _LANG_PRIORITY = ["zh", "ja", "ko", "en", "vi", "th", "hi", "fr", "de", "es", "pt", "ru", "ar"]

    def detect_video_language(self, video_id: str) -> str:
        """
        Detect ngôn ngữ gốc của video bằng 3 bước:

        Bước 1 — Auto-generated transcript:
            YouTube chỉ tự tạo caption cho ngôn ngữ THỰC SỰ được nói.
            Nếu có → đây là ngôn ngữ gốc, tin 100%.

        Bước 2 — Đọc nội dung transcript để detect qua charset:
            Thử từng transcript trong _LANG_PRIORITY theo thứ tự.
            Đọc 3 câu đầu → kiểm tra unicode ranges:
              - CJK (\u4e00-\u9fff) → zh
              - Hiragana/Katakana (\u3040-\u30ff) → ja
              - Hangul (\uac00-\ud7af) → ko
              - Arabic (\u0600-\u06ff) → ar
              - Latin chủ yếu → en

        Bước 3 — Fallback: chọn ngôn ngữ ưu tiên nhất trong list available.
        """
        try:
            transcripts = self.list_available_transcripts(video_id)
            if not transcripts:
                return "en"

            all_codes = [t["language_code"] for t in transcripts]

            def _normalize(code: str) -> str:
                code = (code or "").lower()
                if code.startswith("zh"): return "zh"
                if code.startswith("en"): return "en"
                if code.startswith("ja"): return "ja"
                if code.startswith("ko"): return "ko"
                if code.startswith("vi"): return "vi"
                if code.startswith("ar"): return "ar"
                if code.startswith("th"): return "th"
                return code[:2]

            # ── Bước 1: Auto-generated ────────────────────────────────────
            auto_transcripts = [t for t in transcripts if t["is_generated"]]
            if auto_transcripts:
                # Ưu tiên auto trong ngôn ngữ DeepLingo support trước
                for lang in self._LANG_PRIORITY:
                    for t in auto_transcripts:
                        if _normalize(t["language_code"]) == lang:
                            result = lang
                            logger.info(
                                f"[{video_id}] detect_video_language: {result} "
                                f"(auto-generated '{t['language_code']}') | all={all_codes}"
                            )
                            return result
                # Nếu không match _LANG_PRIORITY, lấy auto đầu tiên
                result = _normalize(auto_transcripts[0]["language_code"])
                logger.info(
                    f"[{video_id}] detect_video_language: {result} "
                    f"(auto-generated fallback) | all={all_codes}"
                )
                return result

            # ── Bước 2: Đọc nội dung transcript để detect charset ─────────

            def _detect_lang_from_text(text: str) -> str | None:
                """Detect ngôn ngữ từ unicode ranges trong text."""
                counts = {"zh": 0, "ja": 0, "ko": 0, "ar": 0, "latin": 0}
                for ch in text:
                    cp = ord(ch)
                    if 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF:
                        counts["zh"] += 1   # CJK Unified → Chinese hoặc Japanese Kanji
                    if 0x3040 <= cp <= 0x30FF:
                        counts["ja"] += 1   # Hiragana + Katakana
                    if 0xAC00 <= cp <= 0xD7AF:
                        counts["ko"] += 1
                    if 0x0600 <= cp <= 0x06FF:
                        counts["ar"] += 1
                    if 0x0041 <= cp <= 0x024F:
                        counts["latin"] += 1

                total = sum(counts.values())
                if total < 10:
                    return None  # Không đủ dữ liệu

                # Japanese: có Hiragana/Katakana
                if counts["ja"] / total > 0.05:
                    return "ja"
                # Korean: có Hangul
                if counts["ko"] / total > 0.1:
                    return "ko"
                # Arabic
                if counts["ar"] / total > 0.2:
                    return "ar"
                # Chinese: CJK nhưng không có Hiragana/Katakana
                if counts["zh"] / total > 0.2:
                    return "zh"
                # Latin-based
                if counts["latin"] / total > 0.3:
                    return "en"
                return None

            # Thử detect từng transcript — ưu tiên theo _LANG_PRIORITY
            sorted_transcripts = sorted(
                transcripts,
                key=lambda t: (
                    self._LANG_PRIORITY.index(_normalize(t["language_code"]))
                    if _normalize(t["language_code"]) in self._LANG_PRIORITY
                    else 99
                )
            )
            from youtube_transcript_api import YouTubeTranscriptApi
            ytt_api = YouTubeTranscriptApi()

            for t in sorted_transcripts:
                # Một track lỗi tạm thời (vd. YouTube 502) không được làm rơi
                # xuống track ưu tiên thấp hơn — track đó có thể là bản dịch.
                raw = self._fetch_detection_sample(ytt_api, video_id, t["language_code"])
                if raw is None:
                    continue
                sample = " ".join(s.get("text", "") for s in raw[:5])
                detected = _detect_lang_from_text(sample)
                if detected:
                    logger.info(
                        f"[{video_id}] detect_video_language: {detected} "
                        f"(charset detect from '{t['language_code']}') | all={all_codes}"
                    )
                    return detected

            # ── Bước 3: Fallback — ngôn ngữ ưu tiên nhất trong list ───────
            for lang in self._LANG_PRIORITY:
                for t in transcripts:
                    if _normalize(t["language_code"]) == lang:
                        logger.info(
                            f"[{video_id}] detect_video_language: {lang} "
                            f"(priority fallback from '{t['language_code']}') | all={all_codes}"
                        )
                        return lang

            result = _normalize(transcripts[0]["language_code"])
            logger.info(f"[{video_id}] detect_video_language: {result} (last resort) | all={all_codes}")
            return result

        except SourceProviderError:
            raise
        except Exception as e:
            logger.warning(f"Could not detect language: {e}")
            return "en"

    _DETECTION_FETCH_ATTEMPTS = 3

    def _fetch_detection_sample(self, ytt_api, video_id: str, language_code: str) -> list | None:
        """Fetch a caption track for language detection.

        Returns None only when the track genuinely has no transcript. A track that
        keeps failing after bounded retries fails closed instead of being skipped.
        """
        for attempt in range(1, self._DETECTION_FETCH_ATTEMPTS + 1):
            try:
                return ytt_api.fetch(video_id, languages=[language_code]).to_raw_data()
            except (NoTranscriptFound, TranscriptsDisabled):
                return None
            except Exception as e:
                logger.warning(
                    "[%s] caption fetch for language detection failed track=%s attempt=%s error_type=%s",
                    video_id, language_code, attempt, type(e).__name__,
                )
                if attempt < self._DETECTION_FETCH_ATTEMPTS:
                    time.sleep(attempt)
        raise SourceProviderError(
            f"Language detection failed: caption track '{language_code}' could not be fetched."
        )

    
    # ============================================
    # Channel Methods (Limited without API key)
    # ============================================
    


# ========== HELPER FUNCTIONS ==========
