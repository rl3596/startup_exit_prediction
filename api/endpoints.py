"""
Typed wrappers for every Crunchbase API v4 endpoint used in the pipeline.

Each method raises AccessTierError on 403 — callers catch and handle gracefully.
"""

from api.client import CrunchbaseClient, AccessTierError  # noqa: F401 (re-exported)


class CrunchbaseEndpoints:

    def __init__(self, client: CrunchbaseClient):
        self.client = client

    # ------------------------------------------------------------------ #
    #  Autocomplete                                                        #
    # ------------------------------------------------------------------ #

    def autocomplete(self, query: str, collection_ids: str = "categories",
                     limit: int = 25) -> dict:
        """
        GET /autocompletes?query=...&collection_ids=categories&limit=N
        Available on Basic tier. Used to resolve category slug -> UUID.
        """
        return self.client._get("autocompletes", params={
            "query": query,
            "collection_ids": collection_ids,
            "limit": limit,
        })

    # ------------------------------------------------------------------ #
    #  Organization Search                                                 #
    # ------------------------------------------------------------------ #

    def search_organizations(self, query_predicates: list, field_ids: list,
                              limit: int = 1000, after_id: str = None) -> dict:
        """
        POST /searches/organizations
        Basic tier. Keyset-paginated via after_id.
        """
        body = {
            "field_ids": field_ids,
            "limit": limit,
            "query": query_predicates,
            "order": [{"field_id": "created_at", "sort": "asc"}],
        }
        if after_id:
            body["after_id"] = after_id
        return self.client._post("searches/organizations", body)

    # ------------------------------------------------------------------ #
    #  Organization Entity Lookup                                          #
    # ------------------------------------------------------------------ #

    def get_organization(self, permalink: str, field_ids: list,
                          card_ids: list = None) -> dict:
        """
        GET /entities/organizations/{permalink}
        Basic tier for org fields; card availability varies by tier.
        """
        params = {"field_ids": ",".join(field_ids)}
        if card_ids:
            params["card_ids"] = ",".join(card_ids)
        return self.client._get(f"entities/organizations/{permalink}", params=params)

    def get_org_card_page(self, permalink: str, card_id: str,
                           card_field_ids: list = None, after_id: str = None) -> dict:
        """
        GET /entities/organizations/{permalink}/cards/{card_id}
        Paginate a single card beyond the 100-item default.

        Some cards (e.g. participated_investments) must be called WITHOUT
        card_field_ids — pass an empty list or None to omit the param.
        The response is always a dict: {"cards": {card_id: [...]}}
        """
        params = {}
        if card_field_ids:
            params["card_field_ids"] = ",".join(card_field_ids)
        if after_id:
            params["after_id"] = after_id
        return self.client._get(
            f"entities/organizations/{permalink}/cards/{card_id}", params=params
        )

    # ------------------------------------------------------------------ #
    #  Funding Rounds Search (Enterprise only)                             #
    # ------------------------------------------------------------------ #

    def search_funding_rounds(self, predicates: list, field_ids: list,
                               limit: int = 1000, after_id: str = None) -> dict:
        """
        POST /searches/funding_rounds
        Enterprise only — raises AccessTierError on Basic tier.
        """
        body = {"field_ids": field_ids, "limit": limit, "query": predicates}
        if after_id:
            body["after_id"] = after_id
        return self.client._post("searches/funding_rounds", body)

    # ------------------------------------------------------------------ #
    #  People Search (Enterprise only)                                     #
    # ------------------------------------------------------------------ #

    def search_people(self, predicates: list, field_ids: list,
                       limit: int = 1000, after_id: str = None) -> dict:
        """
        POST /searches/people
        Enterprise only — raises AccessTierError on Basic tier.
        """
        body = {"field_ids": field_ids, "limit": limit, "query": predicates}
        if after_id:
            body["after_id"] = after_id
        return self.client._post("searches/people", body)

    # ------------------------------------------------------------------ #
    #  Person Entity Lookup                                                #
    # ------------------------------------------------------------------ #

    def get_person(self, permalink: str, field_ids: list,
                    card_ids: list = None) -> dict:
        """
        GET /entities/people/{permalink}
        May be restricted on Basic tier depending on the card.
        """
        params = {"field_ids": ",".join(field_ids)}
        if card_ids:
            params["card_ids"] = ",".join(card_ids)
        return self.client._get(f"entities/people/{permalink}", params=params)

    def get_person_card_page(self, permalink: str, card_id: str,
                              card_field_ids: list, after_id: str = None) -> dict:
        """
        GET /entities/people/{permalink}/cards/{card_id}
        Paginate a single person card (e.g. degrees, jobs).
        """
        params = {"card_field_ids": ",".join(card_field_ids)}
        if after_id:
            params["after_id"] = after_id
        return self.client._get(
            f"entities/people/{permalink}/cards/{card_id}", params=params
        )
