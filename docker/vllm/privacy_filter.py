import logging
import re
import traceback


class PrivacyLogFilter(logging.Filter):
    """Log filter for redacting prompts, tokens, and secrets."""

    QUOTED_PROMPT_PATTERN = re.compile(
        r"((?:prompt|user_prompt|instruction|instructions|input|generated_text)\s*[:=]\s*|[\"'](?:prompt|user_prompt|instruction|instructions|input|generated_text)[\"']\s*:\s*)(?:'''[\s\S]*?(?:'''|$)|(?:\"{3})[\s\S]*?(?:(?:\"{3})|$)|'(?:\\.|[^'\\])*(?:'|$)|(?:\"(?:\\.|[^\"\\])*(?:\"|$))|`(?:\\.|[^`\\])*(?:`|$))",
        re.IGNORECASE,
    )
    UNQUOTED_PROMPT_PATTERN = re.compile(
        r"(?<![?&])\b((?:prompt|user_prompt|instruction|instructions|input|generated_text)\s*[:=]\s*)(?!['\"`]|\[REDACTED\])(.*?)(?=(?:,\s*(?:params|sampling_params|prompt_token_ids|lora_request|request_id)\s*[:=]|\s+HTTP/\d|\r?\n|$))",
        re.IGNORECASE,
    )
    TOKEN_IDS_PATTERN = re.compile(
        r"((?:prompt_token_ids|token_ids)\s*[:=]\s*|[\"'](?:prompt_token_ids|token_ids)[\"']\s*:\s*)(?:\[[\d\s,\[\]]*\]|tensor\(\[[\d\s,]*\]\)|\([\d\s,]*\))",
        re.IGNORECASE,
    )
    OUTPUT_PATTERN = re.compile(
        r"((?:output|generated_text|text|content|stop|bad_words)\s*[:=]\s*|[\"'](?:output|generated_text|text|content|stop|bad_words)[\"']\s*:\s*)(?:'''[\s\S]*?(?:'''|$)|(?:\"{3})[\s\S]*?(?:(?:\"{3})|$)|'(?:\\.|[^'\\])*(?:'|$)|(?:\"(?:\\.|[^\"\\])*(?:\"|$))|`(?:\\.|[^`\\])*(?:`|$))",
        re.IGNORECASE,
    )
    TOKEN_PATTERN = re.compile(
        r"(?:Bearer\s+|(?:api[_-]?key|token|access_token|auth_token)\s*[:=]\s*['\"]?|[\"'](?:api[_-]?key|token|access_token|auth_token)[\"']\s*:\s*['\"]?|[\?&](?:api[_-]?key|token|access_token|prompt|content|generated_text)=)[^\s,;&\r\n\"']+['\"]?|hf_[a-zA-Z0-9]{20,}|sk-[a-zA-Z0-9_\-]{20,}",
        re.IGNORECASE,
    )

    @staticmethod
    def _redact_token_ids(match: re.Match) -> str:
        prefix = match.group(1)
        if '"' in prefix or "'" in prefix:
            return f'{prefix}"[REDACTED]"'
        return f"{prefix}[REDACTED]"

    @staticmethod
    def _redact_token(match: re.Match) -> str:
        text = match.group(0)
        if text.lower().startswith("bearer "):
            return f"{text[:7]}[REDACTED]"
        if text.lower().startswith("hf_") or text.lower().startswith("sk-"):
            return "[REDACTED]"
        if "=" in text:
            prefix, _ = text.split("=", 1)
            return f"{prefix}=[REDACTED]"
        if ":" in text:
            prefix, _ = text.split(":", 1)
            return f'{prefix}: "[REDACTED]"' if '"' in prefix else f"{prefix}: [REDACTED]"
        return "[REDACTED]"

    def redact_sensitive_fields(self, raw_message: str) -> str:
        if not raw_message:
            return raw_message
        msg = self.QUOTED_PROMPT_PATTERN.sub(r'\g<1>"[REDACTED]"', raw_message)
        msg = self.UNQUOTED_PROMPT_PATTERN.sub(r'\g<1>"[REDACTED]"', msg)
        msg = self.TOKEN_IDS_PATTERN.sub(self._redact_token_ids, msg)
        msg = self.OUTPUT_PATTERN.sub(r'\g<1>"[REDACTED]"', msg)
        msg = self.TOKEN_PATTERN.sub(self._redact_token, msg)
        return msg

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            original_message = record.getMessage()

            sanitized_message = self.redact_sensitive_fields(original_message)

            if sanitized_message != original_message:
                record.msg = sanitized_message
                record.args = ()
                if hasattr(record, "message"):
                    record.message = sanitized_message

            if record.exc_info:
                formatted_exc = traceback.format_exception(*record.exc_info)
                sanitized_exc = [self.redact_sensitive_fields(line) for line in formatted_exc]
                record.exc_text = "".join(sanitized_exc)
                record.exc_info = None
            elif getattr(record, "exc_text", None):
                record.exc_text = self.redact_sensitive_fields(record.exc_text)

            if getattr(record, "stack_info", None):
                record.stack_info = self.redact_sensitive_fields(record.stack_info)

        except Exception:
            record.msg = "[LOG_SANITIZATION_FAILED]"
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None

        return True


logging.captureWarnings(True)
