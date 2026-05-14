import argparse
import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def parse_line(line: str) -> tuple[str, str] | None:
    cleaned = line.strip().rstrip(",")
    if not cleaned:
        return None

    if cleaned.startswith('"') and cleaned.endswith('"'):
        cleaned = cleaned[1:-1]

    if ":" not in cleaned:
        raise ValueError(f"Invalid line format: {line!r}")

    chat_id, text = cleaned.split(":", 1)
    return chat_id.strip().strip('"'), text.strip().strip('"')


def http_json(method: str, url: str, token: str, payload: dict | None = None, ssl_context: ssl.SSLContext | None = None):
    data = None
    headers = {"Authorization": f"Bearer {token}"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, context=ssl_context) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Test SMS store API using a local file")
    parser.add_argument("source", nargs="?", default="data_for_test.txt")
    parser.add_argument("--base-url", default=os.getenv("SMS_STORE_URL", "https://127.0.0.1:8000"))
    parser.add_argument("--token", default=os.getenv("SMS_STORE_TOKEN", ""))
    parser.add_argument("--delete", action="store_true", help="Delete imported messages after verification")
    args = parser.parse_args()

    if not args.token:
        raise SystemExit("Token is required: set SMS_STORE_TOKEN or pass --token")

    ca_certfile = os.getenv("SMS_STORE_CA_CERTFILE") or os.getenv("SSL_CA_CERTFILE") or os.getenv("CA_CERT_FILE")
    ssl_context = ssl.create_default_context(cafile=ca_certfile) if ca_certfile else None

    source_path = Path(args.source)
    if not source_path.exists():
        raise SystemExit(f"File not found: {source_path}")

    lines = source_path.read_text(encoding="utf-8").splitlines()
    parsed_messages = [item for item in (parse_line(line) for line in lines) if item is not None]
    if not parsed_messages:
        raise SystemExit("No messages found in source file")

    base_url = args.base_url.rstrip("/")
    imported = []

    print(f"Importing {len(parsed_messages)} message(s) from {source_path}...")
    for chat_id, text in parsed_messages:
        status, payload = http_json(
            "POST",
            f"{base_url}/messages",
            args.token,
            {"chat_id": chat_id, "text": text},
            ssl_context=ssl_context,
        )
        imported.append(payload)
        print(f"POST /messages -> {status} message_id={payload['message_id']}")

    first_chat_id = imported[0]["chat_id"]
    query = urllib.parse.urlencode({"chat_id": first_chat_id})
    status, items = http_json("GET", f"{base_url}/messages?{query}", args.token, ssl_context=ssl_context)
    print(f"GET /messages -> {status} returned {len(items)} message(s)")

    if args.delete:
        deleted_total = 0
        for item in imported:
            delete_query = urllib.parse.urlencode({"message_id": item["message_id"]})
            status, payload = http_json(
                "DELETE",
                f"{base_url}/messages?{delete_query}",
                args.token,
                ssl_context=ssl_context,
            )
            deleted_total += payload["deleted"]
            print(f"DELETE /messages -> {status} deleted={payload['deleted']}")
        print(f"Deleted total: {deleted_total}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP error {exc.code}: {body}") from exc
