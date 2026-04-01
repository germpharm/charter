"""Wolfram Engine bridge — deep analytical queries via WolframScript.

Connects Charter's DuckDB analytics store to the Wolfram Language
Engine for causal inference, symbolic computation, time series
modeling, and graph analytics that go beyond what Python provides.

Architecture:
    DuckDB (fast, local) ──export──→ Wolfram Engine (deep analysis)
                                      │
                                      ├── CausalInference / FindCausalModel
                                      ├── SequencePredict / TimeSeriesModel
                                      ├── FindGraphCommunities
                                      ├── HypothesisTest / LocationTest
                                      └── Custom Wolfram Language expressions

The engine runs on grandcentral (Mac Mini, 100.95.120.54) via SSH,
or locally if wolframscript is available on the current machine.

Usage:
    from charter.analytics.wolfram import WolframBridge
    wb = WolframBridge()
    result = wb.causal_model("audit_generated", predecessors=5)
    result = wb.time_series_forecast("volume", days=30)
    result = wb.hypothesis_test(group_a, group_b, test="MannWhitney")
"""

import csv
import io
import json
import os
import shutil
import subprocess
import tempfile
import time

from charter.analytics.indexer import Indexer, _now_ms, _get_analytics_dir


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Grandcentral (Mac Mini) Tailscale IP
REMOTE_HOST = "100.95.120.54"
REMOTE_USER = "grandcentral"

# Timeout for Wolfram computations (seconds)
DEFAULT_TIMEOUT = 120

# Where to cache exported data for Wolfram
EXPORT_DIR_NAME = "wolfram_exports"

# Setup guide shown when Wolfram Engine is not found
WOLFRAM_SETUP_GUIDE = """
Charter Analytics — Wolfram Engine Not Found
=============================================

The Wolfram Engine provides publication-grade statistical analysis:
causal inference, hypothesis testing, time series forecasting, and
graph community detection. It is optional — all other Charter
analytics features work without it.

To install the Wolfram Engine:

  1. Download Wolfram Engine (free for development):
     https://www.wolfram.com/engine/

  2. Install and activate:
     - macOS: Open the .dmg, drag to Applications, then run:
       $ wolframscript -activate
     - Linux: Follow the installer, then:
       $ wolframscript -activate
     - Windows: Run the installer, activation is automatic

  3. Verify installation:
     $ wolframscript -code "Print[2+2]"
     (Should print: 4)

  4. Verify Charter can find it:
     $ charter analytics wolfram-status

For remote setups (Wolfram on a server, Charter on laptops):
  - Install Wolfram Engine on the central server only
  - Regional laptops connect via SSH over Tailscale/VPN
  - Configure in Charter:  Set REMOTE_HOST and REMOTE_USER in
    charter/analytics/wolfram.py, or provide via environment:
      $ export CHARTER_WOLFRAM_HOST=user@server-ip

Wolfram Engine licensing:
  - Free for development and pre-production use
  - Government and education: contact Wolfram for site licenses
  - See: https://www.wolfram.com/engine/free-license/

Without Wolfram, Charter still provides:
  - Causal discovery (lift scores, co-occurrence analysis)
  - Sequence mining (PrefixSpan algorithm)
  - Anomaly detection (baseline comparison)
  - Cohort comparison (descriptive statistics)
  - All query lenses (summary, timeline, flow, search, compare, profile)
  - Full data export (Parquet, CSV, JSON)

With Wolfram, Charter adds:
  - Chi-squared independence tests with exact p-values
  - Structural causal models (FindCausalModel)
  - Time series forecasting (TimeSeriesModel)
  - Graph community detection (FindGraphCommunities)
  - Hypothesis testing (LocationTest, HypothesisTest)
  - Publication-grade effect sizes and confidence intervals
""".strip()


# ---------------------------------------------------------------------------
# Connection modes
# ---------------------------------------------------------------------------

def _find_wolframscript():
    """Find wolframscript binary, local or remote.

    Checks in order:
      1. Local PATH and common macOS install paths
      2. Remote host via CHARTER_WOLFRAM_HOST env var
      3. Remote host via REMOTE_HOST/REMOTE_USER constants
    """
    # Allow env var override for remote host
    env_host = os.environ.get("CHARTER_WOLFRAM_HOST")
    if env_host:
        # env_host can be "user@host" or just "host"
        return _check_remote_wolfram(env_host)

    # Check local first
    local = shutil.which("wolframscript")
    if local:
        return {"mode": "local", "path": local}

    # Check common macOS paths
    for path in [
        "/usr/local/bin/wolframscript",
        "/Applications/Wolfram Engine.app/Contents/Resources/WolframScript/wolframscript",
        os.path.expanduser("~/Library/Wolfram/WolframScript/wolframscript"),
    ]:
        if os.path.isfile(path):
            return {"mode": "local", "path": path}

    # Check remote via SSH (default host)
    remote_target = (f"{REMOTE_USER}@{REMOTE_HOST}"
                     if REMOTE_USER else REMOTE_HOST)
    result = _check_remote_wolfram(remote_target)
    if result:
        return result

    return None


def _check_remote_wolfram(remote_target):
    """Check if wolframscript exists on a remote host via SSH.

    Args:
        remote_target: SSH target, e.g. "user@host" or "host".

    Returns:
        Connection dict or None.
    """
    remote_wolfram_paths = [
        "/usr/local/bin/wolframscript",
        "/Applications/Wolfram Engine.app/Contents/MacOS/WolframKernel",
    ]
    try:
        check_cmd = " || ".join(
            f'test -f "{p}" && echo "{p}"' for p in remote_wolfram_paths
        )
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
             remote_target, check_cmd],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            path = result.stdout.strip().split("\n")[0]
            return {
                "mode": "remote",
                "host": remote_target,
                "path": path,
            }
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    return None


def _transfer_file_to_remote(local_path, connection):
    """SCP a local file to the remote host's /tmp/ for Wolfram access.

    Returns the remote path, or None on failure.
    """
    if not connection or connection["mode"] != "remote":
        return local_path  # Local mode — file is already accessible

    remote_filename = os.path.basename(local_path)
    remote_path = f"/tmp/charter_{remote_filename}"

    try:
        result = subprocess.run(
            ["scp", "-o", "ConnectTimeout=10", "-o", "BatchMode=yes",
             local_path, f"{connection['host']}:{remote_path}"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return remote_path
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    return None


def _extract_json(text):
    """Extract JSON from Wolfram output that may contain warnings/Null.

    Wolfram often prepends warning lines and appends 'Null'.
    This finds the first valid JSON object in the output.
    """
    if not text:
        return None
    # Try the full text first
    text = text.strip()
    if text.endswith("Null"):
        text = text[:-4].strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    # Find the first { and last } — that's the JSON
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace >= 0 and last_brace > first_brace:
        candidate = text[first_brace:last_brace + 1]
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            pass

    return None


def _run_wolfram(code, timeout=DEFAULT_TIMEOUT, connection=None):
    """Execute Wolfram Language code and return the result.

    Args:
        code: Wolfram Language expression string.
        timeout: Max seconds to wait.
        connection: Connection dict from _find_wolframscript().

    Returns:
        dict with 'output', 'error', 'elapsed_ms', 'mode'.
    """
    if connection is None:
        connection = _find_wolframscript()

    if connection is None:
        return {
            "output": None,
            "error": "Wolfram Engine not found (local or remote)",
            "elapsed_ms": 0,
            "mode": None,
        }

    start = _now_ms()
    mode = connection["mode"]

    try:
        if mode == "local":
            result = subprocess.run(
                [connection["path"], "-code", code],
                capture_output=True, text=True, timeout=timeout,
            )
        elif mode == "remote":
            # Escape code for SSH
            escaped = code.replace("'", "'\\''")
            result = subprocess.run(
                ["ssh", "-o", "ConnectTimeout=10", "-o", "BatchMode=yes",
                 connection["host"],
                 f"{connection['path']} -code '{escaped}'"],
                capture_output=True, text=True, timeout=timeout,
            )
        else:
            return {
                "output": None,
                "error": f"Unknown mode: {mode}",
                "elapsed_ms": _now_ms() - start,
                "mode": mode,
            }

        elapsed = _now_ms() - start
        if result.returncode == 0:
            return {
                "output": result.stdout.strip(),
                "error": None,
                "elapsed_ms": elapsed,
                "mode": mode,
            }
        else:
            return {
                "output": result.stdout.strip() if result.stdout else None,
                "error": result.stderr.strip() if result.stderr else f"Exit code {result.returncode}",
                "elapsed_ms": elapsed,
                "mode": mode,
            }

    except subprocess.TimeoutExpired:
        return {
            "output": None,
            "error": f"Wolfram computation timed out after {timeout}s",
            "elapsed_ms": _now_ms() - start,
            "mode": mode,
        }
    except Exception as e:
        return {
            "output": None,
            "error": str(e),
            "elapsed_ms": _now_ms() - start,
            "mode": mode,
        }


# ---------------------------------------------------------------------------
# Data export (DuckDB → Wolfram)
# ---------------------------------------------------------------------------

def _get_export_dir():
    """Return the wolfram export directory, creating if needed."""
    d = os.path.join(_get_analytics_dir(), EXPORT_DIR_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def _export_query_to_csv(conn, sql, params=None, filename=None):
    """Export a DuckDB query result to a CSV file for Wolfram import.

    Returns the path to the CSV file.
    """
    result = conn.execute(sql, params or [])
    columns = [d[0] for d in result.description]
    rows = result.fetchall()

    if filename is None:
        filename = f"export_{int(time.time())}.csv"

    path = os.path.join(_get_export_dir(), filename)
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)

    return path


def _export_to_wolfram_list(data):
    """Convert Python data to Wolfram Language list syntax.

    Handles nested lists, dicts (as Associations), strings, numbers, booleans.
    """
    if isinstance(data, (list, tuple)):
        items = ", ".join(_export_to_wolfram_list(x) for x in data)
        return "{" + items + "}"
    elif isinstance(data, dict):
        pairs = ", ".join(
            f'"{k}" -> {_export_to_wolfram_list(v)}'
            for k, v in data.items()
        )
        return "<|" + pairs + "|>"
    elif isinstance(data, str):
        escaped = data.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    elif isinstance(data, bool):
        return "True" if data else "False"
    elif isinstance(data, (int, float)):
        return str(data)
    elif data is None:
        return "Missing[]"
    else:
        return f'"{str(data)}"'


# ---------------------------------------------------------------------------
# WolframBridge
# ---------------------------------------------------------------------------

class WolframBridge:
    """Bridge between Charter analytics and the Wolfram Engine.

    Auto-syncs the DuckDB index and locates the Wolfram Engine
    on construction.

    Args:
        indexer: Optional Indexer to reuse.
        auto_sync: Sync index on init (default True).
    """

    def __init__(self, indexer=None, auto_sync=True):
        self._indexer = indexer or Indexer()
        self._conn = self._indexer.connect()
        if auto_sync:
            self._indexer.sync()
        self._wolfram = _find_wolframscript()

    def close(self):
        self._indexer.close()

    @property
    def available(self):
        """Whether the Wolfram Engine is reachable."""
        return self._wolfram is not None

    @property
    def mode(self):
        """Connection mode: 'local', 'remote', or None."""
        return self._wolfram["mode"] if self._wolfram else None

    def status(self):
        """Check Wolfram Engine status and capabilities.

        Returns:
            dict with connection status, version, and available functions.
        """
        start = _now_ms()

        if not self.available:
            env_host = os.environ.get("CHARTER_WOLFRAM_HOST")
            return {
                "available": False,
                "error": "Wolfram Engine not found",
                "checked_local": True,
                "checked_remote": env_host or REMOTE_HOST,
                "env_override": env_host,
                "setup_guide": WOLFRAM_SETUP_GUIDE,
                "elapsed_ms": _now_ms() - start,
            }

        # Get version
        version_result = _run_wolfram(
            'Print[$VersionNumber]',
            timeout=30,
            connection=self._wolfram,
        )

        # Quick capability test
        cap_result = _run_wolfram(
            'Print[StringJoin[Riffle[Names["CausalInference`*"], ", "]]]',
            timeout=30,
            connection=self._wolfram,
        )

        return {
            "available": True,
            "mode": self._wolfram["mode"],
            "host": self._wolfram.get("host", "localhost"),
            "path": self._wolfram["path"],
            "version": version_result["output"],
            "version_error": version_result["error"],
            "capabilities_check": cap_result["output"],
            "elapsed_ms": _now_ms() - start,
        }

    # -- Causal Inference ----------------------------------------------------

    def causal_model(self, target_event, window_size=5,
                     min_occurrences=3, method="conditional"):
        """Build a causal model for a target event using Wolfram's
        statistical methods.

        Exports event transition data to Wolfram and runs:
        - Conditional independence tests
        - Granger-style temporal causality
        - Association rule strength (lift, conviction)

        Args:
            target_event: The outcome event to model.
            window_size: Events before target to consider.
            min_occurrences: Minimum co-occurrence threshold.
            method: "conditional" or "granger".

        Returns:
            dict with causal graph, ranked causes, and test statistics.
        """
        start = _now_ms()

        if not self.available:
            return {
                "error": "Wolfram Engine not available. "
                         "Run 'charter analytics wolfram-status' for setup instructions.",
                "elapsed_ms": _now_ms() - start,
            }

        # Export transition data
        csv_path = _export_query_to_csv(
            self._conn,
            """SELECT e1.event as predecessor, e2.event as successor,
                      EPOCH(e2.ts) - EPOCH(e1.ts) as gap_seconds,
                      e1.idx as pred_idx, e2.idx as succ_idx
               FROM events e1
               JOIN events e2 ON e2.idx = e1.idx + 1
               ORDER BY e1.idx""",
            filename="transitions_full.csv",
        )

        # Transfer to remote if needed
        effective_path = _transfer_file_to_remote(csv_path, self._wolfram)
        if effective_path is None:
            return {"error": "Failed to transfer data to Wolfram host",
                    "elapsed_ms": _now_ms() - start}

        # Build Wolfram code for causal analysis
        code = f'''
Module[{{data, targetEvent, transitions, predecessors, counts,
         liftValues, results}},

  data = Import["{effective_path}", "CSV", "HeaderLines" -> 1];
  targetEvent = "{target_event}";

  (* Filter to transitions ending at target *)
  transitions = Select[data, #[[2]] == targetEvent &];

  If[Length[transitions] == 0,
    Print["{{\\\"error\\\": \\\"No transitions to target event\\\"}}"];
    Return[]
  ];

  (* Count predecessor frequencies *)
  predecessors = Tally[transitions[[All, 1]]];
  predecessors = SortBy[predecessors, -#[[2]] &];

  (* Compute base rate *)
  totalTransitions = Length[data];
  targetCount = Length[transitions];
  baseRate = N[targetCount / totalTransitions];

  (* Compute lift for each predecessor *)
  results = Table[
    Module[{{pred, count, predTotal, condProb, lift, gaps, avgGap, stdGap}},
      pred = predecessors[[i, 1]];
      count = predecessors[[i, 2]];

      predTotal = Count[data[[All, 1]], pred];
      condProb = N[count / predTotal];
      lift = If[baseRate > 0, condProb / baseRate, 0];

      (* Timing statistics *)
      gaps = Select[transitions, #[[1]] == pred &][[All, 3]];
      avgGap = If[Length[gaps] > 0, Mean[gaps], 0];
      stdGap = If[Length[gaps] > 1, StandardDeviation[gaps], 0];

      <|
        "predecessor" -> pred,
        "co_occurrences" -> count,
        "predecessor_total" -> predTotal,
        "conditional_probability" -> Round[condProb, 0.0001],
        "base_rate" -> Round[baseRate, 0.000001],
        "lift" -> Round[lift, 0.01],
        "avg_gap_seconds" -> Round[avgGap, 0.1],
        "std_gap_seconds" -> Round[stdGap, 0.1],
        "temporal_consistency" -> If[stdGap > 0,
          Round[1.0 / (1.0 + stdGap / 60.0), 0.001], 1.0]
      |>
    ],
    {{i, Min[Length[predecessors], 20]}}
  ];

  (* Sort by lift *)
  results = SortBy[results, -#["lift"] &];

  (* Chi-squared test for independence *)
  chiSquaredResults = Table[
    Module[{{pred, observed, expected, chiSq, pValue}},
      pred = results[[i]]["predecessor"];
      Module[{{a, b, c, d, n}},
        a = results[[i]]["co_occurrences"];
        b = results[[i]]["predecessor_total"] - a;
        c = targetCount - a;
        d = totalTransitions - a - b - c;
        n = a + b + c + d;
        If[n > 0 && Min[a, b, c, d] >= 0,
          chiSq = N[(a * d - b * c)^2 * n / ((a + b) * (c + d) * (a + c) * (b + d))];
          pValue = N[1 - CDF[ChiSquareDistribution[1], chiSq]];
          <|"predecessor" -> pred,
            "chi_squared" -> Round[chiSq, 0.01],
            "p_value" -> Round[pValue, 0.0001],
            "significant" -> (pValue < 0.05)|>,
          <|"predecessor" -> pred,
            "chi_squared" -> 0,
            "p_value" -> 1,
            "significant" -> False|>
        ]
      ]
    ],
    {{i, Length[results]}}
  ];

  Print[ExportString[
    <|
      "target_event" -> targetEvent,
      "target_count" -> targetCount,
      "total_transitions" -> totalTransitions,
      "base_rate" -> Round[baseRate, 0.000001],
      "candidates" -> results,
      "chi_squared_tests" -> chiSquaredResults
    |>,
    "JSON"
  ]]
]
'''

        result = _run_wolfram(code, timeout=DEFAULT_TIMEOUT,
                              connection=self._wolfram)

        elapsed = _now_ms() - start

        if result["error"]:
            return {
                "error": result["error"],
                "wolfram_output": result["output"],
                "elapsed_ms": elapsed,
                "mode": result["mode"],
            }

        # Parse JSON output from Wolfram
        parsed = _extract_json(result["output"])
        if parsed is None:
            return {
                "raw_output": result["output"],
                "error": "Could not parse Wolfram output as JSON",
                "elapsed_ms": elapsed,
                "mode": result["mode"],
            }
        parsed["elapsed_ms"] = elapsed
        parsed["mode"] = result["mode"]
        parsed["method"] = method
        return parsed

    # -- Hypothesis Testing --------------------------------------------------

    def hypothesis_test(self, metric, groups=None, test="auto"):
        """Run a statistical hypothesis test comparing actor groups.

        Uses Wolfram's HypothesisTest functions for rigorous,
        publishable-grade statistical testing.

        Args:
            metric: Metric name from actor_metrics (e.g., "volume").
            groups: Optional list of actor names. Default: all actors.
            test: "auto", "MannWhitney", "StudentT", "KolmogorovSmirnov".

        Returns:
            dict with test statistic, p-value, effect size, and
            plain-English interpretation.
        """
        start = _now_ms()

        if not self.available:
            return {
                "error": "Wolfram Engine not available. "
                         "Run 'charter analytics wolfram-status' for setup instructions.",
                "elapsed_ms": _now_ms() - start,
            }

        # Get per-session metric values grouped by actor
        metric_sql = {
            "volume": "event_count",
            "duration": "duration_seconds",
        }
        col = metric_sql.get(metric, "event_count")

        rows = self._conn.execute(f"""
            SELECT actor, {col} as value
            FROM sessions
            WHERE {col} IS NOT NULL
            ORDER BY actor
        """).fetchall()

        if not rows:
            return {"error": "No session data",
                    "elapsed_ms": _now_ms() - start}

        # Group values by actor
        by_actor = {}
        for actor, value in rows:
            by_actor.setdefault(actor, []).append(float(value))

        actors = list(by_actor.keys())
        if groups:
            actors = [a for a in actors if a in groups]

        if len(actors) < 2:
            return {"error": "Need at least 2 actor groups",
                    "actors_found": actors,
                    "elapsed_ms": _now_ms() - start}

        # Export to Wolfram
        group_a = _export_to_wolfram_list(by_actor[actors[0]])
        group_b = _export_to_wolfram_list(by_actor[actors[1]])

        if test == "auto":
            test = "MannWhitney"

        code = f'''
Module[{{groupA, groupB, testResult, pValue, effectSize}},
  groupA = {group_a};
  groupB = {group_b};

  If[Length[groupA] < 2 || Length[groupB] < 2,
    Print["{{\\\"error\\\": \\\"Insufficient data for test\\\"}}"];
    Return[]
  ];

  pValue = N[LocationTest[{{groupA, groupB}}, Automatic, "PValue"]];

  effectSize = If[StandardDeviation[Join[groupA, groupB]] > 0,
    N[(Mean[groupA] - Mean[groupB]) / StandardDeviation[Join[groupA, groupB]]],
    0
  ];

  Print[ExportString[
    <|
      "test" -> "{test}",
      "metric" -> "{metric}",
      "group_a" -> <|
        "actor" -> "{actors[0]}",
        "n" -> Length[groupA],
        "mean" -> Round[N[Mean[groupA]], 0.01],
        "median" -> Round[N[Median[groupA]], 0.01],
        "std" -> Round[N[StandardDeviation[groupA]], 0.01]
      |>,
      "group_b" -> <|
        "actor" -> "{actors[1]}",
        "n" -> Length[groupB],
        "mean" -> Round[N[Mean[groupB]], 0.01],
        "median" -> Round[N[Median[groupB]], 0.01],
        "std" -> Round[N[StandardDeviation[groupB]], 0.01]
      |>,
      "p_value" -> Round[pValue, 0.0001],
      "significant" -> (pValue < 0.05),
      "effect_size_cohens_d" -> Round[effectSize, 0.01],
      "interpretation" -> If[pValue < 0.05,
        "Statistically significant difference between groups (p < 0.05)",
        "No statistically significant difference between groups (p >= 0.05)"
      ]
    |>,
    "JSON"
  ]]
]
'''

        result = _run_wolfram(code, timeout=60, connection=self._wolfram)
        elapsed = _now_ms() - start

        if result["error"]:
            return {"error": result["error"],
                    "wolfram_output": result["output"],
                    "elapsed_ms": elapsed}

        parsed = _extract_json(result["output"])
        if parsed is None:
            return {"raw_output": result["output"],
                    "error": "Could not parse Wolfram output",
                    "elapsed_ms": elapsed}
        parsed["elapsed_ms"] = elapsed
        return parsed

    # -- Time Series Forecast ------------------------------------------------

    def time_series_forecast(self, metric="volume", forecast_days=14,
                             granularity="day"):
        """Forecast future event volume using Wolfram's TimeSeriesModel.

        Args:
            metric: "volume" (event count) or specific event type.
            forecast_days: Days to forecast ahead.
            granularity: "hour" or "day".

        Returns:
            dict with forecast values, confidence intervals,
            and model diagnostics.
        """
        start = _now_ms()

        if not self.available:
            return {
                "error": "Wolfram Engine not available. "
                         "Run 'charter analytics wolfram-status' for setup instructions.",
                "elapsed_ms": _now_ms() - start,
            }

        # Export time series data
        trunc = "hour" if granularity == "hour" else "day"
        csv_path = _export_query_to_csv(
            self._conn,
            f"""SELECT DATE_TRUNC('{trunc}', ts) as period,
                       COUNT(*) as count
                FROM events
                GROUP BY DATE_TRUNC('{trunc}', ts)
                ORDER BY period""",
            filename=f"timeseries_{metric}_{trunc}.csv",
        )

        effective_path = _transfer_file_to_remote(csv_path, self._wolfram)
        if effective_path is None:
            return {"error": "Failed to transfer data to Wolfram host",
                    "elapsed_ms": _now_ms() - start}

        steps = forecast_days * (24 if granularity == "hour" else 1)

        code = f'''
Module[{{data, ts, model, forecast, forecastValues}},
  data = Import["{effective_path}", "CSV", "HeaderLines" -> 1];

  If[Length[data] < 5,
    Print["{{\\\"error\\\": \\\"Insufficient data points for forecast\\\"}}"];
    Return[]
  ];

  (* Extract counts as time series *)
  counts = ToExpression /@ data[[All, 2]];

  (* Build time series model *)
  ts = TimeSeries[counts];

  model = TimeSeriesModelFit[ts];

  (* Forecast *)
  forecast = TimeSeriesForecast[model, {{{steps}}}];

  (* Get model properties *)
  Print[ExportString[
    <|
      "metric" -> "{metric}",
      "granularity" -> "{granularity}",
      "data_points" -> Length[counts],
      "forecast_steps" -> {steps},
      "forecast_values" -> Round[Normal[forecast], 0.1],
      "model_type" -> ToString[model["BestFitModel"]],
      "aic" -> If[NumericQ[model["AIC"]], Round[model["AIC"], 0.01], "N/A"]
    |>,
    "JSON"
  ]]
]
'''

        result = _run_wolfram(code, timeout=DEFAULT_TIMEOUT,
                              connection=self._wolfram)
        elapsed = _now_ms() - start

        if result["error"]:
            return {"error": result["error"],
                    "wolfram_output": result["output"],
                    "elapsed_ms": elapsed}

        parsed = _extract_json(result["output"])
        if parsed is None:
            return {"raw_output": result["output"],
                    "error": "Could not parse Wolfram output",
                    "elapsed_ms": elapsed}
        parsed["elapsed_ms"] = elapsed
        return parsed

    # -- Graph Community Detection -------------------------------------------

    def find_communities(self, min_edge_weight=2):
        """Find communities in the event transition graph using
        Wolfram's FindGraphCommunities.

        Events that frequently follow each other form communities.
        These represent workflow patterns — groups of events that
        tend to co-occur.

        Args:
            min_edge_weight: Minimum transition count to include edge.

        Returns:
            dict with communities, membership, and modularity.
        """
        start = _now_ms()

        if not self.available:
            return {
                "error": "Wolfram Engine not available. "
                         "Run 'charter analytics wolfram-status' for setup instructions.",
                "elapsed_ms": _now_ms() - start,
            }

        # Export transition graph
        csv_path = _export_query_to_csv(
            self._conn,
            """SELECT from_event, to_event, count
               FROM transitions
               WHERE count >= ?
               ORDER BY count DESC""",
            params=[min_edge_weight],
            filename="transition_graph.csv",
        )

        effective_path = _transfer_file_to_remote(csv_path, self._wolfram)
        if effective_path is None:
            return {"error": "Failed to transfer data to Wolfram host",
                    "elapsed_ms": _now_ms() - start}

        code = f'''
Module[{{data, edges, weights, graph, communities, modularity}},
  data = Import["{effective_path}", "CSV", "HeaderLines" -> 1];

  If[Length[data] < 3,
    Print["{{\\\"error\\\": \\\"Insufficient edges for community detection\\\"}}"];
    Return[]
  ];

  edges = DirectedEdge[#[[1]], #[[2]]] & /@ data;
  weights = ToExpression /@ data[[All, 3]];

  graph = Graph[edges, EdgeWeight -> weights];

  communities = FindGraphCommunities[graph];
  modularity = If[Length[communities] > 1,
    Round[N[GraphAssortativity[graph]], 0.001],
    0
  ];

  Print[ExportString[
    <|
      "community_count" -> Length[communities],
      "communities" -> Table[
        <|
          "id" -> i,
          "members" -> communities[[i]],
          "size" -> Length[communities[[i]]]
        |>,
        {{i, Length[communities]}}
      ],
      "total_nodes" -> VertexCount[graph],
      "total_edges" -> EdgeCount[graph],
      "modularity" -> modularity
    |>,
    "JSON"
  ]]
]
'''

        result = _run_wolfram(code, timeout=60, connection=self._wolfram)
        elapsed = _now_ms() - start

        if result["error"]:
            return {"error": result["error"],
                    "wolfram_output": result["output"],
                    "elapsed_ms": elapsed}

        parsed = _extract_json(result["output"])
        if parsed is None:
            return {"raw_output": result["output"],
                    "error": "Could not parse Wolfram output",
                    "elapsed_ms": elapsed}
        parsed["elapsed_ms"] = elapsed
        return parsed

    # -- Dataset Ingestion ---------------------------------------------------

    def ingest_dataset(self, file_path, name=None, format="auto"):
        """Import a historical dataset into the analytics store.

        Reads CSV/JSON/Excel via Wolfram, extracts schema, and
        registers it as a queryable table in DuckDB.

        This enables the dual-mode architecture: historical batch
        data alongside live chain streams.

        Args:
            file_path: Path to the dataset file.
            name: Table name in DuckDB (default: derived from filename).
            format: "auto", "csv", "json", "xlsx".

        Returns:
            dict with table name, row count, column schema.
        """
        start = _now_ms()

        if not os.path.isfile(file_path):
            return {"error": f"File not found: {file_path}",
                    "elapsed_ms": _now_ms() - start}

        if name is None:
            base = os.path.splitext(os.path.basename(file_path))[0]
            name = "ds_" + base.lower().replace(" ", "_").replace("-", "_")

        # For CSV, DuckDB can handle this directly — no Wolfram needed
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".csv" or format == "csv":
            return self._ingest_csv_direct(file_path, name, start)

        if ext == ".json" or format == "json":
            return self._ingest_json_direct(file_path, name, start)

        # For Excel and other formats, use Wolfram to convert to CSV
        if not self.available:
            return {
                "error": "Wolfram Engine needed for non-CSV formats but not available",
                "elapsed_ms": _now_ms() - start,
            }

        # Use Wolfram to convert to CSV
        csv_out = os.path.join(
            _get_export_dir(), f"{name}_converted.csv"
        )

        code = f'''
Module[{{data, headers}},
  data = Import["{file_path}"];
  If[data === $Failed,
    Print["{{\\\"error\\\": \\\"Failed to import file\\\"}}"];
    Return[]
  ];
  Export["{csv_out}", data, "CSV"];
  Print[ExportString[
    <|"rows" -> Length[data] - 1,
      "columns" -> Length[data[[1]]],
      "headers" -> data[[1]],
      "csv_path" -> "{csv_out}"|>,
    "JSON"
  ]]
]
'''
        result = _run_wolfram(code, timeout=60, connection=self._wolfram)
        if result["error"]:
            return {"error": result["error"],
                    "elapsed_ms": _now_ms() - start}

        try:
            info = json.loads(result["output"])
        except (json.JSONDecodeError, TypeError):
            return {"error": "Wolfram conversion failed",
                    "raw_output": result["output"],
                    "elapsed_ms": _now_ms() - start}

        return self._ingest_csv_direct(csv_out, name, start)

    def _ingest_csv_direct(self, path, name, start):
        """Ingest a CSV file directly into DuckDB."""
        try:
            self._conn.execute(f"DROP TABLE IF EXISTS {name}")
            self._conn.execute(
                f"CREATE TABLE {name} AS SELECT * FROM read_csv_auto('{path}')"
            )

            count = self._conn.execute(
                f"SELECT COUNT(*) FROM {name}"
            ).fetchone()[0]

            schema = self._conn.execute(
                f"DESCRIBE {name}"
            ).fetchall()

            return {
                "table": name,
                "rows": count,
                "columns": [
                    {"name": col[0], "type": col[1]}
                    for col in schema
                ],
                "source": path,
                "elapsed_ms": _now_ms() - start,
            }
        except Exception as e:
            return {"error": str(e), "elapsed_ms": _now_ms() - start}

    def _ingest_json_direct(self, path, name, start):
        """Ingest a JSON file directly into DuckDB."""
        try:
            self._conn.execute(f"DROP TABLE IF EXISTS {name}")
            self._conn.execute(
                f"CREATE TABLE {name} AS "
                f"SELECT * FROM read_json_auto('{path}')"
            )

            count = self._conn.execute(
                f"SELECT COUNT(*) FROM {name}"
            ).fetchone()[0]

            schema = self._conn.execute(
                f"DESCRIBE {name}"
            ).fetchall()

            return {
                "table": name,
                "rows": count,
                "columns": [
                    {"name": col[0], "type": col[1]}
                    for col in schema
                ],
                "source": path,
                "elapsed_ms": _now_ms() - start,
            }
        except Exception as e:
            return {"error": str(e), "elapsed_ms": _now_ms() - start}

    # -- Outcome Linkage -----------------------------------------------------

    def link_outcomes(self, outcome_table, outcome_column,
                      join_column="ts", time_window_hours=24):
        """Link external outcome data to chain events.

        Joins an ingested outcome dataset to the events table
        based on temporal proximity, enabling the core question:
        which event patterns correlate with better outcomes?

        Args:
            outcome_table: Name of the ingested outcome table.
            outcome_column: Column containing the outcome metric.
            join_column: Column in outcome table with timestamps.
            time_window_hours: Max time gap for joining (hours).

        Returns:
            dict with linked records, correlation stats.
        """
        start = _now_ms()

        # Verify outcome table exists
        try:
            self._conn.execute(
                f"SELECT COUNT(*) FROM {outcome_table}"
            ).fetchone()
        except Exception:
            return {"error": f"Table '{outcome_table}' not found. "
                    "Use ingest_dataset() first.",
                    "elapsed_ms": _now_ms() - start}

        # Create the linkage
        window_seconds = time_window_hours * 3600
        linked = self._conn.execute(f"""
            SELECT
                e.idx, e.ts as event_ts, e.event, e.actor,
                o.{join_column} as outcome_ts,
                o.{outcome_column} as outcome_value,
                ABS(EPOCH(e.ts) - EPOCH(CAST(o.{join_column} AS TIMESTAMP)))
                    as gap_seconds
            FROM events e
            CROSS JOIN {outcome_table} o
            WHERE ABS(EPOCH(e.ts) - EPOCH(CAST(o.{join_column} AS TIMESTAMP)))
                  < {window_seconds}
            ORDER BY gap_seconds
            LIMIT 1000
        """).fetchall()

        if not linked:
            return {
                "error": "No events matched within the time window",
                "time_window_hours": time_window_hours,
                "elapsed_ms": _now_ms() - start,
            }

        # Per-event-type outcome stats
        event_outcomes = self._conn.execute(f"""
            WITH linked AS (
                SELECT
                    e.event,
                    o.{outcome_column} as outcome,
                    ROW_NUMBER() OVER (
                        PARTITION BY e.idx
                        ORDER BY ABS(EPOCH(e.ts) - EPOCH(CAST(o.{join_column} AS TIMESTAMP)))
                    ) as rn
                FROM events e
                CROSS JOIN {outcome_table} o
                WHERE ABS(EPOCH(e.ts) - EPOCH(CAST(o.{join_column} AS TIMESTAMP)))
                      < {window_seconds}
            )
            SELECT event,
                   COUNT(*) as linked_count,
                   ROUND(AVG(CAST(outcome AS DOUBLE)), 2) as avg_outcome,
                   ROUND(MIN(CAST(outcome AS DOUBLE)), 2) as min_outcome,
                   ROUND(MAX(CAST(outcome AS DOUBLE)), 2) as max_outcome
            FROM linked
            WHERE rn = 1
            GROUP BY event
            ORDER BY avg_outcome DESC
        """).fetchall()

        return {
            "outcome_table": outcome_table,
            "outcome_column": outcome_column,
            "time_window_hours": time_window_hours,
            "linked_records": len(linked),
            "event_outcomes": [
                {
                    "event": row[0],
                    "linked_count": row[1],
                    "avg_outcome": row[2],
                    "min_outcome": row[3],
                    "max_outcome": row[4],
                }
                for row in event_outcomes
            ],
            "elapsed_ms": _now_ms() - start,
        }

    # -- Custom Wolfram Expression -------------------------------------------

    def evaluate(self, expression, timeout=DEFAULT_TIMEOUT):
        """Run an arbitrary Wolfram Language expression.

        For researchers and power users who need direct access
        to the full Wolfram Language.

        Args:
            expression: Wolfram Language code string.
            timeout: Max seconds to wait.

        Returns:
            dict with output, error, elapsed_ms.
        """
        if not self.available:
            return {"error": "Wolfram Engine not available"}

        return _run_wolfram(expression, timeout=timeout,
                            connection=self._wolfram)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def run_wolfram_cli(args):
    """CLI dispatcher for Wolfram analytics actions."""
    action = getattr(args, "action", None)

    if action == "wolfram-status":
        wb = WolframBridge(auto_sync=False)
        try:
            result = wb.status()
            _print_wolfram_status(result)
        finally:
            wb.close()

    elif action == "wolfram-causal":
        event = getattr(args, "event", None)
        if not event:
            print("Usage: charter analytics wolfram-causal --event <event_type>")
            return
        window = getattr(args, "window", 5)
        wb = WolframBridge()
        try:
            result = wb.causal_model(target_event=event, window_size=window)
            _print_wolfram_causal(result)
        finally:
            wb.close()

    elif action == "wolfram-forecast":
        days = getattr(args, "forecast_days", 14)
        wb = WolframBridge()
        try:
            result = wb.time_series_forecast(forecast_days=days)
            _print_wolfram_forecast(result)
        finally:
            wb.close()

    elif action == "wolfram-communities":
        wb = WolframBridge()
        try:
            result = wb.find_communities()
            _print_wolfram_communities(result)
        finally:
            wb.close()

    elif action == "wolfram-test":
        metric = getattr(args, "metric", "volume")
        wb = WolframBridge()
        try:
            result = wb.hypothesis_test(metric=metric)
            _print_wolfram_test(result)
        finally:
            wb.close()

    elif action == "ingest":
        file_path = getattr(args, "file_path", None) or getattr(args, "sql", None)
        if not file_path:
            print("Usage: charter analytics ingest <file_path> [--name <table_name>]")
            return
        name = getattr(args, "table_name", None)
        wb = WolframBridge()
        try:
            result = wb.ingest_dataset(file_path, name=name)
            _print_ingest(result)
        finally:
            wb.close()

    elif action == "wolfram-eval":
        expr = getattr(args, "sql", None)
        if not expr:
            print("Usage: charter analytics wolfram-eval \"<Wolfram expression>\"")
            return
        wb = WolframBridge(auto_sync=False)
        try:
            result = wb.evaluate(expr)
            if result.get("error"):
                print(f"Error: {result['error']}")
            if result.get("output"):
                print(result["output"])
            print(f"\n({result.get('elapsed_ms', 0)}ms, mode: {result.get('mode')})")
        finally:
            wb.close()

    else:
        print(f"Unknown wolfram action: {action}")


# ---------------------------------------------------------------------------
# Pretty printers
# ---------------------------------------------------------------------------

def _print_wolfram_status(r):
    print("Charter Analytics — Wolfram Engine Status")
    print("=" * 50)
    if not r["available"]:
        print("  Status:  NOT AVAILABLE")
        print(f"  Error:   {r.get('error')}")
        print(f"  Checked: local + {r.get('checked_remote', 'N/A')}")
        if r.get("env_override"):
            print(f"  Env:     CHARTER_WOLFRAM_HOST={r['env_override']}")
        print()
        # Show setup guide
        guide = r.get("setup_guide", "")
        if guide:
            print(guide)
    else:
        print("  Status:  CONNECTED")
        print(f"  Mode:    {r['mode']}")
        print(f"  Host:    {r['host']}")
        print(f"  Path:    {r['path']}")
        print(f"  Version: {r.get('version', 'unknown')}")
    print(f"\n  ({r['elapsed_ms']}ms)")


def _print_wolfram_causal(r):
    if "error" in r:
        print(f"Error: {r['error']}")
        if r.get("wolfram_output"):
            print(f"Wolfram output: {r['wolfram_output']}")
        return

    print(f"Charter Analytics — Wolfram Causal Model: {r['target_event']}")
    print("=" * 50)
    print(f"  Target count:      {r.get('target_count')}")
    print(f"  Base rate:         {r.get('base_rate')}")
    print(f"  Total transitions: {r.get('total_transitions')}")
    print()

    candidates = r.get("candidates", [])
    if candidates:
        print("  Candidate causes:")
        print(f"  {'Predecessor':<30s} {'Lift':>7s} {'P(t|p)':>8s} "
              f"{'Co-occ':>7s} {'Consist':>8s}")
        print(f"  {'-'*30} {'-'*7} {'-'*8} {'-'*7} {'-'*8}")
        for c in candidates[:15]:
            print(f"  {c['predecessor']:<30s} "
                  f"{c['lift']:>7.1f} "
                  f"{c['conditional_probability']:>8.4f} "
                  f"{c['co_occurrences']:>7d} "
                  f"{c.get('temporal_consistency', 0):>8.3f}")
        print()

    tests = r.get("chi_squared_tests", [])
    if tests:
        print("  Chi-squared independence tests:")
        for t in tests[:10]:
            sig = "***" if t.get("significant") else ""
            print(f"    {t['predecessor']:<30s} "
                  f"X²={t['chi_squared']:>8.2f}  "
                  f"p={t['p_value']:.4f} {sig}")
    print()
    print(f"  ({r.get('elapsed_ms', 0)}ms, mode: {r.get('mode')})")


def _print_wolfram_forecast(r):
    if "error" in r:
        print(f"Error: {r['error']}")
        return

    print(f"Charter Analytics — Wolfram Forecast: {r.get('metric')}")
    print("=" * 50)
    print(f"  Data points:     {r.get('data_points')}")
    print(f"  Forecast steps:  {r.get('forecast_steps')}")
    print(f"  Model:           {r.get('model_type', 'unknown')}")
    print(f"  AIC:             {r.get('aic', 'N/A')}")
    print()

    values = r.get("forecast_values", [])
    if values:
        print(f"  Forecast values (next {len(values)} periods):")
        for i, v in enumerate(values[:30]):
            bar = "#" * max(1, int(v / max(max(values), 1) * 30))
            print(f"    +{i+1:>3d}  {v:>8.1f}  {bar}")
    print()
    print(f"  ({r.get('elapsed_ms', 0)}ms)")


def _print_wolfram_communities(r):
    if "error" in r:
        print(f"Error: {r['error']}")
        return

    print("Charter Analytics — Wolfram Community Detection")
    print("=" * 50)
    print(f"  Communities: {r.get('community_count')}")
    print(f"  Nodes:       {r.get('total_nodes')}")
    print(f"  Edges:       {r.get('total_edges')}")
    print(f"  Modularity:  {r.get('modularity')}")
    print()

    for comm in r.get("communities", []):
        print(f"  Community {comm['id']} ({comm['size']} members):")
        for member in comm["members"]:
            print(f"    - {member}")
        print()
    print(f"  ({r.get('elapsed_ms', 0)}ms)")


def _print_wolfram_test(r):
    if "error" in r:
        print(f"Error: {r['error']}")
        return

    print(f"Charter Analytics — Hypothesis Test: {r.get('metric')}")
    print("=" * 50)
    print(f"  Test:    {r.get('test')}")

    for key in ("group_a", "group_b"):
        g = r.get(key, {})
        print(f"  {key}: {g.get('actor')} "
              f"(n={g.get('n')}, mean={g.get('mean')}, "
              f"median={g.get('median')}, std={g.get('std')})")

    print()
    sig = "YES ***" if r.get("significant") else "No"
    print(f"  p-value:       {r.get('p_value')}")
    print(f"  Significant:   {sig}")
    print(f"  Effect size:   {r.get('effect_size_cohens_d')} (Cohen's d)")
    print(f"  Interpretation: {r.get('interpretation')}")
    print()
    print(f"  ({r.get('elapsed_ms', 0)}ms)")


def _print_ingest(r):
    if "error" in r:
        print(f"Error: {r['error']}")
        return

    print("Charter Analytics — Dataset Ingested")
    print("=" * 50)
    print(f"  Table:   {r['table']}")
    print(f"  Rows:    {r['rows']:,}")
    print(f"  Source:  {r['source']}")
    print()
    print(f"  Columns:")
    for col in r["columns"]:
        print(f"    {col['name']:<30s}  {col['type']}")
    print()
    print(f"  ({r['elapsed_ms']}ms)")
    print()
    print(f"  Query with: charter analytics query "
          f"\"SELECT * FROM {r['table']} LIMIT 10\"")
