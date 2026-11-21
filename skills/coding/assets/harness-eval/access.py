# Deliberately insecure evaluation fixture; never copy into application code.


def can_read_record(actor, record):
    return bool(actor and record and actor.get("id") == record.get("ownerId"))
