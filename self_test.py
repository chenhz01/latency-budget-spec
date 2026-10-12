# -*- coding: utf-8 -*-
"""self_test for latency-budget-spec — R14, inherits 4-defence template v2."""
import atexit
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", newline="\n")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import latency_budget_spec as m  # noqa: E402

_TMP = tempfile.mkdtemp(prefix="lbs_selftest_")
atexit.register(shutil.rmtree, _TMP, ignore_errors=True)


def wf(name, content):
    p = os.path.join(_TMP, name)
    with open(p, "w", encoding="utf-8", newline="") as f:  # Defence 3
        f.write(content)
    return p


def run_cli(argv):
    buf_out, buf_err = io.StringIO(), io.StringIO()
    code = 0
    try:
        with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
            m.main(argv)
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except Exception as e:  # noqa: BLE001
        code = 1
        buf_err.write(repr(e))
    return code, buf_out.getvalue(), buf_err.getvalue()


def node(name, layer, budget, children=None, **kw):
    d = {"name": name, "layer": layer, "budget_ms": budget,
         "children": children if children is not None else []}
    d.update(kw)
    return d

GOOD_TREE = node("api", "gateway", 300, [
    node("svc", "service", 200, [
        node("db", "db", 100),
        node("cache", "cache", 40)])])
GOOD_MEAS = [{"component": "db", "p50_ms": 20, "p99_ms": 80}]

TREE_OK = wf("b_ok.json", json.dumps(GOOD_TREE))
TREE_BAD = wf("b_bad.json", json.dumps(node("api", "gateway", 10,
                                            [node("svc", "service", 500)])))
TREE_MALFORMED = wf("b_malformed.json", "{oops")
ATTR_OK = wf("attr_ok.json", json.dumps(GOOD_MEAS))
ATTR_MISSING = wf("attr_missing.json", json.dumps([{"component": "ghost", "p50_ms": 1, "p99_ms": 1}]))

# ---- [A] functional: (name, tree, checks, no_errors) ----
A_CASES = [
    ("valid_tree_clean", GOOD_TREE, [], True),
    ("child_sum_exceeds", node("api", "gateway", 100, [node("a", "service", 80), node("b", "service", 80)]),
     [("BUDGET_EXCEEDED", "")], False),
    ("headroom_low_warn", node("api", "gateway", 100, [node("a", "service", 95)]),
     [("HEADROOM_LOW", "")], False),
    ("headroom_exactly_90_ok", node("api", "gateway", 100, [node("a", "service", 90)]), [], True),
    ("invalid_layer", node("api", "proxy", 100), [("LAYER_INVALID", "")], False),
    ("negative_budget", node("api", "gateway", -5), [("BUDGET_INVALID", "")], False),
    ("zero_budget", node("api", "gateway", 0), [("BUDGET_INVALID", "")], False),
    ("bool_budget", node("api", "gateway", True), [("BUDGET_INVALID", "")], False),
    ("string_budget", node("api", "gateway", "300"), [("BUDGET_INVALID", "")], False),
    ("missing_name", node(None, "gateway", 100), [("NAME_MISSING", "")], False),
    ("dup_names", node("api", "gateway", 100, [node("api", "db", 50)]),
     [("NAME_DUP", "api")], False),
    ("children_not_list", {"name": "api", "layer": "gateway", "budget_ms": 100, "children": "x"},
     [("CHILDREN_NOT_LIST", "")], False),
    ("nested_three_levels_clean", GOOD_TREE, [], True),
    ("deep_child_exceeds", node("api", "gateway", 300, [
        node("svc", "service", 200, [node("db", "db", 250)])]),
     [("BUDGET_EXCEEDED", "svc")], False),
    ("float_budget_ok", node("api", "gateway", 100.5), [], True),
    ("no_children_key_ok", {"name": "api", "layer": "gateway", "budget_ms": 100}, [], True),
    ("children_null_ok", {"name": "api", "layer": "gateway", "budget_ms": 100, "children": None}, [], True),
    ("attr_breach_error", GOOD_TREE, [("BUDGET_BREACH", "")], False),
    ("attr_unknown_component", GOOD_TREE, [("UNKNOWN_COMPONENT", "ghost")], False),
    ("attr_near_limit_warn", GOOD_TREE, [("NEAR_LIMIT", "")], False),
    ("attr_valid_clean", GOOD_TREE, [], True),
]


def _mk_a(name, tree, checks, no_errors, meas=None):
    def t(self):
        fs = m.validate_budget(tree)
        if meas is not None:
            fs = fs + m.audit_attribution(tree, meas)
        if no_errors:
            self.assertEqual([f for f in fs if f["severity"] == "ERROR"], [], msg=name)
        for code, sub in checks:
            hit = [f for f in fs if f["code"] == code and sub in f["message"]]
            self.assertTrue(hit, msg="%s expects %s (%r)" % (name, code, sub))
    t.__doc__ = "A: %s" % name
    return t


class TestA(unittest.TestCase):
    def test_a23_breach_from_measurement(self):
        fs = m.audit_attribution(GOOD_TREE, [{"component": "db", "p50_ms": 10, "p99_ms": 150}])
        self.assertEqual([f for f in fs if f["code"] == "BUDGET_BREACH"][0]["severity"], "ERROR")

    def test_a24_p99_equal_budget_no_breach(self):
        fs = m.audit_attribution(GOOD_TREE, [{"component": "db", "p50_ms": 10, "p99_ms": 100}])
        self.assertEqual([f for f in fs if f["code"] == "BUDGET_BREACH"], [])

    def test_a25_attr_non_list_raises(self):
        with self.assertRaises(TypeError):
            m.audit_attribution(GOOD_TREE, {"component": "db"})

    def test_a26_tree_list_raises(self):
        with self.assertRaises(TypeError):
            m.validate_budget([GOOD_TREE])

    def test_a27_unmeasured_only_when_true(self):
        tree = node("api", "gateway", 100, [node("db", "db", 50, measured=False)])
        fs = m.audit_attribution(tree, [])
        self.assertEqual([f for f in fs if f["code"] == "UNMEASURED"], [])

    def test_a28_unmeasured_when_true(self):
        tree = node("api", "gateway", 100, [node("db", "db", 50, measured=True)])
        fs = m.audit_attribution(tree, [{"component": "api", "p50_ms": 1, "p99_ms": 5}])
        self.assertEqual([f for f in fs if f["code"] == "UNMEASURED"][0]["severity"], "WARN")


_M = None  # removed in round-2 cleanup

_MEAS_BY_IDX = {
    17: [{"component": "db", "p50_ms": 10, "p99_ms": 150}],
    18: [{"component": "ghost", "p50_ms": 1, "p99_ms": 1}],
    19: [{"component": "db", "p50_ms": 10, "p99_ms": 98}],
    20: [{"component": "db", "p50_ms": 10, "p99_ms": 80}],
}

for _i, _c in enumerate(A_CASES):
    _nm, _tr, _ck, _ne = _c[0], _c[1], _c[2], _c[3]
    _meas = _MEAS_BY_IDX.get(_i, None)
    setattr(TestA, "test_a%02d_%s" % (_i, _nm), _mk_a(_nm, _tr, _ck, _ne, _meas))

# ---- [B] CLI contract ----
B_CASES = [
    ("valid_exit0", TREE_OK, [], 0, "", ""),
    ("invalid_exit1", TREE_BAD, [], 1, "", ""),
    ("json_flag", TREE_OK, ["--json"], 0, '"findings"', ""),
    ("missing_file", None, [], 2, "", "cannot read"),
    ("malformed_json", TREE_MALFORMED, [], 2, "", "not valid JSON"),
    ("attr_ok_exit0", TREE_OK, ["--attribution", ATTR_OK], 0, "", ""),
    ("attr_unknown_exit1", TREE_OK, ["--attribution", ATTR_MISSING], 1, "", ""),
    ("attr_missing_file_exit2", TREE_OK, ["--attribution", "absent_attr.json"], 2, "", "cannot read"),
    ("text_output_summary", TREE_OK, [], 0, "summary:", ""),
    ("json_summary_key", TREE_BAD, ["--json"], 1, '"summary"', ""),
    ("warn_only_exit0", wf("b_warn.json", json.dumps(
        node("api", "gateway", 100, [node("a", "service", 95)]))), [], 0, "", ""),
]


def _mk_b(name, content, extra, code, out_sub="", err_sub=""):
    def t(self):
        path = content if content is not None else os.path.join(_TMP, "absent_%s.json" % name)
        c, out, err = run_cli([path] + extra)
        self.assertEqual(c, code, msg="out=%r err=%r" % (out, err))
        if out_sub:
            self.assertIn(out_sub, out)
        if err_sub:
            self.assertIn(err_sub, err)
    t.__doc__ = "B: %s" % name
    return t


class TestB(unittest.TestCase):
    def test_b11_missing_positional(self):
        c, _out, _err = run_cli([])
        self.assertEqual(c, 2)

    def test_b12_help_exit0(self):
        c, out, _err = run_cli(["--help"])
        self.assertEqual(c, 0)
        self.assertIn("usage:", out)


for _i, (_nm, _ct, _ex, _cd, _os, _es) in enumerate(B_CASES):
    setattr(TestB, "test_b%02d_%s" % (_i, _nm), _mk_b(_nm, _ct, _ex, _cd, _os, _es))

# ---- [C] extreme/edge ----
C_CASES = [
    ("empty_dict_tree", lambda s: s.assertTrue(
        {"NAME_MISSING", "LAYER_INVALID", "BUDGET_INVALID"} <=
        {f["code"] for f in m.validate_budget({})})),
    ("tree_none_raises", lambda s: s.assertRaises(TypeError, m.validate_budget, None)),
    ("tree_str_raises", lambda s: s.assertRaises(TypeError, m.validate_budget, "x")),
    ("chain_50_deep_clean", lambda s: s.assertEqual(
        m.validate_budget(_chain(50)), [])),
    ("chain_each_child_equals_parent_warns", lambda s: s.assertEqual(
        len([f for f in m.validate_budget(_chain_equal(10))
             if f["code"] == "HEADROOM_LOW"]), 9)),
    ("thousand_nodes_clean", lambda s: s.assertEqual(
        len(m.validate_budget(_wide(1000))), 0)),
    ("unicode_name_ok", lambda s: s.assertEqual(
        m.validate_budget(node("网关", "gateway", 100)), [])),
    ("bool_p99_rejected", lambda s: s.assertTrue(any(
        f["code"] == "ATTR_INVALID" for f in m.audit_attribution(
            GOOD_TREE, [{"component": "db", "p50_ms": True, "p99_ms": 10}])))),
    ("negative_p50_rejected", lambda s: s.assertTrue(any(
        f["code"] == "ATTR_INVALID" for f in m.audit_attribution(
            GOOD_TREE, [{"component": "db", "p50_ms": -1, "p99_ms": 10}])))),
    ("missing_component_rejected", lambda s: s.assertTrue(any(
        f["code"] == "ATTR_INVALID" for f in m.audit_attribution(
            GOOD_TREE, [{"p50_ms": 1, "p99_ms": 10}])))),
    ("measurement_not_object", lambda s: s.assertTrue(any(
        f["code"] == "RECORD_NOT_OBJECT" for f in m.audit_attribution(GOOD_TREE, [42])))),
    ("measured_false_no_warn", lambda s: s.assertEqual(
        [f for f in m.audit_attribution(
            node("api", "gateway", 100, [node("db", "db", 50, measured=False)]), [])
         if f["code"] == "UNMEASURED"], [])),
    ("layer_uppercase_invalid", lambda s: s.assertTrue(any(
        f["code"] == "LAYER_INVALID"
        for f in m.validate_budget(node("api", "Gateway", 100))))),
    ("name_with_spaces_ok", lambda s: s.assertEqual(
        m.validate_budget(node("edge gateway", "gateway", 100)), [])),
    ("extra_fields_allowed", lambda s: s.assertEqual(
        m.validate_budget(node("api", "gateway", 100, owner="sre")), [])),
    ("child_zero_budget_skipped_in_sum", lambda s: s.assertEqual(
        [f for f in m.validate_budget(node("api", "gateway", 100,
                                           [node("a", "service", 0), node("b", "service", 50)]))
         if f["code"] == "BUDGET_EXCEEDED"], [])),
    ("p99_just_below_90pct_no_warn", lambda s: s.assertEqual(
        [f for f in m.audit_attribution(
            node("api", "gateway", 100),
            [{"component": "api", "p50_ms": 1, "p99_ms": 89}])
         if f["code"] == "NEAR_LIMIT"], [])),
    ("huge_budget_float_ok", lambda s: s.assertEqual(
        m.validate_budget(node("api", "gateway", 1e12)), [])),
    ("emoji_name_ok", lambda s: s.assertEqual(
        m.validate_budget(node("🚀", "gateway", 100)), [])),
    ("cli_json_roundtrip", lambda s: s.assertEqual(
        json.loads(run_cli([TREE_OK, "--json"])[1])["summary"]["error"], 0)),
    ("cli_directory_exit2", lambda s: s.assertEqual(run_cli([_TMP])[0], 2)),
    ("cli_attr_malformed_exit2", lambda s: s.assertEqual(
        run_cli([TREE_OK, "--attribution", wf("attr_bad.json", "{oops")])[0], 2)),
    ("cli_attr_is_object_exit2", lambda s: s.assertEqual(
        run_cli([TREE_OK, "--attribution",
                 wf("attr_obj.json", json.dumps({"component": "db"}))])[0], 2)),
    ("deep_exceed_message_has_node", lambda s: s.assertTrue(any(
        ("'svc'" in f["message"] or "'db'" in f["message"])
        for f in m.validate_budget(node("api", "gateway", 300, [
            node("svc", "service", 200, [node("db", "db", 150,
                                             [node("idx", "db", 180)])])]))))),
]


def _chain(depth, budget=10 ** 15):
    n = node("n0", "gateway", budget)
    cur = n
    for i in range(1, depth):
        ch = node("n%d" % i, "service", budget // (2 ** i))
        cur["children"] = [ch]
        cur = ch
    return n


def _chain_equal(depth, budget=100):
    n = node("n0", "gateway", budget)
    cur = n
    for i in range(1, depth):
        ch = node("n%d" % i, "service", budget)
        cur["children"] = [ch]
        cur = ch
    return n


def _wide(count):
    root = node("root", "gateway", 10 ** 9)
    root["children"] = [node("leaf%d" % i, "service", 1000) for i in range(count)]
    return root


class TestC(unittest.TestCase):
    pass


for _i, (_nm, _fn) in enumerate(C_CASES):
    setattr(TestC, "test_c%02d_%s" % (_i, _nm), _fn)


# ---- Round-2 additions (v0.1.1): extra extreme-edge coverage ----
class TestR2(unittest.TestCase):
    def test_r2_tiny_float_budget_ok(self):
        self.assertEqual(m.validate_budget(node("api", "gateway", 1e-5)), [])

    def test_r2_chain_200_deep_completes(self):
        root = node("n0", "gateway", 1e9)
        cur = root
        b = 1e9
        for i in range(1, 200):
            b = b * 0.9
            ch = node("n%d" % i, "service", b)
            cur["children"] = [ch]
            cur = ch
        self.assertEqual(m.validate_budget(root), [])

    def test_r2_p99_at_80pct_clean(self):
        fs = m.audit_attribution(node("api", "gateway", 100),
                                 [{"component": "api", "p50_ms": 1, "p99_ms": 80}])
        self.assertEqual(fs, [])

    def test_r2_duplicate_measurement_records(self):
        meas = [{"component": "db", "p50_ms": 10, "p99_ms": 50}] * 2
        fs = m.audit_attribution(GOOD_TREE, meas)
        self.assertEqual([f for f in fs if f["severity"] == "ERROR"], [])

if __name__ == "__main__":
    r = unittest.TextTestRunner(verbosity=0).run(
        unittest.defaultTestLoader.loadTestsFromModule(sys.modules["__main__"]))
    total, fails = r.testsRun, len(r.failures) + len(r.errors)
    print("SUMMARY: PASS %d/%d" % (total - fails, total))  # Defence 4
    sys.exit(0 if fails == 0 else 1)
