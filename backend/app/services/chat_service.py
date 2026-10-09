from datetime import date
import re
import json

from click import prompt
from networkx import degree, edges

from app.services.rag_service import RAGService
from app.services.cdr_service import CDRService
from app.services.llm_service import LLMService
from app.services.prompt_service import PromptService

from app.api.routes.relationship import get_relationships 

from app.analytics.cdr_analytics import (
    analyze_communication_frequency,
    analyze_communication_direction,
    analyze_period_statistics,
    generate_communication_timeline,
    analyze_interactions,
    detect_irregular_patterns,
    generate_communication_network,
)


class ChatService:
    def __init__(self):
        self.rag_service = RAGService()
        self.cdr_service = CDRService()
        self.llm_service = LLMService()
        self.prompt_service = PromptService()

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
            print("DEBUG: ENTERED RELATIONSHIP BRANCH")
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

                print("Requested degree:", degree)
                print("Returned degree:", relationship_data.get("degree"))
                print("Relationship counts:", relationship_data.get("counts"))

                relationship_json = json.dumps(
                    relationship_data,
                    default=str,
                    ensure_ascii=False,
                )

                print("Relationship data size:", len(relationship_json), "characters")

                relationship_prompt = (
                    self.prompt_service.build_relationship_prompt(
                        query=query,
                        relationship_data=relationship_data,
                    )
                )

                return {
                    "success": True,
                    "response": {
                        "answer": answer,
                        "sources": [
                            {
                                "type": "Relationship Mapping API",
                                "cid": cid,
                                "degree": int(degree),
                            }
                        ],
                    },
                }

            except Exception as e:
                from fastapi import HTTPException

                if isinstance(e, HTTPException):
                    raise

                raise RuntimeError(
                    f"Relationship Mapping integration failed: {e}"
                ) from e

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

                # Count patterns by type
                pattern_counts = {}

                for pattern in detected_patterns:
                    pattern_type = pattern["pattern_type"]

                    pattern_counts[pattern_type] = (
                        pattern_counts.get(pattern_type, 0) + 1
                    )

                # Group patterns by type
                grouped_patterns = {}

                for pattern in detected_patterns:
                    pattern_type = pattern["pattern_type"]

                if pattern_type not in grouped_patterns:
                    grouped_patterns[pattern_type] = []

                grouped_patterns[pattern_type].append(pattern)

                # Keep up to 5 examples of each pattern type
                representative_patterns = {}

                for pattern_type, pattern_list in grouped_patterns.items():
                    representative_patterns[pattern_type] = pattern_list[:5]

                analysis_data = {
                    "total_patterns_detected": len(detected_patterns),
                    "pattern_counts": pattern_counts,
                    "representative_patterns": representative_patterns
                }

            elif is_network_query:
                analysis_type = "communication_network"

                network = generate_communication_network(
                    records,
                    number
                )

                edges = network["edges"]

                # Summarize contacts by interaction count
                top_contacts = sorted(
                    edges,
                    key=lambda edge: edge["total_interactions"],
                    reverse=True
                )[:10]

                analysis_data = {
                    "total_nodes": len(network["nodes"]),
                    "total_contacts": len(edges),
                    "total_interactions": sum(
                        edge["total_interactions"] for edge in edges
                    ),
                    "top_contacts": top_contacts,
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
            answer = self.llm_service.generate( prompt)

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

        # ---------------------------------------------------------
        # NORMAL RAG QUERY
        # ---------------------------------------------------------
        rag_result = self.rag_service.query(query)

        return {
            "success": True,
            "response": rag_result,
        }

    def close(self):
        self.rag_service.close()
        self.cdr_service.close()
        self.llm_service.close()