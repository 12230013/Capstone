from typing import Any
import os

import httpx
from fastapi import APIRouter, HTTPException, Path

from urllib.parse import quote

RELATIONSHIP_API = os.getenv(
    "RELATIONSHIP_API",
    "http://172.21.48.162:3000",
)

router = APIRouter(
    prefix="/api/relationship",
    tags=["Relationship Mapping"],
)


# ============================================================
# Configuration
# ============================================================

RELATIONSHIP_API = os.getenv(
    "RELATIONSHIP_API",
    "http://172.21.48.162:3000",
)


# ============================================================
# Utility Helpers
# ============================================================

def normalize_id(value: Any) -> str:
    """
    Convert an ID/CID value to a cleaned string.
    """
    if value is None:
        return ""

    return str(value).strip()


def get_father_id(person: dict) -> str:
    """
    Get father's CID from different possible field names.
    """

    return normalize_id(
        person.get("fatherCID")
        or person.get("fatherCIDNo")
        or person.get("fatherCidNo")
        or person.get("fatherCid")
    )


def get_mother_id(person: dict) -> str:
    """
    Get mother's CID from different possible field names.
    """

    return normalize_id(
        person.get("motherCID")
        or person.get("motherCIDNo")
        or person.get("motherCidNo")
        or person.get("motherCid")
    )


def get_person_id(person: dict) -> str:
    """
    Get a person's CID from different possible field names.
    """

    return normalize_id(
        person.get("cid")
        or person.get("CID")
        or person.get("cidNo")
    )


def format_person(person: dict) -> dict:
    """
    Return only the information required by the
    relationship mapping frontend.
    """

    return {
        "cid": get_person_id(person),
        "fullName": person.get("fullName"),
        "gender": person.get("gender"),
        "dob": person.get("dob"),
    }


# ============================================================
# External Relationship API Helpers
# ============================================================

async def fetch_citizen(cid: str) -> dict | None:
    """
    Retrieve citizen information from the external
    relationship/family-tree API.
    """

    url = (
        f"{RELATIONSHIP_API}/api/familytree/citizen/"
        f"{quote(cid, safe='')}"
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url)

        response.raise_for_status()

        data = response.json()

        return data.get("citizen")


async def fetch_household(household_no: str) -> list:
    """
    Retrieve all members of a household.
    """

    url = (
        f"{RELATIONSHIP_API}/api/familytree/household/"
        f"{quote(str(household_no), safe='')}"
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url)

        response.raise_for_status()

        data = response.json()

        household = data.get("household")

        return household if isinstance(household, list) else []


async def enrich_person(person: dict) -> dict:
    """
    Retrieve full citizen information for a person
    when a CID is available.
    """

    person_id = get_person_id(person)

    if not person_id:
        return person

    try:
        full_person = await fetch_citizen(person_id)

        if full_person:
            enriched = {
                **person,
                **full_person,
            }

            return enriched

    except Exception as error:
        print(
            f"Unable to fetch full details for "
            f"{person_id}: {error}"
        )

    return person


# ============================================================
# Ping Endpoint
# GET /api/relationship/_ping
# ============================================================

@router.get("/_ping")
async def relationship_ping():
    """
    Check whether the Relationship Integration API
    is running.
    """

    return {
        "ok": True,
        "message": "Relationship Integration API is running",
    }


# ============================================================
# Relationship API
#
# GET /api/relationship/{cid}/{degree}
#
# Supported:
# Degree 1
# Degree 2
# Degree 3
# ============================================================

@router.get("/{cid}/{degree}")
async def get_relationships(
    cid: str = Path(
        ...,
        min_length=11,
        max_length=11,
        pattern=r"^\d{11}$",
    ),
    degree: str = Path(
        ...,
        pattern=r"^[123]$",
    ),
):
    """
    Retrieve family relationships for a citizen
    up to Degree 3.
    """

    # ========================================================
    # Validate Degree
    # ========================================================

    if degree not in {"1", "2", "3"}:
        raise HTTPException(
            status_code=400,
            detail=(
                "This endpoint currently supports "
                "Degree 1, Degree 2 and Degree 3."
            ),
        )

    # ========================================================
    # Normalize CID
    # ========================================================

    cid = normalize_id(cid)

    # ========================================================
    # Main Processing
    # ========================================================

    try:

        # ----------------------------------------------------
        # 1. FETCH TARGET
        # ----------------------------------------------------

        target = await fetch_citizen(cid)

        if not target:
            raise HTTPException(
                status_code=404,
                detail="Target citizen was not found.",
            )

        target_id = get_person_id(target) or cid

        # ----------------------------------------------------
        # 2. FIND TARGET'S CHILDREN
        # ----------------------------------------------------

        target_household = []

        household_no = target.get("householdNo")

        if household_no:
            target_household = await fetch_household(
                household_no
            )

        children = []

        for person in target_household:

            person_id = get_person_id(person)

            if not person_id:
                continue

            if person_id == target_id:
                continue

            is_child = (
                get_father_id(person) == target_id
                or get_mother_id(person) == target_id
            )

            if is_child:
                children.append(person)

        # Enrich children with complete details
        children_with_details = []

        for child in children:
            child_details = await enrich_person(child)
            children_with_details.append(child_details)

        # ----------------------------------------------------
        # 3. FIND TARGET'S SPOUSE(S)
        # ----------------------------------------------------

        spouse_ids = set()

        for child in children_with_details:

            father_id = get_father_id(child)
            mother_id = get_mother_id(child)

            if father_id == target_id:
                other_parent_id = mother_id

            elif mother_id == target_id:
                other_parent_id = father_id

            else:
                other_parent_id = ""

            if (
                other_parent_id
                and other_parent_id != target_id
            ):
                spouse_ids.add(other_parent_id)

        spouses = []

        for spouse_id in spouse_ids:

            spouse = None

            try:
                spouse = await fetch_citizen(spouse_id)

            except Exception as error:
                print(
                    f"Unable to fetch spouse "
                    f"{spouse_id}: {error}"
                )

            if spouse:

                spouses.append(spouse)

            else:

                spouses.append(
                    {
                        "cid": spouse_id,
                        "fullName": None,
                        "gender": None,
                        "dob": None,
                        "detailsAvailable": False,
                    }
                )

        # ====================================================
        # DEGREE 1
        #
        # Target
        # ├── Spouse(s)
        # └── Children
        # ====================================================

        if degree == "1":

            relationships = [
                {
                    "type": "TARGET",
                    "side": "TARGET",
                    "person": format_person(target),
                }
            ]

            for person in spouses:

                relationships.append(
                    {
                        "type": "SPOUSE",
                        "side": "TARGET",
                        "person": format_person(person),
                    }
                )

            for person in children_with_details:

                relationships.append(
                    {
                        "type": "CHILD",
                        "side": "TARGET",
                        "person": format_person(person),
                    }
                )

            return {
                "success": True,
                "degree": 1,
                "target": format_person(target),
                "spouses": [
                    format_person(person)
                    for person in spouses
                ],
                "children": [
                    format_person(person)
                    for person in children_with_details
                ],
                "relationships": relationships,
                "counts": {
                    "spouses": len(spouses),
                    "children": len(
                        children_with_details
                    ),
                },
            }

        # ====================================================
        # DEGREE 2
        #
        # Degree 1
        # +
        # Target's parents
        # Target's siblings
        # Spouse's parents
        # Spouse's siblings
        # ====================================================

        target_parents = {}
        spouse_parents = {}

        target_siblings = {}
        spouse_siblings = {}

        # ----------------------------------------------------
        # Process Parents and Siblings
        # ----------------------------------------------------

        async def process_parents_and_siblings(
            person: dict,
            side: str,
        ):

            person_id = get_person_id(person)

            if not person_id:
                return

            father_id = get_father_id(person)
            mother_id = get_mother_id(person)

            # ------------------------------------------------
            # Father
            # ------------------------------------------------

            if (
                father_id
                and father_id != person_id
            ):

                try:

                    father = await fetch_citizen(
                        father_id
                    )

                    if father:

                        if side == "TARGET":
                            target_parents[
                                father_id
                            ] = father
                        else:
                            spouse_parents[
                                father_id
                            ] = father

                except Exception as error:

                    print(
                        f"Unable to fetch father "
                        f"{father_id}: {error}"
                    )

            # ------------------------------------------------
            # Mother
            # ------------------------------------------------

            if (
                mother_id
                and mother_id != person_id
            ):

                try:

                    mother = await fetch_citizen(
                        mother_id
                    )

                    if mother:

                        if side == "TARGET":
                            target_parents[
                                mother_id
                            ] = mother
                        else:
                            spouse_parents[
                                mother_id
                            ] = mother

                except Exception as error:

                    print(
                        f"Unable to fetch mother "
                        f"{mother_id}: {error}"
                    )

            # ------------------------------------------------
            # Siblings
            # ------------------------------------------------

            person_household_no = person.get(
                "householdNo"
            )

            if person_household_no:

                try:

                    household = await fetch_household(
                        person_household_no
                    )

                    for household_person in household:

                        sibling_id = get_person_id(
                            household_person
                        )

                        if not sibling_id:
                            continue

                        if sibling_id == person_id:
                            continue

                        same_father = (
                            bool(father_id)
                            and get_father_id(
                                household_person
                            ) == father_id
                        )

                        same_mother = (
                            bool(mother_id)
                            and get_mother_id(
                                household_person
                            ) == mother_id
                        )

                        if (
                            same_father
                            and same_mother
                        ):

                            sibling = await enrich_person(
                                household_person
                            )

                            if side == "TARGET":

                                target_siblings[
                                    sibling_id
                                ] = sibling

                            else:

                                spouse_siblings[
                                    sibling_id
                                ] = sibling

                except Exception as error:

                    print(
                        f"Unable to process siblings "
                        f"for {person_id}: {error}"
                    )

        # ----------------------------------------------------
        # Process Target
        # ----------------------------------------------------

        await process_parents_and_siblings(
            target,
            "TARGET",
        )

        # ----------------------------------------------------
        # Process Spouse(s)
        # ----------------------------------------------------

        for spouse in spouses:

            await process_parents_and_siblings(
                spouse,
                "SPOUSE",
            )

        # ----------------------------------------------------
        # Remove Degree 1 people from Degree 2
        # ----------------------------------------------------

        degree1_ids = {
            target_id,
            *[
                get_person_id(person)
                for person in spouses
            ],
            *[
                get_person_id(person)
                for person in children_with_details
            ],
        }

        for person_id in degree1_ids:

            target_parents.pop(
                person_id,
                None,
            )

            spouse_parents.pop(
                person_id,
                None,
            )

            target_siblings.pop(
                person_id,
                None,
            )

            spouse_siblings.pop(
                person_id,
                None,
            )

        target_parent_list = list(
            target_parents.values()
        )

        spouse_parent_list = list(
            spouse_parents.values()
        )

        target_sibling_list = list(
            target_siblings.values()
        )

        spouse_sibling_list = list(
            spouse_siblings.values()
        )

        all_parents = [
            *target_parent_list,
            *spouse_parent_list,
        ]

        all_siblings = [
            *target_sibling_list,
            *spouse_sibling_list,
        ]

        # ====================================================
        # DEGREE 2 RESPONSE
        # ====================================================

        if degree == "2":

            relationships = [
                {
                    "type": "TARGET",
                    "side": "TARGET",
                    "person": format_person(target),
                }
            ]

            # Spouses
            for person in spouses:

                relationships.append(
                    {
                        "type": "SPOUSE",
                        "side": "TARGET",
                        "person": format_person(person),
                    }
                )

            # Children
            for person in children_with_details:

                relationships.append(
                    {
                        "type": "CHILD",
                        "side": "TARGET",
                        "person": format_person(person),
                    }
                )

            # Target parents
            for person in target_parent_list:

                relationships.append(
                    {
                        "type": "PARENT",
                        "side": "TARGET",
                        "person": format_person(person),
                    }
                )

            # Spouse parents
            for person in spouse_parent_list:

                relationships.append(
                    {
                        "type": "PARENT",
                        "side": "SPOUSE",
                        "person": format_person(person),
                    }
                )

            # Target siblings
            for person in target_sibling_list:

                relationships.append(
                    {
                        "type": "SIBLING",
                        "side": "TARGET",
                        "person": format_person(person),
                    }
                )

            # Spouse siblings
            for person in spouse_sibling_list:

                relationships.append(
                    {
                        "type": "SIBLING",
                        "side": "SPOUSE",
                        "person": format_person(person),
                    }
                )

            return {
                "success": True,
                "degree": 2,
                "target": format_person(target),

                "spouses": [
                    format_person(person)
                    for person in spouses
                ],

                "children": [
                    format_person(person)
                    for person in children_with_details
                ],

                "parents": [
                    {
                        "side": (
                            "TARGET"
                            if any(
                                get_person_id(parent)
                                == get_person_id(person)
                                for parent
                                in target_parent_list
                            )
                            else "SPOUSE"
                        ),
                        "person": format_person(person),
                    }
                    for person in all_parents
                ],

                "siblings": [
                    {
                        "side": (
                            "TARGET"
                            if any(
                                get_person_id(sibling)
                                == get_person_id(person)
                                for sibling
                                in target_sibling_list
                            )
                            else "SPOUSE"
                        ),
                        "person": format_person(person),
                    }
                    for person in all_siblings
                ],

                "relationships": relationships,

                "counts": {
                    "spouses": len(spouses),
                    "children": len(
                        children_with_details
                    ),
                    "parents": len(all_parents),
                    "siblings": len(all_siblings),

                    "targetParents": len(
                        target_parent_list
                    ),
                    "spouseParents": len(
                        spouse_parent_list
                    ),

                    "targetSiblings": len(
                        target_sibling_list
                    ),
                    "spouseSiblings": len(
                        spouse_sibling_list
                    ),
                },
            }

        # ====================================================
        # DEGREE 3
        #
        # Degree 2
        # +
        # Sibling's spouse(s)
        # Sibling's children
        # ====================================================

        sibling_families = []

        degree2_ids = {
            target_id,

            *[
                get_person_id(person)
                for person in spouses
            ],

            *[
                get_person_id(person)
                for person in children_with_details
            ],

            *[
                get_person_id(person)
                for person in target_parent_list
            ],

            *[
                get_person_id(person)
                for person in spouse_parent_list
            ],

            *[
                get_person_id(person)
                for person in target_sibling_list
            ],

            *[
                get_person_id(person)
                for person in spouse_sibling_list
            ],
        }

        # ----------------------------------------------------
        # Process One Sibling's Family
        # ----------------------------------------------------

        async def process_sibling_family(
            sibling: dict,
            side: str,
        ):

            sibling_id = get_person_id(sibling)

            if not sibling_id:
                return None

            sibling_spouse_ids = set()
            sibling_children = []

            sibling_household_no = sibling.get(
                "householdNo"
            )

            # ------------------------------------------------
            # Get sibling household
            # ------------------------------------------------

            if sibling_household_no:

                try:

                    household = await fetch_household(
                        sibling_household_no
                    )

                    for household_person in household:

                        person_id = get_person_id(
                            household_person
                        )

                        if not person_id:
                            continue

                        if person_id == sibling_id:
                            continue

                        # Identify sibling's children
                        is_child = (
                            get_father_id(
                                household_person
                            )
                            == sibling_id
                            or
                            get_mother_id(
                                household_person
                            )
                            == sibling_id
                        )

                        if is_child:

                            child = await enrich_person(
                                household_person
                            )

                            sibling_children.append(
                                child
                            )

                            # --------------------------------
                            # Find sibling's spouse
                            # --------------------------------

                            father_id = get_father_id(
                                child
                            )

                            mother_id = get_mother_id(
                                child
                            )

                            if father_id == sibling_id:

                                other_parent_id = (
                                    mother_id
                                )

                            elif mother_id == sibling_id:

                                other_parent_id = (
                                    father_id
                                )

                            else:

                                other_parent_id = ""

                            if (
                                other_parent_id
                                and other_parent_id
                                != sibling_id
                            ):

                                sibling_spouse_ids.add(
                                    other_parent_id
                                )

                except Exception as error:

                    print(
                        f"Unable to process family "
                        f"of sibling {sibling_id}: "
                        f"{error}"
                    )

            # ------------------------------------------------
            # Fetch sibling spouse(s)
            # ------------------------------------------------

            sibling_spouses = []

            for spouse_id in sibling_spouse_ids:

                try:

                    spouse = await fetch_citizen(
                        spouse_id
                    )

                    if spouse:
                        sibling_spouses.append(
                            spouse
                        )

                except Exception as error:

                    print(
                        f"Unable to fetch sibling "
                        f"spouse {spouse_id}: "
                        f"{error}"
                    )

            # ------------------------------------------------
            # Remove Degree 1 & Degree 2 people
            # ------------------------------------------------

            filtered_spouses = [
                person
                for person in sibling_spouses
                if get_person_id(person)
                not in degree2_ids
            ]

            filtered_children = [
                person
                for person in sibling_children
                if get_person_id(person)
                not in degree2_ids
            ]

            return {
                "sibling": format_person(sibling),
                "side": side,

                "spouses": [
                    format_person(person)
                    for person in filtered_spouses
                ],

                "children": [
                    format_person(person)
                    for person in filtered_children
                ],
            }

        # ----------------------------------------------------
        # Process Target-side siblings
        # ----------------------------------------------------

        for sibling in target_sibling_list:

            family = await process_sibling_family(
                sibling,
                "TARGET",
            )

            if family:
                sibling_families.append(
                    family
                )

        # ----------------------------------------------------
        # Process Spouse-side siblings
        # ----------------------------------------------------

        for sibling in spouse_sibling_list:

            family = await process_sibling_family(
                sibling,
                "SPOUSE",
            )

            if family:
                sibling_families.append(
                    family
                )

        # ====================================================
        # BUILD DEGREE 3 RELATIONSHIPS
        # ====================================================

        degree3_relationships = [
            {
                "type": "TARGET",
                "side": "TARGET",
                "person": format_person(target),
            }
        ]

        # Spouses
        for person in spouses:

            degree3_relationships.append(
                {
                    "type": "SPOUSE",
                    "side": "TARGET",
                    "person": format_person(person),
                }
            )

        # Children
        for person in children_with_details:

            degree3_relationships.append(
                {
                    "type": "CHILD",
                    "side": "TARGET",
                    "person": format_person(person),
                }
            )

        # Target parents
        for person in target_parent_list:

            degree3_relationships.append(
                {
                    "type": "PARENT",
                    "side": "TARGET",
                    "person": format_person(person),
                }
            )

        # Spouse parents
        for person in spouse_parent_list:

            degree3_relationships.append(
                {
                    "type": "PARENT",
                    "side": "SPOUSE",
                    "person": format_person(person),
                }
            )

        # Target siblings
        for person in target_sibling_list:

            degree3_relationships.append(
                {
                    "type": "SIBLING",
                    "side": "TARGET",
                    "person": format_person(person),
                }
            )

        # Spouse siblings
        for person in spouse_sibling_list:

            degree3_relationships.append(
                {
                    "type": "SIBLING",
                    "side": "SPOUSE",
                    "person": format_person(person),
                }
            )

        # ----------------------------------------------------
        # Add sibling family relationships
        # ----------------------------------------------------

        for family in sibling_families:

            sibling = family["sibling"]

            for spouse in family["spouses"]:

                degree3_relationships.append(
                    {
                        "type": "SIBLING_SPOUSE",
                        "side": family["side"],

                        "relatedTo": {
                            "cid": sibling["cid"],
                            "fullName": sibling["fullName"],
                        },

                        "person": spouse,
                    }
                )

            for child in family["children"]:

                degree3_relationships.append(
                    {
                        "type": "SIBLING_CHILD",
                        "side": family["side"],

                        "relatedTo": {
                            "cid": sibling["cid"],
                            "fullName": sibling["fullName"],
                        },

                        "person": child,
                    }
                )

        # ====================================================
        # DEGREE 3 COUNTS
        # ====================================================

        total_sibling_spouses = sum(
            len(family["spouses"])
            for family in sibling_families
        )

        total_sibling_children = sum(
            len(family["children"])
            for family in sibling_families
        )

        # ====================================================
        # DEGREE 3 RESPONSE
        # ====================================================

        return {
            "success": True,
            "degree": 3,

            "target": format_person(target),

            # Degree 1
            "spouses": [
                format_person(person)
                for person in spouses
            ],

            "children": [
                format_person(person)
                for person in children_with_details
            ],

            # Degree 2
            "parents": [
                {
                    "side": (
                        "TARGET"
                        if any(
                            get_person_id(parent)
                            == get_person_id(person)
                            for parent
                            in target_parent_list
                        )
                        else "SPOUSE"
                    ),
                    "person": format_person(person),
                }
                for person in all_parents
            ],

            "siblings": [
                {
                    "side": (
                        "TARGET"
                        if any(
                            get_person_id(sibling)
                            == get_person_id(person)
                            for sibling
                            in target_sibling_list
                        )
                        else "SPOUSE"
                    ),
                    "person": format_person(person),
                }
                for person in all_siblings
            ],

            # Degree 3
            "siblingFamilies": sibling_families,

            # Unified relationships
            "relationships": degree3_relationships,

            "counts": {
                "spouses": len(spouses),
                "children": len(
                    children_with_details
                ),
                "parents": len(all_parents),
                "siblings": len(all_siblings),

                "targetParents": len(
                    target_parent_list
                ),
                "spouseParents": len(
                    spouse_parent_list
                ),

                "targetSiblings": len(
                    target_sibling_list
                ),
                "spouseSiblings": len(
                    spouse_sibling_list
                ),

                "siblingSpouses": total_sibling_spouses,
                "siblingChildren": total_sibling_children,
                "siblingFamilies": len(
                    sibling_families
                ),
            },
        }

    # ========================================================
    # Error Handling
    # ========================================================

    except HTTPException:
        raise

    except httpx.TimeoutException:

        raise HTTPException(
            status_code=504,
            detail=(
                "Relationship API request timed out."
            ),
        )

    except httpx.HTTPStatusError as error:

        raise HTTPException(
            status_code=502,
            detail=(
                "Relationship API returned "
                f"HTTP {error.response.status_code}."
            ),
        )

    except httpx.RequestError as error:

        raise HTTPException(
            status_code=502,
            detail=(
                "Unable to connect to the "
                "Relationship API."
            ),
        )

    except Exception as error:

        print(
            f"Degree {degree} relationship API error: "
            f"{error}"
        )

        raise HTTPException(
            status_code=502,
            detail=(
                f"Unable to retrieve Degree "
                f"{degree} relationship data."
            ),
        )