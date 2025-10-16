import json
import gzip
import os
import re
from urllib.parse import unquote_plus

import boto3

s3 = boto3.client("s3")
translate = boto3.client("translate")
bedrock = boto3.client("bedrock-runtime")

OUTPUT_BUCKET = os.environ["OUTPUT_BUCKET"]
SUMMARY_PREFIX = os.environ.get("SUMMARY_PREFIX", "summaries/")
TRANSLATION_PREFIX = os.environ.get("TRANSLATION_PREFIX", "translations/")
TARGET_LANG = os.environ.get("TARGET_LANG", "fr")
MODEL_ID = os.environ.get("MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0")
MAX_BYTES = int(os.environ.get("MAX_BYTES", "500000"))


def _read_s3_text(bucket, key, max_bytes=MAX_BYTES) -> str:
    obj = s3.get_object(Bucket=bucket, Key=key)
    body = obj["Body"].read(max_bytes + 1)
    if len(body) > max_bytes:
        raise ValueError(f"Object too large (> {max_bytes} bytes).")
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return gzip.decompress(body).decode("utf-8")
        except Exception:
            return body.decode("latin-1", errors="ignore")


def _invoke_bedrock(body_dict: dict) -> dict:
    response = bedrock.invoke_model(
        modelId=MODEL_ID,
        body=json.dumps(body_dict),
        accept="application/json",
        contentType="application/json",
    )
    return json.loads(response["body"].read())


def _summarize_with_bedrock(text: str) -> str:
    # Previous prompt variant (bullet-point style) kept for reference.
    # prompt = (
    #     "You are a concise technical summarizer.\n"
    #     "Summarize the following text in 5-8 bullet points, preserving key facts:\n\n"
    #     f"{text[:20000]}"
    # )
    # prompt = (
    #     "You are an expert technical writer. Craft one cohesive paragraph that captures the key insights without repeating the same brand name unless it adds new information.\n"
    #     "Write 4-6 complete sentences that flow naturally and stay focused on the source material.\n\n"
    #     f"{text[:20000]}"
    # )
    truncated = text[:20000]
    word_count = len(truncated.split())
    if word_count >= 120:
        # prompt = (
        #     "You are a concise technical summarizer. Return 5-7 bullet points that cover distinct ideas without repeating the same phrases or brand names unless new information is added.\n"
        #     "If the source text repeats sentences, collapse them into a single bullet that captures the key idea.\n"
        #     "Each bullet should be a complete sentence summarizing a unique aspect of the source.\n\n"
        #     f'{truncated}'
        # )
        prompt = (
            "You are a precise technical summarizer. Produce exactly 5 bullet points, each beginning with '- ' and written as a polished sentence.\n"
            "Ensure every bullet covers a distinct idea; when the source repeats itself, merge those sentences into a single point that preserves the detail.\n"
            "Mention each product or service name at most once unless you are adding a new fact, and keep the tone neutral.\n\n"
            f"{truncated}"
        )
    else:
        # prompt = (
        #     "You are an expert technical writer. Craft one cohesive paragraph (4-6 sentences) that captures the key insights without repeating phrasing unless it conveys a new detail.\n"
        #     "Maintain a neutral tone and avoid marketing language.\n\n"
        #     f"{truncated}"
        # )
        prompt = (
            "You are an expert technical writer. Produce a single paragraph of 3-4 sentences that captures all key facts while sounding natural and concise.\n"
            "Do not repeat phrasing or product names unless adding a new detail, and keep the tone factual rather than promotional.\n\n"
            f"{truncated}"
        )

    if MODEL_ID.startswith("amazon.titan-text"):
        request_body = {
            "inputText": prompt,
            "textGenerationConfig": {
                "maxTokenCount": 800,
                "temperature": 0.2,
                "topP": 0.9,
                "stopSequences": [],
            },
        }
        payload = _invoke_bedrock(request_body)
        results = payload.get("results", [])
        return "".join(item.get("outputText", "") for item in results).strip()

    if MODEL_ID.startswith("anthropic."):
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 800,
            "temperature": 0.2,
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": prompt}]}
            ],
        }
        payload = _invoke_bedrock(request_body)
        parts = [
            block.get("text", "")
            for block in payload.get("output", {}).get("content", [])
            if block.get("type") == "text"
        ]
        return "".join(parts).strip()

    raise ValueError(f"Unsupported model ID for summarization: {MODEL_ID}")


def _translate(text: str, target_lang: str) -> str:
    out = translate.translate_text(
        Text=text, SourceLanguageCode="auto", TargetLanguageCode=target_lang
    )
    return out["TranslatedText"]

# Previous `_dedupe_lines` version:
# def _dedupe_lines(text: str) -> str:
#     seen = set()
#     output_lines = []
#     prev_blank = False
#     for raw_line in text.splitlines():
#         line = raw_line.strip()
#         if not line:
#             if not prev_blank and output_lines:
#                 output_lines.append("")
#             prev_blank = True
#             continue
#         prev_blank = False
#         normalized = line.lstrip("•*-").strip().lower()
#         if normalized in seen:
#             continue
#         seen.add(normalized)
#         output_lines.append(line if raw_line.startswith((" ", "\t")) else raw_line.strip())
#     return "\n".join(output_lines)

_norm_re = re.compile(r"[^a-z0-9]+")


def _normalize_sentence(text: str) -> str:
    cleaned = _norm_re.sub(" ", text.lower())
    return " ".join(cleaned.split())


def _dedupe_lines(text: str) -> str:
    lines = text.splitlines()
    has_bullet = any(line.lstrip().startswith(("-", "*", "•")) for line in lines)

    if has_bullet:
        seen = set()
        bullets = []
        for raw_line in lines:
            stripped = raw_line.strip()
            if not stripped:
                continue
            content = stripped.lstrip("-*• ").strip()
            if not content:
                continue
            normalized = _normalize_sentence(content)
            if normalized in seen:
                continue
            seen.add(normalized)
            bullets.append(f"- {content}")
        return "\n".join(bullets)

    sentences = []
    seen_sentences = set()
    for segment in re.split(r"(?<=[.!?])\s+", text.strip()):
        sentence = segment.strip()
        if not sentence:
            continue
        normalized = _normalize_sentence(sentence)
        if normalized in seen_sentences:
            continue
        seen_sentences.add(normalized)
        sentences.append(sentence)
    return " ".join(sentences)

def _dedupe_lines(text: str) -> str:
    seen = set()
    output_lines = []
    prev_blank = False

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if not prev_blank and output_lines:
                output_lines.append("")
            prev_blank = True
            continue

        prev_blank = False
        normalized = line.lstrip("•*-").strip().lower()
        if normalized in seen:
            continue

        seen.add(normalized)
        output_lines.append(line if raw_line.startswith((" ", "\t")) else raw_line.strip())

    return "\n".join(output_lines)


def _put_text(bucket: str, key: str, text: str):
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=text.encode("utf-8"),
        ContentType="text/plain; charset=utf-8",
    )


def lambda_handler(event, context):
    rec = event["Records"][0]
    in_bucket = rec["s3"]["bucket"]["name"]
    in_key = unquote_plus(rec["s3"]["object"]["key"])

    base_name = in_key.split("/")[-1].rsplit(".", 1)[0]
    summary_key = f"{SUMMARY_PREFIX}{base_name}.summary.txt"
    translation_key = f"{TRANSLATION_PREFIX}{base_name}.summary.{TARGET_LANG}.txt"

    try:
        text = _read_s3_text(in_bucket, in_key)
        summary = _summarize_with_bedrock(text)
        summary = _dedupe_lines(summary)
        _put_text(OUTPUT_BUCKET, summary_key, summary)

        translated = _translate(summary, TARGET_LANG)
        translated = _dedupe_lines(translated)
        _put_text(OUTPUT_BUCKET, translation_key, translated)

        return {
            "status": "ok",
            "summary_key": summary_key,
            "translation_key": translation_key,
        }
    except Exception as e:
        err_key = f"errors/{base_name}.error.json"
        _put_text(
            OUTPUT_BUCKET,
            err_key,
            json.dumps({"input_key": in_key, "error": str(e)}, indent=2),
        )
        raise

