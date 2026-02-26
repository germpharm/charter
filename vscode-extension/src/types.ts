/**
 * Shared TypeScript interfaces for the Charter VS Code extension.
 *
 * Zero external dependencies. All types used by templates, identity,
 * generate, domainDetector, and bootstrap modules.
 */

// ---------------------------------------------------------------------------
// Domain
// ---------------------------------------------------------------------------

export type Domain = "healthcare" | "finance" | "education" | "general" | "personal";

export const ALL_DOMAINS: Domain[] = [
  "healthcare",
  "finance",
  "education",
  "general",
  "personal",
];

// ---------------------------------------------------------------------------
// Governance config (mirrors charter.yaml structure)
// ---------------------------------------------------------------------------

export interface LayerBRule {
  action: string;
  threshold: string;
  requires: string;
  description: string;
}

export interface LayerA {
  description: string;
  universal: string[];
  rules: string[];
}

export interface LayerB {
  description: string;
  rules: LayerBRule[];
}

export interface LayerC {
  description: string;
  frequency: string;
  report_includes: string[];
}

export interface KillTrigger {
  trigger: string;
  description: string;
}

export interface Governance {
  layer_a: LayerA;
  layer_b: LayerB;
  layer_c: LayerC;
  kill_triggers: KillTrigger[];
}

export interface CharterIdentityRef {
  public_id: string;
  alias: string;
}

export interface CharterConfig {
  domain: Domain;
  governance: Governance;
  version?: string;
  identity?: CharterIdentityRef;
}

// ---------------------------------------------------------------------------
// Identity (stored in ~/.charter/identity.json)
// ---------------------------------------------------------------------------

export interface CharterIdentity {
  version: string;
  public_id: string;
  private_seed: string;
  alias: string;
  created_at: string;
  real_identity: RealIdentity | null;
  contributions: number;
}

export interface RealIdentity {
  name: string;
  email: string;
  method: string;
  verification_token: string | null;
  verified_at: string;
  trust_level: string;
}

// ---------------------------------------------------------------------------
// Hash chain entries (stored in ~/.charter/chain.jsonl)
// ---------------------------------------------------------------------------

export interface ChainEntry {
  index: number;
  timestamp: string;
  event: string;
  data: Record<string, unknown>;
  previous_hash: string;
  hash?: string;
  signer?: string;
  signature?: string;
}

// ---------------------------------------------------------------------------
// Bootstrap result
// ---------------------------------------------------------------------------

export interface BootstrapResult {
  success: boolean;
  method: "python-cli" | "typescript-native";
  domain: Domain;
  filesCreated: string[];
  error?: string;
}
