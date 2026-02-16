"""Identity verification via external providers (Persona, ID.me).

Charter supports multiple verification methods with different trust levels.
This module handles the external provider flow:

1. CLI creates a verification request
2. Opens browser for user to complete verification
3. Polls for completion
4. Records verified identity in the hash chain

Providers:
    persona: Government ID + selfie. Free tier: 500/month.
    id_me: Government-level (NIST IAL2). Requires enterprise contract.

The verification result upgrades the trust level of the Charter identity
and triggers authorship transfer for all prior hash chain entries.
"""

import json
import os
import time
import webbrowser

VERIFY_CONFIG_FILE = "verify_config.json"


def get_verify_config_path():
    home = os.path.expanduser("~")
    return os.path.join(home, ".charter", VERIFY_CONFIG_FILE)


def load_verify_config():
    path = get_verify_config_path()
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        return json.load(f)


def save_verify_config(config):
    path = get_verify_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(config, f, indent=2)


def configure_persona(api_key, template_id=None, environment="sandbox"):
    """Save Persona API credentials.

    api_key: Your Persona API key (starts with persona_sandbox_ or persona_)
    template_id: Inquiry template ID (from Persona dashboard)
    environment: 'sandbox' or 'production'
    """
    config = load_verify_config() or {}
    config["persona"] = {
        "api_key": api_key,
        "template_id": template_id,
        "environment": environment,
        "configured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    save_verify_config(config)
    return config["persona"]


def configure_idme(client_id, client_secret, redirect_uri="http://localhost:8765/callback",
                   environment="sandbox"):
    """Save ID.me OAuth credentials.

    client_id: From ID.me developer portal
    client_secret: From ID.me developer portal
    redirect_uri: Callback URL for OAuth flow
    environment: 'sandbox' or 'production'
    """
    config = load_verify_config() or {}
    config["id_me"] = {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "environment": environment,
        "configured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    save_verify_config(config)
    return config["id_me"]


def create_persona_inquiry(reference_id=None):
    """Create a Persona verification inquiry and return the one-time link.

    Returns dict with inquiry_id, one_time_link, and status.
    """
    try:
        import urllib.request
        import urllib.error
    except ImportError:
        raise RuntimeError("urllib required for API calls")

    config = load_verify_config()
    if not config or "persona" not in config:
        raise RuntimeError(
            "Persona not configured. Run 'charter verify configure persona' first."
        )

    persona = config["persona"]
    api_key = persona["api_key"]
    template_id = persona.get("template_id")

    # Build request body
    body = {
        "data": {
            "attributes": {}
        }
    }
    if template_id:
        body["data"]["attributes"]["inquiry-template-id"] = template_id
    if reference_id:
        body["data"]["attributes"]["reference-id"] = reference_id

    request_data = json.dumps(body).encode()

    req = urllib.request.Request(
        "https://withpersona.com/api/v1/inquiries",
        data=request_data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Persona-Version": "2023-01-05",
            "Key-Inflection": "camel",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else str(e)
        raise RuntimeError(f"Persona API error ({e.code}): {error_body}")

    inquiry_id = result.get("data", {}).get("id")
    meta = result.get("meta", {})
    one_time_link = meta.get("oneTimeLink") or meta.get("one-time-link")
    one_time_link_short = meta.get("oneTimeLinkShort") or meta.get("one-time-link-short")

    return {
        "inquiry_id": inquiry_id,
        "one_time_link": one_time_link,
        "one_time_link_short": one_time_link_short,
        "status": result.get("data", {}).get("attributes", {}).get("status", "pending"),
    }


def check_persona_inquiry(inquiry_id):
    """Check the status of a Persona inquiry.

    Returns the inquiry data including status and verified fields.
    """
    import urllib.request
    import urllib.error

    config = load_verify_config()
    if not config or "persona" not in config:
        raise RuntimeError("Persona not configured.")

    api_key = config["persona"]["api_key"]

    req = urllib.request.Request(
        f"https://withpersona.com/api/v1/inquiries/{inquiry_id}",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Persona-Version": "2023-01-05",
            "Key-Inflection": "camel",
        },
    )

    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else str(e)
        raise RuntimeError(f"Persona API error ({e.code}): {error_body}")

    attrs = result.get("data", {}).get("attributes", {})
    fields = attrs.get("fields", {})

    return {
        "inquiry_id": inquiry_id,
        "status": attrs.get("status", "unknown"),
        "name_first": fields.get("nameFirst", {}).get("value")
            if isinstance(fields.get("nameFirst"), dict) else fields.get("nameFirst"),
        "name_last": fields.get("nameLast", {}).get("value")
            if isinstance(fields.get("nameLast"), dict) else fields.get("nameLast"),
        "email": fields.get("emailAddress", {}).get("value")
            if isinstance(fields.get("emailAddress"), dict) else fields.get("emailAddress"),
        "birthdate": fields.get("birthdate", {}).get("value")
            if isinstance(fields.get("birthdate"), dict) else fields.get("birthdate"),
        "completed_at": attrs.get("completedAt"),
        "created_at": attrs.get("createdAt"),
    }


def poll_persona_inquiry(inquiry_id, timeout_seconds=300, poll_interval=5):
    """Poll a Persona inquiry until it reaches a terminal state.

    Terminal states: completed, approved, declined, failed, expired.
    Returns the final inquiry data.
    """
    terminal_states = {"completed", "approved", "declined", "failed", "expired", "needs_review"}
    start = time.time()

    while time.time() - start < timeout_seconds:
        result = check_persona_inquiry(inquiry_id)
        status = result.get("status", "unknown")

        if status in terminal_states:
            return result

        time.sleep(poll_interval)

    raise TimeoutError(
        f"Verification did not complete within {timeout_seconds} seconds. "
        f"Last status: {result.get('status', 'unknown')}. "
        f"Inquiry ID: {inquiry_id}. You can check later with "
        f"'charter verify check {inquiry_id}'."
    )


def run_persona_verification(reference_id=None):
    """Full Persona verification flow for CLI.

    1. Creates inquiry
    2. Opens browser
    3. Polls for completion
    4. Returns verified identity data
    """
    from charter.identity import load_identity

    identity = load_identity()
    if not identity:
        raise RuntimeError("No identity found. Run 'charter init' first.")

    ref_id = reference_id or identity["public_id"][:16]

    print("Creating verification inquiry...")
    inquiry = create_persona_inquiry(reference_id=ref_id)
    inquiry_id = inquiry["inquiry_id"]

    link = inquiry.get("one_time_link") or inquiry.get("one_time_link_short")
    if not link:
        raise RuntimeError(f"No verification link returned. Inquiry ID: {inquiry_id}")

    print(f"\nInquiry created: {inquiry_id}")
    print(f"Verification link: {link}")
    print("\nOpening browser for identity verification...")
    print("Complete the verification in your browser.")
    print("This window will wait for you to finish.\n")

    webbrowser.open(link)

    print("Waiting for verification to complete (timeout: 5 minutes)...")
    try:
        result = poll_persona_inquiry(inquiry_id)
    except TimeoutError as e:
        print(f"\n{e}")
        return None

    return result


def run_verify(args):
    """CLI entry point for charter verify."""
    if args.action == "configure":
        provider = args.provider
        if not provider:
            print("Usage: charter verify configure <persona|id_me>")
            print("  Then provide your API credentials.")
            return

        if provider == "persona":
            api_key = input("  Persona API key: ").strip()
            if not api_key:
                print("API key required.")
                return
            template_id = input("  Template ID (optional, press Enter to skip): ").strip() or None
            env = input("  Environment (sandbox/production) [sandbox]: ").strip() or "sandbox"
            configure_persona(api_key, template_id, env)
            print(f"\nPersona configured ({env}).")
            print("  Run 'charter verify start' to begin verification.")

        elif provider == "id_me":
            client_id = input("  ID.me Client ID: ").strip()
            if not client_id:
                print("Client ID required.")
                return
            client_secret = input("  ID.me Client Secret: ").strip()
            if not client_secret:
                print("Client Secret required.")
                return
            env = input("  Environment (sandbox/production) [sandbox]: ").strip() or "sandbox"
            configure_idme(client_id, client_secret, environment=env)
            print(f"\nID.me configured ({env}).")
            print("  Run 'charter verify start --provider id_me' to begin verification.")

        else:
            print(f"Unknown provider: {provider}")
            print("Supported: persona, id_me")

    elif args.action == "start":
        provider = getattr(args, "provider", None) or "persona"

        if provider == "persona":
            result = run_persona_verification()
            if not result:
                return

            status = result.get("status", "unknown")
            print(f"\nVerification status: {status}")

            if status in ("completed", "approved"):
                name = f"{result.get('name_first', '')} {result.get('name_last', '')}".strip()
                email = result.get("email", "")

                if name:
                    print(f"  Verified name:  {name}")
                if email:
                    print(f"  Verified email: {email}")

                # Record in Charter identity
                from charter.identity import verify_identity
                print("\nRecording verification in Charter identity chain...")
                verification, prior = verify_identity(
                    name=name or "Verified User",
                    email=email or "",
                    method="persona",
                    verification_token=result.get("inquiry_id"),
                )
                print(f"  Trust level: {verification['trust_level']}")
                print(f"  Transferred: {prior} chain entries now attributed to {name}")
                print("\nIdentity verified. Use 'charter identity proof' for a transfer proof.")
            else:
                print(f"  Verification did not complete successfully.")
                print(f"  Inquiry ID: {result.get('inquiry_id')}")
                print(f"  Check again later: charter verify check {result.get('inquiry_id')}")

        elif provider == "id_me":
            print("ID.me verification flow not yet implemented.")
            print("Use Persona for now: charter verify start")

    elif args.action == "check":
        inquiry_id = args.name
        if not inquiry_id:
            print("Usage: charter verify check <inquiry_id>")
            return

        print(f"Checking inquiry {inquiry_id}...")
        result = check_persona_inquiry(inquiry_id)
        print(f"  Status: {result['status']}")
        if result.get("name_first"):
            print(f"  Name: {result['name_first']} {result.get('name_last', '')}")
        if result.get("email"):
            print(f"  Email: {result['email']}")

    elif args.action == "status":
        config = load_verify_config()
        if not config:
            print("No verification providers configured.")
            print("  Run 'charter verify configure persona' to set up Persona.")
            return

        print("Verification Providers:\n")
        if "persona" in config:
            p = config["persona"]
            env = p.get("environment", "unknown")
            has_template = "yes" if p.get("template_id") else "no"
            print(f"  Persona ({env})")
            print(f"    API key: ...{p['api_key'][-8:]}")
            print(f"    Template: {has_template}")
            print(f"    Configured: {p.get('configured_at', 'unknown')}")
        if "id_me" in config:
            i = config["id_me"]
            env = i.get("environment", "unknown")
            print(f"  ID.me ({env})")
            print(f"    Client ID: ...{i['client_id'][-8:]}")
            print(f"    Configured: {i.get('configured_at', 'unknown')}")
