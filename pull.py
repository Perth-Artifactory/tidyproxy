import json
import logging
import os
import sys
from pprint import pprint

import requests

from util import tidyhq

# Set up logging
logging.basicConfig(level=logging.INFO)
# Set urllib3 logging level to INFO to reduce noise when individual modules are set to debug
urllib3_logger = logging.getLogger("urllib3")
urllib3_logger.setLevel(logging.INFO)
setup_logger = logging.getLogger("setup")
proc_logger = logging.getLogger("processing")
post_logger = logging.getLogger("post")


# Look for --force flag
force = False
if "--force" in sys.argv:
    force = True

# Look for a pull.lock file
if not force:
    try:
        with open("pull.lock") as f:
            setup_logger.error("pull.lock found. Exiting to prevent concurrent runs")
            sys.exit(1)
    except FileNotFoundError:
        pass

# Create main.lock file
with open("pull.lock", "w") as f:
    f.write("")
    setup_logger.info("pull.lock created")


# Load config
try:
    with open("config.json") as f:
        config = json.load(f)
except FileNotFoundError:
    setup_logger.error(
        "config.json not found. Create it using example.config.json as a template"
    )
    sys.exit(1)

# Check for required TidyHQ config values
if not all(key in config["tidyhq"] for key in ["token", "ids"]):
    setup_logger.error(
        "Missing required config values in tidyhq section. Check config.json"
    )
    sys.exit(1)

# Check for cache expiry and set if not present
if "cache_expiry" not in config:
    config["cache_expiry"] = 86400
    setup_logger.error("Cache expiry not set in config. Defaulting to 24 hours")


# Set up TidyHQ cache
tidyhq_cache = tidyhq.fresh_cache(config=config)
setup_logger.info(
    f"TidyHQ cache set up: {len(tidyhq_cache['contacts'])} contacts, {len(tidyhq_cache['groups'])} groups"
)
# The cache pulled direct from TidyHQ is a touch different to the cache stored in teh file since JSON can't use ints as keys.
# This is a bit of a hack to make sure the cache is always the same format
tidyhq_cache = tidyhq.fresh_cache(config=config)

# Set up folder structure if it doesn't exist yet
if not os.path.exists("serve"):
    setup_logger.info("Creating serve directory")
    os.makedirs("serve")

for folder in [
    "contacts",
    "groups",
    "invoices",
    "memberships",
    "maps",
    "maps/slack",
    "maps/taiga",
    "maps/tidyhq",
]:
    if not os.path.exists(f"serve/{folder}"):
        setup_logger.info(f"Creating {folder} directory")
        os.makedirs(f"serve/{folder}")


# Process the cache and write it to /serve
tidyhq.push_to_files(
    tidyhq_cache=tidyhq_cache, config=config, directory="serve", logger=proc_logger
)

# Write the raw cache to /serve/cache.json
with open("serve/cache.json", "w") as f:
    json.dump(tidyhq_cache, f, indent=2)
    proc_logger.info("Cache written to serve/cache.json")

# Remove pull.lock file
post_logger.info("Removing pull.lock")
os.remove("pull.lock")
post_logger.info("Pull complete")
