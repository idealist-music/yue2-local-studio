import argparse
from copy import deepcopy
import logging
from pathlib import Path

import uvicorn

from .app import create_app
from .config import ROOT, load_config


class SkipGetAccess(logging.Filter):
    """Keep mutation/error access records while suppressing polling noise."""

    def filter(self, record):
        args = record.args
        # Uvicorn's access args are (client, method, path, http_version, status).
        return not (isinstance(args, tuple) and len(args) >= 2 and args[1] == "GET")


def main():
    parser = argparse.ArgumentParser(description="YuE2 Local Studio")
    parser.add_argument("--config", type=Path, default=ROOT / "config.local.json")
    parser.add_argument("--test-engine", action="store_true", help="GPUを使わないテスト音声専用モード")
    args = parser.parse_args()
    config = load_config(args.config, test_engine=args.test_engine)
    if args.test_engine and config.data_dir == load_config(args.config).data_dir:
        # Test data must never share the real music library.
        from dataclasses import replace
        config = replace(config, data_dir=config.data_dir.with_name(config.data_dir.name + "-test"))
    print(f"YuE2 Local Studio: http://{config.host}:{config.port}", flush=True)
    if args.test_engine:
        print("テストエンジン: YuE2で作曲せず、検証用の短い音を生成します", flush=True)
    log_dir = config.data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging_config = deepcopy(uvicorn.config.LOGGING_CONFIG)
    logging_config["formatters"]["file"] = {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}
    logging_config["handlers"]["file"] = {
        "class": "logging.handlers.RotatingFileHandler", "formatter": "file",
        "filename": str(log_dir / "server.log"), "maxBytes": 5 * 1024 * 1024,
        "backupCount": 3, "encoding": "utf-8"}
    logging_config.setdefault("filters", {})["skip_get"] = {"()": SkipGetAccess}
    access_handlers = logging_config["loggers"]["uvicorn.access"]["handlers"] + ["file"]
    for handler_name in set(access_handlers):
        logging_config["handlers"].setdefault(handler_name, {}).setdefault("filters", []).append("skip_get")
    logging_config["loggers"]["uvicorn"]["handlers"].append("file")
    logging_config["loggers"]["uvicorn.access"]["handlers"].append("file")
    uvicorn.run(create_app(config), host=config.host, port=config.port, workers=1, reload=False,
                proxy_headers=False, timeout_graceful_shutdown=15, log_config=logging_config)


if __name__ == "__main__":
    main()
