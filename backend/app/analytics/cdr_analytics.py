from collections import defaultdict
from app.models.cdr import CDRRecord
from datetime import date

# mainly used for analyzing communication frequency from CDR records
def analyze_communication_frequency(
    records: list[CDRRecord],
    target_number: str
):
    contacts = defaultdict(
        lambda: {
            "contact_number": "",
            "contact_name": "unknown",
            "contact_cid": "unknown",
            "total_interactions": 0,
            "incoming_interactions": 0,
            "outgoing_interactions": 0,
            "total_duration_seconds": 0
        }
    )

    for record in records:

        # Determine whether the target made or received the communication
        if record.calling_number == target_number:
            contact_number = record.called_number
            direction = "outgoing"

        elif record.called_number == target_number:
            contact_number = record.calling_number
            direction = "incoming"

        else:
            # Ignore records that do not involve the target
            continue

        contact = contacts[contact_number]

        contact["contact_number"] = contact_number

        # Store available identity information
        if direction == "outgoing":
            contact["contact_name"] = record.called_party_name
            contact["contact_cid"] = record.called_party_cid

        contact["total_interactions"] += 1
        contact["total_duration_seconds"] += record.duration_seconds

        if direction == "outgoing":
            contact["outgoing_interactions"] += 1
        else:
            contact["incoming_interactions"] += 1

    # Convert dictionary to list
    results = list(contacts.values())

    # Most frequent contacts first
    results.sort(
        key=lambda x: x["total_interactions"],
        reverse=True
    )

    return results

# how much communication was incoming vs outgoing for a given number
def analyze_communication_direction(
    records: list[CDRRecord],
    target_number: str
):
    incoming_count = 0
    outgoing_count = 0

    incoming_duration = 0
    outgoing_duration = 0

    for record in records:

        if record.calling_number == target_number:
            # Target made the call
            outgoing_count += 1
            outgoing_duration += record.duration_seconds

        elif record.called_number == target_number:
            # Target received the call
            incoming_count += 1
            incoming_duration += record.duration_seconds

    total_count = incoming_count + outgoing_count
    total_duration = incoming_duration + outgoing_duration

    return {
        "total_interactions": total_count,
        "incoming": {
            "count": incoming_count,
            "duration_seconds": incoming_duration
        },
        "outgoing": {
            "count": outgoing_count,
            "duration_seconds": outgoing_duration
        },
        "total_duration_seconds": total_duration
    }

#filter CDR records by date
def filter_records_by_date(
    records: list[CDRRecord],
    start_date: date,
    end_date: date
):
    filtered_records = []

    for record in records:
        record_date = record.datetime.date()

        if start_date <= record_date <= end_date:
            filtered_records.append(record)

    return filtered_records

#period based communication statistics for a given number
def analyze_period_statistics(
    records: list[CDRRecord],
    target_number: str,
    start_date: date,
    end_date: date
):
    # First, filter records to the requested period
    filtered_records = filter_records_by_date(
        records,
        start_date,
        end_date
    )

    # Analyze incoming and outgoing communication
    statistics = analyze_communication_direction(
        filtered_records,
        target_number
    )

    return {
        "start_date": start_date,
        "end_date": end_date,
        "statistics": statistics
    }

# Generate a chronological timeline of communications for a given number
def generate_communication_timeline(
    records: list[CDRRecord],
    target_number: str,
    start_date: date | None = None,
    end_date: date | None = None
):
    timeline = []

    for record in records:

        # Identify communication direction and contact
        if record.calling_number == target_number:
            direction = "outgoing"
            contact_number = record.called_number
            contact_name = record.called_party_name
            contact_cid = record.called_party_cid

        elif record.called_number == target_number:
            direction = "incoming"
            contact_number = record.calling_number

            # The source record identifies the called party,
            # which is the target in an incoming communication.
            contact_name = "unknown"
            contact_cid = "unknown"

        else:
            continue

        record_date = record.datetime.date()

        # Apply optional date filters
        if start_date and record_date < start_date:
            continue

        if end_date and record_date > end_date:
            continue

        timeline.append({
            "datetime": record.datetime,
            "contact_number": contact_number,
            "contact_name": contact_name,
            "contact_cid": contact_cid,
            "direction": direction,
            "service": record.service,
            "duration": record.duration,
            "duration_seconds": record.duration_seconds
        })

    # Sort chronologically, earliest communication first
    timeline.sort(key=lambda item: item["datetime"])

    return timeline

# Analyze interactions with each contact for a given number
def analyze_interactions(
    records: list[CDRRecord],
    target_number: str
):
    interactions = {}

    for record in records:

        # Determine the contact and communication direction
        if record.calling_number == target_number:
            contact_number = record.called_number
            direction = "outgoing"

        elif record.called_number == target_number:
            contact_number = record.calling_number
            direction = "incoming"

        else:
            continue

        # Create contact entry if it does not exist
        if contact_number not in interactions:
            interactions[contact_number] = {
                "contact_number": contact_number,
                "total_interactions": 0,
                "incoming_interactions": 0,
                "outgoing_interactions": 0,
                "total_duration_seconds": 0,
                "first_communication": record.datetime,
                "last_communication": record.datetime
            }

        contact = interactions[contact_number]

        # Interaction count
        contact["total_interactions"] += 1

        # Direction
        if direction == "incoming":
            contact["incoming_interactions"] += 1
        else:
            contact["outgoing_interactions"] += 1

        # Duration
        contact["total_duration_seconds"] += record.duration_seconds

        # First communication
        if record.datetime < contact["first_communication"]:
            contact["first_communication"] = record.datetime

        # Last communication
        if record.datetime > contact["last_communication"]:
            contact["last_communication"] = record.datetime

    # Calculate average duration
    results = []

    for contact in interactions.values():

        if contact["total_interactions"] > 0:
            contact["average_duration_seconds"] = round(
                contact["total_duration_seconds"]
                / contact["total_interactions"],
                2
            )
        else:
            contact["average_duration_seconds"] = 0

        results.append(contact)

    # Most frequent contacts first
    results.sort(
        key=lambda x: x["total_interactions"],
        reverse=True
    )

    return results

# IRREGULAR SUSPICIOUS COMMUNICATION BEHAVIOUR AND IRREGULAR CONTACT PATTERN
# High frequency contacts, one sided communication, repeated short calls and unusual communication hours
def detect_irregular_patterns(
    records: list[CDRRecord],
    target_number: str
):
    interactions = analyze_interactions(
        records,
        target_number
    )

    patterns = []

    if not interactions:
        return patterns

    total_interactions = sum(
        contact["total_interactions"]
        for contact in interactions
    )

    average_interactions = (
        total_interactions / len(interactions)
    )

    for contact in interactions:
        contact_number = contact["contact_number"]
        total = contact["total_interactions"]
        incoming = contact["incoming_interactions"]
        outgoing = contact["outgoing_interactions"]

        # 1. HIGH-FREQUENCY CONTACT

        # Flag contacts with at least 3x the average interactions
        if (
            average_interactions > 0
            and total >= average_interactions * 3
        ):
            patterns.append({
                "pattern_type": "HIGH_FREQUENCY",
                "contact_number": contact_number,
                "description": (
                    "This contact has a substantially higher "
                    "communication frequency than the average contact."
                ),
                "evidence": {
                    "total_interactions": total,
                    "average_contact_interactions": round(
                        average_interactions,
                        2
                    )
                }
            })

        # 2. ONE-SIDED COMMUNICATION
        # Only evaluate contacts with at least 5 interactions with the contact
        if total >= 5:
            incoming_ratio = incoming / total
            outgoing_ratio = outgoing / total

            # Mostly incoming
            if incoming_ratio >= 0.80:
                patterns.append({
                    "pattern_type": "ONE_SIDED_INCOMING",
                    "contact_number": contact_number,
                    "description": (
                        "Communication with this contact is strongly "
                        "dominated by incoming interactions."
                    ),
                    "evidence": {
                        "total_interactions": total,
                        "incoming_interactions": incoming,
                        "outgoing_interactions": outgoing,
                        "incoming_ratio": round(
                            incoming_ratio,
                            2
                        )
                    }
                })

            # Mostly outgoing
            elif outgoing_ratio >= 0.80:
                patterns.append({
                    "pattern_type": "ONE_SIDED_OUTGOING",
                    "contact_number": contact_number,
                    "description": (
                        "Communication with this contact is strongly "
                        "dominated by outgoing interactions."
                    ),
                    "evidence": {
                        "total_interactions": total,
                        "incoming_interactions": incoming,
                        "outgoing_interactions": outgoing,
                        "outgoing_ratio": round(
                            outgoing_ratio,
                            2
                        )
                    }
                })

        # 3. REPEATED SHORT CALLS

        # Only evaluate contacts with at least 5 interactions
        if total >= 5:

            short_call_count = 0

            for record in records:

                # Check whether this record belongs to this contact
                if (
                    record.calling_number == target_number
                    and record.called_number == contact_number
                ) or (
                    record.called_number == target_number
                    and record.calling_number == contact_number
                ):

                    # Short call = 10 seconds or less
                    if record.duration_seconds <= 10:
                        short_call_count += 1

            short_call_ratio = short_call_count / total

            # Flag if at least 60% of calls are short
            if short_call_ratio >= 0.60:
                patterns.append({
                    "pattern_type": "REPEATED_SHORT_CALLS",
                    "contact_number": contact_number,
                    "description": (
                        "A high proportion of communications with "
                        "this contact consist of very short calls."
                    ),
                    "evidence": {
                        "total_interactions": total,
                        "short_call_count": short_call_count,
                        "short_call_ratio": round(
                            short_call_ratio,
                            2
                        ),
                        "short_call_threshold_seconds": 10
                    }
                })

        # 4. UNUSUAL COMMUNICATION HOURS

        late_night_count = 0

        for record in records:

            # Check whether this record belongs to this contact
            if (
                record.calling_number == target_number
                and record.called_number == contact_number
            ) or (
                record.called_number == target_number
                and record.calling_number == contact_number
            ):

                hour = record.datetime.hour

                # Unusual hours:
                # 22:00 - 23:59
                # 00:00 - 05:59
                if hour >= 22 or hour < 6:
                    late_night_count += 1

        if total > 0:

            unusual_hour_ratio = late_night_count / total

            # Flag when at least 20% occur during unusual hours
            if unusual_hour_ratio >= 0.20:
                patterns.append({
                    "pattern_type": "UNUSUAL_COMMUNICATION_HOURS",
                    "contact_number": contact_number,
                    "description": (
                        "A notable proportion of communications with "
                        "this contact occurred during late-night or "
                        "early-morning hours."
                    ),
                    "evidence": {
                        "total_interactions": total,
                        "unusual_hour_interactions": late_night_count,
                        "unusual_hour_ratio": round(
                            unusual_hour_ratio,
                            2
                        ),
                        "unusual_hours": "22:00-06:00"
                    }
                })

        # 5. COMMUNICATION SPIKE

        # Store the number of interactions for each day
        daily_interactions = defaultdict(int)

        for record in records:

            # Check whether this record belongs to this contact
            if (
                record.calling_number == target_number
                and record.called_number == contact_number
            ) or (
                record.called_number == target_number
                and record.calling_number == contact_number
            ):

                record_date = record.datetime.date()

                daily_interactions[record_date] += 1

        # Only analyze contacts with multiple active days
        if len(daily_interactions) >= 2:

            total_contact_interactions = sum(
                daily_interactions.values()
            )

            average_daily_interactions = (
                total_contact_interactions
                / len(daily_interactions)
            )

            # Find unusually high-activity days
            for communication_date, daily_count in daily_interactions.items():

                if (
                    average_daily_interactions > 0
                    and daily_count >= average_daily_interactions * 3
                    and daily_count >= 3
                ):
                    patterns.append({
                        "pattern_type": "COMMUNICATION_SPIKE",
                        "contact_number": contact_number,
                        "description": (
                            "This contact shows a substantially higher "
                            "number of interactions on a particular day "
                            "compared with its average daily activity."
                        ),
                        "evidence": {
                            "date": communication_date,
                            "interactions_on_date": daily_count,
                            "average_daily_interactions": round(
                                average_daily_interactions,
                                2
                            ),
                            "spike_ratio": round(
                                daily_count
                                / average_daily_interactions,
                                2
                            )
                        }
                    })
    return patterns

#Network data generation
def generate_communication_network(
    records: list[CDRRecord],
    target_number: str
):
    nodes = {}
    edges = {}

    # 1. ADD TARGET NODE

    nodes[target_number] = {
        "id": target_number,
        "label": target_number,
        "type": "target"
    }

    # 2. PROCESS COMMUNICATION RECORDS

    for record in records:

        # Determine communication direction

        if record.calling_number == target_number:
            contact_number = record.called_number
            direction = "outgoing"

            contact_name = record.called_party_name
            contact_cid = record.called_party_cid

        elif record.called_number == target_number:
            contact_number = record.calling_number
            direction = "incoming"

            contact_name = "unknown"
            contact_cid = "unknown"

        else:
            continue

        if not contact_number:
            continue

        # Add contact node

        if contact_number not in nodes:
            nodes[contact_number] = {
                "id": contact_number,
                "label": contact_number,
                "type": "contact",
                "name": contact_name,
                "cid": contact_cid
            }

        # Create edge ID

        edge_id = f"{target_number}-{contact_number}"

        # Create edge if it does not exist

        if edge_id not in edges:
            edges[edge_id] = {
                "id": edge_id,
                "source": target_number,
                "target": contact_number,
                "total_interactions": 0,
                "incoming_interactions": 0,
                "outgoing_interactions": 0,
                "total_duration_seconds": 0,
                "first_communication": record.datetime,
                "last_communication": record.datetime
            }

        edge = edges[edge_id]

        # Update interaction statistics

        edge["total_interactions"] += 1

        edge["total_duration_seconds"] += (
            record.duration_seconds
        )

        if direction == "incoming":
            edge["incoming_interactions"] += 1
        else:
            edge["outgoing_interactions"] += 1

        # Update first communication

        if record.datetime < edge["first_communication"]:
            edge["first_communication"] = record.datetime

        # Update last communication

        if record.datetime > edge["last_communication"]:
            edge["last_communication"] = record.datetime

    # 3. CALCULATE AVERAGE DURATION

    for edge in edges.values():

        if edge["total_interactions"] > 0:
            edge["average_duration_seconds"] = round(
                edge["total_duration_seconds"]
                / edge["total_interactions"],
                2
            )
        else:
            edge["average_duration_seconds"] = 0

    # 4. RETURN NETWORK DATA

    return {
        "nodes": list(nodes.values()),
        "edges": list(edges.values())
    }