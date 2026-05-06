import argparse
import logging
import os

from sms_client import SmsStoreClient


def build_logger() -> logging.Logger:
    logger = logging.getLogger("sms_client_runner")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
        )
        logger.addHandler(handler)
    return logger


def main() -> int:
    parser = argparse.ArgumentParser(description="Run SMS store client")
    parser.add_argument("--chat-id", required=True, help="Chat identifier to query")
    parser.add_argument("--delete", action="store_true", help="Delete the last message after fetching it")
    args = parser.parse_args()

    logger = build_logger()
    client = SmsStoreClient(
        base_url=os.getenv("BASE_URL"),
        token=os.getenv("TOKEN"),
        logger=logger,
    )

    message = client.get_last_message_by_chat_id(args.chat_id)
    if args.delete:
        result = client.delete_last_message_by_chat_id(args.chat_id)
        if result.message is None:
            logger.info("no messages found for chat_id=%s", args.chat_id)
        else:
            logger.info(
                "deleted=%s message_id=%s chat_id=%s created_at=%s text=%s",
                result.deleted,
                result.message.message_id,
                result.message.chat_id,
                result.message.created_at,
                result.message.text,
            )
        return 0

    if message is None:
        logger.info("no messages found for chat_id=%s", args.chat_id)
        return 0

    logger.info(
        "last message chat_id=%s message_id=%s created_at=%s text=%s",
        message.chat_id,
        message.message_id,
        message.created_at,
        message.text,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
