from datetime import date
import re
import json

from click import prompt
from networkx import degree, edges

from app.services.rag_service import RAGService
from app.services.cdr_service import CDRService
from app.services.llm_service import LLMService
from app.services.prompt_service import PromptService

from app.api.routes.relationship import (get_relationships,relationship_visualization)

from app.analytics.cdr_analytics import (
    analyze_communication_frequency,
    analyze_communication_direction,
    analyze_period_statistics,
    generate_communication_timeline,
    analyze_interactions,
    detect_irregular_patterns,
    generate_communication_network,
)

def format_relationship_answer(data: dict, query: str) -> str:
    query_lower = query.lower()

    def person_label(person):
        name = person.get("fullName") or person.get("name") or "Unknown"
        cid = person.get("cid") or person.get("id") or "Unknown"
        return f"{name} with CID {cid}"

    target = data.get("target", {})
    target_label = person_label(target)

    # The API's relationship data is the source of truth.
    relationships = data.get("relationships", [])

    def get_people(relation_type):
        return [
            item for item in relationships
            if item.get("type") == relation_type
        ]

    def format_people(items):
        if not items:
            return ["No information available."]
        return [
            f"{index}. On the {item.get('side', 'UNKNOWN')} side: "
            f"{person_label(item.get('person', {}))}."
            for index, item in enumerate(items, start=1)
        ]

    asks_parents = bool(
        re.search(r"\b(parent|parents|father|mother)\b", query_lower)
    )
    asks_siblings = bool(
        re.search(r"\b(sibling|siblings|brother|sister)\b", query_lower)
    )
    asks_spouse_side = bool(
    re.search(r"\bspouse[- ]side\b|\bside of the spouse\b", query_lower)
    )
    asks_target_side = bool(
    re.search(r"\btarget[- ]side\b|\btarget's side\b", query_lower)
    )
    asks_first_degree = bool(
        re.search(r"\b(first|1st)[-\s]+degree\b|\bdegree\s*1\b", query_lower)
    )
    asks_complete_tree = any(
        phrase in query_lower
        for phrase in (
            "complete family tree",
            "full family tree",
            "all relationships",
            "all degrees",
            "show the family tree",
            "visualize the family tree",
            "visualise the family tree",
        )
    )

    lines = [f"The target person is {target_label}."]

    # Answer only the requested relationship categories when appropriate.
    if (asks_parents or asks_siblings) and not asks_complete_tree:
        def filter_by_side(items):
            if asks_spouse_side:
                return [item for item in items if item.get("side") == "SPOUSE"]
            if asks_target_side:
                return [item for item in items if item.get("side") == "TARGET"]
            return items

        if asks_parents:
            lines.extend(["", "The spouse-side parents are:" if asks_spouse_side
                      else "The target-side parents are:" if asks_target_side
                      else "Her parents are:"])
            lines.extend(format_people(filter_by_side(get_people("PARENT"))))

        if asks_siblings:
            lines.extend(["", "The spouse-side siblings are:" if asks_spouse_side
                      else "The target-side siblings are:" if asks_target_side
                      else "Her siblings are:"])
            lines.extend(format_people(filter_by_side(get_people("SIBLING"))))

        return "\n".join(lines)

    if asks_first_degree or (
        not asks_complete_tree
        and not asks_parents
        and not asks_siblings
        and int(data.get("degree", 1)) == 1
    ):
        spouses = data.get("spouses", [])
        children = data.get("children", [])

        lines.extend(["", "Spouse(s):"])
        if spouses:
            lines.extend(
                f"{i}. {person_label(p)}."
                for i, p in enumerate(spouses, 1)
            )
        else:
            lines.append("No spouse information available.")

        lines.extend(["", "Children:"])
        if children:
            lines.extend(
                f"{i}. {person_label(p)}."
                for i, p in enumerate(children, 1)
            )
        else:
            lines.append("No child information available.")

        return "\n".join(lines)

    # Full family-tree response.
    lines.extend(["", "Spouse(s):"])
    spouses = data.get("spouses", [])
    lines.extend(
        f"{i}. {person_label(p)}."
        for i, p in enumerate(spouses, 1)
    ) if spouses else lines.append("No spouse information available.")

    lines.extend(["", "Children:"])
    children = data.get("children", [])
    lines.extend(
        f"{i}. {person_label(p)}."
        for i, p in enumerate(children, 1)
    ) if children else lines.append("No child information available.")

    lines.extend(["", "Parents:"])
    lines.extend(format_people(get_people("PARENT")))

    lines.extend(["", "Siblings:"])
    lines.extend(format_people(get_people("SIBLING")))

    lines.extend(["", "Extended family:"])
    for family in data.get("siblingFamilies", []):
        sibling = family.get("sibling", {})
        lines.append(
            f"\nFamily of {person_label(sibling)} "
            f"(side: {family.get('side', 'UNKNOWN')}):"
        )

        for spouse in family.get("spouses", []):
            lines.append(f"- Spouse: {person_label(spouse)}.")

        for child in family.get("children", []):
            lines.append(f"- Child: {person_label(child)}.")

    return "\n".join(lines)



class ChatService:
    def __init__(self):
        self._rag_service = None
        self._cdr_service = None
        self._llm_service = None
        self._prompt_service = None
        self._statement_service = None

    @property
    def rag_service(self):
        if self._rag_service is None:
            self._rag_service = RAGService()
        return self._rag_service

    @property
    def cdr_service(self):
        if self._cdr_service is None:
            self._cdr_service = CDRService()
        return self._cdr_service

    @property
    def llm_service(self):
        if self._llm_service is None:
            self._llm_service = LLMService()
        return self._llm_service

    @property
    def prompt_service(self):
        if self._prompt_service is None:
            self._prompt_service = PromptService()
        return self._prompt_service

    @property
    def statement_service(self):
        if self._statement_service is None:
            from app.services.statement_service import StatementService
            self._statement_service = StatementService()
        return self._statement_service

    async def query(self, query: str) -> dict:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Query cannot be empty.")

        query_lower = query.lower()

        # ---------------------------------------------------------
        # Detect phone number
        # ---------------------------------------------------------
        number_match = re.search(r"\b\d{5,20}\b", query)

        # ---------------------------------------------------------
        # Detect CDR-related query
        # ---------------------------------------------------------
        cdr_keywords = [
            "cdr",
            "call",
            "calls",
            "communication",
            "communications",
            "contact",
            "contacts",
            "interaction",
            "interactions",
            "incoming",
            "outgoing",
            "duration",
            "irregular",
            "suspicious",
            "frequency",
            "frequent",
            "timeline",
            "network",
            "history",
        ]

        
        # Relationship Mapping API routing
        cid_match = re.search(r"\b\d{11}\b", query)

        relationship_keywords = [
            "relationship",
            "relationships",
            "family",
            "family tree",
            "relatives",
            "parent",
            "parents",
            "siblings",
            "sibling",
            "spouse",
            "children",
            "degree",
        ]

        is_relationship_query = any(
            keyword in query_lower
            for keyword in relationship_keywords
        )

        if cid_match and is_relationship_query:
            cid = cid_match.group(0)

            # Detect requested relationship degree
            degree = "1"

            if re.search(
                r"\b(?:all degrees|all relationships|complete family tree|full family tree)\b",
                query_lower,
            ):
                degree = "3"

            elif re.search(
                r"\b(?:third|3rd)[-\s]+degree\b|\bdegree\s*3\b",
                query_lower,
            ):
                degree = "3"

            elif re.search(
                r"\b(?:second|2nd)[-\s]+degree\b|\bdegree\s*2\b",
                query_lower,
            ):
                degree = "2"

            elif re.search(
                r"\b(?:first|1st)[-\s]+degree\b|\bdegree\s*1\b",
                query_lower,
            ):
                degree = "1"

            elif any(term in query_lower for term in [
                "parent",
                "parents",
                "father",
                "mother",
                "sibling",
                "siblings",
                "brother",
                "sister",
            ]) :
                degree = "2"

            try:
                
                relationship_data = await get_relationships(
                    cid=cid,
                    degree=degree,
                )

                relationship_prompt = (
                    self.prompt_service.build_relationship_prompt(
                        query=query,
                        relationship_data=relationship_data,
                    )
                )
                relationship_prompt += """

                IMPORTANT INSTRUCTIONS:
                For every parent and sibling, explicitly identify the side:
                - TARGET means the target's side.
                - SPOUSE means the target's spouse's side.

                Never describe a spouse's sibling as the target's sibling.
                Only report relationships and sides present in the supplied data
                - Identify the target person by name and CID.
                - For every parent and sibling, state whose side they belong to.
                - side="TARGET" means the person is the subject of the query.
                - If a relationship is on the target's side, label it as TARGET.
                - If it belongs to the other parent or partner side, label it clearly.
                """

                answer = format_relationship_answer(relationship_data,query)

                # Show the visualization only when explicitly requested.
                visualization_keywords = [
                    "complete family tree",
                    "full family tree",
                    "show the family tree",
                    "show me the family tree",
                    "display the family tree",
                    "visualize the family tree",
                    "visualise the family tree",
                    "show the relationship network",
                    "display the relationship network",
                    "visualize relationships",
                    "visualise relationships",
                    "visualize the relationships",
                    "visualise the relationships",
                    "map the relationships",
                    "show me the relationship map",
                ]

                should_visualize = any(
                    phrase in query_lower
                    for phrase in visualization_keywords
                )

                response = {
                    "answer": answer,
                    "sources": [
                        {
                            "type": "Relationship Mapping API",
                            "cid": cid,
                            "degree": int(degree),
                        }
                    ],
                }

                if should_visualize:
                    visualization_data = await relationship_visualization(
                        cid=cid,
                        degree=degree,
                    )

                    response["visualization"] = {
                        "type": "relationship_network",
                        "data": visualization_data,
                    }

                return {
                    "success": True,
                    "response": response,
                }

            except Exception as e:
                print(f"Relationship query error: {e}")
                return {
                    "success": False,
                    "response": {
                        "answer": (
                            "I couldn't retrieve the relationship information "
                            "for this person. Please try again."
                        ),
                        "sources": [],
                    },
                }

        is_cdr_query = any(
            keyword in query_lower
            for keyword in cdr_keywords
        )

        # ---------------------------------------------------------
        # CDR QUERY
        # ---------------------------------------------------------
        if number_match and is_cdr_query:

            number = number_match.group(0)

            # Get all CDR records once
            summary = await self.cdr_service.get_summary(number)
            records = summary.records

            # =====================================================
            # 1. IRREGULAR / SUSPICIOUS PATTERNS
            # =====================================================
            is_irregular_query = any(
                keyword in query_lower
                for keyword in [
                    "irregular",
                    "suspicious",
                    "unusual",
                    "anomal",
                ]
            )

            # =====================================================
            # 2. COMMUNICATION NETWORK
            # =====================================================
            is_network_query = any(
                phrase in query_lower
                for phrase in [
                    "communication network",
                    "network graph",
                    "call network",
                    "network",
                ]
            )

            # =====================================================
            # 3. COMMUNICATION TIMELINE / HISTORY
            # =====================================================
            is_timeline_query = any(
                phrase in query_lower
                for phrase in [
                    "communication timeline",
                    "call timeline",
                    "communication history",
                    "call history",
                    "history of communication",
                    "timeline",
                ]
            )

            # =====================================================
            # 4. SPECIFIC INTERACTIONS
            # =====================================================
            is_interactions_query = any(
                phrase in query_lower
                for phrase in [
                    "interactions with",
                    "interaction with",
                    "interactions for",
                    "interaction for",
                    "interactions of",
                    "interaction of",
                    "show me the interactions",
                    "interaction details",
                    "contact interactions",
                    "communicated with",
                    "communication with",
                ]
            )

            # =====================================================
            # 5. GENERAL SUMMARY
            # =====================================================
            summary_indicators = [
                "summary",
                "summarize",
                "overview",
                "communication activity",
                "overall communication",
                "overall activity",
            ]

            requested_statistics = [
                "total interactions",
                "incoming",
                "outgoing",
                "total duration",
                "most frequent",
                "frequency",
            ]

            number_of_requested_statistics = sum(
                1
                for statistic in requested_statistics
                if statistic in query_lower
            )

            is_general_summary_query = (
                any(
                    indicator in query_lower
                    for indicator in summary_indicators
                )
                or number_of_requested_statistics >= 2
            )

            # =====================================================
            # 6. FREQUENCY ONLY
            # =====================================================
            is_frequency_query = any(
                phrase in query_lower
                for phrase in [
                    "communication frequency",
                    "call frequency",
                    "frequent contacts",
                    "most frequent contacts",
                    "most frequent",
                    "most contacted",
                    "top contacts",
                    "frequency",
                ]
            )

            # =====================================================
            # 7. DIRECTION ONLY
            # =====================================================
            is_direction_query = any(
                phrase in query_lower
                for phrase in [
                    "incoming",
                    "outgoing",
                    "communication direction",
                    "call direction",
                    "direction",
                ]
            )

             # =====================================================
             # 8 PERIOD STATISTICS
            # =====================================================
            dates_in_query = re.findall(r"\d{4}-\d{2}-\d{2}", query)

            has_date_range = len(dates_in_query) >= 2
            is_period_statistics_query = (
                has_date_range
                and any(
                    phrase in query_lower
                    for phrase in [
                        "statistics",
                        "compare",
                        "comparison",
                        "communication activity",
                        "total interactions",
                        "total duration",
                        "incoming",
                        "outgoing",
                        "communication",
                        "interactions",
                        "calls",
                    ]
                )
            )

            # =====================================================
            # ROUTING
            # =====================================================
            if is_period_statistics_query:
                analysis_type = "period_statistics"

                dates = re.findall(
                    r"\d{4}-\d{2}-\d{2}",
                    query
                )

                if len(dates) >= 2:
                    start_date = date.fromisoformat(dates[0])
                    end_date = date.fromisoformat(dates[1])

                    period_records = [
                        record for record in records
                        if start_date <= record.datetime.date() <= end_date
                    ]

                    analysis_data = analyze_period_statistics(
                        period_records,
                        number,
                        start_date,
                        end_date
                    )
                else:
                    raise ValueError(
                        "Please provide both a start date and an end date."
                )


            
            elif is_irregular_query:
                analysis_type = "irregular_patterns"

                detected_patterns = detect_irregular_patterns(
                    records,
                    number
                )

                # Group patterns by type.
                pattern_counts = {}
                grouped_patterns = {}

                for pattern in detected_patterns:
                    pattern_type = pattern["pattern_type"]

                    pattern_counts[pattern_type] = (
                        pattern_counts.get(pattern_type, 0) + 1
                    )

                    if pattern_type not in grouped_patterns:
                        grouped_patterns[pattern_type] = []

                    grouped_patterns[pattern_type].append(pattern)

                # Keep up to 5 examples per category for the response data.
                representative_patterns = {
                    pattern_type: pattern_list[:5]
                    for pattern_type, pattern_list in grouped_patterns.items()
                }

                analysis_data = {
                    "total_patterns": len(detected_patterns),
                    "pattern_counts": pattern_counts,
                    "patterns": representative_patterns,
                }

                # Format the results into readable text.
                if not detected_patterns:
                    answer = (
                        f"No irregular communication patterns were detected "
                        f"for {number} in the available CDR records."
                    )

                else:
                    pattern_labels = {
                        "HIGH_FREQUENCY": "High-Frequency Contacts",
                        "COMMUNICATION_SPIKE": "Communication Spikes",
                        "ONE_SIDED_OUTGOING": "Predominantly Outgoing Calls",
                        "ONE_SIDED_INCOMING": "Predominantly Incoming Calls",
                        "UNUSUAL_COMMUNICATION_HOURS": "Unusual Communication Hours",
                    }

                    lines = [
                        f"Communication Pattern Analysis: {number}",
                        "",
                        f"Overview: {len(detected_patterns)} potential "
                        "irregular patterns were identified.",
                        "",
                        "These findings highlight communication patterns "
                        "that may warrant further investigation. They are "
                        "indicators for review, not proof of wrongdoing.",
                    ]

                    for pattern_type, pattern_list in grouped_patterns.items():
                        label = pattern_labels.get(
                            pattern_type,
                            pattern_type.replace("_", " ").title()
                        )

                        lines.extend([
                            "",
                            f"### {label} ({len(pattern_list)})",
                        ])

                        for pattern in pattern_list[:5]:
                            contact = pattern.get(
                                "contact_number", "Unknown"
                            )
                            evidence = pattern.get("evidence", {})

                            if pattern_type == "HIGH_FREQUENCY":
                                details = (
                                    f"{evidence.get('total_interactions', 0)} "
                                    f"interactions, compared with an average "
                                    f"of {evidence.get('average_contact_interactions', 0)}."
                                )

                            elif pattern_type == "COMMUNICATION_SPIKE":
                                details = (
                                    f"{evidence.get('interactions_on_date', 0)} "
                                    f"interactions on "
                                    f"{evidence.get('date', 'an unspecified date')}; "
                                    f"{evidence.get('spike_ratio', 0)} times "
                                    "the average daily activity."
                                )

                            elif pattern_type == "ONE_SIDED_OUTGOING":
                                details = (
                                    f"{evidence.get('outgoing_interactions', 0)} outgoing "
                                    f"and {evidence.get('incoming_interactions', 0)} incoming "
                                    f"interactions; "
                                    f"{evidence.get('outgoing_ratio', 0) * 100:.0f}% outgoing."
                                )

                            elif pattern_type == "ONE_SIDED_INCOMING":
                                details = (
                                    f"{evidence.get('incoming_interactions', 0)} incoming "
                                    f"and {evidence.get('outgoing_interactions', 0)} outgoing "
                                    f"interactions; "
                                    f"{evidence.get('incoming_ratio', 0) * 100:.0f}% incoming."
                                )

                            elif pattern_type == "UNUSUAL_COMMUNICATION_HOURS":
                                details = (
                                    f"{evidence.get('unusual_hour_interactions', 0)} of "
                                    f"{evidence.get('total_interactions', 0)} interactions "
                                    f"occurred during "
                                    f"{evidence.get('unusual_hours', 'unusual hours')}; "
                                    f"{evidence.get('unusual_hour_ratio', 0) * 100:.0f}% "
                                    "of interactions."
                                )

                            else:
                                details = pattern.get(
                                    "description",
                                    "Potential irregularity detected."
                                )

                            lines.append(f"- Contact: {contact}")
                            lines.append(f"  Finding: {details}")

                        remaining = len(pattern_list) - 5

                        if remaining > 0:
                            lines.append(
                                f"- {remaining} additional finding(s) "
                                "in this category are not displayed."
                            )

                    lines.extend([
                        "",
                        "Note: These flags are based on configured "
                        "detection thresholds. Verify the underlying "
                        "records and case context before drawing conclusions."
                    ])

                    answer = "\n".join(lines)

                # Return the formatted results directly without the LLM.
                return {
                    "success": True,
                    "response": {
                        "answer": answer,
                        "sources": [
                            {
                                "type": "CDR analysis",
                                "phone_number": number,
                                "analysis": analysis_type,
                            }
                        ],
                    },
                }

            elif is_network_query:
                analysis_type = "communication_network"

                network = generate_communication_network(
                    records,
                    number
                )

                nodes = network["nodes"]
                edges = network["edges"]

                #rank contacts by interaction count
                sorted_edges = sorted(
                    edges,
                    key=lambda edge: edge["total_interactions"],
                    reverse=True
                )

                #display only the 10 most frequent ones
                top_edges = sorted_edges[:10]

                #include the target and only the selected contacts
                visible_contact_ids = {
                    edge["target"] for edge in top_edges
                }

                visible_nodes = [
                    node for node in nodes
                    if node["id"] == number
                    or node["id"] in visible_contact_ids
                ]

                analysis_data = {
                    "total_nodes": len(nodes),
                    "total_contacts": len(edges),
                    "total_interactions": sum(
                        edge["total_interactions"] for edge in edges
                    ),
                    "top_contacts": top_edges,
                    "nodes": visible_nodes,
                    "edges": top_edges,
                }

            elif is_timeline_query:
                analysis_type = "communication_timeline"

                timeline = generate_communication_timeline(
                    records,
                    number
                )

             # Create a compact timeline summary for the LLM.
                if timeline:
                    first_record = timeline[0]
                    last_record = timeline[-1]

                    daily_activity = {}

                    for record in timeline:
                        date_key = record["datetime"].date().isoformat()

                        if date_key not in daily_activity:
                            daily_activity[date_key] = {
                                "total_interactions": 0,
                                "incoming_interactions": 0,
                                "outgoing_interactions": 0
                        }

                        daily_activity[date_key]["total_interactions"] += 1

                        if record["direction"] == "incoming":
                            daily_activity[date_key]["incoming_interactions"] += 1
                        else:
                            daily_activity[date_key]["outgoing_interactions"] += 1

                    # Find the busiest communication dates.
                    busiest_dates = sorted(
                        [
                            {
                                "date": date,
                                **activity
                            }
                            for date, activity in daily_activity.items()
                        ],
                        key=lambda item: item["total_interactions"],
                        reverse=True
                    )[:10]

                    analysis_data = {
                        "total_interactions": len(timeline),

                        "timeline_start": first_record["datetime"],
                        "timeline_end": last_record["datetime"],

                        "first_5_communications": timeline[:5],
                        "last_5_communications": timeline[-5:],

                        "busiest_communication_dates": busiest_dates,

                        "total_active_days": len(daily_activity)
                        }

                else:
                    analysis_data = {
                        "total_interactions": 0,
                        "timeline_start": None,
                        "timeline_end": None,
                        "first_5_communications": [],
                        "last_5_communications": [],
                        "busiest_communication_dates": [],
                        "total_active_days": 0
                    }


            elif is_interactions_query:
                analysis_type = "contact_interactions"

                analysis_data = analyze_interactions(
                    records,
                    number
                )

                # Extract the interactions from the API result.
                if isinstance(analysis_data, dict):
                    interactions = analysis_data.get(
                        "interactions",
                        analysis_data.get("contacts", None)
                    )

                    if interactions is None:
                        interactions = (
                            [analysis_data]
                            if any(
                                key in analysis_data
                                for key in [
                                    "contact_number",
                                    "total_interactions",
                                    "incoming_interactions",
                                ]
                            )
                            else []
                        )

                elif isinstance(analysis_data, list):
                    interactions = analysis_data

                else:
                    interactions = []

                # Handle empty results.
                if not interactions:
                    answer = f"No interactions were found for {number}."

                    return {
                        "success": True,
                        "response": {
                            "answer": answer,
                            "sources": [
                                {
                                    "type": "CDR analysis",
                                    "phone_number": number,
                                    "analysis": analysis_type,
                                }
                            ],
                        },
                    }

                # Sort contacts by total interactions, highest first.
                interactions = sorted(
                    interactions,
                    key=lambda item: (
                        item.get("total_interactions", 0)
                        if isinstance(item, dict)
                        else 0
                    ),
                    reverse=True,
                )

                total_contacts = len(interactions)
                limit = 10
                displayed_interactions = interactions[:limit]

                lines = [
                    f"Top {len(displayed_interactions)} contacts for {number}:",
                    f"Total contacts found: {total_contacts}",
                ]

                for index, item in enumerate(
                    displayed_interactions,
                    start=1
                ):
                    if not isinstance(item, dict):
                        continue

                    contact = str(
                        item.get("contact_number")
                        or item.get("called_number")
                        or item.get("contact")
                        or "Unknown"
                    )

                    lines.extend([
                        "",
                        f"{index}. Contact number: {contact}",
                        f"   Total interactions: {item.get('total_interactions', 0)}",
                        f"   Incoming interactions: {item.get('incoming_interactions', 0)}",
                        f"   Outgoing interactions: {item.get('outgoing_interactions', 0)}",
                        f"   Total duration: {item.get('total_duration_seconds', 0)} seconds",
                        f"   Last communication: {item.get('last_communication') or 'N/A'}",
                    ])

                if total_contacts > limit:
                    lines.append(
                        f"\nShowing {limit} of {total_contacts} contacts. "
                        "Ask about a specific contact for more details."
                    )

                answer = "\n".join(lines)

                # Return directly without asking the LLM to rewrite the data.
                return {
                    "success": True,
                    "response": {
                        "answer": answer,
                        "sources": [
                            {
                                "type": "CDR analysis",
                                "phone_number": number,
                                "analysis": analysis_type,
                            }
                        ],
                    },
                }


            elif is_frequency_query:

                frequency = analyze_communication_frequency(
                    records,
                    number
                )

                analysis_type = "communication_frequency"

                analysis_data = {
                    "total_unique_contacts": len(frequency),
                    "most_frequent_contacts": frequency[:10],
                }

            elif is_direction_query:

                analysis_type = "communication_direction"

                analysis_data = analyze_communication_direction(
                    records,
                    number
                )
            

            elif is_general_summary_query:

                # -------------------------------------------------
                # GENERAL SUMMARY
                #
                # Calculate all required statistics explicitly.
                # -------------------------------------------------

                direction = analyze_communication_direction(
                    records,
                    number
                )

                frequency = analyze_communication_frequency(
                    records,
                    number
                )

                analysis_type = "general_summary"

                analysis_data = {
                    "total_interactions": direction[
                        "total_interactions"
                    ],

                    "incoming": direction[
                        "incoming"
                    ],

                    "outgoing": direction[
                        "outgoing"
                    ],

                    "total_duration_seconds": direction[
                        "total_duration_seconds"
                    ],

                    "total_unique_contacts": len(frequency),

                    "most_frequent_contacts": frequency[:10],
                }

            else:

                # -------------------------------------------------
                # DEFAULT CDR SUMMARY
                # -------------------------------------------------

                direction = analyze_communication_direction(
                    records,
                    number
                )

                frequency = analyze_communication_frequency(
                    records,
                    number
                )

                analysis_type = "general_summary"

                analysis_data = {
                    "total_interactions": direction[
                        "total_interactions"
                    ],

                    "incoming": direction[
                        "incoming"
                    ],

                    "outgoing": direction[
                        "outgoing"
                    ],

                    "total_duration_seconds": direction[
                        "total_duration_seconds"
                    ],

                    "total_unique_contacts": len(frequency),

                    "most_frequent_contacts": frequency[:10],
                }

            # -----------------------------------------------------
            # Build CDR data for PromptService
            # -----------------------------------------------------
            cdr_data = {
                "target_number": number,
                "analysis_type": analysis_type,
                "data": analysis_data,
            }

            # -----------------------------------------------------
            # Build prompt using PromptService
            # -----------------------------------------------------
            prompt = self.prompt_service.build_cdr_prompt(
                query=query,
                cdr_data=cdr_data,
            )

            # -----------------------------------------------------
            # Generate answer
            # -----------------------------------------------------
          
            answer = self.llm_service.generate(prompt)

            response_data = {
                "answer": answer,
                "sources": [
                    {
                        "type": "CDR analysis",
                        "phone_number": number,
                        "analysis": analysis_type,
                    }
                ],
            }

            # Include graph data only for network queries.
            if analysis_type == "communication_network":
                response_data["visualization"] = {
                    "type": "communication_network",
                    "data": {
                        "nodes": analysis_data["nodes"],
                        "edges": analysis_data["edges"],
                    },
                }

            return {
                "success": True,
                "response": response_data,
            }


        # ---------------------------------------------------------
        # STATEMENT CONTRADICTION DETECTION
        # ---------------------------------------------------------
        contradiction_keywords = [
            "contradiction",
            "contradictions",
            "conflicting statement",
            "conflicting statements",
            "discrepancy",
            "discrepancies",
        ]
        is_contradiction_query = any(k in query_lower for k in contradiction_keywords) and (
            "statement" in query_lower or "witness" in query_lower or "accused" in query_lower
        )

        if is_contradiction_query:
            try:
                from app.services.statement_service import StatementService
                stmt_service = StatementService()
                contradiction_data = stmt_service.detect_contradictions()
                result = contradiction_data["result"]

                findings = result.get("findings", [])
                overall = result.get("overall_result", "NO CONTRADICTION FOUND")

                lines = [f"### Statement Contradiction Analysis: {overall}\n"]
                if findings:
                    lines.append(f"Identified {len(findings)} factual contradiction(s) across witness/suspect statements:\n")
                    for idx, f in enumerate(findings, 1):
                        lines.append(f"**{idx}. Subject: {f.get('subject', 'Unknown').title()} ({f.get('type', 'Attribute').title()})**")
                        for val in f.get("values", []):
                            stmts = ", ".join(val.get("statements", []))
                            lines.append(f"- *Claim:* \"{val.get('value')}\" (Source: {stmts})")
                        lines.append("")
                else:
                    lines.append("No explicit factual contradictions were found across the analyzed statement claims.")

                return {
                    "success": True,
                    "response": {
                        "answer": "\n".join(lines),
                        "sources": [
                            {
                                "type": "Statement Contradiction Analysis",
                                "statements": contradiction_data["analyzed_statements"]
                            }
                        ]
                    }
                }
            except Exception as e:
                print(f"Statement contradiction analysis error: {e}")

        # ---------------------------------------------------------
        # LIST ALL STATEMENTS QUERY
        # ---------------------------------------------------------
        is_list_statements = (
            any(phrase in query_lower for phrase in [
                "list statements",
                "list the statements",
                "list all statements",
                "show statements",
                "show all statements",
                "available statements",
                "what statements do we have",
                "what statements are available",
                "witness statements available",
                "all witness statements",
            ])
            and not any(k in query_lower for k in ["contradiction", "summarize", "summary"])
        )

        if is_list_statements:
            try:
                from app.services.statement_service import StatementService
                stmt_service = StatementService()
                statements = stmt_service.list_statements()
                if statements:
                    lines = [f"Found {len(statements)} statement document(s) in the system:\n"]
                    for idx, s in enumerate(statements, 1):
                        lines.append(
                            f"{idx}. **{s['name']}** (Document ID: `{s['statement_id']}`)\n"
                            f"   - **CID:** {s['cid']}\n"
                            f"   - **Occupation:** {s['occupation']}\n"
                            f"   - **Dzongkhang:** {s['dzongkhang']}\n"
                            f"   - **Phone:** {s['phone_number']}"
                        )
                    return {
                        "success": True,
                        "response": {
                            "answer": "\n".join(lines),
                            "sources": [
                                {
                                    "type": "Statement Documents",
                                    "statement_id": s["statement_id"],
                                    "name": s["name"]
                                }
                                for s in statements
                            ]
                        }
                    }
            except Exception as e:
                print(f"List statements error: {e}")

        # ---------------------------------------------------------
        # STATEMENT SUMMARIZATION QUERY
        # ---------------------------------------------------------
        is_summary_query = any(k in query_lower for k in ["summarize", "summary", "brief overview", "key points"]) and (
            "statement" in query_lower or any(n in query_lower for n in ["kinga", "prem", "tashi"])
        )

        if is_summary_query:
            try:
                from app.services.statement_service import StatementService
                stmt_service = StatementService()
                all_stmts = stmt_service.list_statements()
                target_stmt = None
                st_match = re.search(r"statement\s*[_#]?\s*(\d+)", query_lower)
                if st_match:
                    st_id = f"statement_{st_match.group(1)}"
                    target_stmt = next((s for s in all_stmts if s["statement_id"] == st_id), None)
                if not target_stmt:
                    for s in all_stmts:
                        if s["name"].lower() in query_lower:
                            target_stmt = s
                            break
                if not target_stmt and all_stmts:
                    target_stmt = all_stmts[0]

                if target_stmt:
                    summary_res = stmt_service.summarize_statement(target_stmt["statement_id"])
                    if summary_res.get("success"):
                        lines = [f"### Summary of Statement: {target_stmt['name']} ({target_stmt['statement_id']})\n"]
                        lines.append(summary_res.get("summary", ""))
                        if summary_res.get("key_points"):
                            lines.append("\n**Key Points:**")
                            for kp in summary_res["key_points"]:
                                cits = " ".join(f"[{cid}]" for cid in kp.get("sentence_ids", []))
                                lines.append(f"- {kp['point']} {cits}".strip())
                        return {
                            "success": True,
                            "response": {
                                "answer": "\n".join(lines),
                                "sources": [
                                    {
                                        "type": "Statement Summary",
                                        "statement_id": target_stmt["statement_id"],
                                        "name": target_stmt["name"]
                                    }
                                ]
                            }
                        }
            except Exception as e:
                print(f"Statement summarization error: {e}")

        # ---------------------------------------------------------
        # STATEMENT TIMELINE QUERY
        # ---------------------------------------------------------
        is_timeline_query = any(k in query_lower for k in ["timeline", "chronology", "sequence of events"]) and (
            "statement" in query_lower or "witness" in query_lower or "case" in query_lower
        )
        if is_timeline_query:
            try:
                from app.services.statement_service import StatementService
                stmt_service = StatementService()
                timeline = stmt_service.build_timeline()
                if timeline:
                    lines = ["### Chronological Case Timeline from Statements:\n"]
                    for ev in timeline:
                        dt = ev.get("date") or "(no date)"
                        tm = f" ({ev.get('time')})" if ev.get("time") else ""
                        sid = f" [{ev.get('source', {}).get('sentence_id')}]" if ev.get("source") else ""
                        lines.append(f"- **{dt}{tm}:** {ev.get('event')}{sid}")
                    return {
                        "success": True,
                        "response": {
                            "answer": "\n".join(lines),
                            "sources": [
                                {
                                    "type": "Statement Timeline",
                                    "events_count": len(timeline)
                                }
                            ]
                        }
                    }
            except Exception as e:
                print(f"Statement timeline error: {e}")

        # ---------------------------------------------------------
        # STATEMENT EVIDENCE RAG QUERY (WITH SENTENCE CITATIONS)
        # ---------------------------------------------------------
        is_statement_query = ("statement" in query_lower or any(n in query_lower for n in ["kinga norbu", "prem kr rai", "tashi topden"]))
        if is_statement_query:
            try:
                from app.services.statement_service import StatementService
                stmt_service = StatementService()
                stmt_rag = stmt_service.query_statement_evidence(query=query)
                if stmt_rag.get("success") and stmt_rag.get("answer"):
                    return {
                        "success": True,
                        "response": {
                            "answer": stmt_rag["answer"],
                            "sources": stmt_rag.get("sources", []),
                            "warnings": stmt_rag.get("warnings", []),
                            "disclaimer": stmt_rag.get("disclaimer", "")
                        }
                    }
            except Exception as e:
                print(f"Statement RAG error: {e}")

        # ---------------------------------------------------------
        # NORMAL RAG QUERY (Investigation Cases & Statements)
        # ---------------------------------------------------------
        rag_result = self.rag_service.query(query)

        return {
            "success": True,
            "response": rag_result,
        }

    def close(self):
        if self._rag_service and hasattr(self._rag_service, "close"):
            self._rag_service.close()
        if self._cdr_service and hasattr(self._cdr_service, "close"):
            self._cdr_service.close()
        if self._llm_service and hasattr(self._llm_service, "close"):
            self._llm_service.close()