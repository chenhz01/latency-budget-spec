# -*- coding: utf-8 -*-
"""latency-budget-spec: layered latency budget schema + attribution audit.

Validates a hierarchical budget tree (gateway/service/db/cache/external):
positive budgets, children sums within parent budget, headroom warnings.
Audits p99 attribution records against declared budgets. Pure stdlib.
"""
import argparse
import json
import sys

__version__ = "0.1.1"

LAYERS = {"gateway", "service", "db", "cache", "external"}


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _walk(node, path, findings, seen, add):
    loc = "$" + "".join(".%s" % p for p in path)
    if not isinstance(node, dict):
        add("NODE_NOT_OBJECT", "ERROR", "budget node must be an object", loc)
        return
    name = node.get("name")
    if not isinstance(name, str) or not name.strip():
        add("NAME_MISSING", "ERROR", "budget node requires non-empty 'name'", loc)
        name = "?"
    elif name in seen:
        add("NAME_DUP", "ERROR", "duplicate node name: %s" % name, loc)
    else:
        seen.add(name)

    layer = node.get("layer")
    if layer not in LAYERS:
        add("LAYER_INVALID", "ERROR",
            "layer must be one of %s" % sorted(LAYERS), loc)

    budget = node.get("budget_ms")
    budget_ok = _is_num(budget) and budget > 0
    if not budget_ok:
        add("BUDGET_INVALID", "ERROR",
            "budget_ms must be a positive number", loc)

    children = node.get("children", [])
    if children is None:
        children = []
    if not isinstance(children, list):
        add("CHILDREN_NOT_LIST", "ERROR", "children must be a list", loc)
        children = []

    if budget_ok and children:
        total = 0.0
        for ch in children:
            cb = ch.get("budget_ms") if isinstance(ch, dict) else None
            if _is_num(cb) and cb > 0:
                total += cb
        if total > budget:
            add("BUDGET_EXCEEDED", "ERROR",
                "children sum %.6g exceeds parent budget %.6g at '%s'" % (total, budget, name), loc)
        elif total > 0.9 * budget:
            add("HEADROOM_LOW", "WARN",
                "children use %.1f%% of parent budget at '%s'" % (100.0 * total / budget, name), loc)

    for ch in children:
        _walk(ch, path + [str(name)], findings, seen, add)


def validate_budget(tree):
    """Validate a budget tree dict; return findings. Raises TypeError if not dict."""
    if not isinstance(tree, dict):
        raise TypeError("budget tree must be a dict")
    findings = []
    seen = set()
    _walk(tree, [], findings, seen,
          lambda code, sev, msg, loc: findings.append(
              {"code": code, "severity": sev, "message": msg, "location": loc}))
    return findings


def _collect_names(node, acc):
    if isinstance(node, dict):
        name = node.get("name")
        if isinstance(name, str) and name.strip():
            acc[name] = node
        for ch in node.get("children") or []:
            _collect_names(ch, acc)
    return acc


def audit_attribution(tree, measurements):
    """Audit p99 attribution records against the budget tree.

    measurements: list of {component, p50_ms, p99_ms}. Raises TypeError on
    non-dict tree or non-list measurements.
    """
    if not isinstance(tree, dict):
        raise TypeError("budget tree must be a dict")
    if not isinstance(measurements, list):
        raise TypeError("measurements must be a list")
    findings = []
    nodes = _collect_names(tree, {})

    def add(code, sev, msg, loc):
        findings.append({"code": code, "severity": sev, "message": msg, "location": loc})

    measured_names = set()
    for i, rec in enumerate(measurements):
        loc = "$.measurements[%d]" % i
        if not isinstance(rec, dict):
            add("RECORD_NOT_OBJECT", "ERROR", "measurement must be an object", loc)
            continue
        comp = rec.get("component")
        if not isinstance(comp, str) or not comp.strip():
            add("ATTR_INVALID", "ERROR",
                "measurement requires non-empty 'component'", loc)
            continue
        measured_names.add(comp)
        if comp not in nodes:
            add("UNKNOWN_COMPONENT", "ERROR",
                "component '%s' not present in budget tree" % comp, loc)
            continue
        p50, p99 = rec.get("p50_ms"), rec.get("p99_ms")
        if not _is_num(p50) or p50 <= 0 or not _is_num(p99) or p99 <= 0:
            add("ATTR_INVALID", "ERROR",
                "p50_ms/p99_ms must be positive numbers", loc)
            continue
        budget = nodes[comp].get("budget_ms")
        if _is_num(budget):
            if p99 > budget:
                add("BUDGET_BREACH", "ERROR",
                    "component '%s' p99 %.6g exceeds budget %.6g" % (comp, p99, budget), loc)
            elif p99 > 0.9 * budget:
                add("NEAR_LIMIT", "WARN",
                    "component '%s' p99 within 10%% of budget" % comp, loc)

    for name, node in nodes.items():
        if node.get("measured") is True and name not in measured_names:
            add("UNMEASURED", "WARN",
                "node '%s' marked measured=true but has no attribution record" % name,
                "$.%s" % name)
    return findings


def summarize(findings):
    out = {"error": 0, "warn": 0, "info": 0}
    for f in findings:
        key = f["severity"].lower()
        out[key] = out.get(key, 0) + 1
    return out


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="latency-budget-spec",
        description="Validate layered latency budget trees and audit p99 "
                    "attribution records against declared budgets.")
    p.add_argument("budget", help="path to budget tree JSON")
    p.add_argument("--attribution", default=None,
                   help="path to attribution JSON: [{component, p50_ms, p99_ms}]")
    p.add_argument("--json", dest="as_json", action="store_true",
                   help="emit findings as JSON")
    a = p.parse_args(argv)

    try:
        with open(a.budget, "r", encoding="utf-8") as f:
            tree = json.load(f)
    except OSError as e:
        print("error: cannot read budget: %s" % e, file=sys.stderr)
        sys.exit(2)
    except ValueError as e:
        print("error: budget is not valid JSON: %s" % e, file=sys.stderr)
        sys.exit(2)

    try:
        findings = validate_budget(tree)
    except TypeError as e:
        print("error: %s" % e, file=sys.stderr)
        sys.exit(2)

    if a.attribution:
        try:
            with open(a.attribution, "r", encoding="utf-8") as f:
                measurements = json.load(f)
            findings += audit_attribution(tree, measurements)
        except OSError as e:
            print("error: cannot read attribution: %s" % e, file=sys.stderr)
            sys.exit(2)
        except ValueError as e:
            print("error: attribution is not valid JSON: %s" % e, file=sys.stderr)
            sys.exit(2)
        except TypeError as e:
            print("error: %s" % e, file=sys.stderr)
            sys.exit(2)

    s = summarize(findings)
    if a.as_json:
        print(json.dumps({"findings": findings, "summary": s},
                         ensure_ascii=False, indent=2))
    else:
        for f in findings:
            print("[%s] %s %s: %s" % (f["severity"], f["location"],
                                      f["code"], f["message"]))
        print("summary: %d error(s), %d warn(s), %d info(s)"
              % (s["error"], s["warn"], s["info"]))
    sys.exit(1 if s["error"] else 0)


if __name__ == "__main__":
    main()
