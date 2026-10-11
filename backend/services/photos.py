"""Photo evidence for leak reports: browser -> S3 (presigned POST) -> Amazon Rekognition check.

The photo goes straight from the browser to a private S3 bucket (size-capped by the presigned POST), so it never
passes through Lambda. When the report is saved, Rekognition looks for water AND a pipe/tap/hose, and for
inappropriate content (rejected and deleted). The result is a HELPER for reviewers, not proof of a leak.
Without PHOTO_BUCKET (local dev) uploads are switched off and reports work as before.
"""
import os
import re
import uuid

REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
BUCKET = os.getenv("PHOTO_BUCKET", "")
MAX_BYTES = 4_000_000
KEY_RE = re.compile(r"^leaks/[0-9a-f]{32}\.jpg$")
MIN_CONF = 70.0
WATER = {"water", "droplet", "puddle", "flood", "leak", "splash", "spray", "fountain", "wet", "stream"}
PIPE = {"pipe", "plumbing", "faucet", "tap", "hose", "pipeline", "valve", "hydrant", "fire hydrant", "drain", "sink faucet"}


class Rejected(ValueError):
    """Photo missing, invalid or blocked by content moderation (maps to HTTP 422)."""


def enabled() -> bool:
    return bool(BUCKET)


def _s3():
    import boto3
    from botocore.config import Config
    # regional endpoint avoids the 307 redirects new buckets give on the global endpoint
    return boto3.client("s3", region_name=REGION, endpoint_url=f"https://s3.{REGION}.amazonaws.com",
                        config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}))


def upload_form() -> dict:
    """Presigned POST the browser uses to upload ONE jpeg (max 4 MB, valid 5 minutes)."""
    if not enabled():
        raise Rejected("Photo upload needs the AWS deployment (PHOTO_BUCKET is not set).")
    key = f"leaks/{uuid.uuid4().hex}.jpg"
    post = _s3().generate_presigned_post(
        BUCKET, key, Fields={"Content-Type": "image/jpeg"},
        Conditions=[["content-length-range", 1, MAX_BYTES], {"Content-Type": "image/jpeg"}], ExpiresIn=300)
    return {"key": key, "url": post["url"], "fields": post["fields"], "max_bytes": MAX_BYTES}


def _names(label: dict) -> set:
    out = {label["Name"].lower()}
    out |= {p["Name"].lower() for p in label.get("Parents", [])}
    out |= {a["Name"].lower() for a in label.get("Aliases", [])}
    return out


def check(key: str) -> dict:
    """Amazon Rekognition: is there water and a pipe/tap/hose? Rejects and deletes blocked content."""
    if not KEY_RE.match(key or "") or not enabled():
        raise Rejected("Invalid photo reference.")
    import boto3
    from botocore.exceptions import ClientError
    rek = boto3.client("rekognition", region_name=REGION)
    img = {"S3Object": {"Bucket": BUCKET, "Name": key}}
    try:
        mod = rek.detect_moderation_labels(Image=img, MinConfidence=60)["ModerationLabels"]
        if mod:
            _s3().delete_object(Bucket=BUCKET, Key=key)
            raise Rejected("This photo was rejected by content moderation. Please upload a photo of the leak only.")
        labels = rek.detect_labels(Image=img, MaxLabels=40, MinConfidence=MIN_CONF)["Labels"]
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("InvalidS3ObjectException", "NoSuchKey", "ImageTooLargeException", "InvalidImageFormatException"):
            raise Rejected("Photo not found or not a valid image. Please try uploading again.")
        return {"status": "unchecked", "water": False, "pipe": False, "labels": []}  # AWS problem: keep the report
    water = any(_names(l) & WATER for l in labels)
    pipe = any(_names(l) & PIPE for l in labels)
    status = "verified" if water and pipe else "partial" if water or pipe else "unclear"
    top = [{"name": l["Name"], "confidence": round(l["Confidence"])} for l in labels[:6]]
    return {"status": status, "water": water, "pipe": pipe, "labels": top}


def attach_urls(items: list) -> list:
    """Short-lived (10 min) private view links for reports that have a photo. Local computation, no network call."""
    if not enabled():
        return items
    s3 = None
    for i in items:
        if i.get("photo_key"):
            s3 = s3 or _s3()
            i["photo_url"] = s3.generate_presigned_url("get_object", Params={"Bucket": BUCKET, "Key": i["photo_key"]},
                                                       ExpiresIn=600)
    return items
