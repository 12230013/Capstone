
from typing import Any
import os
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Path, Query

RELATIONSHIP_API = os.getenv(
    "RELATIONSHIP_API",
    "http://172.21.48.162:3000",
)

router = APIRouter(
    prefix="/api/relationship",
    tags=["Relationship Mapping"],
)


# ============================================================
# Validation Helpers
# ============================================================

def validate_cid(cid: str) -> str:
    """Validate that CID contains exactly 11 ASCII digits."""

    if not cid.isascii() or not cid.isdigit():
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid CID. CID must contain digits only; "
                "letters and symbols are not allowed."
            ),
        )

    if len(cid) < 11:
        raise HTTPException(
            status_code=400,
            detail="CID is too short. CID must be exactly 11 digits.",
        )

    if len(cid) > 11:
        raise HTTPException(
            status_code=400,
            detail="CID is too long. CID must be exactly 11 digits.",
        )

    return cid


def validate_degree(degree: str) -> str:
    """Allow only relationship degrees 1, 2, and 3."""

    if degree not in {"1", "2", "3"}:
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid degree. Only Degree 1, Degree 2, "
                "and Degree 3 are supported."
            ),
        )

    return degree


# ============================================================
# Utility Helpers
# ============================================================

def normalize_id(value: Any) -> str:
    """Convert an ID/CID value to a cleaned string."""

    if value is None:
        return ""

    return str(value).strip()


def get_father_id(person: dict) -> str:
    """Get father's CID from different possible field names."""

    return normalize_id(
        person.get("fatherCID")
        or person.get("fatherCIDNo")
        or person.get("fatherCidNo")
        or person.get("fatherCid")
    )


def get_mother_id(person: dict) -> str:
    """Get mother's CID from different possible field names."""

    return normalize_id(
        person.get("motherCID")
        or person.get("motherCIDNo")
        or person.get("motherCidNo")
        or person.get("motherCid")
    )


def get_person_id(person: dict) -> str:
    """Get a person's CID from different possible field names."""

    return normalize_id(
        person.get("cid")
        or person.get("CID")
        or person.get("cidNo")
    )


def format_person(person: dict) -> dict:
    """Return only the information required by the frontend."""

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
    """Retrieve citizen information from the external API."""

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
    """Retrieve all members of a household."""

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
    """Retrieve full citizen information when a CID is available."""

    person_id = get_person_id(person)

    if not person_id:
        return person

    try:
        full_person = await fetch_citizen(person_id)

        if full_person:
            return {**person, **full_person}

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
    """Check whether the Relationship Integration API is running."""

    return {
        "ok": True,
        "message": "Relationship Integration API is running",
    }


# ============================================================
# Relationship Visualization
# GET /api/relationship/visualization/{cid}?degree=1
# ============================================================

@router.get("/visualization/{cid}")
async def relationship_visualization(
    cid: str,
    degree: str = Query(
        default="1",
        description="Supported relationship degree: 1, 2, or 3",
    ),
):
    """
    Return relationship data in graph format.

    Degree 1: Target, spouse(s), and children.
    Degree 2: Degree 1 plus parents and siblings.
    Degree 3: Degree 2 plus sibling spouses and children.
    """

    # Validate inputs before making external API requests.
    cid = validate_cid(cid)
    degree = validate_degree(degree)

    try:
        relationship_data = await get_relationships(
            cid=cid,
            degree=degree,
        )

        nodes = {}
        edges = []

        def add_node(
            person: dict,
            node_degree: int | None,
            relationship_type: str,
            side: str = "TARGET",
        ):
            person_id = normalize_id(person.get("cid"))

            if not person_id:
                return

            if node_degree is None:
                nodes[person_id] = {
                    "id": person_id,
                    "cid": person_id,
                    "name": person.get("fullName"),
                    "gender": person.get("gender"),
                    "dob": person.get("dob"),
                    "relationship": relationship_type,
                    "side": side,
                }
                return

            if person_id not in nodes:
                nodes[person_id] = {
                    "id": person_id,
                    "cid": person_id,
                    "name": person.get("fullName"),
                    "gender": person.get("gender"),
                    "dob": person.get("dob"),
                    "relationship": relationship_type,
                    "side": side,
                    "degree": node_degree,
                }
            else:
                existing_degree = nodes[person_id].get("degree")

                if (
                    existing_degree is not None
                    and node_degree < existing_degree
                ):
                    nodes[person_id]["degree"] = node_degree
                    nodes[person_id]["relationship"] = relationship_type
                    nodes[person_id]["side"] = side

        def add_edge(
            source: str,
            target: str,
            relationship_type: str,
            edge_degree: int,
        ):
            source = normalize_id(source)
            target = normalize_id(target)

            if not source or not target or source == target:
                return

            for existing in edges:
                same_direction = (
                    existing["source"] == source
                    and existing["target"] == target
                    and existing["relationship"] == relationship_type
                )

                reverse_direction = (
                    existing["source"] == target
                    and existing["target"] == source
                    and existing["relationship"] == relationship_type
                )

                if same_direction or reverse_direction:
                    return

            edges.append({
                "source": source,
                "target": target,
                "relationship": relationship_type,
                "degree": edge_degree,
            })

        # Add the target.
        target = relationship_data.get("target", {})
        target_id = normalize_id(target.get("cid"))

        if not target_id:
            raise HTTPException(
                status_code=404,
                detail="Target citizen was not found.",
            )

        add_node(
            person=target,
            node_degree=None,
            relationship_type="TARGET",
            side="TARGET",
        )

        # Add relationship nodes and edges.
        relationships = relationship_data.get("relationships", [])

        for relationship in relationships:
            relationship_type = relationship.get("type")
            side = relationship.get("side", "TARGET")
            person = relationship.get("person", {})
            person_id = normalize_id(person.get("cid"))

            if not person_id:
                continue

            if relationship_type == "TARGET":
                node_degree = None
            elif relationship_type in {"SPOUSE", "CHILD"}:
                node_degree = 1
            elif relationship_type in {"PARENT", "SIBLING"}:
                node_degree = 2
            elif relationship_type in {"SIBLING_SPOUSE", "SIBLING_CHILD"}:
                node_degree = 3
            else:
                continue

            # The requested degree determines which nodes are included.
            if (
                node_degree is not None
                and node_degree > int(degree)
            ):
                continue

            add_node(
                person=person,
                node_degree=node_degree,
                relationship_type=relationship_type,
                side=side,
            )

            if relationship_type == "SPOUSE":
                add_edge(
                    target_id, person_id, "SPOUSE", 1
                )

            elif relationship_type == "CHILD":
                add_edge(
                    target_id, person_id, "CHILD", 1
                )

            elif relationship_type == "PARENT":
                if side == "TARGET":
                    add_edge(
                        target_id, person_id, "PARENT", 2
                    )
                elif side == "SPOUSE":
                    spouses = relationship_data.get("spouses", [])

                    if spouses:
                        spouse_id = normalize_id(spouses[0].get("cid"))

                        if spouse_id:
                            add_edge(
                                spouse_id, person_id, "PARENT", 2
                            )

            elif relationship_type == "SIBLING":
                if side == "TARGET":
                    add_edge(
                        target_id, person_id, "SIBLING", 2
                    )
                elif side == "SPOUSE":
                    spouses = relationship_data.get("spouses", [])

                    if spouses:
                        spouse_id = normalize_id(spouses[0].get("cid"))

                        if spouse_id:
                            add_edge(
                                spouse_id, person_id, "SIBLING", 2
                            )

            elif relationship_type in {"SIBLING_SPOUSE", "SIBLING_CHILD"}:
                related_to = relationship.get("relatedTo", {})
                sibling_id = normalize_id(related_to.get("cid"))

                if sibling_id:
                    add_edge(
                        sibling_id,
                        person_id,
                        relationship_type,
                        3,
                    )

        node_list = list(nodes.values())

        def node_sort_key(node):
            if node.get("relationship") == "TARGET":
                return 0

            return node.get("degree", 99)

        node_list.sort(key=node_sort_key)

        degree_counts = {1: 0, 2: 0, 3: 0}

        for node in node_list:
            node_degree = node.get("degree")

            if node_degree in degree_counts:
                degree_counts[node_degree] += 1

        return {
            "success": True,
            "target": {
                "cid": target_id,
                "name": target.get("fullName"),
            },
            "requestedDegree": degree,
            "nodes": node_list,
            "edges": edges,
            "counts": {
                "nodes": len(node_list),
                "edges": len(edges),
                "degree1": degree_counts[1],
                "degree2": degree_counts[2],
                "degree3": degree_counts[3],
            },
            "visualization": {
                "type": "FAMILY_TREE",
                "degreeLevels": {
                    "1": "DEGREE_1",
                    "2": "DEGREE_2",
                    "3": "DEGREE_3",
                },
            },
        }

    except HTTPException:
        raise

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="Relationship API request timed out.",
        )

    except httpx.HTTPStatusError as error:
        raise HTTPException(
            status_code=502,
            detail=(
                "Relationship API returned "
                f"HTTP {error.response.status_code}."
            ),
        )

    except httpx.RequestError:
        raise HTTPException(
            status_code=502,
            detail="Unable to connect to the Relationship API.",
        )

    except Exception as error:
        print("VISUALIZATION ERROR:", repr(error))

        raise HTTPException(
            status_code=502,
            detail="Unable to generate relationship visualization data.",
        )


# ============================================================
# Relationship API
# GET /api/relationship/{cid}/{degree}
# ============================================================

@router.get("/{cid}/{degree}")
async def get_relationships(
    cid: str = Path(
        ...,
        description="Citizen ID must contain exactly 11 digits",
    ),
    degree: str = Path(
        ...,
        description="Supported relationship degree: 1, 2, or 3",
    ),
):
    """Retrieve family relationships for a citizen up to Degree 3."""

    # Validate before any external API request.
    cid = validate_cid(cid)
    degree = validate_degree(degree)

    try:
        # 1. Fetch target.
        target = await fetch_citizen(cid)

        if not target:
            raise HTTPException(
                status_code=404,
                detail="Target citizen was not found.",
            )

        target_id = get_person_id(target) or cid

        # 2. Find target's children.
        target_household = []
        household_no = target.get("householdNo")

        if household_no:
            target_household = await fetch_household(household_no)

        children = []

        for person in target_household:
            person_id = get_person_id(person)

            if not person_id or person_id == target_id:
                continue

            is_child = (
                get_father_id(person) == target_id
                or get_mother_id(person) == target_id
            )

            if is_child:
                children.append(person)

        children_with_details = []

        for child in children:
            child_details = await enrich_person(child)
            children_with_details.append(child_details)

        # 3. Find target's spouse(s) using the children's parent IDs.
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

            if other_parent_id and other_parent_id != target_id:
                spouse_ids.add(other_parent_id)

        spouses = []

        for spouse_id in spouse_ids:
            spouse = None

            try:
                spouse = await fetch_citizen(spouse_id)
            except Exception as error:
                print(f"Unable to fetch spouse {spouse_id}: {error}")

            if spouse:
                spouses.append(spouse)
            else:
                spouses.append({
                    "cid": spouse_id,
                    "fullName": None,
                    "gender": None,
                    "dob": None,
                    "detailsAvailable": False,
                })

        # ====================================================
        # DEGREE 1: Target, spouse(s), children
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
                relationships.append({
                    "type": "SPOUSE",
                    "side": "TARGET",
                    "person": format_person(person),
                })

            for person in children_with_details:
                relationships.append({
                    "type": "CHILD",
                    "side": "TARGET",
                    "person": format_person(person),
                })

            return {
                "success": True,
                "degree": 1,
                "target": format_person(target),
                "spouses": [
                    format_person(person) for person in spouses
                ],
                "children": [
                    format_person(person)
                    for person in children_with_details
                ],
                "relationships": relationships,
                "counts": {
                    "spouses": len(spouses),
                    "children": len(children_with_details),
                },
            }

        # ====================================================
        # DEGREE 2: Degree 1 plus parents and siblings
        # ====================================================

        target_parents = {}
        spouse_parents = {}
        target_siblings = {}
        spouse_siblings = {}

        async def process_parents_and_siblings(
            person: dict,
            side: str,
        ):
            person_id = get_person_id(person)

            if not person_id:
                return

            father_id = get_father_id(person)
            mother_id = get_mother_id(person)

            # Father.
            if father_id and father_id != person_id:
                try:
                    father = await fetch_citizen(father_id)

                    if father:
                        if side == "TARGET":
                            target_parents[father_id] = father
                        else:
                            spouse_parents[father_id] = father

                except Exception as error:
                    print(f"Unable to fetch father {father_id}: {error}")

            # Mother.
            if mother_id and mother_id != person_id:
                try:
                    mother = await fetch_citizen(mother_id)

                    if mother:
                        if side == "TARGET":
                            target_parents[mother_id] = mother
                        else:
                            spouse_parents[mother_id] = mother

                except Exception as error:
                    print(f"Unable to fetch mother {mother_id}: {error}")

            # Siblings.
            person_household_no = person.get("householdNo")

            if person_household_no:
                try:
                    household = await fetch_household(person_household_no)

                    for household_person in household:
                        sibling_id = get_person_id(household_person)

                        if not sibling_id or sibling_id == person_id:
                            continue

                        same_father = (
                            bool(father_id)
                            and get_father_id(household_person) == father_id
                        )

                        same_mother = (
                            bool(mother_id)
                            and get_mother_id(household_person) == mother_id
                        )

                        if same_father and same_mother:
                            sibling = await enrich_person(household_person)

                            if side == "TARGET":
                                target_siblings[sibling_id] = sibling
                            else:
                                spouse_siblings[sibling_id] = sibling

                except Exception as error:
                    print(
                        f"Unable to process siblings for "
                        f"{person_id}: {error}"
                    )

        await process_parents_and_siblings(target, "TARGET")

        for spouse in spouses:
            await process_parents_and_siblings(spouse, "SPOUSE")

        # Remove Degree 1 people from Degree 2 collections.
        degree1_ids = {
            target_id,
            *[get_person_id(person) for person in spouses],
            *[
                get_person_id(person)
                for person in children_with_details
            ],
        }

        for person_id in degree1_ids:
            target_parents.pop(person_id, None)
            spouse_parents.pop(person_id, None)
            target_siblings.pop(person_id, None)
            spouse_siblings.pop(person_id, None)

        target_parent_list = list(target_parents.values())
        spouse_parent_list = list(spouse_parents.values())
        target_sibling_list = list(target_siblings.values())
        spouse_sibling_list = list(spouse_siblings.values())

        all_parents = [*target_parent_list, *spouse_parent_list]
        all_siblings = [*target_sibling_list, *spouse_sibling_list]

        if degree == "2":
            relationships = [
                {
                    "type": "TARGET",
                    "side": "TARGET",
                    "person": format_person(target),
                }
            ]

            for person in spouses:
                relationships.append({
                    "type": "SPOUSE",
                    "side": "TARGET",
                    "person": format_person(person),
                })

            for person in children_with_details:
                relationships.append({
                    "type": "CHILD",
                    "side": "TARGET",
                    "person": format_person(person),
                })

            for person in target_parent_list:
                relationships.append({
                    "type": "PARENT",
                    "side": "TARGET",
                    "person": format_person(person),
                })

            for person in spouse_parent_list:
                relationships.append({
                    "type": "PARENT",
                    "side": "SPOUSE",
                    "person": format_person(person),
                })

            for person in target_sibling_list:
                relationships.append({
                    "type": "SIBLING",
                    "side": "TARGET",
                    "person": format_person(person),
                })

            for person in spouse_sibling_list:
                relationships.append({
                    "type": "SIBLING",
                    "side": "SPOUSE",
                    "person": format_person(person),
                })

            return {
                "success": True,
                "degree": 2,
                "target": format_person(target),
                "spouses": [
                    format_person(person) for person in spouses
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
                                get_person_id(parent) == get_person_id(person)
                                for parent in target_parent_list
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
                                get_person_id(sibling) == get_person_id(person)
                                for sibling in target_sibling_list
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
                    "children": len(children_with_details),
                    "parents": len(all_parents),
                    "siblings": len(all_siblings),
                    "targetParents": len(target_parent_list),
                    "spouseParents": len(spouse_parent_list),
                    "targetSiblings": len(target_sibling_list),
                    "spouseSiblings": len(spouse_sibling_list),
                },
            }

        # ====================================================
        # DEGREE 3: Degree 2 plus sibling spouses and children
        # ====================================================

        sibling_families = []

        degree2_ids = {
            target_id,
            *[get_person_id(person) for person in spouses],
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

        async def process_sibling_family(
            sibling: dict,
            side: str,
        ):
            sibling_id = get_person_id(sibling)

            if not sibling_id:
                return None

            sibling_spouse_ids = set()
            sibling_children = []
            sibling_household_no = sibling.get("householdNo")

            if sibling_household_no:
                try:
                    household = await fetch_household(sibling_household_no)

                    for household_person in household:
                        person_id = get_person_id(household_person)

                        if not person_id or person_id == sibling_id:
                            continue

                        is_child = (
                            get_father_id(household_person) == sibling_id
                            or get_mother_id(household_person) == sibling_id
                        )

                        if is_child:
                            child = await enrich_person(household_person)
                            sibling_children.append(child)

                            father_id = get_father_id(child)
                            mother_id = get_mother_id(child)

                            if father_id == sibling_id:
                                other_parent_id = mother_id
                            elif mother_id == sibling_id:
                                other_parent_id = father_id
                            else:
                                other_parent_id = ""

                            if (
                                other_parent_id
                                and other_parent_id != sibling_id
                            ):
                                sibling_spouse_ids.add(other_parent_id)

                except Exception as error:
                    print(
                        f"Unable to process family of sibling "
                        f"{sibling_id}: {error}"
                    )

            sibling_spouses = []

            for spouse_id in sibling_spouse_ids:
                try:
                    spouse = await fetch_citizen(spouse_id)

                    if spouse:
                        sibling_spouses.append(spouse)

                except Exception as error:
                    print(
                        f"Unable to fetch sibling spouse "
                        f"{spouse_id}: {error}"
                    )

            filtered_spouses = [
                person
                for person in sibling_spouses
                if get_person_id(person) not in degree2_ids
            ]

            filtered_children = [
                person
                for person in sibling_children
                if get_person_id(person) not in degree2_ids
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

        for sibling in target_sibling_list:
            family = await process_sibling_family(sibling, "TARGET")

            if family:
                sibling_families.append(family)

        for sibling in spouse_sibling_list:
            family = await process_sibling_family(sibling, "SPOUSE")

            if family:
                sibling_families.append(family)

        degree3_relationships = [
            {
                "type": "TARGET",
                "side": "TARGET",
                "person": format_person(target),
            }
        ]

        for person in spouses:
            degree3_relationships.append({
                "type": "SPOUSE",
                "side": "TARGET",
                "person": format_person(person),
            })

        for person in children_with_details:
            degree3_relationships.append({
                "type": "CHILD",
                "side": "TARGET",
                "person": format_person(person),
            })

        for person in target_parent_list:
            degree3_relationships.append({
                "type": "PARENT",
                "side": "TARGET",
                "person": format_person(person),
            })

        for person in spouse_parent_list:
            degree3_relationships.append({
                "type": "PARENT",
                "side": "SPOUSE",
                "person": format_person(person),
            })

        for person in target_sibling_list:
            degree3_relationships.append({
                "type": "SIBLING",
                "side": "TARGET",
                "person": format_person(person),
            })

        for person in spouse_sibling_list:
            degree3_relationships.append({
                "type": "SIBLING",
                "side": "SPOUSE",
                "person": format_person(person),
            })

        for family in sibling_families:
            sibling = family["sibling"]

            for spouse in family["spouses"]:
                degree3_relationships.append({
                    "type": "SIBLING_SPOUSE",
                    "side": family["side"],
                    "relatedTo": {
                        "cid": sibling["cid"],
                        "fullName": sibling["fullName"],
                    },
                    "person": spouse,
                })

            for child in family["children"]:
                degree3_relationships.append({
                    "type": "SIBLING_CHILD",
                    "side": family["side"],
                    "relatedTo": {
                        "cid": sibling["cid"],
                        "fullName": sibling["fullName"],
                    },
                    "person": child,
                })

        total_sibling_spouses = sum(
            len(family["spouses"]) for family in sibling_families
        )

        total_sibling_children = sum(
            len(family["children"]) for family in sibling_families
        )

        return {
            "success": True,
            "degree": 3,
            "target": format_person(target),
            "spouses": [
                format_person(person) for person in spouses
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
                            get_person_id(parent) == get_person_id(person)
                            for parent in target_parent_list
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
                            get_person_id(sibling) == get_person_id(person)
                            for sibling in target_sibling_list
                        )
                        else "SPOUSE"
                    ),
                    "person": format_person(person),
                }
                for person in all_siblings
            ],
            "siblingFamilies": sibling_families,
            "relationships": degree3_relationships,
            "counts": {
                "spouses": len(spouses),
                "children": len(children_with_details),
                "parents": len(all_parents),
                "siblings": len(all_siblings),
                "targetParents": len(target_parent_list),
                "spouseParents": len(spouse_parent_list),
                "targetSiblings": len(target_sibling_list),
                "spouseSiblings": len(spouse_sibling_list),
                "siblingSpouses": total_sibling_spouses,
                "siblingChildren": total_sibling_children,
                "siblingFamilies": len(sibling_families),
            },
        }

    
    except HTTPException:
        raise

    except httpx.TimeoutException as error:
        print("RELATIONSHIP TIMEOUT:", repr(error))
        raise HTTPException(
            status_code=504,
            detail="Relationship API request timed out.",
        )

    except httpx.HTTPStatusError as error:
        print("RELATIONSHIP HTTP ERROR:")
        print("URL:", error.request.url)
        print("STATUS:", error.response.status_code)
        print("BODY:", error.response.text[:1000])

        raise HTTPException(
            status_code=502,
            detail=(
                f"External Relationship API returned "
                f"HTTP {error.response.status_code}."
            ),
        )

    except httpx.RequestError as error:
        print("RELATIONSHIP CONNECTION ERROR:", repr(error))
        print("URL:", error.request.url if error.request else "Unknown")

        raise HTTPException(
            status_code=502,
            detail="Unable to connect to the Relationship API.",
        )

    except Exception as error:
        import traceback
        traceback.print_exc()

        raise HTTPException(
            status_code=502,
            detail="Unable to retrieve relationship data.",
        )
