/**
 * Pseudonymous identity creation and hash chain management.
 *
 * Port of charter/identity.py. Creates identities, initializes hash chains,
 * and appends signed entries. Compatible with the Python CLI output:
 * - Same identity.json structure
 * - Same chain.jsonl format
 * - Same hash computation (stableStringify -> SHA-256)
 * - Same HMAC-SHA256 signing
 *
 * Zero external dependencies. Uses only Node.js crypto, fs, path, os.
 */

import * as crypto from "crypto";
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import { CharterIdentity, ChainEntry } from "./types";

// ---------------------------------------------------------------------------
// Paths (mirrors Python identity.py constants)
// ---------------------------------------------------------------------------

const IDENTITY_DIR = ".charter";
const IDENTITY_FILE = "identity.json";
const CHAIN_FILE = "chain.jsonl";

function getIdentityDir(): string {
  return path.join(os.homedir(), IDENTITY_DIR);
}

function getIdentityPath(): string {
  return path.join(getIdentityDir(), IDENTITY_FILE);
}

function getChainPath(): string {
  return path.join(getIdentityDir(), CHAIN_FILE);
}

// ---------------------------------------------------------------------------
// Stable JSON serialization — byte-for-byte match with Python's
// json.dumps(sort_keys=True, separators=(",", ":"))
// ---------------------------------------------------------------------------

/**
 * Produce a deterministic JSON string that matches Python's
 * json.dumps(obj, sort_keys=True, separators=(",", ":")).
 *
 * This is critical for hash chain compatibility between the TypeScript
 * and Python implementations.
 */
export function stableStringify(obj: unknown): string {
  if (obj === null) {
    return "null";
  }
  if (typeof obj === "boolean") {
    return obj ? "true" : "false";
  }
  if (typeof obj === "number") {
    // Python json.dumps uses repr-style: no trailing .0 for ints,
    // but JavaScript's JSON.stringify handles this correctly for integers.
    return JSON.stringify(obj);
  }
  if (typeof obj === "string") {
    return JSON.stringify(obj);
  }
  if (Array.isArray(obj)) {
    const items = obj.map((item) => stableStringify(item));
    return "[" + items.join(",") + "]";
  }
  if (typeof obj === "object") {
    const sorted = Object.keys(obj as Record<string, unknown>).sort();
    const pairs = sorted.map(
      (key) =>
        JSON.stringify(key) +
        ":" +
        stableStringify((obj as Record<string, unknown>)[key])
    );
    return "{" + pairs.join(",") + "}";
  }
  // Fallback
  return JSON.stringify(obj);
}

// ---------------------------------------------------------------------------
// Hashing and signing
// ---------------------------------------------------------------------------

/**
 * Compute SHA-256 hash of a chain entry (excluding the "hash" field).
 * Mirrors Python identity.py hash_entry().
 */
export function hashEntry(entry: ChainEntry): string {
  const content: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(entry)) {
    if (k !== "hash") {
      content[k] = v;
    }
  }
  const raw = stableStringify(content);
  return crypto.createHash("sha256").update(raw, "utf8").digest("hex");
}

/**
 * Sign data with HMAC-SHA256 using the private seed.
 * Mirrors Python identity.py sign_data().
 */
export function signData(
  data: Record<string, unknown>,
  privateSeed: string
): string {
  const raw = stableStringify(data);
  return crypto
    .createHmac("sha256", Buffer.from(privateSeed, "hex"))
    .update(raw, "utf8")
    .digest("hex");
}

// ---------------------------------------------------------------------------
// UTC timestamp — matches Python time.strftime("%Y-%m-%dT%H:%M:%SZ", gmtime())
// ---------------------------------------------------------------------------

function utcTimestamp(): string {
  const d = new Date();
  const pad = (n: number): string => n.toString().padStart(2, "0");
  return (
    d.getUTCFullYear() +
    "-" +
    pad(d.getUTCMonth() + 1) +
    "-" +
    pad(d.getUTCDate()) +
    "T" +
    pad(d.getUTCHours()) +
    ":" +
    pad(d.getUTCMinutes()) +
    ":" +
    pad(d.getUTCSeconds()) +
    "Z"
  );
}

// ---------------------------------------------------------------------------
// Identity management
// ---------------------------------------------------------------------------

/**
 * Load an existing identity from ~/.charter/identity.json, or null if
 * none exists.
 */
export function loadIdentity(): CharterIdentity | null {
  const idPath = getIdentityPath();
  try {
    if (!fs.existsSync(idPath)) {
      return null;
    }
    const raw = fs.readFileSync(idPath, "utf8");
    return JSON.parse(raw) as CharterIdentity;
  } catch {
    return null;
  }
}

/**
 * Create a new pseudonymous identity.
 *
 * Mirrors Python identity.py create_identity():
 * - 32 random bytes + timestamp nanoseconds -> SHA-256 = public_id
 * - Separate 32-byte private seed for signing
 * - Alias defaults to "node-{first 8 hex chars of public_id}"
 * - Genesis chain entry written to chain.jsonl
 */
export function createIdentity(alias?: string): CharterIdentity {
  const idDir = getIdentityDir();
  fs.mkdirSync(idDir, { recursive: true });

  // Generate public ID from random bytes + timestamp
  // Python uses: secrets.token_bytes(32) + str(time.time_ns()).encode()
  const seed = Buffer.concat([
    crypto.randomBytes(32),
    Buffer.from(Date.now().toString() + "000"), // approximate nanoseconds
  ]);
  const publicId = crypto.createHash("sha256").update(seed).digest("hex");

  // Separate private seed for signing
  const privateSeed = crypto.randomBytes(32).toString("hex");

  const now = utcTimestamp();
  const nodeAlias = alias || `node-${publicId.slice(0, 8)}`;

  const identity: CharterIdentity = {
    version: "1.0",
    public_id: publicId,
    private_seed: privateSeed,
    alias: nodeAlias,
    created_at: now,
    real_identity: null,
    contributions: 0,
  };

  // Write identity.json
  fs.writeFileSync(getIdentityPath(), JSON.stringify(identity, null, 2), "utf8");

  // Initialize hash chain with genesis entry
  const genesis: ChainEntry = {
    index: 0,
    timestamp: now,
    event: "identity_created",
    data: { public_id: publicId, alias: nodeAlias },
    previous_hash: "0".repeat(64),
  };
  genesis.hash = hashEntry(genesis);

  // Write chain.jsonl (overwrite — this is genesis)
  fs.writeFileSync(getChainPath(), JSON.stringify(genesis) + "\n", "utf8");

  return identity;
}

/**
 * Append a new entry to the hash chain.
 *
 * Mirrors Python identity.py append_to_chain():
 * - Reads the last entry to get previous_hash
 * - Computes hash of new entry
 * - Signs with HMAC-SHA256
 * - Appends as a new line to chain.jsonl
 * - Updates contribution count in identity.json
 */
export function appendToChain(
  event: string,
  data: Record<string, unknown>
): ChainEntry | null {
  const identity = loadIdentity();
  if (!identity) {
    return null;
  }

  const chainPath = getChainPath();

  // Read last entry for previous_hash and index
  let lastHash = "0".repeat(64);
  let index = 0;

  try {
    if (fs.existsSync(chainPath)) {
      const content = fs.readFileSync(chainPath, "utf8");
      const lines = content.split("\n").filter((line) => line.trim());
      if (lines.length > 0) {
        const lastEntry = JSON.parse(lines[lines.length - 1]) as ChainEntry;
        lastHash = lastEntry.hash || "0".repeat(64);
        index = (lastEntry.index || 0) + 1;
      }
    }
  } catch {
    // If chain is unreadable, start fresh after genesis
  }

  const entry: ChainEntry = {
    index,
    timestamp: utcTimestamp(),
    event,
    data,
    previous_hash: lastHash,
    signer: identity.public_id,
  };
  entry.hash = hashEntry(entry);
  entry.signature = signData(
    entry as unknown as Record<string, unknown>,
    identity.private_seed
  );

  // Append to chain
  fs.appendFileSync(chainPath, JSON.stringify(entry) + "\n", "utf8");

  // Update contribution count
  identity.contributions = index;
  fs.writeFileSync(getIdentityPath(), JSON.stringify(identity, null, 2), "utf8");

  return entry;
}
