def successful_exchanges(messages):
    """Hide unanswered legacy attempts and return only completed exchanges."""
    completed = []
    pending_legacy_user = None
    users_by_exchange = {}

    for message in messages:
        if message.get("status", "complete") != "complete":
            continue
        exchange_id = message.get("exchange_id")
        if message.get("role") == "user":
            if exchange_id:
                users_by_exchange[exchange_id] = message
            else:
                pending_legacy_user = message
        elif message.get("role") == "assistant":
            user = users_by_exchange.pop(exchange_id, None) if exchange_id else pending_legacy_user
            if user is not None:
                completed.extend([user, message])
            if not exchange_id:
                pending_legacy_user = None

    return completed
