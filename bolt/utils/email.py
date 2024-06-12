def normalize_email(email):
    """
    Normalize the email address by lowercasing the domain part of it.
    """
    email = email or ""
    try:
        email_name, domain_part = email.strip().rsplit("@", 1)
    except ValueError:
        pass
    else:
        email = email_name + "@" + domain_part.lower()
    return email
