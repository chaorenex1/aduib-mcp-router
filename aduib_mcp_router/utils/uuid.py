import secrets
import string


def random_uuid() -> str:
    """Generate a random UUID."""
    import uuid
    return str(uuid.uuid4())


def message_uuid() -> str:
    """Generate a UUID for a message."""
    import uuid
    return f"chatcmpl-{str(uuid.uuid4().hex)}"

def trace_uuid() -> str:
    """Generate a UUID for a trace."""
    import uuid
    return f"trace-{str(uuid.uuid4().hex)}"

def generate_string(n):
    letters_digits = string.ascii_letters + string.digits
    result = ""
    for i in range(n):
        result += secrets.choice(letters_digits)

    return result