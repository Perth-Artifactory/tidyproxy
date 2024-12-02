import datetime
import json
import logging
import sys
import time
from copy import deepcopy as copy
from pprint import pprint
from typing import Any, Literal

import requests

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def query(
    cat: str | int,
    config: dict,
    term: str | None = None,
    cache: dict | None = None,
) -> dict | list:
    """Send a query to the TidyHQ API"""

    if type(term) == int:
        term = str(term)

    # If we have a cache, try using that first before querying TidyHQ
    if cache:
        if cat in cache:
            # Groups are indexed by ID before being cached
            if cat == "groups":
                if term:
                    if term in cache["groups"]:
                        return cache["groups"][term]
                    else:
                        try:
                            if int(term) in cache["groups"]:
                                return cache["groups"][int(term)]
                        except:
                            pass
                    # If we can't find the group, handle via query instead
                    logger.debug(f"Could not find group with ID {term} in cache")
                else:
                    return cache["groups"]
            elif cat == "contacts":
                if term:
                    for contact in cache["contacts"]:
                        if int(contact["id"]) == int(term):
                            return contact
                    # If we can't find the contact, handle via query
                    logger.debug(f"Could not find contact with ID {term} in cache")
                else:
                    return cache["contacts"]
        else:
            logger.debug(f"Could not find category {cat} in cache")

    append = ""
    if term:
        append = f"/{term}"

    logger.debug(f"Querying TidyHQ for {cat}{append}")
    try:
        r = requests.get(
            f"https://api.tidyhq.com/v1/{cat}{append}",
            params={"access_token": config["tidyhq"]["token"]},
        )
        data = r.json()
    except requests.exceptions.RequestException as e:
        logger.error("Could not reach TidyHQ")
        sys.exit(1)

    if cat == "groups" and not term:
        # Index groups by ID
        groups_indexed = {}
        for group in data:
            groups_indexed[group["id"]] = group
        return groups_indexed

    return data


def setup_cache(config: dict) -> dict[str, Any]:
    """Retrieve preset data from TidyHQ and store it in a cache file"""
    logger.info("Cache is being retrieved from TidyHQ")
    cache = {}
    logger.debug("Getting contacts from TidyHQ")
    cache["contacts"] = query(cat="contacts", config=config)
    logger.debug(f"Got {len(cache['contacts'])} contacts from TidyHQ")

    logger.debug("Getting groups from TidyHQ")
    cache["groups"] = query(cat="groups", config=config)

    logger.debug(f'Got {len(cache["groups"])} groups from TidyHQ')

    logger.debug("Getting memberships from TidyHQ")
    cache["memberships"] = query(cat="memberships", config=config)
    logger.debug(f'Got {len(cache["memberships"])} memberships from TidyHQ')

    logger.debug("Getting invoices from TidyHQ")
    raw_invoices = query(cat="invoices", config=config)
    logger.debug(f"Got {len(raw_invoices)} invoices from TidyHQ")

    logger.debug("Getting org details from TidyHQ")
    cache["org"] = query(cat="organization", config=config)
    logger.debug(f"Org domain is set to {cache['org']['domain_prefix']}")  # type: ignore

    # Sort invoices by contact ID
    cache["invoices"] = {}
    newest = {}
    for invoice in raw_invoices:
        if invoice["contact_id"] not in cache["invoices"]:
            cache["invoices"][invoice["contact_id"]] = []
            # Convert created_at to unix timestamp
            # Starts in format 2022-12-30T16:36:35+0000
            created_at = datetime.datetime.strptime(
                invoice["created_at"], "%Y-%m-%dT%H:%M:%S%z"
            ).timestamp()

            newest[invoice["contact_id"]] = created_at
        cache["invoices"][invoice["contact_id"]].append(invoice)
        if created_at > newest[invoice["contact_id"]]:
            newest[invoice["contact_id"]] = created_at

    # Remove contacts from the invoice cache if they have no invoices in 18 months
    removed = 0
    cleaned_invoices = {}
    for contact_id in cache["invoices"]:
        if newest[contact_id] > datetime.datetime.now().timestamp() - 86400 * 30 * 18:
            cleaned_invoices[contact_id] = cache["invoices"][contact_id]
        else:
            removed += 1
    logger.debug(
        f"Removed {removed} invoice lists where contact hasn't had an invoice in 18 months"
    )
    logger.debug(f"Left with {len(cleaned_invoices)} contacts with invoices")
    cache["invoices"] = cleaned_invoices

    # Sort invoices in each contact by date
    for contact_id in cache["invoices"]:
        cache["invoices"][contact_id].sort(key=lambda x: x["created_at"], reverse=True)

    logger.debug("Writing cache to file")
    cache["time"] = datetime.datetime.now().timestamp()
    with open("cache.json", "w") as f:
        json.dump(cache, f)

    return cache


def fresh_cache(cache=None, config=None, force=False) -> dict[str, Any]:
    """Return a fresh TidyHQ cache.

    Freshness is determined by the cache_expiry value in the config file.
    Cache source is (in order of priority):
    - Provided cache
    - Cache file
    - TidyHQ API
    """
    if not config:
        with open("config.json") as f:
            logger.debug("Loading config from file")
            config = json.load(f)

    if cache:
        # Check if the cache we've been provided with is fresh
        if (
            cache["time"] < datetime.datetime.now().timestamp() - config["cache_expiry"]
            or force
        ):
            logger.debug("Provided cache is stale")
        else:
            # If the provided cache is fresh, just return it
            return cache

    # If we haven't been provided with a cache, or the provided cache is stale, try loading from file
    try:
        with open("cache.json") as f:
            cache = json.load(f)
    except FileNotFoundError:
        logger.debug("No cache file found")
        cache = setup_cache(config=config)
        return cache
    except json.decoder.JSONDecodeError:
        logger.error("Cache file is invalid")
        cache = setup_cache(config=config)
        return cache

    # If the cache file is also stale, refresh it
    if (
        cache["time"] < datetime.datetime.now().timestamp() - config["cache_expiry"]
        or force
    ):
        logger.debug("Cache file is stale")
        cache = setup_cache(config=config)
        return cache
    else:
        logger.debug("Cache file is fresh")
        return cache


def push_to_files(
    tidyhq_cache: dict, config: dict, logger: logging.Logger, directory: str = "serve"
) -> None:
    """Process the cache and write to the appropriate files"""

    # Contacts
    # Contacts are provided in three formats:
    # * A list of all contacts - part of cache.json (generated elsewhere)
    # * A dictionary of contacts indexed by ID - contacts/sorted.json
    # * A directory of contacts indexed by ID - contacts/{ID}.json

    contacts = tidyhq_cache["contacts"]

    logger.info(f"Sorting contacts")

    # Index contacts by ID
    sorted_contacts = {}
    for contact in contacts:
        sorted_contacts[contact["id"]] = contact

    # Write sorted contacts to file
    logger.info("Writing contacts to contacts/sorted.json")
    with open(f"{directory}/contacts/sorted.json", "w") as f:
        json.dump(sorted_contacts, f)

    # Write contacts to individual files
    logger.info("Writing contacts to individual files")
    for contact in contacts:
        with open(f"{directory}/contacts/{contact['id']}.json", "w") as f:
            json.dump(contact, f)

    # Groups
    # Groups are provided in two formats:
    # * A dictionary of groups indexed by ID - groups/sorted.json
    # * A directory of groups indexed by ID - groups/{ID}.json
    # We also add a "membership" key to each group that lists the IDs of contacts that are members

    groups = tidyhq_cache["groups"]

    # Groups are pre-indexed by ID during the initial cache setup

    # Groups don't include their members but should
    for contact in contacts:
        for group in contact["groups"]:
            # Easier to change to string here than in the following lines
            group["id"] = str(group["id"])
            if "membership" not in groups[group["id"]]:
                groups[group["id"]]["membership"] = []
            groups[group["id"]]["membership"].append(contact["id"])

    # Write sorted groups to file
    logger.info("Writing groups to groups/sorted.json")
    with open(f"{directory}/groups/sorted.json", "w") as f:
        json.dump(groups, f)

    # Write groups to individual files
    logger.info("Writing groups to individual files")
    for group in groups:
        with open(f"{directory}/groups/{group}.json", "w") as f:
            json.dump(groups[group], f)

    # Invoices
    # Invoices are provided in three formats:
    # * A dictionary of invoices indexed by contact ID - invoices/sorted.json
    # * A directory of invoices indexed by contact ID - invoices/{ID}.json
    # * A sorted dictionary of all invoices indexed by invoice ID - invoices/all_sorted.json
    # * A list of all invoices sorted by date - invoices/all.json
    # Both formats are pre-trimmed to contacts with invoices in the last 18 months

    invoices = tidyhq_cache["invoices"]

    # Write sorted invoices to file
    logger.info("Writing invoices to invoices/sorted.json")
    with open(f"{directory}/invoices/sorted.json", "w") as f:
        json.dump(invoices, f)

    # Write invoices to individual files
    logger.info("Writing invoices to individual files")
    for contact in invoices:
        with open(f"{directory}/invoices/{contact}.json", "w") as f:
            json.dump(invoices[contact], f)

    # Write all invoices to file
    logger.info("Writing all invoices to invoices/all.json")
    all_invoices = []
    for contact in invoices:
        all_invoices += invoices[contact]
    all_invoices.sort(key=lambda x: x["created_at"])
    with open(f"{directory}/invoices/all.json", "w") as f:
        json.dump(all_invoices, f)

    # Write sorted all invoices to file
    logger.info("Writing all invoices to invoices/all_sorted.json")
    all_invoices_sorted = {}
    for invoice in all_invoices:
        all_invoices_sorted[invoice["id"]] = invoice
    with open(f"{directory}/invoices/all_sorted.json", "w") as f:
        json.dump(all_invoices_sorted, f)

    # Memberships
    # Memberships are provided in two formats:
    # * A dictionary of memberships indexed by contact ID - memberships/sorted_by_contact.json
    # * A dictionary of memberships indexed by membership type ID - memberships/sorted_by_type.json
    # * A directory of memberships indexed by contact ID - memberships/{ID}.json

    memberships = tidyhq_cache["memberships"]

    memberships_by_contact = {}
    memberships_by_type = {}

    for membership in memberships:
        contact_id = membership["contact_id"]
        type_id = membership["membership_level_id"]

        if contact_id not in memberships_by_contact:
            memberships_by_contact[contact_id] = []
        memberships_by_contact[contact_id].append(membership)

        if type_id not in memberships_by_type:
            memberships_by_type[type_id] = []
        memberships_by_type[type_id].append(membership)

    # Write sorted memberships to file
    logger.info("Writing memberships to memberships/sorted_by_contact.json")
    with open(f"{directory}/memberships/sorted_by_contact.json", "w") as f:
        json.dump(memberships_by_contact, f)
    logger.info("Writing memberships to memberships/sorted_by_type.json")
    with open(f"{directory}/memberships/sorted_by_type.json", "w") as f:
        json.dump(memberships_by_type, f)

    # Write memberships to individual files
    logger.info("Writing memberships to individual files")
    for contact in memberships_by_contact:
        with open(f"{directory}/memberships/{contact}.json", "w") as f:
            json.dump(memberships_by_contact[contact], f)

    # Org
    # The organization details are provided in one format:
    # * A dictionary of organization details - org.json

    org = tidyhq_cache["org"]

    # Write org to file
    logger.info("Writing org to org.json")
    with open(f"{directory}/org.json", "w") as f:
        json.dump(org, f)

    # Contact mapping
    # Contact maps are provided in multiple formats indexed by the user ID of each service
    # Both a dictionary and directory is provided for each service
    # Slack - map/slack.json, map/slack/{SLACK_ID}.json
    # Taiga - map/taiga.json, map/taiga/{TAIGA_ID}.json
    # TidyHQ - map/tidyhq.json, map/tidyhq/{TIDYHQ_ID}.json
    # Each map includes the IDs of the accounts on every other linked service

    map_by_slack = {}
    map_by_taiga = {}
    map_by_tidyhq = {}

    for contact in contacts:
        tidyhq = str(contact["id"])
        slack = get_custom_field(
            config=config, cache={}, contact=contact, field_map_name="slack"
        )
        taiga = get_custom_field(
            config=config, cache={}, contact=contact, field_map_name="taiga"
        )

        # The custom field function returns more than just the value field we need
        if slack:
            slack = slack["value"]
        if taiga:
            taiga = taiga["value"]

        map_by_tidyhq[tidyhq] = {"slack": slack, "taiga": taiga}
        if slack:
            map_by_slack[slack] = {"tidyhq": tidyhq, "taiga": taiga}
        if taiga:
            map_by_taiga[taiga] = {"tidyhq": tidyhq, "slack": slack}

    # Write maps to file
    logger.info("Writing maps to map/slack.json")
    with open(f"{directory}/maps/slack/all.json", "w") as f:
        json.dump(map_by_slack, f)
    logger.info("Writing maps to map/taiga.json")
    with open(f"{directory}/maps/taiga/all.json", "w") as f:
        json.dump(map_by_taiga, f)
    logger.info("Writing maps to map/tidyhq.json")
    with open(f"{directory}/maps/tidyhq/all.json", "w") as f:
        json.dump(map_by_tidyhq, f)

    # Write maps to individual files
    logger.info("Writing maps to individual files")
    for contact in map_by_tidyhq:
        with open(f"{directory}/maps/tidyhq/{contact}.json", "w") as f:
            json.dump(map_by_tidyhq[contact], f)
    for slack in map_by_slack:
        with open(f"{directory}/maps/slack/{slack}.json", "w") as f:
            json.dump(map_by_slack[slack], f)
    for taiga in map_by_taiga:
        with open(f"{directory}/maps/taiga/{taiga}.json", "w") as f:
            json.dump(map_by_taiga[taiga], f)


def get_custom_field(
    config: dict,
    cache: dict | None = None,
    contact_id: str | None = None,
    contact: dict | None = None,
    field_id: str | None = None,
    field_map_name: str | None = None,
) -> dict | None:
    """Get the value of a custom field for a contact within TidyHQ.

    The field can be specified by either its ID or its name in the config file.
    """
    if field_map_name:
        logger.debug(f"Looking for field {field_map_name} for contact {contact_id}")
        field_id = config["tidyhq"]["ids"].get(field_map_name, None)
        logger.debug(f"Field ID for {field_map_name} is {field_id}")

    if not field_id:
        logger.error("No field ID provided or found in config")
        return None

    if not contact and contact_id:
        if not cache:
            logger.error("Contact ID provided but no cache")
            return None
        for c in cache["contacts"]:
            if str(c["id"]) == str(contact_id):
                contact = c
                break
    elif not contact and not contact_id:
        logger.error("No contact ID or contact provided")
        return None

    if not contact:
        logger.error(f"Contact {contact_id} not found in cache or we failed to find it")
        return None

    for field in contact["custom_fields"]:
        if field["id"] == field_id:
            logger.debug(f"Found field {field_id} with value {field['value']}")
            return field
        else:
            logger.debug(f"Field {field_id} does not match {field['id']}")
    logger.debug(f"Could not find field {field_id} for contact {contact_id}")
    return None
