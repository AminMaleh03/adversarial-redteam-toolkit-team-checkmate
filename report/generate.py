"""Render analysis schema v2 or v3 into an offline HTML/PDF evidence bundle.

No model loading or cross-component imports: analysis JSON is the public interface.
Run ``python -m report.generate --help`` for the file and stdin interfaces.
"""

from __future__ import annotations

import argparse
import base64
import functools
import hashlib
import json
import math
from pathlib import Path
import sys

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

CATEGORIES = ("malformed", "boundary", "perturbation", "encoding", "whitespace", "truncation")
OPERATIONS = {
    "unhandled_5xx": "Unhandled HTTP 5xx",
    "timeouts": "Request timeouts",
    "connection_failures": "Connection failures",
    "service_unavailable": "Failed health checks",
    "slow_responses": "Slow responses",
    "info_leaks": "Information leaks",
    "invalid_input_accepted": "Invalid input accepted",
}
TIERS = ("Critical", "High", "Medium", "Low")
HERE = Path(__file__).resolve().parent
# The real Team Checkmate logo, at the repository root. Embedded as a data: URI so every
# generated report is fully self-contained -- it travels with report.html regardless of
# where the bundle is copied, with no relative asset path and no external fetch.
LOGO_PATH = HERE.parent / "Team Checkmate Logo.png"

# Single source of truth for product identity strings, shared with web/app.py so the active
# product version label never drifts between the web app and generated reports. The archived
# /verified-full/ artifact is a frozen, pre-generated snapshot and is never re-rendered from
# this constant -- only active pages and freshly generated reports read through it.
CREATOR_NAME = "Team Checkmate"
PRODUCT_NAME = "RED LAB"
PRODUCT_TAGLINE = "Adversarial Testing Redefined"
PRODUCT_VERSION_LABEL = "Red Lab v6.5"

V3_REQUIRED_SUMMARY_FIELDS = (
    "target_id", "version", "task_id", "suite_id", "identity", "coverage",
    "category_stats", "operational", "drift", "findings",
    "validity_tier_census", "diagnostic_observations", "review_cases", "limitations",
)


@functools.lru_cache(maxsize=1)
def _logo_data_uri() -> str:
    if not LOGO_PATH.exists():
        raise RuntimeError(
            f"Required logo asset not found: {LOGO_PATH}. Expected the real Team Checkmate "
            "logo at the repository root; refusing to substitute a placeholder."
        )
    return "data:image/png;base64," + base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")


def require(condition, path, message):
    if not condition:
        raise ValueError(f"{path}: {message}")


def obj(value, path, fields=()):
    require(isinstance(value, dict), path, "expected an object")
    for field in fields:
        require(field in value, path, f"missing {field}")
    return value


def string(value, path):
    require(isinstance(value, str) and bool(value.strip()), path, "expected a nonempty string")


def count(value, path):
    require(type(value) is int and value >= 0, path, "expected a nonnegative integer")


def number(value, path, low=0, high=1):
    require(type(value) in (int, float) and math.isfinite(value) and low <= value <= high,
            path, f"expected a finite number between {low} and {high}")


def array(value, path):
    require(isinstance(value, list), path, "expected an array")
    return value


def strings(value, path):
    for item in array(value, path):
        string(item, path)
    require(len(value) == len(set(value)), path, "duplicate values")
    return value


def rate(value, numerator, denominator, path):
    count(numerator, path)
    count(denominator, path)
    require(numerator <= denominator, path, "numerator exceeds denominator")
    if denominator == 0:
        require(value == "N/A", path, "zero denominator requires N/A")
    else:
        number(value, path)
        require(math.isclose(value, numerator / denominator, abs_tol=1e-12),
                path, "rate does not match counts")


def coverage(value, path):
    fields = ("planned", "selected", "completed", "missing", "skipped", "limit_excluded", "coverage_rate")
    obj(value, path, fields)
    for field in fields[:-1]:
        count(value[field], f"{path}.{field}")
    require(value["selected"] + value["skipped"] + value["limit_excluded"] == value["planned"],
            path, "selected/skipped/limit-excluded counts do not partition the plan")
    require(value["completed"] + value["missing"] == value["selected"], path,
            "completed/missing counts do not partition selection")
    # Runner defines empty-plan coverage as 0.0, unlike analysis rate objects.
    expected = value["completed"] / value["planned"] if value["planned"] else 0.0
    number(value["coverage_rate"], path)
    require(math.isclose(round(expected, 6), value["coverage_rate"], abs_tol=1e-12), path, "inconsistent coverage rate")


def group_key(entry):
    return (entry["finding"]["category"], entry["subfamily"], entry["failure_mode"])


def comparison_key(value, path):
    array(value, path)
    require(len(value) == 3, path, "expected category, subfamily and failure mode")
    for part in value:
        string(part, path)
    return tuple(value)


def validate_summary(summary, version):
    path = f"summary_{version}"
    obj(summary, path, ("version", "coverage", "category_stats", "operational", "drift", "findings",
                        "validity_tier_census", "diagnostic_observations", "review_cases", "limitations"))
    require(summary["version"] == version, path, "wrong endpoint version")
    coverage(summary["coverage"], path + ".coverage")
    obj(summary["category_stats"], path + ".category_stats", CATEGORIES)
    require(set(summary["category_stats"]) == set(CATEGORIES), path, "expected exactly six categories")
    for category, stats in summary["category_stats"].items():
        p = f"{path}.category_stats.{category}"
        obj(stats, p, ("failed", "eligible", "failure_rate", "review", "diagnostic", "unevaluable"))
        rate(stats["failure_rate"], stats["failed"], stats["eligible"], p)
        for key in ("review", "diagnostic", "unevaluable"):
            count(stats[key], p + "." + key)
    obj(summary["operational"], path + ".operational", OPERATIONS)
    for key in OPERATIONS:
        count(summary["operational"][key], path + ".operational." + key)
    drift = obj(summary["drift"], path + ".drift", ("eligible_comparisons", "qualifying_flips", "flip_rate",
                "baseline_denominator", "confidence_change", "excluded", "unevaluable", "flip_attack_ids"))
    rate(drift["flip_rate"], drift["qualifying_flips"], drift["eligible_comparisons"], path + ".drift")
    census = obj(drift["baseline_denominator"], path + ".baseline_denominator",
                 ("eligible", "total", "excluded_below_threshold", "excluded_baselines", "no_prediction", "statement", "threshold"))
    for key in ("eligible", "total", "excluded_below_threshold"):
        count(census[key], path + ".baseline_denominator." + key)
    string(census["statement"], path + ".baseline_denominator.statement")
    require(census["threshold"] == 0.6, path, "clean-confidence threshold must be 0.6")
    strings(census["no_prediction"], path + ".no_prediction")
    excluded_ids = []
    for entry in array(census["excluded_baselines"], path + ".excluded_baselines"):
        obj(entry, path, ("baseline_id", "clean_confidence"))
        string(entry["baseline_id"], path)
        number(entry["clean_confidence"], path)
        require(entry["clean_confidence"] < 0.6, path, "excluded baseline meets confidence threshold")
        excluded_ids.append(entry["baseline_id"])
    strings(excluded_ids, path)
    require(not set(excluded_ids) & set(census["no_prediction"]), path, "overlapping baseline exclusions")
    require(len(excluded_ids) == census["excluded_below_threshold"] and
            census["eligible"] + len(excluded_ids) + len(census["no_prediction"]) == census["total"], path,
            "inconsistent baseline census")
    ids = strings(drift["flip_attack_ids"], path + ".flip_attack_ids")
    require(len(ids) == drift["qualifying_flips"], path, "flip count differs from evidence")
    for key in ("excluded", "unevaluable"):
        for value in obj(drift[key], path + "." + key).values():
            count(value, path + "." + key)
    change = obj(drift["confidence_change"], path, ("mean_delta_on_flips", "per_flip"))
    if change["mean_delta_on_flips"] is not None:
        number(change["mean_delta_on_flips"], path, -1, 1)
    flip_ids = []
    for entry in array(change["per_flip"], path):
        obj(entry, path, ("attack_id", "clean_confidence", "attacked_confidence", "delta"))
        string(entry["attack_id"], path)
        number(entry["clean_confidence"], path, 0.6, 1)
        number(entry["attacked_confidence"], path)
        number(entry["delta"], path, -1, 1)
        require(math.isclose(entry["delta"], entry["attacked_confidence"] - entry["clean_confidence"], abs_tol=1e-12),
                path, "inconsistent confidence delta")
        flip_ids.append(entry["attack_id"])
    strings(flip_ids, path)
    require(set(flip_ids) == set(ids), path, "confidence evidence differs from flip IDs")
    expected_mean = sum(e["delta"] for e in change["per_flip"]) / len(ids) if ids else None
    require(change["mean_delta_on_flips"] is None if expected_mean is None else
            change["mean_delta_on_flips"] is not None and math.isclose(change["mean_delta_on_flips"], expected_mean, abs_tol=1e-12),
            path, "inconsistent mean confidence delta")

    groups, finding_ids, census_actual = {}, set(), {}
    for entry in array(summary["findings"], path + ".findings"):
        obj(entry, path, ("finding", "subfamily", "failure_mode", "validity_tiers", "affected_cases"))
        finding = obj(entry["finding"], path, ("finding_id", "title", "category", "severity_score", "severity_tier",
                                                  "description", "remediation", "evidence"))
        for key in ("finding_id", "title", "category", "description", "remediation"):
            string(finding[key], path + "." + key)
        require(finding["category"] in CATEGORIES, path, "unknown finding category")
        require(finding["finding_id"] not in finding_ids, path, "duplicate finding ID")
        finding_ids.add(finding["finding_id"])
        number(finding["severity_score"], path, 0, 100)
        require(finding["severity_tier"] in TIERS, path, "unknown severity tier")
        for key in ("subfamily", "failure_mode"):
            string(entry[key], path + "." + key)
        tiers = strings(entry["validity_tiers"], path + ".validity_tiers")
        require(bool(tiers) and set(tiers) <= {"GOLD", "SILVER"}, path, "findings require GOLD/SILVER scored evidence")
        for tier in tiers:
            census_actual[tier] = census_actual.get(tier, 0) + 1
        ids = strings(finding["evidence"], path + ".evidence")
        count(entry["affected_cases"], path + ".affected_cases")
        require(len(ids) == entry["affected_cases"], path, "affected cases differ from evidence count")
        key = group_key(entry)
        require(key not in groups, path, "duplicate finding group")
        groups[key] = entry
    census_value = obj(summary["validity_tier_census"], path + ".validity_tier_census")
    for key, value in census_value.items():
        require(key in {"GOLD", "SILVER"}, path, "unknown scored validity tier")
        count(value, path)
    require({k: v for k, v in census_value.items() if v} == census_actual, path, "inconsistent finding-tier census")
    for field in ("diagnostic_observations", "review_cases"):
        observation_ids = []
        for entry in array(summary[field], path + "." + field):
            obj(entry, path, ("attack_id", "category", "subfamily"))
            for key in ("attack_id", "category", "subfamily"):
                string(entry[key], path)
            require(entry["category"] in CATEGORIES, path, "unknown observation category")
            if field == "diagnostic_observations":
                obj(entry, path, ("validity_tier", "oracle", "tier_differs_from_diagnostic"))
                require(entry["validity_tier"] in {"GOLD", "SILVER", "REVIEW", "DIAGNOSTIC"}, path, "unknown diagnostic tier")
                require(entry["oracle"] == "diagnostic_no_fixed_oracle", path, "unexpected diagnostic oracle")
                require(type(entry["tier_differs_from_diagnostic"]) is bool, path, "expected diagnostic tier flag")
            observation_ids.append(entry["attack_id"])
        strings(observation_ids, path)
    strings(summary["limitations"], path + ".limitations")
    return groups


def _validate_v2(data):
    """Validate the historical paired-emotion schema; do not rescore it."""
    obj(data, "report", ("schema_version", "summary_v1", "summary_v2", "comparison"))
    require(type(data["schema_version"]) is int and data["schema_version"] == 2, "schema_version", "only version 2 is supported")
    groups = {v: validate_summary(data[f"summary_{v}"], v) for v in ("v1", "v2")}
    comparison = obj(data["comparison"], "comparison", ("fingerprints", "coverage", "limitations"))
    flags = obj(comparison["fingerprints"], "comparison.fingerprints",
                ("planned_match", "manifest_match", "whole_suite_comparable"))
    require(all(type(flags[k]) is bool for k in ("planned_match", "manifest_match", "whole_suite_comparable")),
            "comparison.fingerprints", "expected boolean flags")
    cov = obj(comparison["coverage"], "comparison.coverage",
              ("v1", "v2", "matched_count", "v1_only_count", "v2_only_count", "unavailable_count", "v1_only", "v2_only", "unavailable"))
    for v in ("v1", "v2"):
        require(cov[v] == data[f"summary_{v}"]["coverage"], "comparison.coverage", "differs from version coverage")
    count(cov["matched_count"], "comparison.coverage")
    for key in ("v1_only", "v2_only", "unavailable"):
        strings(cov[key], "comparison.coverage." + key)
        count(cov[key + "_count"], "comparison.coverage." + key)
        require(cov[key + "_count"] == len(cov[key]), "comparison.coverage", "inconsistent unmatched count")
    require(not set(cov["v1_only"]) & set(cov["v2_only"]), "comparison.coverage", "overlapping version-only IDs")
    for v in ("v1", "v2"):
        require(cov["matched_count"] + cov[v + "_only_count"] == cov[v]["completed"],
                "comparison.coverage", "matched/version-only counts differ from completed coverage")
    strings(comparison["limitations"], "comparison.limitations")
    # Presence of the reason is authoritative even if stale comparison fields coexist.
    if "comparison_withheld_reason" in comparison:
        string(comparison["comparison_withheld_reason"], "comparison_withheld_reason")
        return
    require(all(flags[k] for k in ("planned_match", "manifest_match", "whole_suite_comparable")),
            "comparison", "incompatible inputs require a comparison_withheld_reason")
    require(cov["v1"]["planned"] == cov["v2"]["planned"] and
            cov["matched_count"] + cov["unavailable_count"] == cov["v1"]["planned"],
            "comparison.coverage", "compatible plan not partitioned by matched/unavailable cases")
    obj(comparison, "comparison", ("finding_comparisons", "new_finding_evidence", "inconclusive_new_findings",
                                    "category_failure_rates", "operational", "drift"))
    for v in ("v1", "v2"):
        require(obj(comparison["operational"], "comparison.operational", (v,))[v] == data[f"summary_{v}"]["operational"],
                "comparison.operational", "differs from version summary")
        d = data[f"summary_{v}"]["drift"]
        for key in ("qualifying_flips", "eligible_comparisons", "flip_rate"):
            require(obj(comparison["drift"], "comparison.drift", (v + "_" + key,))[v + "_" + key] == d[key],
                    "comparison.drift", "differs from version summary")
        require(comparison["drift"].get(v + "_baseline_denominator") == d["baseline_denominator"]["statement"],
                "comparison.drift", "baseline denominator differs from summary")
    rates = obj(comparison["category_failure_rates"], "comparison.category_failure_rates", CATEGORIES)
    for category in CATEGORIES:
        for v in ("v1", "v2"):
            s = data[f"summary_{v}"]["category_stats"][category]
            require(obj(rates[category], category, (v,))[v] == {"failed": s["failed"], "eligible": s["eligible"], "rate": s["failure_rate"]},
                    "comparison.category_failure_rates", "differs from version summary")
    seen = set()
    for entry in array(comparison["finding_comparisons"], "finding_comparisons"):
        obj(entry, "finding_comparisons", ("key", "status", "remaining_ids", "unavailable_ids", "improved_ids"))
        key = comparison_key(entry["key"], "finding_comparisons.key")
        require(len(key) == 3 and key in groups["v1"] and key not in seen, "finding_comparisons", "unknown or duplicate V1 group")
        seen.add(key)
        require(entry["status"] in {"resolved", "remaining", "unavailable"}, "finding_comparisons", "unknown status")
        sets = {k: set(strings(entry[k], "finding_comparisons." + k)) for k in ("remaining_ids", "unavailable_ids", "improved_ids")}
        original = set(groups["v1"][key]["finding"]["evidence"])
        v2_ids = set(groups["v2"].get(key, {}).get("finding", {}).get("evidence", []))
        require(sets["remaining_ids"] == v2_ids and sets["unavailable_ids"] <= original and sets["improved_ids"] <= original,
                "finding_comparisons", "evidence does not join finding groups")
        require(not (sets["remaining_ids"] & sets["unavailable_ids"] or sets["remaining_ids"] & sets["improved_ids"] or
                     sets["unavailable_ids"] & sets["improved_ids"]), "finding_comparisons", "overlapping evidence statuses")
        require(original <= set.union(*sets.values()), "finding_comparisons", "missing original evidence qualification")
        require((entry["status"] == "remaining" and bool(sets["remaining_ids"])) or
                (entry["status"] == "unavailable" and not v2_ids and bool(sets["unavailable_ids"])) or
                (entry["status"] == "resolved" and not v2_ids and not sets["unavailable_ids"]),
                "finding_comparisons", "status contradicts supplied evidence")
    require(seen == set(groups["v1"]), "finding_comparisons", "missing V1 finding groups")
    new_sets = {}
    for field, ids_field in (("new_finding_evidence", "regression_ids"), ("inconclusive_new_findings", "unavailable_ids")):
        seen = set()
        for entry in array(comparison[field], field):
            obj(entry, field, ("key", ids_field))
            key = comparison_key(entry["key"], field + ".key")
            require(len(key) == 3 and key in groups["v2"] and key not in groups["v1"] and key not in seen, field, "invalid new group")
            seen.add(key)
            ids = set(strings(entry[ids_field], field))
            require(bool(ids) and ids <= set(groups["v2"][key]["finding"]["evidence"]), field, "evidence does not join V2 group")
            require(not ids & new_sets.get(key, set()), field, "overlapping new/inconclusive evidence")
            new_sets.setdefault(key, set()).update(ids)
    require(set(new_sets) == set(groups["v2"]) - set(groups["v1"]), "comparison", "missing new V2 group qualifications")
    for key, ids in new_sets.items():
        require(ids == set(groups["v2"][key]["finding"]["evidence"]), "comparison", "missing new V2 case qualifications")


def _validate_rate_object(value, path):
    value = obj(value, path, ("numerator", "denominator", "rate"))
    count(value["numerator"], path + ".numerator")
    count(value["denominator"], path + ".denominator")
    numerator = value["numerator"]
    denominator = value["denominator"]
    require(numerator <= denominator, path, "numerator exceeds denominator")
    observed = value["rate"]
    if denominator == 0:
        require(observed is None, path + ".rate", "zero denominator must render as null/N/A")
    else:
        require(type(observed) in (int, float) and math.isfinite(observed), path + ".rate", "expected a finite ratio")
        require(0 <= observed <= 1, path + ".rate", "ratio outside 0..1")
        require(abs(observed - numerator / denominator) <= 0.000001, path + ".rate", "rate differs from its counts")
    return value


def _validate_remediation(entry, path, target_id):
    obj(entry, path, ("finding", "subfamily", "failure_mode", "validity_tiers", "affected_cases", "remediation_detail"))
    finding = obj(entry["finding"], path + ".finding", (
        "finding_id", "title", "category", "severity_score", "severity_tier",
        "description", "remediation", "evidence",
    ))
    require(finding["severity_tier"] in TIERS, path + ".finding.severity_tier", "unknown severity tier")
    require(type(finding["remediation"]) is str and finding["remediation"].strip(), path + ".finding.remediation", "required")
    detail = obj(entry["remediation_detail"], path + ".remediation_detail", (
        "rule_id", "rule_version", "rule_sha256", "observed", "significance",
        "diagnosis_confidence", "fix", "verification", "unavailable_evidence",
    ))
    for key in ("rule_id", "rule_version", "rule_sha256", "observed", "significance", "fix"):
        require(type(detail[key]) is str and detail[key].strip(), path + ".remediation_detail." + key, "required")
    require(detail["diagnosis_confidence"] in {"supported", "suspected"}, path + ".remediation_detail.diagnosis_confidence", "unknown value")
    verification = obj(detail["verification"], path + ".remediation_detail.verification", (
        "target_id", "command", "case_set_file", "includes_baselines", "expected",
    ))
    require(verification["target_id"] == target_id, path + ".remediation_detail.verification.target_id", "must verify the affected target")
    require(type(verification["command"]) is str and verification["command"].strip(), path + ".remediation_detail.verification.command", "required")
    require(type(verification["includes_baselines"]) is bool, path + ".remediation_detail.verification.includes_baselines", "expected boolean")
    strings(detail["unavailable_evidence"], path + ".remediation_detail.unavailable_evidence")


def _validate_v3(data):
    require("summary_v1" not in data and "summary_v2" not in data, "schema_version", "version 3 requires the target-aware evaluations envelope")
    obj(data, "report", ("schema_version", "contracts_version", "run_identity", "evaluations", "limitations"))
    require(data["schema_version"] == 3, "schema_version", "only version 2 or 3 is supported")
    require(data["contracts_version"] == "3.0.0", "contracts_version", "unsupported contract version")
    obj(data["run_identity"], "run_identity")
    strings(data["limitations"], "limitations")
    evaluations = array(data["evaluations"], "evaluations")
    require(bool(evaluations), "evaluations", "at least one evaluation is required")
    seen_evaluations = set()
    for index, evaluation in enumerate(evaluations):
        path = f"evaluations[{index}]"
        obj(evaluation, path, ("evaluation_id", "kind", "task_id", "suite_id", "targets", "summaries", "comparison", "coverage", "oces"))
        string(evaluation["evaluation_id"], path + ".evaluation_id")
        evaluation_id = evaluation["evaluation_id"]
        require(evaluation_id not in seen_evaluations, path + ".evaluation_id", "duplicate evaluation")
        seen_evaluations.add(evaluation_id)
        kind = evaluation["kind"]
        require(kind in {"paired", "single"}, path + ".kind", "expected paired or single")
        suite_id = evaluation["suite_id"]
        require(suite_id in {"core", "oces"}, path + ".suite_id", "unknown suite")
        targets = strings(evaluation["targets"], path + ".targets")
        require(len(targets) == (2 if kind == "paired" else 1), path + ".targets", "target count disagrees with kind")
        require(len(set(targets)) == len(targets), path + ".targets", "duplicate target")
        summaries = obj(evaluation["summaries"], path + ".summaries")
        require(set(summaries) == set(targets), path + ".summaries", "keys must match targets")
        declared_categories = None
        for target_id in targets:
            summary_path = path + f".summaries.{target_id}"
            summary = obj(summaries[target_id], summary_path, V3_REQUIRED_SUMMARY_FIELDS)
            require(summary["target_id"] == target_id, summary_path + ".target_id", "identity mismatch")
            require(summary["task_id"] == evaluation["task_id"], summary_path + ".task_id", "task mismatch")
            require(summary["suite_id"] == suite_id, summary_path + ".suite_id", "suite mismatch")
            categories = tuple(summary["category_stats"].keys()) if isinstance(summary["category_stats"], dict) else ()
            require(bool(categories), summary_path + ".category_stats", "declared families are missing")
            if declared_categories is None:
                declared_categories = categories
            else:
                require(set(categories) == set(declared_categories), summary_path + ".category_stats", "paired targets declare different families")
            require(set(categories) <= (set(CATEGORIES) if suite_id == "core" else {"oces.paraphrase", "oces.distractor"}), summary_path + ".category_stats", "family is not declared for this suite")
            array(summary["findings"], summary_path + ".findings")
            for finding_index, entry in enumerate(summary["findings"]):
                _validate_remediation(entry, f"{summary_path}.findings[{finding_index}]", target_id)
            strings(summary["limitations"], summary_path + ".limitations")
        if kind == "single":
            require(evaluation["comparison"] is None, path + ".comparison", "single-target comparison must be null")
        else:
            require(isinstance(evaluation["comparison"], dict), path + ".comparison", "paired comparison is required")
        if suite_id == "core":
            require(isinstance(evaluation["coverage"], dict), path + ".coverage", "core evaluation requires coverage evidence")
            require(evaluation["oces"] is None, path + ".oces", "core evaluation cannot contain OCES results")
        else:
            require(evaluation["coverage"] is None, path + ".coverage", "OCES coverage is expressed by its frozen declarations")
            oces = obj(evaluation["oces"], path + ".oces", ("families",))
            require(set(strings(oces["families"], path + ".oces.families")) == {"oces.paraphrase", "oces.distractor"}, path + ".oces.families", "exactly two OCES families are required")


def validate_report(data):
    """Validate a report input without inventing missing evidence or rescoring it."""
    require(isinstance(data, dict), "report", "expected an object")
    version = data.get("schema_version")
    if version == 2:
        return _validate_v2(data)
    if version == 3:
        return _validate_v3(data)
    raise ValueError(f"schema_version: only version 2 or 3 is supported (got {version!r})")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "JSON", f"duplicate key {key!r}")
        result[key] = value
    return result


def parse_report(raw: bytes):
    def invalid_constant(value):
        raise ValueError(f"JSON: invalid constant {value}")

    try:
        data = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object,
                          parse_constant=invalid_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(f"Invalid UTF-8 analysis JSON: {exc}") from exc
    validate_report(data)
    return data


def percent(value):
    return "N/A" if value == "N/A" else f"{value * 100:.2f}%"


def score_display(finding):
    score = finding["severity_score"]
    # Preserve the supplied tier when display rounding reaches its upper boundary.
    upper = {"Low": 35, "Medium": 60, "High": 85}.get(finding["severity_tier"])
    if upper is not None and score < upper <= round(score, 1):
        return f"<{upper}"
    return f"{score:.1f}".removesuffix(".0")


TEMPLATE_BY_MODE = {"full": "template.html", "demo": "demo_template.html"}


def rate_object(value):
    if not isinstance(value, dict):
        return "N/A"
    ratio = value.get("rate")
    denominator = value.get("denominator")
    numerator = value.get("numerator")
    if ratio is None:
        return f"N/A ({numerator}/{denominator})"
    return f"{ratio * 100:.2f}% ({numerator}/{denominator})"


def _environment():
    env = Environment(loader=FileSystemLoader(HERE), autoescape=select_autoescape(("html",)),
                      undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True)
    env.filters.update(percent=percent, score=score_display, label=lambda s: s.replace("_", " "),
                       delta=lambda v: "N/A" if v is None else f"{v:+.4f}",
                       rate_object=rate_object)
    return env


def render_html(data, *, source_sha256, include_pdf=True, mode="full"):
    require(mode in TEMPLATE_BY_MODE, "mode", f"unknown report mode {mode!r}")
    validate_report(data)
    env = _environment()
    if data["schema_version"] == 3:
        return env.get_template("template_v3.html").render(
            data=data, source_sha256=source_sha256, include_pdf=include_pdf, mode=mode,
            css=HERE.joinpath("style.css").read_text(encoding="utf-8"),
            logo_data_uri=_logo_data_uri(), creator_name=CREATOR_NAME,
            product_name=PRODUCT_NAME, product_tagline=PRODUCT_TAGLINE,
            product_version_label=PRODUCT_VERSION_LABEL,
        )
    comparison = data["comparison"]
    withheld = comparison.get("comparison_withheld_reason")
    # No inferred status. Absent evidence stays absent; stale fields are ignored when withheld.
    rows = [] if withheld else comparison["finding_comparisons"]
    statuses = {tuple(r["key"]): r for r in rows}
    new = {} if withheld else {tuple(r["key"]): r for r in comparison["new_finding_evidence"]}
    uncertain = {} if withheld else {tuple(r["key"]): r for r in comparison["inconclusive_new_findings"]}
    versions = []
    for v in ("v1", "v2"):
        summary = data[f"summary_{v}"]
        entries = []
        for i, entry in enumerate(sorted(summary["findings"], key=lambda e: (TIERS.index(e["finding"]["severity_tier"]),
                                             -e["finding"]["severity_score"], group_key(e)))):
            key = group_key(entry)
            entries.append({**entry, "anchor": f"finding-{v}-{i + 1}", "comparison": statuses.get(key),
                            "new": new.get(key), "inconclusive_new": uncertain.get(key)})
        versions.append({**summary, "entries": entries})
    counts = {status: sum(r["status"] == status for r in rows) for status in ("resolved", "remaining", "unavailable")}
    counts.update(new=len(new), inconclusive_new=len(uncertain), new_groups=len(set(new) | set(uncertain)))
    limitations = list(dict.fromkeys(note for s in [*versions, comparison] for note in s["limitations"]))
    return env.get_template(TEMPLATE_BY_MODE[mode]).render(versions=versions, comparison=comparison, withheld=withheld,
        counts=counts, categories=CATEGORIES, operations=OPERATIONS, tiers=TIERS, limitations=limitations,
        source_sha256=source_sha256, include_pdf=include_pdf, css=HERE.joinpath("style.css").read_text(encoding="utf-8"),
        demo_evidence=data.get("demo_evidence"), mode=mode, logo_data_uri=_logo_data_uri(),
        detailed_report=data.get("detailed_report"), creator_name=CREATOR_NAME,
        product_version_label=PRODUCT_VERSION_LABEL)


def deny_resource(url, *args, **kwargs):
    """The report has inline CSS and no images/fonts to fetch, including local files."""
    raise ValueError("External resource loading is disabled for reports")


def render_pdf(html):
    try:
        from weasyprint import HTML
    except (ImportError, OSError) as exc:
        raise RuntimeError("PDF renderer unavailable. Use --html-only to generate HTML independently.") from exc
    try:
        return HTML(string=html, url_fetcher=deny_resource).write_pdf()
    except Exception as exc:
        raise RuntimeError(f"PDF rendering failed: {exc}") from exc


def generate_report(raw: bytes, output: Path | str, *, html_only=False, mode="full"):
    """Create a NEW bundle directory; failed validation/PDF rendering writes nothing.

    ``mode`` selects presentation only (see TEMPLATE_BY_MODE) -- "full" is the complete
    technical/audit report, "demo" is a short single-page judge-facing report. Both read
    the identical analysis JSON; no scoring or finding semantics differ between them.
    """
    output = Path(output)
    require(not output.exists(), str(output), "output directory already exists; choose a fresh path")
    data = parse_report(raw)
    digest = hashlib.sha256(raw).hexdigest()
    html = render_html(data, source_sha256=digest, include_pdf=not html_only, mode=mode)
    pdf = None if html_only else render_pdf(html)
    files = {"report.html": html.encode("utf-8"), "analysis.json": raw}
    if pdf is not None:
        files["report.pdf"] = pdf
    metadata = {"report_version": 2 if data["schema_version"] == 3 else 1,
                "analysis_schema_version": data["schema_version"], "source_sha256": digest,
                "files": {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}}
    files["export_meta.json"] = (json.dumps(metadata, indent=2) + "\n").encode("utf-8")
    output.mkdir(parents=True, exist_ok=False)
    for name, content in files.items():
        with (output / name).open("xb") as handle:
            handle.write(content)
    return output / "report.html"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Render analysis schema v2 or v3 as an offline HTML/PDF report bundle.")
    parser.add_argument("--input", required=True, help="analysis JSON path, or - to read UTF-8 JSON from stdin")
    parser.add_argument("--out", required=True, type=Path, help="new output directory under results/ (must not already exist)")
    parser.add_argument("--html-only", action="store_true", help="generate HTML without loading WeasyPrint")
    parser.add_argument("--mode", choices=tuple(TEMPLATE_BY_MODE), default="full",
                        help="report presentation: full technical/audit report, or a short demo report")
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.buffer.read() if args.input == "-" else Path(args.input).read_bytes()
        path = generate_report(raw, args.out, html_only=args.html_only, mode=args.mode)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Report generation failed: {exc}", file=sys.stderr)
        return 1
    print(f"HTML: {path}")
    if not args.html_only:
        print(f"PDF:  {args.out / 'report.pdf'}")
    print(f"Source JSON and export hashes: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
