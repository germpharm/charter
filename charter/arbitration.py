"""Multi-Model Arbitration — Bezos Type 1/Type 2 decision framework for Charter.

Irreversible decisions (one-way doors) are routed through multiple AI models
for divergence analysis before human approval. Reversible decisions (two-way
doors) can use a single model. This implements the core insight: not all
decisions carry the same cost of error.

The module classifies actions by reversibility, queries available models,
computes divergence between their responses, and recommends whether to
proceed, review, or escalate to a human. Every step is logged to the
immutable hash chain.

Divergence detection uses Jaccard similarity over word sets — intentionally
simple, zero ML dependencies. Semantic comparison is a future enhancement.
The goal here is structural: route high-stakes decisions through multiple
perspectives before they become irreversible.

Decision framework:
    Type 2 (two-way door): Reversible. Single model. Move fast.
    Type 1 (one-way door): Irreversible. Multi-model. Measure twice.
"""

import hashlib
import json
import os
import time
import urllib.request
import urllib.error

from charter.identity import append_to_chain


# ---------------------------------------------------------------------------
# Reversibility classification
# ---------------------------------------------------------------------------

REVERSIBILITY_LEVELS = {
    "reversible": "Two-way door. Single model sufficient. Easy to undo.",
    "low_reversibility": "Partially reversible. Multi-model recommended.",
    "irreversible": "One-way door. Multi-model check required before human approval.",
}

_IRREVERSIBLE_KEYWORDS = [
    "delete",
    "terminate",
    "fire",
    "publish",
    "send",
    "deploy to production",
    "sign contract",
    "commit funds",
    "regulatory filing",
    "destroy",
    "revoke",
    "dismiss",
    "execute trade",
    "wire transfer",
    "submit to fda",
    "file lawsuit",
]

_LOW_REVERSIBILITY_KEYWORDS = [
    "change",
    "modify",
    "update pricing",
    "restructure",
    "migrate",
    "rename",
    "reassign",
    "merge",
    "refactor",
    "rebrand",
]


def classify_reversibility(action_description):
    """Classify an action's reversibility based on keyword heuristics.

    Scans the action description for keywords associated with irreversible
    or partially reversible actions. Multi-word keywords are matched as
    substrings; single-word keywords are matched against individual words.

    Args:
        action_description: Free-text description of the proposed action.

    Returns:
        One of "irreversible", "low_reversibility", or "reversible".
    """
    if not action_description:
        return "reversible"

    lower = action_description.lower()

    # Check irreversible keywords first (higher priority)
    for keyword in _IRREVERSIBLE_KEYWORDS:
        if " " in keyword:
            # Multi-word: substring match
            if keyword in lower:
                return "irreversible"
        else:
            # Single word: check word boundaries via split
            if keyword in lower.split():
                return "irreversible"

    # Check low-reversibility keywords
    for keyword in _LOW_REVERSIBILITY_KEYWORDS:
        if " " in keyword:
            if keyword in lower:
                return "low_reversibility"
        else:
            if keyword in lower.split():
                return "low_reversibility"

    return "reversible"


# ---------------------------------------------------------------------------
# Model adapters
# ---------------------------------------------------------------------------

class ModelAdapter:
    """Base adapter for querying an AI model."""

    name = "base"

    def query(self, prompt, system=None):
        """Send prompt to model, return response text.

        Args:
            prompt: The user prompt to send.
            system: Optional system prompt for context.

        Returns:
            Response text as a string, or None on failure.
        """
        raise NotImplementedError


class LocalModelAdapter(ModelAdapter):
    """Adapter for local Qwen3 via Charter's local_model module.

    Uses the existing call_local_model function which handles its own
    chain logging and connection management.
    """

    name = "local"

    def query(self, prompt, system=None):
        """Query the local model server.

        Returns:
            Response text, or None on failure.
        """
        try:
            from charter.mcp_server.local_model import call_local_model
            result = call_local_model(prompt, system=system, max_tokens=2048)
            return result.get("text")
        except (ConnectionError, ImportError, KeyError, Exception):
            return None


class AnthropicAdapter(ModelAdapter):
    """Adapter for Anthropic Claude API via urllib (no SDK dependency).

    Reads ANTHROPIC_API_KEY from the environment. Uses the messages API
    endpoint with claude-sonnet-4-20250514. Connection failures return None
    rather than raising — the arbitration flow handles missing responses
    gracefully.
    """

    name = "anthropic"

    _API_URL = "https://api.anthropic.com/v1/messages"
    _MODEL = "claude-sonnet-4-20250514"

    def query(self, prompt, system=None):
        """Query the Anthropic API.

        Returns:
            Response text, or None on failure.
        """
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return None

        messages = [{"role": "user", "content": prompt}]

        payload = {
            "model": self._MODEL,
            "max_tokens": 2048,
            "messages": messages,
        }
        if system:
            payload["system"] = system

        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }

        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            self._API_URL,
            data=body,
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read())
        except (urllib.error.HTTPError, urllib.error.URLError,
                ConnectionRefusedError, TimeoutError, OSError):
            return None

        # Extract text from the messages API response
        content_blocks = result.get("content", [])
        if not content_blocks:
            return None

        # Concatenate all text blocks
        texts = []
        for block in content_blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(block.get("text", ""))

        return "\n".join(texts) if texts else None


# Registry of available adapter classes
_ADAPTER_REGISTRY = {
    "local": LocalModelAdapter,
    "anthropic": AnthropicAdapter,
}


def _get_adapter(name):
    """Instantiate a model adapter by name.

    Args:
        name: Adapter name (e.g., "local", "anthropic").

    Returns:
        ModelAdapter instance, or None if name is unknown.
    """
    cls = _ADAPTER_REGISTRY.get(name)
    if cls is None:
        return None
    return cls()


# ---------------------------------------------------------------------------
# Divergence detection
# ---------------------------------------------------------------------------

def _tokenize(text):
    """Basic lowercased word tokenization.

    Strips punctuation by keeping only alphanumeric characters and spaces,
    then splits on whitespace. This is intentionally naive — semantic
    comparison is a future enhancement.

    Args:
        text: Raw response text.

    Returns:
        Set of lowercase word tokens.
    """
    if not text:
        return set()
    cleaned = ""
    for ch in text.lower():
        if ch.isalnum() or ch == " ":
            cleaned += ch
        else:
            cleaned += " "
    return set(cleaned.split())


def detect_divergence(responses):
    """Compute divergence score across multiple model responses.

    For each pair of responses, computes Jaccard similarity of word sets.
    Averages the pairwise similarities. Divergence = 1.0 - average_similarity.

    A score of 0.0 means full agreement (identical word sets).
    A score of 1.0 means full disagreement (no shared words).

    Args:
        responses: Dict of {model_name: response_text}.

    Returns:
        Float between 0.0 and 1.0. Returns 0.0 for single or empty responses.
    """
    # Filter out None responses
    valid = {k: v for k, v in responses.items() if v is not None}

    if len(valid) < 2:
        return 0.0

    # Tokenize all responses
    token_sets = {name: _tokenize(text) for name, text in valid.items()}

    # Compute pairwise Jaccard similarities
    names = list(token_sets.keys())
    similarities = []

    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            set_a = token_sets[names[i]]
            set_b = token_sets[names[j]]

            union = set_a | set_b
            if not union:
                # Both empty — treat as identical
                similarities.append(1.0)
                continue

            intersection = set_a & set_b
            jaccard = len(intersection) / len(union)
            similarities.append(jaccard)

    if not similarities:
        return 0.0

    avg_similarity = sum(similarities) / len(similarities)
    return round(1.0 - avg_similarity, 4)


# ---------------------------------------------------------------------------
# Layer B integration
# ---------------------------------------------------------------------------

def check_layer_b_requirement(config, action_type):
    """Check if any Layer B rule requires multi_model_check for this action type.

    Scans the governance.layer_b.rules list in the config for a rule whose
    action matches action_type and whose requires field is "multi_model_check".

    Args:
        config: The charter config dict (from charter.yaml).
        action_type: The action type string to check (e.g., "financial_transaction").

    Returns:
        True if multi-model arbitration is required, False otherwise.
    """
    if not config:
        return False

    gov = config.get("governance", {})
    layer_b = gov.get("layer_b", {})
    rules = layer_b.get("rules", [])

    for rule in rules:
        if not isinstance(rule, dict):
            continue
        if rule.get("action") == action_type and rule.get("requires") == "multi_model_check":
            return True

    return False


# ---------------------------------------------------------------------------
# Availability check
# ---------------------------------------------------------------------------

def get_available_models():
    """Check which model adapters are currently available.

    Tests connectivity for local model and checks API key presence
    for cloud models.

    Returns:
        List of available model name strings.
    """
    available = []

    # Check local model — attempt a lightweight import and URL check
    try:
        from charter.mcp_server.local_model import DEFAULT_URL
        url = f"{DEFAULT_URL}/models"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                available.append("local")
    except (urllib.error.HTTPError, urllib.error.URLError,
            ConnectionRefusedError, TimeoutError, OSError,
            ImportError):
        pass

    # Check Anthropic — API key presence is sufficient
    if os.environ.get("ANTHROPIC_API_KEY"):
        available.append("anthropic")

    return available


# ---------------------------------------------------------------------------
# Core arbitration
# ---------------------------------------------------------------------------

def _determine_recommendation(reversibility, divergence_score, response_count):
    """Determine the recommended action based on reversibility and divergence.

    Args:
        reversibility: One of the REVERSIBILITY_LEVELS keys.
        divergence_score: Float between 0.0 and 1.0.
        response_count: Number of models that returned valid responses.

    Returns:
        One of "proceed", "review_divergence", "human_decision_required".
    """
    if response_count == 0:
        return "human_decision_required"

    if reversibility == "irreversible":
        if response_count < 2:
            return "human_decision_required"
        if divergence_score > 0.3:
            return "human_decision_required"
        return "proceed"

    if reversibility == "low_reversibility":
        if divergence_score > 0.5:
            return "review_divergence"
        if divergence_score > 0.3:
            return "review_divergence"
        return "proceed"

    # reversible
    if divergence_score > 0.5:
        return "review_divergence"
    return "proceed"


def arbitrate(question, models=None, context=None, reversibility=None):
    """Run multi-model arbitration on a question or proposed action.

    Routes the question through one or more AI models, computes divergence
    between their responses, and returns a recommendation. Irreversible
    actions default to multi-model consultation; reversible actions default
    to a single local model.

    Args:
        question: The question or action description to arbitrate.
        models: Optional list of model names (e.g., ["local", "anthropic"]).
            Defaults based on reversibility classification.
        context: Optional additional context string prepended to the prompt.
        reversibility: Optional override for reversibility classification.
            If None, classified from the question text.

    Returns:
        Dict with arbitration results, or None on complete failure.
    """
    if not question:
        return None

    # Classify reversibility
    if reversibility is None:
        reversibility = classify_reversibility(question)
    elif reversibility not in REVERSIBILITY_LEVELS:
        reversibility = "reversible"

    # Determine which models to use
    if models is None:
        if reversibility == "irreversible":
            models = ["local", "anthropic"]
        elif reversibility == "low_reversibility":
            models = ["local", "anthropic"]
        else:
            models = ["local"]

    question_hash = hashlib.sha256(question.encode()).hexdigest()[:16]

    # Log the request
    append_to_chain("arbitration_requested", {
        "question_hash": question_hash,
        "models": models,
        "reversibility": reversibility,
    })

    # Build the prompt
    system_prompt = (
        "You are a governance advisor evaluating a proposed action. "
        "Assess the risks, benefits, and potential consequences. "
        "Be specific about what could go wrong and what safeguards are needed. "
        "Keep your response concise (under 300 words)."
    )

    user_prompt = f"Proposed action: {question}"
    if context:
        user_prompt = f"Context: {context}\n\n{user_prompt}"
    user_prompt += (
        f"\n\nReversibility classification: {reversibility} "
        f"({REVERSIBILITY_LEVELS[reversibility]})\n\n"
        f"Please evaluate this action. What are the key risks? "
        f"Should it proceed, and under what conditions?"
    )

    # Query each model
    responses = {}
    for model_name in models:
        adapter = _get_adapter(model_name)
        if adapter is None:
            responses[model_name] = None
            continue
        responses[model_name] = adapter.query(user_prompt, system=system_prompt)

    # Count valid responses
    valid_count = sum(1 for v in responses.values() if v is not None)

    # Compute divergence
    divergence_score = detect_divergence(responses)
    agreement = divergence_score < 0.3

    # Determine recommendation
    recommended_action = _determine_recommendation(
        reversibility, divergence_score, valid_count
    )

    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    result = {
        "question_hash": question_hash,
        "reversibility": reversibility,
        "models_consulted": [m for m in models if responses.get(m) is not None],
        "models_failed": [m for m in models if responses.get(m) is None],
        "responses": responses,
        "agreement": agreement,
        "divergence_score": divergence_score,
        "recommended_action": recommended_action,
        "timestamp": timestamp,
    }

    # Log completion
    append_to_chain("arbitration_completed", {
        "question_hash": question_hash,
        "agreement": agreement,
        "divergence_score": divergence_score,
        "models_consulted": result["models_consulted"],
        "recommended_action": recommended_action,
    })

    # Log divergence if significant
    if divergence_score > 0.3:
        append_to_chain("arbitration_divergence_detected", {
            "question_hash": question_hash,
            "models": result["models_consulted"],
            "divergence_score": divergence_score,
        })

    return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def run_arbitrate(args):
    """CLI entry point for charter arbitrate.

    Args:
        args: Namespace with:
            question (str): The question or action to arbitrate.
            models (str, optional): Comma-separated model names.
            reversibility (str, optional): Override reversibility classification.
    """
    question = getattr(args, "question", None)
    if not question:
        print("Usage: charter arbitrate --question 'Should we deploy to production?'")
        return

    # Parse models
    model_list = None
    models_arg = getattr(args, "models", None)
    if models_arg:
        model_list = [m.strip() for m in models_arg.split(",") if m.strip()]

    # Parse reversibility override
    rev_override = getattr(args, "reversibility", None)
    if rev_override and rev_override not in REVERSIBILITY_LEVELS:
        print(f"Invalid reversibility level: {rev_override}")
        print(f"  Valid levels: {', '.join(REVERSIBILITY_LEVELS.keys())}")
        return

    # Show available models
    available = get_available_models()
    print("Charter Multi-Model Arbitration")
    print("=" * 50)
    print(f"  Available models: {', '.join(available) if available else '(none detected)'}")
    print()

    # Run arbitration
    result = arbitrate(
        question,
        models=model_list,
        reversibility=rev_override,
    )

    if result is None:
        print("Arbitration failed. No question provided.")
        return

    # Display results
    print(f"  Question hash:   {result['question_hash']}")
    print(f"  Reversibility:   {result['reversibility']}")
    print(f"                   {REVERSIBILITY_LEVELS[result['reversibility']]}")
    print(f"  Models consulted: {', '.join(result['models_consulted']) if result['models_consulted'] else '(none)'}")
    if result["models_failed"]:
        print(f"  Models failed:   {', '.join(result['models_failed'])}")
    print()

    # Show responses
    for model_name, response in result["responses"].items():
        print(f"  --- {model_name} ---")
        if response is None:
            print(f"  (no response — model unavailable)")
        else:
            # Indent and wrap response for readability
            for line in response.split("\n"):
                print(f"  {line}")
        print()

    # Show analysis
    print(f"  Divergence score: {result['divergence_score']:.4f}")
    print(f"  Agreement:        {'Yes' if result['agreement'] else 'No'}")
    print()

    # Show recommendation with color-coded urgency
    rec = result["recommended_action"]
    if rec == "proceed":
        print(f"  RECOMMENDATION:   PROCEED")
        print(f"  Models are in agreement. Action appears safe to execute.")
    elif rec == "review_divergence":
        print(f"  RECOMMENDATION:   REVIEW DIVERGENCE")
        print(f"  Models disagree significantly. Human review recommended")
        print(f"  before proceeding.")
    elif rec == "human_decision_required":
        print(f"  RECOMMENDATION:   HUMAN DECISION REQUIRED")
        print(f"  This is a one-way door with insufficient model consensus.")
        print(f"  Do not proceed without explicit human authorization.")

    print()
    print(f"  Logged to chain at {result['timestamp']}")
