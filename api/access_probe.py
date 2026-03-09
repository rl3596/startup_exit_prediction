"""
Phase 0: API access level probe.

Calls a sequence of endpoints from least-restricted to most-restricted,
records what succeeds or fails with 403, infers the tier, and sets the
client rate limit accordingly.
"""

import logging
from api.client import CrunchbaseClient, AccessTierError
import config

logger = logging.getLogger(__name__)

# Each probe entry: (name, tier_required, method, path, body)
PROBES = [
    {
        "name":   "org_search",
        "tier":   "basic",
        "method": "POST",
        "path":   "searches/organizations",
        "body": {
            "field_ids": ["identifier", "short_description"],
            "limit": 1,
            "query": [{"type": "predicate", "field_id": "facet_ids",
                        "operator_id": "includes", "values": ["company"]}],
        },
    },
    {
        "name":   "org_entity_lookup",
        "tier":   "basic",
        "method": "GET",
        "path":   "entities/organizations/openai",
        "body":   None,
        "params": {"field_ids": "identifier,short_description,founded_on"},
    },
    {
        "name":   "org_founders_card",
        "tier":   "basic",
        "method": "GET",
        "path":   "entities/organizations/openai/cards/founders",
        "body":   None,
        "params": {"card_field_ids": "identifier"},
    },
    {
        "name":   "funding_rounds_search",
        "tier":   "enterprise",
        "method": "POST",
        "path":   "searches/funding_rounds",
        "body": {
            "field_ids": ["identifier", "announced_on", "money_raised"],
            "limit": 1,
            "query": [],
        },
    },
    {
        "name":   "people_search",
        "tier":   "enterprise",
        "method": "POST",
        "path":   "searches/people",
        "body": {
            "field_ids": ["identifier", "first_name", "last_name"],
            "limit": 1,
            "query": [],
        },
    },
    {
        "name":   "person_entity_lookup",
        "tier":   "enterprise",
        "method": "GET",
        "path":   "entities/people/sam-altman",
        "body":   None,
        "params": {"field_ids": "identifier,first_name,last_name"},
    },
    {
        "name":   "person_degrees_card",
        "tier":   "enterprise",
        "method": "GET",
        "path":   "entities/people/mark-zuckerberg",
        "body":   None,
        # degrees card is fetched via card_ids on entity lookup, not via card page endpoint
        "params": {"field_ids": "identifier", "card_ids": "degrees"},
    },
]


def run_access_probe(client: CrunchbaseClient) -> dict:
    """
    Run all probes and return an access report.

    Returns:
        {
          "inferred_tier": "basic" | "enterprise" | "no_access",
          "rpm": int,
          "endpoints": {name: {"status": "OK"|"403"|"ERROR", ...}}
        }
    """
    report: dict = {"endpoints": {}, "inferred_tier": "unknown",
                    "rpm": config.RATE_LIMIT_RPM_BASIC}

    for probe in PROBES:
        name   = probe["name"]
        method = probe["method"]
        path   = probe["path"]
        params = probe.get("params")

        try:
            if method == "POST":
                client._post(path, probe["body"])
            else:
                client._get(path, params=params)

            report["endpoints"][name] = {"status": "OK", "tier": probe["tier"]}
            logger.info("[PROBE] %-35s -> OK", name)

        except AccessTierError:
            report["endpoints"][name] = {"status": "403_FORBIDDEN",
                                          "tier": probe["tier"]}
            logger.warning("[PROBE] %-35s -> 403 (insufficient tier)", name)

        except PermissionError as exc:
            report["endpoints"][name] = {"status": "401_UNAUTHORIZED"}
            logger.error("[PROBE] %-35s -> 401 (bad API key): %s", name, exc)
            # Stop probing — key is invalid
            report["inferred_tier"] = "no_access"
            return report

        except Exception as exc:
            report["endpoints"][name] = {"status": f"ERROR: {exc}"}
            logger.error("[PROBE] %-35s -> ERROR: %s", name, exc)

    # Infer tier
    def ok(name):
        return report["endpoints"].get(name, {}).get("status") == "OK"

    if ok("people_search") or ok("person_degrees_card"):
        report["inferred_tier"] = "enterprise"
        report["rpm"]           = config.RATE_LIMIT_RPM_ENTERPRISE
    elif ok("org_search"):
        report["inferred_tier"] = "basic"
        report["rpm"]           = config.RATE_LIMIT_RPM_BASIC
    else:
        report["inferred_tier"] = "no_access"

    client.set_rate_limit(report["rpm"])

    logger.info(
        "=== Access probe complete: tier=%s, rpm=%d ===",
        report["inferred_tier"], report["rpm"]
    )
    _print_report(report)
    return report


def _print_report(report: dict):
    print("\n--- API Access Probe Results ---")
    print(f"Inferred tier : {report['inferred_tier']}")
    print(f"Rate limit    : {report['rpm']} RPM")
    print("")
    for name, info in report["endpoints"].items():
        status = info.get("status", "?")
        tier   = info.get("tier", "")
        mark   = "OK" if status == "OK" else "NO"
        print(f"  [{mark}] {name:<35} (requires {tier})")
    print("--------------------------------\n")
