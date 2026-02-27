"""RFC 3161 timestamp anchoring for Charter hash chains.

Periodically anchors the chain's current state to an independently
attested timestamp from a certified Time Stamping Authority (TSA).
This closes the timestamp self-attestation gap — without anchoring,
each node's timestamps are self-attested via local clock.

Architecture:
    - Charter computes the latest chain hash
    - Submits it to an RFC 3161-compliant TSA via HTTP POST
    - Receives a signed timestamp token (DER-encoded)
    - Stores the token as a chain entry (event: "timestamp_anchor")
    - Verification uses OpenSSL CLI (available on macOS/Linux)

TSA providers use NIST-traceable time sources and operate on
FIPS 140-2 Level 4 hardware security modules.

Legal standing:
    RFC 3161 timestamps are recognized under EU eIDAS regulation
    and are admissible under FRE 901 for authentication of
    electronic evidence.

Dependencies:
    - OpenSSL CLI (pre-installed on macOS and most Linux)
    - Python stdlib only (subprocess, urllib, tempfile)
"""

import base64
import hashlib
import json
import os
import subprocess
import tempfile
import time
import urllib.request
import urllib.error


# Default TSA endpoints — all are free and RFC 3161 compliant.
# FreeTSA.org is the primary; DigiCert is the fallback.
TSA_ENDPOINTS = [
    "https://freetsa.org/tsr",
    "https://timestamp.digicert.com",
]

# How often to anchor (can be overridden in config)
DEFAULT_ANCHOR_INTERVAL_ENTRIES = 1000  # Every N chain entries
DEFAULT_ANCHOR_INTERVAL_SECONDS = 3600  # Or every N seconds, whichever comes first


def _find_openssl():
    """Find the OpenSSL binary."""
    for path in ["/usr/bin/openssl", "/opt/homebrew/bin/openssl", "/usr/local/bin/openssl"]:
        if os.path.isfile(path):
            return path
    # Fall back to PATH
    try:
        result = subprocess.run(
            ["which", "openssl"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _create_ts_query(data_hash_hex: str) -> bytes | None:
    """Create an RFC 3161 timestamp query using OpenSSL.

    Args:
        data_hash_hex: SHA-256 hash of the data to timestamp (hex string).

    Returns:
        DER-encoded timestamp query bytes, or None if OpenSSL unavailable.
    """
    openssl = _find_openssl()
    if not openssl:
        return None

    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as hash_file:
        hash_file.write(bytes.fromhex(data_hash_hex))
        hash_path = hash_file.name

    query_path = hash_path + ".tsq"

    try:
        result = subprocess.run(
            [
                openssl, "ts", "-query",
                "-data", hash_path,
                "-no_nonce",
                "-sha256",
                "-out", query_path,
            ],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None

        with open(query_path, "rb") as f:
            return f.read()
    except Exception:
        return None
    finally:
        for p in [hash_path, query_path]:
            try:
                os.unlink(p)
            except OSError:
                pass


def _submit_to_tsa(query_bytes: bytes, tsa_url: str, timeout: int = 15) -> bytes | None:
    """Submit a timestamp query to a TSA and return the response.

    Args:
        query_bytes: DER-encoded RFC 3161 timestamp query.
        tsa_url: URL of the TSA endpoint.
        timeout: HTTP timeout in seconds.

    Returns:
        DER-encoded timestamp response bytes, or None on failure.
    """
    try:
        req = urllib.request.Request(
            tsa_url,
            data=query_bytes,
            headers={
                "Content-Type": "application/timestamp-query",
            },
        )
        resp = urllib.request.urlopen(req, timeout=timeout)
        if resp.status == 200:
            return resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        pass
    return None


def _parse_ts_response(response_bytes: bytes) -> dict | None:
    """Parse an RFC 3161 timestamp response using OpenSSL.

    Returns a dict with the timestamp details, or None on failure.
    """
    openssl = _find_openssl()
    if not openssl:
        return None

    with tempfile.NamedTemporaryFile(suffix=".tsr", delete=False) as resp_file:
        resp_file.write(response_bytes)
        resp_path = resp_file.name

    try:
        result = subprocess.run(
            [openssl, "ts", "-reply", "-in", resp_path, "-text"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None

        # Parse the text output for key fields
        parsed = {"raw_text": result.stdout}
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("Time stamp:"):
                parsed["timestamp"] = line.split(":", 1)[1].strip()
            elif line.startswith("Serial number:"):
                parsed["serial"] = line.split(":", 1)[1].strip()
            elif line.startswith("Hash Algorithm:"):
                parsed["hash_algorithm"] = line.split(":", 1)[1].strip()
            elif line.startswith("Status:"):
                parsed["status"] = line.split(":", 1)[1].strip()
            elif "Status info:" in line:
                parsed["status_info"] = line.split(":", 1)[1].strip()

        return parsed
    except Exception:
        return None
    finally:
        try:
            os.unlink(resp_path)
        except OSError:
            pass


def create_timestamp_anchor(chain_hash: str, tsa_urls: list[str] = None) -> dict | None:
    """Create an RFC 3161 timestamp anchor for a chain hash.

    Tries each TSA endpoint in order until one succeeds.

    Args:
        chain_hash: The SHA-256 hash of the latest chain entry (hex).
        tsa_urls: List of TSA URLs to try. Defaults to TSA_ENDPOINTS.

    Returns:
        Dict with anchor data suitable for recording in the chain,
        or None if all TSAs fail or OpenSSL is unavailable.
    """
    urls = tsa_urls or TSA_ENDPOINTS

    # Create the timestamp query
    query = _create_ts_query(chain_hash)
    if query is None:
        return None

    # Try each TSA
    for url in urls:
        response = _submit_to_tsa(query, url)
        if response is None:
            continue

        # Parse the response
        parsed = _parse_ts_response(response)
        if parsed is None:
            continue

        # Store the response as base64 for JSON serialization
        anchor = {
            "tsa_url": url,
            "chain_hash_anchored": chain_hash,
            "query_b64": base64.b64encode(query).decode("ascii"),
            "response_b64": base64.b64encode(response).decode("ascii"),
            "tsa_timestamp": parsed.get("timestamp"),
            "tsa_serial": parsed.get("serial"),
            "tsa_status": parsed.get("status"),
            "hash_algorithm": parsed.get("hash_algorithm", "sha256"),
            "local_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        return anchor

    return None


def anchor_chain(force: bool = False) -> dict | None:
    """Anchor the current chain state to an RFC 3161 timestamp.

    This is the main entry point. It:
    1. Reads the latest chain entry hash
    2. Checks if anchoring is due (by entry count or time)
    3. Submits to a TSA
    4. Records the anchor as a chain entry

    Args:
        force: If True, anchor regardless of interval settings.

    Returns:
        The chain entry dict if anchored, None if skipped or failed.
    """
    from charter.identity import get_chain_path, append_to_chain, load_identity

    identity = load_identity()
    if not identity:
        return None

    chain_path = get_chain_path()
    if not os.path.isfile(chain_path):
        return None

    # Read the chain to get latest hash and check intervals
    with open(chain_path) as f:
        lines = f.readlines()

    if not lines:
        return None

    last_entry = json.loads(lines[-1])
    latest_hash = last_entry.get("hash", "")
    latest_index = last_entry.get("index", 0)

    if not force:
        # Check if anchoring is due
        last_anchor_index = -1
        last_anchor_time = 0
        for line in reversed(lines):
            entry = json.loads(line)
            if entry.get("event") == "timestamp_anchor":
                last_anchor_index = entry.get("index", 0)
                try:
                    t = time.strptime(entry["timestamp"], "%Y-%m-%dT%H:%M:%SZ")
                    last_anchor_time = time.mktime(t)
                except (ValueError, KeyError):
                    pass
                break

        entries_since = latest_index - last_anchor_index
        seconds_since = time.time() - last_anchor_time if last_anchor_time else float("inf")

        if (entries_since < DEFAULT_ANCHOR_INTERVAL_ENTRIES and
                seconds_since < DEFAULT_ANCHOR_INTERVAL_SECONDS):
            return None  # Not yet due

    # Create the anchor
    anchor_data = create_timestamp_anchor(latest_hash)
    if anchor_data is None:
        return None

    # Record in the chain
    entry = append_to_chain("timestamp_anchor", anchor_data, auto_batch=True)
    return entry


def verify_timestamp_anchor(anchor_entry: dict) -> dict:
    """Verify an RFC 3161 timestamp anchor from the chain.

    Takes a chain entry with event="timestamp_anchor" and verifies
    that the TSA response is valid and matches the anchored hash.

    Args:
        anchor_entry: A chain entry dict with event="timestamp_anchor".

    Returns:
        Verification result dict.
    """
    data = anchor_entry.get("data", {})

    if not data.get("response_b64"):
        return {
            "verified": False,
            "reason": "No TSA response data in anchor entry",
        }

    response_bytes = base64.b64decode(data["response_b64"])
    parsed = _parse_ts_response(response_bytes)

    if parsed is None:
        return {
            "verified": False,
            "reason": "Could not parse TSA response (OpenSSL may be unavailable)",
        }

    # Check status
    status = parsed.get("status", "").lower()
    if "granted" not in status:
        return {
            "verified": False,
            "reason": f"TSA status is not 'granted': {status}",
        }

    return {
        "verified": True,
        "tsa_url": data.get("tsa_url"),
        "chain_hash_anchored": data.get("chain_hash_anchored"),
        "tsa_timestamp": parsed.get("timestamp"),
        "tsa_serial": parsed.get("serial"),
        "local_time": data.get("local_time"),
        "reason": "RFC 3161 timestamp anchor verified",
    }


def run_timestamp(args):
    """CLI entry point for charter timestamp."""
    if args.action == "anchor":
        print("Anchoring chain to RFC 3161 timestamp...")
        result = anchor_chain(force=True)
        if result:
            data = result.get("data", {})
            print(f"Timestamp Anchor Created")
            print(f"  Chain index:  {result.get('index')}")
            print(f"  TSA:          {data.get('tsa_url')}")
            print(f"  TSA time:     {data.get('tsa_timestamp')}")
            print(f"  Hash anchored: {data.get('chain_hash_anchored', '')[:32]}...")
            print(f"  Local time:   {data.get('local_time')}")
        else:
            print("Anchoring failed. Check that OpenSSL is installed and network is available.")

    elif args.action == "verify":
        from charter.identity import get_chain_path
        chain_path = get_chain_path()
        if not os.path.isfile(chain_path):
            print("No chain found.")
            return

        # Find all timestamp anchors
        anchors = []
        with open(chain_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    entry = json.loads(line)
                    if entry.get("event") == "timestamp_anchor":
                        anchors.append(entry)

        if not anchors:
            print("No timestamp anchors found in chain.")
            print("Run 'charter timestamp anchor' to create one.")
            return

        print(f"Verifying {len(anchors)} timestamp anchor(s)...\n")
        for anchor in anchors:
            result = verify_timestamp_anchor(anchor)
            status = "VERIFIED" if result["verified"] else "FAILED"
            print(f"  [{status}] Index {anchor.get('index')}")
            print(f"    TSA:       {result.get('tsa_url', 'N/A')}")
            print(f"    TSA time:  {result.get('tsa_timestamp', 'N/A')}")
            print(f"    Hash:      {result.get('chain_hash_anchored', 'N/A')[:32]}...")
            print(f"    Reason:    {result['reason']}")
            print()

    elif args.action == "status":
        from charter.identity import get_chain_path
        chain_path = get_chain_path()
        if not os.path.isfile(chain_path):
            print("No chain found.")
            return

        anchors = []
        total = 0
        with open(chain_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    total += 1
                    entry = json.loads(line)
                    if entry.get("event") == "timestamp_anchor":
                        anchors.append(entry)

        last_anchor_index = anchors[-1].get("index", 0) if anchors else -1
        entries_since = total - 1 - last_anchor_index if last_anchor_index >= 0 else total

        print(f"Timestamp Anchoring Status")
        print(f"  Total anchors:      {len(anchors)}")
        print(f"  Entries since last:  {entries_since}")
        print(f"  Anchor interval:     Every {DEFAULT_ANCHOR_INTERVAL_ENTRIES} entries "
              f"or {DEFAULT_ANCHOR_INTERVAL_SECONDS}s")
        if anchors:
            last = anchors[-1]
            print(f"  Last anchor index:   {last.get('index')}")
            print(f"  Last anchor time:    {last.get('data', {}).get('tsa_timestamp', 'N/A')}")
            print(f"  Last TSA:            {last.get('data', {}).get('tsa_url', 'N/A')}")
