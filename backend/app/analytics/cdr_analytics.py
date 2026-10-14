from collections import defaultdict
from datetime import date, datetime, time
from typing import Any

from app.models.cdr import CDRRecord

def _contact_for_record(record: CDRRecord, target_number: str):
    """Return contact details and direction when a record involves target."""
    if record.calling_number == target_number:
        return {
            "contact_number": record.called_number,
            "contact_name": getattr(record, "called_party_name", None) or "unknown",
            "contact_cid": getattr(record, "called_party_cid", None) or "unknown",
            "direction": "outgoing",
        }
    if record.called_number == target_number:
        return {
            "contact_number": record.calling_number,
            "contact_name": "unknown",
            "contact_cid": "unknown",
            "direction": "incoming",
        }
    return None


def filter_records(
    records: list[CDRRecord],
    target_number: str,
    start_date: date | None = None,
    end_date: date | None = None,
    start_time: time | None = None,
    end_time: time | None = None,
    direction: str | None = None,
    contact_number: str | None = None,
) -> list[CDRRecord]:
    """Filter records by target, date, time-of-day, direction, and contact.

    Time windows crossing midnight (e.g. 22:00-02:00) are supported.
    """
    filtered = []
    for record in records:
        contact = _contact_for_record(record, target_number)
        if contact is None:
            continue

        dt = record.datetime
        record_date = dt.date()
        record_time = dt.time().replace(tzinfo=None)

        if start_date and record_date < start_date:
            continue
        if end_date and record_date > end_date:
            continue
        if direction and contact["direction"] != direction:
            continue
        if contact_number and contact["contact_number"] != contact_number:
            continue

        if start_time is not None and end_time is not None:
            if start_time < end_time:
                if not (start_time <= record_time < end_time):
                    continue
            elif start_time > end_time:
                if not (record_time >= start_time or record_time < end_time):
                    continue
            else:
                # Equal times are ambiguous; reject at route validation.
                continue
        elif start_time is not None:
            if record_time < start_time:
                continue
        elif end_time is not None:
            if record_time >= end_time:
                continue

        filtered.append(record)

    return filtered


def analyze_communication_direction(
    records: list[CDRRecord], target_number: str
) -> dict[str, Any]:
    incoming_count = outgoing_count = 0
    incoming_duration = outgoing_duration = 0

    for record in records:
        duration = int(getattr(record, "duration_seconds", 0) or 0)
        if record.calling_number == target_number:
            outgoing_count += 1
            outgoing_duration += duration
        elif record.called_number == target_number:
            incoming_count += 1
            incoming_duration += duration

    return {
        "total_interactions": incoming_count + outgoing_count,
        "incoming": {
            "count": incoming_count,
            "duration_seconds": incoming_duration,
        },
        "outgoing": {
            "count": outgoing_count,
            "duration_seconds": outgoing_duration,
        },
        "total_duration_seconds": incoming_duration + outgoing_duration,
    }


def analyze_interactions(
    records: list[CDRRecord], target_number: str
) -> list[dict[str, Any]]:
    contacts: dict[str, dict[str, Any]] = {}

    for record in records:
        info = _contact_for_record(record, target_number)
        if not info or not info["contact_number"]:
            continue

        number = info["contact_number"]
        dt = record.datetime
        duration = int(getattr(record, "duration_seconds", 0) or 0)

        if number not in contacts:
            contacts[number] = {
                "contact_number": number,
                "contact_name": info["contact_name"],
                "contact_cid": info["contact_cid"],
                "total_interactions": 0,
                "incoming_interactions": 0,
                "outgoing_interactions": 0,
                "total_duration_seconds": 0,
                "first_communication": dt,
                "last_communication": dt,
                "_duration_sum": 0,
            }

        item = contacts[number]
        # Prefer an identified name/CID if one becomes available later.
        if item["contact_name"] == "unknown" and info["contact_name"] != "unknown":
            item["contact_name"] = info["contact_name"]
        if item["contact_cid"] == "unknown" and info["contact_cid"] != "unknown":
            item["contact_cid"] = info["contact_cid"]

        item["total_interactions"] += 1
        item["total_duration_seconds"] += duration
        item["_duration_sum"] += duration

        if info["direction"] == "incoming":
            item["incoming_interactions"] += 1
        else:
            item["outgoing_interactions"] += 1

        item["first_communication"] = min(item["first_communication"], dt)
        item["last_communication"] = max(item["last_communication"], dt)

    results = []
    for item in contacts.values():
        count = item["total_interactions"]
        item["average_duration_seconds"] = round(item["_duration_sum"] / count, 2) if count else 0
        item.pop("_duration_sum", None)
        results.append(item)

    return sorted(results, key=lambda x: x["total_interactions"], reverse=True)


def analyze_communication_frequency(
    records: list[CDRRecord], target_number: str
) -> list[dict[str, Any]]:
    """Compatibility wrapper: frequency now uses the unified contact analysis."""
    return analyze_interactions(records, target_number)


def analyze_period_statistics(
    records: list[CDRRecord],
    target_number: str,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    filtered = [
        r for r in records
        if start_date <= r.datetime.date() <= end_date
        and (r.calling_number == target_number or r.called_number == target_number)
    ]
    interactions = analyze_interactions(filtered, target_number)
    return {
        "start_date": start_date,
        "end_date": end_date,
        "statistics": analyze_communication_direction(filtered, target_number),
        "total_contacts": len(interactions),
        "contacts": interactions,
    }


def generate_communication_timeline(
    records: list[CDRRecord],
    target_number: str,
) -> list[dict[str, Any]]:
    timeline = []
    for record in records:
        info = _contact_for_record(record, target_number)
        if not info:
            continue
        timeline.append({
            "datetime": record.datetime,
            "contact_number": info["contact_number"],
            "contact_name": info["contact_name"],
            "contact_cid": info["contact_cid"],
            "direction": info["direction"],
            "service": getattr(record, "service", None),
            "duration": getattr(record, "duration", None),
            "duration_seconds": int(getattr(record, "duration_seconds", 0) or 0),
        })
    return sorted(timeline, key=lambda item: item["datetime"])


def detect_irregular_patterns(
    records: list[CDRRecord],
    target_number: str,
) -> list[dict[str, Any]]:
    """Detect six rule-based patterns; flags are leads for review, not proof."""
    contacts = analyze_interactions(records, target_number)
    if not contacts:
        return []

    patterns: list[dict[str, Any]] = []
    average_interactions = sum(c["total_interactions"] for c in contacts) / len(contacts)

    for contact in contacts:
        number = contact["contact_number"]
        total = contact["total_interactions"]
        incoming = contact["incoming_interactions"]
        outgoing = contact["outgoing_interactions"]
        related = [
            r for r in records
            if (
                r.calling_number == target_number and r.called_number == number
            ) or (
                r.called_number == target_number and r.calling_number == number
            )
        ]

        # 1. High-frequency contact
        if average_interactions > 0 and total >= average_interactions * 3:
            patterns.append({
                "pattern_type": "HIGH_FREQUENCY",
                "contact_number": number,
                "description": "Communication frequency is substantially above the average contact.",
                "evidence": {
                    "total_interactions": total,
                    "average_contact_interactions": round(average_interactions, 2),
                },
            })

        # 2 and 3. One-sided incoming / outgoing (kept as separate patterns)
        if total >= 5:
            incoming_ratio = incoming / total
            outgoing_ratio = outgoing / total
            if incoming_ratio >= 0.80:
                patterns.append({
                    "pattern_type": "ONE_SIDED_INCOMING",
                    "contact_number": number,
                    "description": "Communication is strongly dominated by incoming interactions.",
                    "evidence": {
                        "total_interactions": total,
                        "incoming_interactions": incoming,
                        "outgoing_interactions": outgoing,
                        "incoming_ratio": round(incoming_ratio, 2),
                    },
                })
            if outgoing_ratio >= 0.80:
                patterns.append({
                    "pattern_type": "ONE_SIDED_OUTGOING",
                    "contact_number": number,
                    "description": "Communication is strongly dominated by outgoing interactions.",
                    "evidence": {
                        "total_interactions": total,
                        "incoming_interactions": incoming,
                        "outgoing_interactions": outgoing,
                        "outgoing_ratio": round(outgoing_ratio, 2),
                    },
                })

        # 4. Repeated short calls
        if total >= 5:
            short_count = sum(
                1 for r in related
                if int(getattr(r, "duration_seconds", 0) or 0) <= 10
            )
            ratio = short_count / total
            if ratio >= 0.60:
                patterns.append({
                    "pattern_type": "REPEATED_SHORT_CALLS",
                    "contact_number": number,
                    "description": "A high proportion of communications are 10 seconds or shorter.",
                    "evidence": {
                        "total_interactions": total,
                        "short_call_count": short_count,
                        "short_call_ratio": round(ratio, 2),
                        "short_call_threshold_seconds": 10,
                    },
                })

        # 5. Unusual hours: preserve existing default definition, 22:00-06:00
        late_count = sum(
            1 for r in related
            if r.datetime.hour >= 22 or r.datetime.hour < 6
        )
        late_ratio = late_count / total if total else 0
        if late_ratio >= 0.20:
            patterns.append({
                "pattern_type": "UNUSUAL_COMMUNICATION_HOURS",
                "contact_number": number,
                "description": "A notable proportion of communications occurred between 22:00 and 06:00.",
                "evidence": {
                    "total_interactions": total,
                    "unusual_hour_interactions": late_count,
                    "unusual_hour_ratio": round(late_ratio, 2),
                    "unusual_hours": "22:00-06:00",
                },
            })

        # 6. Communication spike
        daily = defaultdict(int)
        for r in related:
            daily[r.datetime.date()] += 1
        if len(daily) >= 2:
            avg_daily = sum(daily.values()) / len(daily)
            for day, count in sorted(daily.items()):
                if avg_daily > 0 and count >= avg_daily * 3 and count >= 3:
                    patterns.append({
                        "pattern_type": "COMMUNICATION_SPIKE",
                        "contact_number": number,
                        "description": "Communication activity on this date is substantially above this contact's average active-day activity.",
                        "evidence": {
                            "date": day,
                            "interactions_on_date": count,
                            "average_daily_interactions": round(avg_daily, 2),
                            "spike_ratio": round(count / avg_daily, 2),
                        },
                    })

    return patterns


def generate_communication_network(
    records: list[CDRRecord], target_number: str
) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {
        target_number: {"id": target_number, "label": target_number, "type": "target"}
    }
    edges: dict[str, dict[str, Any]] = {}

    for record in records:
        info = _contact_for_record(record, target_number)
        if not info or not info["contact_number"]:
            continue

        number = info["contact_number"]
        nodes.setdefault(number, {
            "id": number,
            "label": number,
            "type": "contact",
            "name": info["contact_name"],
            "cid": info["contact_cid"],
        })

        edge_id = f"{target_number}-{number}"
        if edge_id not in edges:
            edges[edge_id] = {
                "id": edge_id,
                "source": target_number,
                "target": number,
                "total_interactions": 0,
                "incoming_interactions": 0,
                "outgoing_interactions": 0,
                "total_duration_seconds": 0,
                "first_communication": record.datetime,
                "last_communication": record.datetime,
            }

        edge = edges[edge_id]
        edge["total_interactions"] += 1
        edge["total_duration_seconds"] += int(getattr(record, "duration_seconds", 0) or 0)
        if info["direction"] == "incoming":
            edge["incoming_interactions"] += 1
        else:
            edge["outgoing_interactions"] += 1
        edge["first_communication"] = min(edge["first_communication"], record.datetime)
        edge["last_communication"] = max(edge["last_communication"], record.datetime)

    for edge in edges.values():
        count = edge["total_interactions"]
        edge["average_duration_seconds"] = round(edge["total_duration_seconds"] / count, 2) if count else 0

    return {"nodes": list(nodes.values()), "edges": list(edges.values())}
