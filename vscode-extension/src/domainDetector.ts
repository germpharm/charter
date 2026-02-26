/**
 * Auto-detect project domain from workspace files.
 *
 * Port of charter/bootstrap.py detect_domain(). Scans file names and
 * key content files (README, package.json, pyproject.toml, etc.) for
 * domain-specific keywords. Returns the best match or "general".
 *
 * Zero external dependencies. Uses only Node.js fs and path.
 */

import * as fs from "fs";
import * as path from "path";
import { Domain } from "./types";

// ---------------------------------------------------------------------------
// Keyword indicators per domain (matches Python bootstrap.py exactly)
// ---------------------------------------------------------------------------

const INDICATORS: Record<string, string[]> = {
  healthcare: [
    "hipaa", "hl7", "fhir", "dicom", "clinical", "patient",
    "pharmacy", "medication", "diagnosis", "ehr",
  ],
  finance: [
    "transaction", "ledger", "payment", "invoice", "banking",
    "trading", "portfolio", "compliance", "kyc", "aml",
  ],
  education: [
    "ferpa", "student", "curriculum", "grading", "enrollment",
    "classroom", "syllabus", "lms",
  ],
};

// Files to read for keyword signals (matches Python bootstrap.py exactly)
const CONTENT_FILES = [
  "README.md",
  "README.txt",
  "README",
  "package.json",
  "pyproject.toml",
  "setup.py",
  "setup.cfg",
  "Cargo.toml",
];

// Max bytes to read from each content file
const MAX_READ_BYTES = 4096;

/**
 * Detect the project domain by scanning workspace files.
 *
 * Mirrors the Python detect_domain() logic:
 * 1. Collect all file names in the directory (lowercased)
 * 2. Read the first 4096 bytes of README, package.json, etc.
 * 3. Score each domain by counting keyword hits
 * 4. Return the domain with >= 2 hits, or "general"
 */
export function detectDomain(workspacePath: string): Domain {
  const absPath = path.resolve(workspacePath);

  // Collect file names as lowercase signal strings
  let signalFiles: string[] = [];
  try {
    const entries = fs.readdirSync(absPath);
    signalFiles = entries.map((f) => f.toLowerCase());
  } catch {
    // Can't read directory — fall back to general
    return "general";
  }

  // Build text blob: file names + content snippets
  let textBlob = signalFiles.join(" ");

  for (const cf of CONTENT_FILES) {
    const cfPath = path.join(absPath, cf);
    try {
      if (fs.existsSync(cfPath) && fs.statSync(cfPath).isFile()) {
        const fd = fs.openSync(cfPath, "r");
        const buf = Buffer.alloc(MAX_READ_BYTES);
        const bytesRead = fs.readSync(fd, buf, 0, MAX_READ_BYTES, 0);
        fs.closeSync(fd);
        textBlob += " " + buf.toString("utf8", 0, bytesRead).toLowerCase();
      }
    } catch {
      // Skip unreadable files
    }
  }

  // Score each domain
  const scores: Record<string, number> = {};
  for (const [domain, keywords] of Object.entries(INDICATORS)) {
    scores[domain] = keywords.filter((kw) => textBlob.includes(kw)).length;
  }

  // Find best match
  let bestDomain = "general";
  let bestScore = 0;
  for (const [domain, score] of Object.entries(scores)) {
    if (score > bestScore) {
      bestScore = score;
      bestDomain = domain;
    }
  }

  // Require at least 2 keyword hits to override general
  if (bestScore >= 2) {
    return bestDomain as Domain;
  }

  return "general";
}
