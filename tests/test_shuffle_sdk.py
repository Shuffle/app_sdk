import unittest
import os
import sys
import json
import time
import base64
import hashlib
import zipfile
import logging
import requests
from io import BytesIO
from unittest.mock import patch, MagicMock

# Ensure package root is on sys.path so tests can be executed from any working directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# On Windows, shufflepy imports Unix-only stdlib modules (pty -> tty -> termios).
# Provide lightweight module stubs when running tests on Windows.
try:
    import termios  # noqa: F401
except ModuleNotFoundError:
    import types
    sys.modules["termios"] = types.ModuleType("termios")
    sys.modules["tty"] = types.ModuleType("tty")
    sys.modules["pty"] = types.ModuleType("pty")

import shuffle_sdk.shuffle_sdk as sdk_module
from shuffle_sdk.shuffle_sdk import (
    AppBase,
    shuffle_filters,
    md5,
    sha256,
    md5_base64,
    base64_encode,
    base64_decode,
    shuffle_default,
    random_element,
    json_parse,
    as_object,
    ast_eval,
    escape_string,
    json_escape,
    escape_json,
    escape,
    neat_json,
    flatten,
    last,
    first,
    csv_parse,
    parse_csv,
    format_csv,
    csv_format,
    split,
    url_encode,
    url_decode,
)


def create_test_app(cls=AppBase, **env_overrides):
    """Helper to instantiate AppBase cleanly with optional environment overrides."""
    logger = logging.getLogger("TestAppBaseLogger")
    with patch.dict(os.environ, env_overrides, clear=False):
        app = cls(redis=None, logger=logger, console_logger=logger)
    app.full_execution = {
        "execution_id": "exec-1234",
        "workflow": {
            "id": "wf-1234",
            "execution_org": {"id": "org-1234"},
            "actions": [],
            "branches": [],
            "workflow_variables": [],
        },
        "results": [],
        "execution_variables": [],
        "execution_argument": '{"input": "hello"}',
    }
    app.current_execution_id = "exec-1234"
    app.authorization = "auth-secret-token"
    app.url = "https://shuffler.io"
    app.base_url = "https://shuffler.io"
    return app


def make_mock_post_for_execution(full_execution, extra_responses=None):
    """Helper that returns a side_effect list for requests.post:
    1st call -> /api/v1/streams/results (returns full_execution)
    middle calls -> any extra_responses (e.g. cache, files, unique validation)
    final call -> /api/v1/streams (returns 200 OK)
    """
    streams_resp = MagicMock(status_code=200)
    streams_resp.json.return_value = full_execution

    send_resp = MagicMock(status_code=200, text="OK")
    responses = [streams_resp]
    if extra_responses:
        responses.extend(extra_responses)
    responses.extend([send_resp, send_resp, send_resp])
    return responses


class SampleIntegrationApp(AppBase):
    """A concrete Shuffle App class used for testing action execution, loops, subloops, and integration flows."""

    __version__ = "1.0.0"
    app_name = "sample_integration_app"

    def __init__(self, redis=None, logger=None, console_logger=None):
        super().__init__(redis=redis, logger=logger, console_logger=console_logger)

    def greet(self, name, greeting="Hello"):
        return f"{greeting}, {name}!"

    def combine_three(self, a, b, c="default"):
        return f"{a}:{b}:{c}"

    def echo_value(self, value):
        if isinstance(value, (dict, list)):
            return json.dumps(value)
        return str(value)

    def process_subloop(self, items):
        if isinstance(items, list):
            return {"count": len(items), "joined": "+".join(str(x) for x in items)}
        return {"count": 1, "joined": str(items)}

    def fail_on_bad(self, item):
        if item == "bad":
            raise ValueError("Simulated failure on bad item")
        return f"ok:{item}"

    def process_json(self, payload):
        if isinstance(payload, dict):
            return {"processed": True, "count": len(payload), "keys": sorted(list(payload.keys()))}
        return {"processed": False, "raw": payload}

    def dashed_param_action(self, my_param=""):
        return f"dashed:{my_param}"

    def no_params_action(self):
        return "ran_without_params"

    async def async_action(self, value):
        return f"async:{value}"

    def file_producer_action(self, text):
        return ("produced file", {"filename": "out.txt", "data": text.encode("utf-8")})

    def slow_action(self, delay="0.2"):
        time.sleep(float(delay))
        return "completed_slow"

    def inspect_type_and_value(self, data):
        return json.dumps({"type": type(data).__name__, "value": data})


# =====================================================================
# 1. UNIT TESTS FOR ALL LIQUID FILTER FUNCTIONS
# =====================================================================
class TestLiquidFiltersUnit(unittest.TestCase):
    """Unit tests for all standalone and registered Liquid filter functions."""

    def test_all_custom_filters_registered(self):
        expected_filters = [
            "md5",
            "sha256",
            "md5_base64",
            "base64_encode",
            "base64_decode",
            "shuffle_default",
            "random_element",
            "json_parse",
            "as_object",
            "ast_eval",
            "escape_string",
            "json_escape",
            "escape_json",
            "escape",
            "neat_json",
            "flatten",
            "last",
            "first",
            "csv_parse",
            "parse_csv",
            "format_csv",
            "csv_format",
            "split",
            "url_encode",
            "url_decode",
        ]
        for fname in expected_filters:
            self.assertIn(fname, shuffle_filters.filters, f"Filter '{fname}' not registered in shuffle_filters")

    def test_md5(self):
        self.assertEqual(md5("hello"), hashlib.md5(b"hello").hexdigest())
        self.assertEqual(md5(12345), hashlib.md5(b"12345").hexdigest())
        self.assertEqual(md5(""), hashlib.md5(b"").hexdigest())

    def test_sha256(self):
        self.assertEqual(sha256("hello"), hashlib.sha256(b"hello").hexdigest())
        self.assertEqual(sha256(999), hashlib.sha256(b"999").hexdigest())
        self.assertEqual(sha256(""), hashlib.sha256(b"").hexdigest())

    def test_md5_base64(self):
        foundhash = hashlib.md5(b"hello").hexdigest()
        expected = base64.b64encode(foundhash.encode("utf-8"))
        self.assertEqual(md5_base64("hello"), expected)

    def test_base64_encode(self):
        self.assertEqual(base64_encode("hello world"), "aGVsbG8gd29ybGQ=")
        self.assertEqual(base64_encode(123), base64.b64encode(b"123").decode())
        self.assertEqual(base64_encode(""), "")

    def test_base64_decode(self):
        # Standard base64
        self.assertEqual(base64_decode("aGVsbG8gd29ybGQ="), "hello world")
        # Missing padding (auto-padded by filter)
        self.assertEqual(base64_decode("aGVsbG8gd29ybGQ"), "hello world")
        # URL-safe base64 replacements (- and _)
        url_safe = base64.urlsafe_b64encode(b"subjects?_d=1&x=2").decode()
        self.assertEqual(base64_decode(url_safe), "subjects?_d=1&x=2")

    def test_shuffle_default(self):
        for falsy_or_empty in ["", None, "none", "None", "NIL", "  null  ", "undefined", "UNDEFINED"]:
            self.assertEqual(shuffle_default(falsy_or_empty, "fallback"), "fallback")
        self.assertEqual(shuffle_default("valid_val", "fallback"), "valid_val")
        self.assertEqual(shuffle_default(42, "fallback"), 42)
        self.assertEqual(shuffle_default(["item"], "fallback"), ["item"])

    def test_random_element(self):
        self.assertEqual(random_element([]), "")
        items = ["a", "b", "c"]
        self.assertIn(random_element(items), items)
        self.assertEqual(random_element(["only"]), "only")

    def test_json_parse_and_as_object(self):
        raw = '{"key": "value", "num": 5, "nested": [1, 2]}'
        expected = {"key": "value", "num": 5, "nested": [1, 2]}
        self.assertEqual(json_parse(raw), expected)
        self.assertEqual(as_object(raw), expected)
        with self.assertRaises(json.JSONDecodeError):
            json_parse("not valid json")

    def test_ast_eval(self):
        self.assertEqual(ast_eval("{'a': 1, 'b': [2, 3]}"), {"a": 1, "b": [2, 3]})
        self.assertEqual(ast_eval("[1, 2, 3]"), [1, 2, 3])
        self.assertEqual(ast_eval("('x', 'y')"), ("x", "y"))

    def test_escape_string(self):
        res = escape_string('hello "world" \'test\'')
        self.assertEqual(res, 'hello \\"world\\" \\\'test\\\'')
        # Pre-escaped quotes are normalized without double-escaping
        res2 = escape_string('hello \\"world\\" \\\'test\\\'')
        self.assertEqual(res2, 'hello \\"world\\" \\\'test\\\'')

    def test_json_escape_and_aliases(self):
        raw = 'hello "world" \'test\''
        expected = 'hello \\\\"world\\\\" \\\\\'test\\\\\''
        self.assertEqual(json_escape(raw), expected)
        self.assertEqual(escape_json(raw), expected)
        self.assertEqual(escape(raw), expected)

    def test_neat_json(self):
        raw = '{"b":1,"a":2}'
        expected = json.dumps({"a": 2, "b": 1}, indent=4, sort_keys=True)
        self.assertEqual(neat_json(raw), expected)
        self.assertEqual(neat_json({"b": 1, "a": 2}), expected)

    def test_flatten(self):
        nested = [[1, 2], [3, 4], [5]]
        self.assertEqual(flatten(nested), [1, 2, 3, 4, 5])
        self.assertEqual(flatten([["a", "b"], [], ["c"]]), ["a", "b", "c"])
        self.assertEqual(flatten([]), [])

    def test_first_and_last(self):
        self.assertEqual(first("[10, 20, 30]"), 10)
        self.assertEqual(last("[10, 20, 30]"), 30)
        self.assertEqual(first([10, 20, 30]), 10)
        self.assertEqual(last([10, 20, 30]), 30)
        self.assertEqual(first([]), "")
        self.assertEqual(last([]), "")
        self.assertEqual(first("[]"), "")
        self.assertEqual(last("[]"), "")

    def test_csv_parse_and_aliases(self):
        # Single line returns list of lines
        self.assertEqual(csv_parse("col1,col2"), ["col1,col2"])

        # Multi-line standard CSV
        csv_data = "name,role\nalice,admin\nbob,user"
        parsed = json.loads(csv_parse(csv_data))
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]["index"], 0)
        self.assertEqual(parsed[0]["unparsed"], "alice,admin")
        self.assertEqual(parsed[0]["parsed"], {"name": "alice", "role": "admin"})
        self.assertEqual(parsed[1]["index"], 1)
        self.assertEqual(parsed[1]["parsed"], {"name": "bob", "role": "user"})

        # Row with more columns than header (truncates extra columns)
        more_cols = "a,b\n1,2,3,4"
        parsed_more = json.loads(csv_parse(more_cols))
        self.assertEqual(parsed_more[0]["parsed"], {"a": "1", "b": "2"})

        # Row with fewer columns than header (pads with empty strings)
        fewer_cols = "a,b,c\n1"
        parsed_fewer = json.loads(csv_parse(fewer_cols))
        self.assertEqual(parsed_fewer[0]["parsed"], {"a": "1", "b": "", "c": ""})

        # Aliases
        self.assertEqual(parse_csv(csv_data), csv_parse(csv_data))
        self.assertEqual(format_csv(csv_data), csv_parse(csv_data))

    def test_split(self):
        self.assertEqual(json.loads(split("a,b,c", ",")), ["a", "b", "c"])
        self.assertEqual(json.loads(split("abc", "")), ["a", "b", "c"])

    def test_url_encode_and_decode(self):
        encoded = url_encode("hello world/test?a=1&b=2")
        self.assertEqual(encoded, "hello%20world/test%3Fa%3D1%26b%3D2")
        self.assertEqual(url_decode(encoded), "hello world/test?a=1&b=2")
        self.assertEqual(url_decode("hello+world"), "hello world")


# =====================================================================
# 2. LIQUID TEMPLATES, FILTER CHAINS, AND LIQUID LOOPS IN EXECUTE_ACTION
# =====================================================================
class TestLiquidTemplatesAndLoopsIntegration(unittest.TestCase):
    """Tests for parse_liquid inside execute_action: custom filters, standard filters,
    Liquid {% for %} loops, nested {% for %} subloops, conditionals, and auto-fixing."""

    def setUp(self):
        self.app = create_test_app(cls=SampleIntegrationApp)

    def _run_echo_with_liquid(self, liquid_expr, full_exec=None):
        if full_exec is None:
            full_exec = self.app.full_execution
        with patch("shuffle_sdk.shuffle_sdk.requests.post") as mock_post:
            mock_post.side_effect = make_mock_post_for_execution(full_exec)
            action = {
                "id": "act-liq",
                "name": "echo_value",
                "parameters": [
                    {"name": "value", "value": liquid_expr, "variant": "STATIC_VALUE"}
                ],
            }
            self.app.execute_action(action)
            return self.app.action_result

    def test_liquid_custom_filters_in_templates(self):
        # md5 & sha256
        res = self._run_echo_with_liquid('{{ "shuffle" | md5 }}')
        self.assertEqual(res["result"], hashlib.md5(b"shuffle").hexdigest())

        res = self._run_echo_with_liquid('{{ "shuffle" | sha256 }}')
        self.assertEqual(res["result"], hashlib.sha256(b"shuffle").hexdigest())

        # base64_encode -> base64_decode chain
        res = self._run_echo_with_liquid('{{ "secret payload" | base64_encode | base64_decode }}')
        self.assertEqual(res["result"], "secret payload")

        # shuffle_default
        res = self._run_echo_with_liquid('{{ "undefined" | shuffle_default: "recovered" }}')
        self.assertEqual(res["result"], "recovered")

        # json_parse + first / last
        res = self._run_echo_with_liquid('{{ \'["alpha", "beta", "gamma"]\' | first }}')
        self.assertEqual(res["result"], "alpha")

        res = self._run_echo_with_liquid('{{ \'["alpha", "beta", "gamma"]\' | last }}')
        self.assertEqual(res["result"], "gamma")

        # json_parse + flatten
        res = self._run_echo_with_liquid('{{ \'[["a", "b"], ["c", "d"]]\' | json_parse | flatten | join: "-" }}')
        self.assertEqual(res["result"], "a-b-c-d")

        # url_encode + url_decode
        res = self._run_echo_with_liquid('{{ "a b&c=d" | url_encode }}')
        self.assertEqual(res["result"], "a%20b%26c%3Dd")

        # split
        res = self._run_echo_with_liquid('{{ "one|two|three" | split: "|" }}')
        self.assertEqual(json.loads(res["result"]), ["one", "two", "three"])

    def test_liquid_for_loop_and_nested_subloop_in_template(self):
        # 1. Single Liquid {% for %} loop (wild mode uses Python iterables / range)
        tpl_single = "{% for x in range(1, 5) %}{{ x }}{% if x < 4 %},{% endif %}{% endfor %}"
        res = self._run_echo_with_liquid(tpl_single)
        self.assertEqual(res["status"], "SUCCESS")
        self.assertEqual(res["result"], "1,2,3,4")

        # 2. Nested Liquid {% for %} subloop over JSON data from a previous node
        full_exec = {
            "execution_id": "exec-liq-subloop",
            "workflow": {"id": "wf-1", "execution_org": {"id": "org-1"}, "branches": []},
            "results": [
                {
                    "action": {"id": "n1", "label": "teams_node"},
                    "status": "SUCCESS",
                    "result": json.dumps([
                        {"team": "red", "members": ["alice", "bob"]},
                        {"team": "blue", "members": ["charlie"]},
                    ]),
                }
            ],
        }
        tpl_nested = (
            "{% assign teams = '$teams_node' | json_parse %}"
            "{% for t in teams %}"
            "{{ t.team }}:"
            "{% for m in t.members %}{{ m }} {% endfor %};"
            "{% endfor %}"
        )
        res_nested = self._run_echo_with_liquid(tpl_nested, full_exec=full_exec)
        self.assertEqual(res_nested["status"], "SUCCESS")
        self.assertEqual(res_nested["result"], "red:alice bob ;blue:charlie ;")

    def test_liquid_patternfix_autoremoves_unresolved_vars_and_empty_pipes(self):
        # {{ | default: "fallback" }} and {{ $missing.node | default: "fallback2" }}
        tpl = '{{ | default: "fallback1" }}-{{ $missing.node | default: "fallback2" }}'
        res = self._run_echo_with_liquid(tpl)
        self.assertEqual(res["status"], "SUCCESS")
        self.assertEqual(res["result"], "fallback1-fallback2")

    def test_liquid_globals_self_and_singul_accessible(self):
        tpl = "{{ singul.config.url }}|{{ shuffle.config.url }}"
        res = self._run_echo_with_liquid(tpl)
        self.assertEqual(res["status"], "SUCCESS")
        self.assertEqual(res["result"], "https://shuffler.io|https://shuffler.io")


# =====================================================================
# 3. JSON RECURSION, DOT NOTATION, SLICING, AND VARIABLE RESOLUTION
# =====================================================================
class TestRecurseJsonLoopsAndSubloops(unittest.TestCase):
    """Comprehensive tests for recurse_json and get_json_value via execute_action."""

    def setUp(self):
        self.app = create_test_app(cls=SampleIntegrationApp)
        self.complex_node_result = {
            "simple": "hello",
            "nested": {"deep": {"value": "found_deep"}},
            "key_with_underscore": "underscore_val",
            "key with space": "space_val",
            "dotted.key": "dotted_val_1",
            "multi.dotted.key": "dotted_val_2",
            "json_string_field": '{"inner_str_key": "parsed_from_str", "inner_list": [10, 20]}',
            "python_literal_field": "['parsed_from_ast_0', 'parsed_from_ast_1']",
            "users": [
                {"id": "u1", "role": "admin", "tags": ["sec", "ops"]},
                {"id": "u2", "role": "dev", "tags": ["code"]},
                {"id": "u3", "role": "analyst", "tags": ["soc", "threat", "ir"]},
            ],
            "departments": [
                {
                    "name": "Engineering",
                    "teams": [
                        {"team_name": "Platform", "members": [{"handle": "m1"}, {"handle": "m2"}]},
                        {"team_name": "Security", "members": [{"handle": "m3"}]},
                    ],
                },
                {
                    "name": "Operations",
                    "teams": [
                        {"team_name": "IT", "members": [{"handle": "m4"}, {"handle": "m5"}]},
                    ],
                },
            ],
        }

    def _execute_with_node_data(self, expr, action_name="echo_value", extra_params=None, skip_multicheck=False):
        full_exec = {
            "execution_id": "exec-recurse",
            "workflow": {
                "id": "wf-1",
                "execution_org": {"id": "org-1"},
                "branches": [],
                "workflow_variables": [{"name": "wf_var", "value": "from_wf_var"}],
            },
            "results": [
                {
                    "action": {"id": "act-src", "label": "src"},
                    "status": "SUCCESS",
                    "result": json.dumps(self.complex_node_result),
                }
            ],
            "execution_variables": [{"name": "exec_var", "value": "from_exec_var"}],
            "execution_argument": '{"arg_key": "from_exec_arg"}',
        }
        params = [{"name": "value", "value": expr, "variant": "STATIC_VALUE"}]
        if extra_params:
            params = extra_params

        action = {
            "id": "act-test",
            "name": action_name,
            "parameters": params,
        }
        if skip_multicheck:
            action["skip_multicheck"] = True

        with patch("shuffle_sdk.shuffle_sdk.requests.post") as mock_post:
            mock_post.side_effect = make_mock_post_for_execution(full_exec)
            self.app.execute_action(action)
            return self.app.action_result

    def test_standard_and_deep_dot_notation(self):
        self.assertEqual(self._execute_with_node_data("$src.simple")["result"], "hello")
        self.assertEqual(self._execute_with_node_data("$src.nested.deep.value")["result"], "found_deep")

    def test_underscore_and_space_key_interchangeability(self):
        # Querying with space when key has underscore
        # Note: regex matches $src.key_with_underscore; querying $src.key_with_space matches "key with space"
        self.assertEqual(self._execute_with_node_data("$src.key_with_space")["result"], "space_val")
        self.assertEqual(self._execute_with_node_data("$src.key_with_underscore")["result"], "underscore_val")

    def test_dotted_keys_in_json_objects(self):
        self.assertEqual(self._execute_with_node_data("$src.dotted.key")["result"], "dotted_val_1")
        self.assertEqual(self._execute_with_node_data("$src.multi.dotted.key")["result"], "dotted_val_2")

    def test_nested_json_string_and_ast_literal_auto_parsing(self):
        # Traversing into a stringified JSON field seamlessly
        self.assertEqual(
            self._execute_with_node_data("$src.json_string_field.inner_str_key")["result"],
            "parsed_from_str",
        )
        self.assertEqual(
            self._execute_with_node_data("$src.json_string_field.inner_list.#1")["result"],
            "20",
        )
        # Traversing into a Python single-quoted list string via ast.literal_eval fallback
        self.assertEqual(
            self._execute_with_node_data("$src.python_literal_field.#1")["result"],
            "parsed_from_ast_1",
        )

    def test_single_index_selectors_min_max_first_last_end_numeric(self):
        # Numeric index
        self.assertEqual(self._execute_with_node_data("$src.users.#0.id")["result"], "u1")
        self.assertEqual(self._execute_with_node_data("$src.users.#1.id")["result"], "u2")
        self.assertEqual(self._execute_with_node_data("$src.users.#2.id")["result"], "u3")

        # Named boundary selectors: min / first -> index 0
        self.assertEqual(self._execute_with_node_data("$src.users.#min.id")["result"], "u1")
        self.assertEqual(self._execute_with_node_data("$src.users.#first.id")["result"], "u1")

        # Named boundary selectors: max / last / end -> last index (2)
        self.assertEqual(self._execute_with_node_data("$src.users.#max.id")["result"], "u3")
        self.assertEqual(self._execute_with_node_data("$src.users.#last.id")["result"], "u3")
        self.assertEqual(self._execute_with_node_data("$src.users.#end.id")["result"], "u3")

    def test_range_slicing_selectors(self):
        # #0-1 -> first 2 items
        res_0_1 = json.loads(self._execute_with_node_data("$src.users.#0-1.id")["result"])
        self.assertEqual(res_0_1, ["u1", "u2"])

        # #1-max -> items 1 and 2
        res_1_max = json.loads(self._execute_with_node_data("$src.users.#1-max.id")["result"])
        self.assertEqual(res_1_max, ["u2", "u3"])

        # #min-last -> all items 0, 1, 2
        res_min_last = json.loads(self._execute_with_node_data("$src.users.#min-last.id")["result"])
        self.assertEqual(res_min_last, ["u1", "u2", "u3"])

        # #first-1 -> items 0 and 1
        res_first_1 = json.loads(self._execute_with_node_data("$src.users.#first-1.role")["result"])
        self.assertEqual(res_first_1, ["admin", "dev"])

    def test_single_loop_and_nested_subloops(self):
        # 1. Single loop over objects extracting a field: $src.users.#.id
        res_loop = json.loads(self._execute_with_node_data("$src.users.#.id")["result"])
        self.assertEqual(res_loop, ["u1", "u2", "u3"])

        # 2. Single loop ending in .# ($src.users.#)
        res_raw_loop = json.loads(self._execute_with_node_data("$src.users.#")["result"])
        self.assertEqual(len(res_raw_loop), 3)

        # 3. 2-level nested subloop: $src.users.#.tags.#
        # Each user has a list of tags; outer loop iterates per user, passing their tag list to process_subloop
        res_subloop = json.loads(
            self._execute_with_node_data(
                "$src.users.#.tags.#",
                action_name="process_subloop",
                extra_params=[{"name": "items", "value": "$src.users.#.tags.#", "variant": "STATIC_VALUE"}],
            )["result"]
        )
        self.assertEqual(
            res_subloop,
            [
                {"count": 2, "joined": "sec+ops"},
                {"count": 1, "joined": "code"},
                {"count": 3, "joined": "soc+threat+ir"},
            ],
        )

        # 4. Mixed outer loop + inner index selector: $src.users.#.tags.#0
        # Extracts the first tag of each user -> ["sec", "code", "soc"]
        res_outer_loop_inner_idx = json.loads(
            self._execute_with_node_data("$src.users.#.tags.#0")["result"]
        )
        self.assertEqual(res_outer_loop_inner_idx, ["sec", "code", "soc"])

        # 5. Mixed outer index selector + inner loop: $src.users.#2.tags.#
        # Selects 3rd user ("u3") and loops over their 3 tags -> ["soc", "threat", "ir"]
        res_outer_idx_inner_loop = json.loads(
            self._execute_with_node_data("$src.users.#2.tags.#")["result"]
        )
        self.assertEqual(res_outer_idx_inner_loop, ["soc", "threat", "ir"])

        # 6. 3-level nested subloop: $src.departments.#.teams.#.members.#.handle
        res_3_level = json.loads(
            self._execute_with_node_data("$src.departments.#.teams.#.members.#.handle")["result"]
        )
        # Department 0 has [["m1", "m2"], ["m3"]], Department 1 has [["m4", "m5"]]
        self.assertEqual(len(res_3_level), 2)
        self.assertEqual(res_3_level[0], [["m1", "m2"], ["m3"]])
        self.assertEqual(res_3_level[1], [["m4", "m5"]])

    def test_trigger_aliases_and_escaped_dollar(self):
        # All trigger aliases resolve to execution_argument
        for alias in ["$exec", "$webhook", "$schedule", "$userinput", "$email_trigger", "$trigger"]:
            res = self._execute_with_node_data(f"{alias}.arg_key")
            self.assertEqual(res["result"], "from_exec_arg", f"Failed alias {alias}")

        # Escaped dollar \$ is preserved as literal $ without variable expansion
        res_esc = self._execute_with_node_data(r"Cost is \$100 for $src.simple")
        self.assertEqual(res_esc["result"], "Cost is $100 for hello")

    def test_missing_variable_appends_shuffle_variable_error(self):
        res = self._execute_with_node_data("$nonexistent_node.some_field")
        param_names = [p["name"] for p in res["action"]["parameters"]]
        self.assertIn("shuffle_variable_error", param_names)


# =====================================================================
# 4. MULTI-EXECUTION LOOPS, MULTIPLIERS, DEDUPLICATION, AND ERROR HANDLING
# =====================================================================
class TestMultiExecutionAndSubloops(unittest.TestCase):
    """Tests for get_param_multipliers, run_recursed_items, and multi-execution in execute_action."""

    def setUp(self):
        self.app = create_test_app(cls=SampleIntegrationApp)

    @patch("shuffle_sdk.shuffle_sdk.requests.post")
    def test_paired_same_length_loops_run_in_lockstep(self, mock_post):
        """Two list parameters of the same length (3 and 3) should pair 1-to-1 (3 executions, not 9)."""
        full_exec = {
            "execution_id": "exec-paired",
            "workflow": {"id": "wf-1", "execution_org": {"id": "org-1"}, "branches": []},
            "results": [
                {
                    "action": {"id": "n1", "label": "data"},
                    "status": "SUCCESS",
                    "result": json.dumps([
                        {"user": "alice", "greeting": "Hi"},
                        {"user": "bob", "greeting": "Hello"},
                        {"user": "charlie", "greeting": "Hey"},
                    ]),
                }
            ],
        }
        mock_post.side_effect = make_mock_post_for_execution(full_exec)

        action = {
            "id": "act-pair",
            "name": "greet",
            "parameters": [
                {"name": "name", "value": "$data.#.user", "variant": "STATIC_VALUE"},
                {"name": "greeting", "value": "$data.#.greeting", "variant": "STATIC_VALUE"},
            ],
        }
        self.app.execute_action(action)
        self.assertEqual(self.app.action_result["status"], "SUCCESS")
        self.assertEqual(
            json.loads(self.app.action_result["result"]),
            ["Hi, alice!", "Hello, bob!", "Hey, charlie!"],
        )

    @patch("shuffle_sdk.shuffle_sdk.requests.post")
    def test_unequal_length_loops_cartesian_product_multiplier(self, mock_post):
        """Two list parameters of different lengths (2 and 3) should run Cartesian product (2x3 = 6 executions)."""
        full_exec = {
            "execution_id": "exec-cartesian",
            "workflow": {"id": "wf-1", "execution_org": {"id": "org-1"}, "branches": []},
            "results": [
                {
                    "action": {"id": "n1", "label": "node_a"},
                    "status": "SUCCESS",
                    "result": json.dumps({"greetings": ["Hi", "Yo"], "users": ["u1", "u2", "u3"]}),
                }
            ],
        }
        mock_post.side_effect = make_mock_post_for_execution(full_exec)

        action = {
            "id": "act-cart",
            "name": "greet",
            "parameters": [
                {"name": "name", "value": "$node_a.users.#", "variant": "STATIC_VALUE"},
                {"name": "greeting", "value": "$node_a.greetings.#", "variant": "STATIC_VALUE"},
            ],
        }
        self.app.execute_action(action)
        self.assertEqual(self.app.action_result["status"], "SUCCESS")
        results = json.loads(self.app.action_result["result"])
        self.assertEqual(len(results), 6)
        self.assertEqual(
            set(results),
            {"Hi, u1!", "Hi, u2!", "Hi, u3!", "Yo, u1!", "Yo, u2!", "Yo, u3!"},
        )

    @patch("shuffle_sdk.shuffle_sdk.requests.post")
    def test_multiple_loop_variables_in_single_parameter_with_liquid(self, mock_post):
        """Multiple .# references inside the same parameter string + Liquid filter evaluated per iteration."""
        full_exec = {
            "execution_id": "exec-inline-multi",
            "workflow": {"id": "wf-1", "execution_org": {"id": "org-1"}, "branches": []},
            "results": [
                {
                    "action": {"id": "n1", "label": "events"},
                    "status": "SUCCESS",
                    "result": json.dumps([
                        {"host": "srv01", "ip": "10.0.0.1"},
                        {"host": "srv02", "ip": "10.0.0.2"},
                    ]),
                }
            ],
        }
        mock_post.side_effect = make_mock_post_for_execution(full_exec)

        action = {
            "id": "act-inline",
            "name": "echo_value",
            "parameters": [
                {
                    "name": "value",
                    "value": '{{ "$events.#.host ($events.#.ip)" | upcase }}',
                    "variant": "STATIC_VALUE",
                }
            ],
        }
        self.app.execute_action(action)
        self.assertEqual(self.app.action_result["status"], "SUCCESS")
        self.assertEqual(
            json.loads(self.app.action_result["result"]),
            ["SRV01 (10.0.0.1)", "SRV02 (10.0.0.2)"],
        )

    @patch("shuffle_sdk.shuffle_sdk.requests.post")
    def test_empty_loop_returns_empty_json_array(self, mock_post):
        """Looping over an empty array [] should immediately succeed with '[]' without calling the action."""
        full_exec = {
            "execution_id": "exec-empty-loop",
            "workflow": {"id": "wf-1", "execution_org": {"id": "org-1"}, "branches": []},
            "results": [
                {
                    "action": {"id": "n1", "label": "empty_node"},
                    "status": "SUCCESS",
                    "result": '{"items": []}',
                }
            ],
        }
        mock_post.side_effect = make_mock_post_for_execution(full_exec)

        action = {
            "id": "act-empty",
            "name": "greet",
            "parameters": [
                {"name": "name", "value": "$empty_node.items.#.name", "variant": "STATIC_VALUE"}
            ],
        }
        self.app.execute_action(action)
        self.assertEqual(self.app.action_result["status"], "SUCCESS")
        self.assertEqual(self.app.action_result["result"], "[]")

    @patch("shuffle_sdk.shuffle_sdk.requests.post")
    def test_single_item_loop_and_exception_recovery_in_loop(self, mock_post):
        """If one iteration in a loop raises an exception, run_recursed_items captures it as a failure object while other iterations succeed."""
        full_exec = {
            "execution_id": "exec-loop-err",
            "workflow": {"id": "wf-1", "execution_org": {"id": "org-1"}, "branches": []},
            "results": [
                {
                    "action": {"id": "n1", "label": "batch"},
                    "status": "SUCCESS",
                    "result": '["good1", "bad", "good2"]',
                }
            ],
        }
        mock_post.side_effect = make_mock_post_for_execution(full_exec)

        action = {
            "id": "act-batch",
            "name": "fail_on_bad",
            "parameters": [
                {"name": "item", "value": "$batch.#", "variant": "STATIC_VALUE"},
                {"name": "extra_unexpected_arg", "value": "ignored", "variant": "STATIC_VALUE"},
            ],
        }
        self.app.execute_action(action)
        self.assertEqual(self.app.action_result["status"], "SUCCESS")
        results = json.loads(self.app.action_result["result"])
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0], "ok:good1")
        self.assertIsInstance(results[1], dict)
        self.assertFalse(results[1]["success"])
        self.assertIn("Simulated failure on bad item", results[1]["details"])
        self.assertEqual(results[2], "ok:good2")

    @patch("shuffle_sdk.shuffle_sdk.requests.post")
    def test_unique_fields_deduplication_in_multi_execution_all_filtered(self, mock_post):
        """When all loop items are flagged as non-unique by backend, status becomes SKIPPED."""
        full_exec = {
            "execution_id": "exec-uniq-skip",
            "workflow": {"id": "wf-1", "execution_org": {"id": "org-1"}, "branches": []},
            "results": [
                {
                    "action": {"id": "n1", "label": "items"},
                    "status": "SUCCESS",
                    "result": '["dup1", "dup2"]',
                }
            ],
        }
        uniq_resp = MagicMock(status_code=200)
        uniq_resp.json.return_value = {
            "found": [
                hashlib.md5(b"dup1").hexdigest(),
                hashlib.md5(b"dup2").hexdigest(),
            ]
        }
        mock_post.side_effect = make_mock_post_for_execution(full_exec, extra_responses=[uniq_resp])

        action = {
            "id": "act-uniq",
            "app_name": "sample_integration_app",
            "name": "echo_value",
            "parameters": [
                {"name": "value", "value": "$items.#", "variant": "STATIC_VALUE", "unique_toggled": True}
            ],
        }
        sent_payloads = []
        orig_send_result = self.app.send_result

        def capture_send_result(action_result, headers, path):
            sent_payloads.append(json.loads(json.dumps(action_result)))
            return orig_send_result(action_result, headers, path)

        with patch.object(sdk_module, "runtime", "run"), patch.object(
            self.app, "send_result", side_effect=capture_send_result
        ):
            self.app.execute_action(action)

        self.assertGreaterEqual(len(sent_payloads), 1)
        self.assertEqual(sent_payloads[0]["status"], "SKIPPED")
        self.assertIn("values were non-unique", sent_payloads[0]["result"])


# =====================================================================
# 5. APPBASE INITIALIZATION, PROXIES, AND HELPER METHODS
# =====================================================================
class TestAppBaseInitAndHelperMethods(unittest.TestCase):
    """Unit tests for AppBase initialization, environment configuration, Singul, and helper methods."""

    @patch("shuffle_sdk.shuffle_sdk.Singul")
    def test_init_defaults_and_env_vars(self, mock_singul):
        env = {
            "CALLBACK_URL": "http://localhost:5001",
            "BASE_URL": "http://localhost:5002",
            "ACTION": '{"name": "test_act", "parameters": []}',
            "AUTHORIZATION": "my-auth",
            "EXECUTIONID": "my-exec-id",
            "HTTP_PROXY": "http://proxy:8080",
            "HTTPS_PROXY": "https://proxy:8443",
            "NO_PROXY": "localhost, 127.0.0.1",
            "SHUFFLE_APP_PROXY_CONFIG_OVERRIDE": '{"custom": "http://override"}',
        }
        logger = logging.getLogger("InitTest")
        with patch.dict(os.environ, env, clear=False):
            app = AppBase(logger=logger)

        self.assertEqual(app.url, "http://localhost:5001")
        self.assertEqual(app.base_url, "http://localhost:5002")
        self.assertEqual(app.authorization, "my-auth")
        self.assertEqual(app.current_execution_id, "my-exec-id")
        self.assertIsInstance(app.action, dict)
        self.assertEqual(app.action["name"], "test_act")
        self.assertEqual(app.proxy_config["http"], "http://proxy:8080")
        self.assertEqual(app.proxy_config["https"], "https://proxy:8443")
        self.assertEqual(app.proxy_config["http://localhost"], "")
        self.assertEqual(app.proxy_config["https://127.0.0.1"], "")
        self.assertEqual(app.proxy_config["custom"], "http://override")
        mock_singul.assert_called_with(
            auth="my-auth",
            url="http://localhost:5002",
            execution_id="my-exec-id",
        )

    def test_init_noproxy_and_internal_proxy(self):
        env = {
            "SHUFFLE_INTERNAL_HTTP_PROXY": "noproxy",
            "SHUFFLE_INTERNAL_HTTPS_PROXY": "http://internal:9000",
            "BASE_URL": "",
            "CALLBACK_URL": "http://callback.local",
        }
        logger = logging.getLogger("ProxyTest")
        with patch.dict(os.environ, env, clear=False):
            app = AppBase(logger=logger)

        self.assertEqual(app.proxy_config["http"], "")
        self.assertEqual(app.proxy_config["https"], "http://internal:9000")
        self.assertEqual(app.base_url, "http://callback.local")

    @patch("shuffle_sdk.shuffle_sdk.Singul", side_effect=ValueError("bad singul init"))
    def test_init_singul_handles_value_error(self, mock_singul):
        app = create_test_app()
        app.init_singul()
        self.assertIsNone(app.singul)

    def test_run_magic_parser(self):
        app = create_test_app()
        self.assertEqual(app.run_magic_parser(123), 123)
        self.assertEqual(app.run_magic_parser(["a"]), ["a"])
        self.assertEqual(app.run_magic_parser('{"a": 1}'), '{"a": 1}')
        self.assertEqual(app.run_magic_parser("[1, 2]"), "[1, 2]")
        self.assertEqual(app.run_magic_parser("a,"), "a,")
        self.assertEqual(app.run_magic_parser("hello world"), "hello world")
        large = "a,\n" * 40000
        self.assertEqual(app.run_magic_parser(large), large)
        res = app.run_magic_parser("item1\nitem2\nitem3")
        self.assertEqual(json.loads(res), ["item1", "item2", "item3"])

    def test_prepare_response(self):
        app = create_test_app()
        mock_req = MagicMock()
        mock_req.headers = {"Content-Type": "application/json", "X-Test": "1"}
        mock_req.cookies = {"session": "xyz"}
        mock_req.text = '{"hello": "world"}'
        mock_req.status_code = 200
        mock_req.url = "https://example.com/api"

        res = json.loads(app.prepare_response(mock_req))
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], 200)
        self.assertEqual(res["url"], "https://example.com/api")
        self.assertEqual(res["body"], {"hello": "world"})
        self.assertEqual(res["headers"]["X-Test"], "1")
        self.assertEqual(res["cookies"]["session"], "xyz")

        mock_req.text = "plain text response"
        res_plain = json.loads(app.prepare_response(mock_req))
        self.assertEqual(res_plain["body"], "plain text response")

    def test_patternfix_string_liquid_and_json(self):
        app = create_test_app()
        self.assertEqual(
            app.patternfix_string("hello world", {"{{|": '{{ "" |'}, {}, "liquid"),
            "hello world",
        )
        raw = '{"a": {{ | default: [] }}, "b": {{ $test.asd | default: [] }}}'
        fixed = app.patternfix_string(
            raw,
            {"{{|": '{{ "" |'},
            {r"\{\{\s*\$[^|}]+\s*\|": '{{ "" |'},
            inputtype="liquid",
        )
        self.assertIn('{{ "" | default: [] }}', fixed)
        self.assertNotIn("$test.asd", fixed)

        # JSON mode
        valid = '{"a": "1"}'
        self.assertEqual(app.patternfix_string(valid, {}, {}, "json"), valid)
        self.assertEqual(app.patternfix_string("not json", {}, {}, "json"), "not json")

        broken = '{\n"test1": ,\n"test2": $unresolved,\n"test3": "ok"\n}'
        fixed_json = app.patternfix_string(
            broken,
            {},
            {
                r'\"\s*\:\s*,': '": "",',
                r'\"\s*\:\s*\$[^,]+\w*\,': '": "",',
            },
            inputtype="json",
        )
        self.assertEqual(json.loads(fixed_json), {"test1": "", "test2": "", "test3": "ok"})

    def test_validate_condition_all_operators(self):
        app = create_test_app()
        # = / == / equals
        self.assertTrue(app.validate_condition("Hello", "=", "hello"))
        self.assertTrue(app.validate_condition("Hello", "==", "hello"))
        self.assertTrue(app.validate_condition("Hello", "equals", "hello"))
        self.assertFalse(app.validate_condition("Hello", "=", "world"))

        # != / does not equal
        self.assertTrue(app.validate_condition("Hello", "!=", "world"))
        self.assertTrue(app.validate_condition("Hello", "does not equal", "world"))
        self.assertFalse(app.validate_condition("Hello", "!=", "hello"))

        # startswith / endswith / contains
        self.assertTrue(app.validate_condition("ShuffleSDK", "startswith", "shuffle"))
        self.assertTrue(app.validate_condition("ShuffleSDK", "endswith", "sdk"))
        self.assertTrue(app.validate_condition("ShuffleSDK", "contains", "fles"))
        self.assertFalse(app.validate_condition("ShuffleSDK", "contains", "xyz"))

        # is empty / is_empty
        self.assertTrue(app.validate_condition("", "is empty", ""))
        self.assertTrue(app.validate_condition("[]", "is_empty", ""))
        self.assertFalse(app.validate_condition('["a"]', "is_empty", ""))
        self.assertFalse(app.validate_condition("nonempty", "is empty", ""))

        # contains_any_of
        self.assertTrue(app.validate_condition("error: timeout", "contains_any_of", "warn, timeout"))
        self.assertFalse(app.validate_condition("all good", "contains_any_of", "warn, error"))

        # larger than / bigger than / > / >=
        self.assertTrue(app.validate_condition("10", ">", "5"))
        self.assertTrue(app.validate_condition("10", "larger than", "5"))
        self.assertTrue(app.validate_condition("10", "bigger than", "5"))
        self.assertFalse(app.validate_condition("3", ">", "5"))
        self.assertTrue(app.validate_condition('["a", "b", "c"]', ">", "2"))
        self.assertTrue(app.validate_condition("abcdef", ">", "3"))
        self.assertTrue(app.validate_condition("5", ">", "abc"))

        # smaller than / less than / < / <=
        self.assertTrue(app.validate_condition("3", "<", "10"))
        self.assertTrue(app.validate_condition("3", "less than", "10"))
        self.assertTrue(app.validate_condition("3", "smaller than", "10"))
        self.assertFalse(app.validate_condition("10", "<", "3"))
        self.assertTrue(app.validate_condition('["a"]', "<", "3"))
        self.assertTrue(app.validate_condition("2", "<", "abcdef"))

        # regex / re / matches regex
        self.assertTrue(app.validate_condition("user_1234", "re", r"^user_\d+$"))
        self.assertTrue(app.validate_condition("user_1234", "matches regex", r"\d{4}"))
        self.assertFalse(app.validate_condition("user_abcd", "re", r"^\d+$"))
        self.assertFalse(app.validate_condition("text", "re", "[invalid_regex"))
        self.assertFalse(app.validate_condition("a", "unknown_operator", "a"))


# =====================================================================
# 6. BACKEND COMMUNICATION, FILES, AND DATASTORE CACHE
# =====================================================================
class TestBackendCommunicationFilesAndCache(unittest.TestCase):
    """Unit tests for send_result, validate_unique_fields, files, and cache/datastore methods."""

    def setUp(self):
        self.app = create_test_app()

    @patch("shuffle_sdk.shuffle_sdk.requests.post")
    def test_send_result_success_and_logs(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200, text="OK")
        self.app.action = {"name": "my_action", "parameters": [], "run_magic_output": True}
        action_result = {
            "action": self.app.action,
            "authorization": "auth-1",
            "execution_id": "exec-1",
            "result": "item1,item2",
            "status": "EXECUTING",
        }
        self.app.send_result(action_result, {}, "/api/v1/streams")
        self.assertEqual(action_result["status"], "FAILURE")
        self.assertEqual(json.loads(action_result["result"]), ["item1,item2"])
        param_names = [p["name"] for p in action_result["action"]["parameters"]]
        self.assertIn("shuffle_action_logs", param_names)
        mock_post.assert_called_once()

    @patch("shuffle_sdk.shuffle_sdk.requests.post")
    def test_send_result_proxy_error_fallback_and_read_timeout(self, mock_post):
        # 1st attempt raises ProxyError (clears proxy_config), 2nd attempt succeeds
        mock_post.side_effect = [
            requests.exceptions.ProxyError("proxy down"),
            MagicMock(status_code=200, text="OK"),
        ]
        self.app.proxy_config = {"http": "http://badproxy:8080"}
        self.app.action = {"name": "act", "parameters": []}
        action_result = {
            "action": self.app.action,
            "authorization": "auth-1",
            "execution_id": "exec-1",
            "result": "ok",
            "status": "SUCCESS",
        }
        self.app.send_result(action_result, {}, "/api/v1/streams")
        self.assertEqual(self.app.proxy_config, {})
        self.assertEqual(mock_post.call_count, 2)

        # Read timed out breaks immediately without 10 retries
        mock_post.reset_mock()
        mock_post.side_effect = requests.exceptions.RequestException("Read timed out")
        self.app.send_result(action_result, {}, "/api/v1/streams")
        self.assertEqual(mock_post.call_count, 1)

    @patch("shuffle_sdk.shuffle_sdk.requests.post")
    def test_send_result_30mb_cloud_limit(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200, text="OK")
        self.app.base_url = "https://shuffler.io"
        self.app.action = {"name": "big_action", "parameters": []}
        action_result = {
            "action": self.app.action,
            "authorization": "auth-1",
            "execution_id": "exec-1",
            "result": "x" * 30_000_100,
            "status": "SUCCESS",
        }
        self.app.send_result(action_result, {}, "/api/v1/streams")
        self.assertEqual(action_result["status"], "FAILURE")
        body = json.loads(action_result["result"])
        self.assertFalse(body["success"])
        self.assertIn("Result too large", body["reason"])

    @patch("shuffle_sdk.shuffle_sdk.requests.post")
    def test_cache_operations_set_get_delete_and_ttl(self, mock_post):
        # set_key / set_datastore_key / set_cache
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"success": True})
        res_set = self.app.set_key("my_key", '{"nested": 1}', category="cat1", ignore_security_rules=True)
        self.assertTrue(res_set["success"])
        self.assertEqual(res_set["key"], "my_key")

        # get_key / get_datastore_key / get_cache
        mock_post.return_value = MagicMock(
            status_code=200, json=lambda: {"success": True, "value": '{"nested": 1}'}
        )
        res_get = self.app.get_key("my_key", category="cat1")
        self.assertTrue(res_get["success"])
        self.assertEqual(res_get["value"], {"nested": 1})

        # Second call within 5s hits local_storage
        count_before = mock_post.call_count
        res_cached = self.app.get_datastore_key("my_key", category="cat1")
        self.assertEqual(mock_post.call_count, count_before)
        self.assertEqual(res_cached["value"], {"nested": 1})

        # delete_key clears local_storage
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"success": True})
        res_del = json.loads(self.app.delete_key("my_key", category="cat1"))
        self.assertTrue(res_del["success"])
        self.assertEqual(len(self.app.local_storage), 0)

    @patch("shuffle_sdk.shuffle_sdk.requests.get")
    def test_list_category(self, mock_get):
        self.assertFalse(self.app.list_category("")["success"])
        mock_get.return_value = MagicMock(status_code=200, text='[{"key": "k1"}]')
        res = self.app.list_category("alerts", items=10, org_id="custom-org")
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], 200)
        self.assertIn("category=alerts&top=10", res["url"])

    @patch("shuffle_sdk.shuffle_sdk.requests.get")
    @patch("shuffle_sdk.shuffle_sdk.requests.post")
    @patch("shuffle_sdk.shuffle_sdk.requests.put")
    def test_file_operations(self, mock_put, mock_post, mock_get):
        # 1. get_file_namespace_ids / get_file_category_ids
        mock_get.return_value = MagicMock(status_code=200, json=lambda: ["file_123", "file_456"])
        self.assertEqual(self.app.get_file_namespace_ids("ns1"), ["file_123", "file_456"])

        # 2. get_file_category / get_file_namespace returns ZipFile
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            zf.writestr("sample.txt", b"hello zip")
        mock_get.return_value = MagicMock(status_code=200, content=zip_buffer.getvalue())
        zf_res = self.app.get_file_category("ns1")
        self.assertIsInstance(zf_res, zipfile.ZipFile)
        self.assertEqual(zf_res.read("sample.txt"), b"hello zip")

        # 3. get_file with single and multiple valid file_ids
        meta_resp = MagicMock(status_code=200, json=lambda: {"filename": "report.pdf"})
        content_resp = MagicMock(status_code=200, content=b"%PDF-1.4 content")
        mock_get.side_effect = [meta_resp, content_resp]
        file_res = self.app.get_file({"file_id": "file_12345"})
        self.assertTrue(file_res["success"])
        self.assertEqual(file_res["filename"], "report.pdf")
        self.assertEqual(file_res["data"], b"%PDF-1.4 content")
        mock_get.side_effect = None

        # Invalid file ID length/prefix returns failure dict
        self.assertFalse(self.app.get_file("short_id")["success"])

        # 4. set_file / set_files
        create_resp = MagicMock(status_code=200, json=lambda: {"success": True, "id": "file_new_1"})
        upload_resp = MagicMock(status_code=200)
        mock_post.side_effect = [create_resp, upload_resp]
        ids = self.app.set_file({"filename": "test.txt", "data": b"abc", "category": "cat"})
        self.assertEqual(ids, ["file_new_1"])
        mock_post.side_effect = None

        # 5. update_file
        mock_put.return_value = MagicMock(status_code=200, json=lambda: {"success": True})
        self.assertTrue(self.app.update_file("file_new_1", b"updated content")["success"])


# =====================================================================
# 7. END-TO-END APP INTEGRATION TESTS (ALL RUNTIME MODES)
# =====================================================================
class TestEndToEndAppIntegration(unittest.TestCase):
    """End-to-end integration tests running SampleIntegrationApp across all execution modes."""

    def setUp(self):
        self.app = create_test_app(cls=SampleIntegrationApp)

    @patch("shuffle_sdk.shuffle_sdk.requests.post")
    def test_integration_branch_conditions_pass_negated_and_skip(self, mock_post):
        """Verify branch condition evaluation: failing branch -> SKIPPED, negated condition -> SUCCESS."""
        # 1. Failing branch condition -> SKIPPED
        full_exec_fail = {
            "execution_id": "exec-branch-fail",
            "start": "start-node",
            "workflow": {
                "id": "wf-1",
                "execution_org": {"id": "org-1"},
                "branches": [
                    {
                        "source_id": "start-node",
                        "destination_id": "target-node",
                        "conditions": [
                            {
                                "source": {"value": "10", "variant": "STATIC_VALUE"},
                                "condition": {"value": "equals", "configuration": False},
                                "destination": {"value": "20", "variant": "STATIC_VALUE"},
                            }
                        ],
                    }
                ],
            },
            "results": [
                {"action": {"id": "start-node", "label": "start"}, "status": "SUCCESS", "result": "ok"}
            ],
        }
        mock_post.side_effect = make_mock_post_for_execution(full_exec_fail)
        action = {"id": "target-node", "name": "no_params_action", "parameters": []}
        self.app.execute_action(action)
        self.assertEqual(self.app.action_result["status"], "SKIPPED")

        # 2. Negated branch condition (configuration=True on 10 equals 20 -> True) -> SUCCESS
        full_exec_negated = json.loads(json.dumps(full_exec_fail))
        full_exec_negated["workflow"]["branches"][0]["conditions"][0]["condition"]["configuration"] = True
        mock_post.side_effect = make_mock_post_for_execution(full_exec_negated)
        self.app.execute_action(action)
        self.assertEqual(self.app.action_result["status"], "SUCCESS")
        self.assertEqual(self.app.action_result["result"], "ran_without_params")

    @patch("shuffle_sdk.shuffle_sdk.requests.post")
    def test_integration_openapi_body_replacement_and_dashed_params(self, mock_post):
        """Test OpenAPI body value_replace, recurse_cleanup_script, dashed param conversion, and SHUFFLE_AUTO_REMOVED."""
        full_exec = {
            "execution_id": "exec-openapi",
            "workflow": {
                "id": "wf-1",
                "execution_org": {"id": "org-1"},
                "branches": [],
                "actions": [
                    {
                        "id": "act-auto-replace",
                        "parameters": [
                            {"name": "my-param", "value": "restored_from_workflow", "variant": "STATIC_VALUE"}
                        ],
                    }
                ],
            },
            "results": [],
        }
        mock_post.side_effect = make_mock_post_for_execution(full_exec)

        # Action with SHUFFLE_AUTO_REMOVED restores parameters from workflow.actions and normalizes my-param -> my_param
        action = {
            "id": "act-auto-replace",
            "name": "dashed_param_action",
            "parameters": [{"name": "my-param", "value": "SHUFFLE_AUTO_REMOVED"}],
        }
        self.app.execute_action(action)
        self.assertEqual(self.app.action_result["status"], "SUCCESS")
        self.assertEqual(self.app.action_result["result"], "dashed:restored_from_workflow")

    @patch("shuffle_sdk.shuffle_sdk.requests.post")
    def test_integration_async_coroutine_and_tuple_file_upload(self, mock_post):
        """Verify async coroutine actions and tuple (result, file_dict) return handling."""
        full_exec = {
            "execution_id": "exec-async",
            "workflow": {"id": "wf-1", "execution_org": {"id": "org-1"}, "branches": []},
            "results": [],
        }
        # 1. Async coroutine
        mock_post.side_effect = make_mock_post_for_execution(full_exec)
        action_async = {
            "id": "act-async",
            "name": "async_action",
            "parameters": [{"name": "value", "value": "coroutine_ok", "variant": "STATIC_VALUE"}],
        }
        self.app.execute_action(action_async)
        self.assertEqual(self.app.action_result["status"], "SUCCESS")
        self.assertEqual(self.app.action_result["result"], "async:coroutine_ok")

        # 2. Tuple return (result, file_dict) triggers set_files automatically
        create_file_resp = MagicMock(status_code=200, json=lambda: {"success": True, "id": "file_tuple_1"})
        upload_file_resp = MagicMock(status_code=200)
        mock_post.side_effect = make_mock_post_for_execution(
            full_exec, extra_responses=[create_file_resp, upload_file_resp]
        )
        action_tuple = {
            "id": "act-tuple",
            "name": "file_producer_action",
            "parameters": [{"name": "text", "value": "hello file", "variant": "STATIC_VALUE"}],
        }
        self.app.execute_action(action_tuple)
        self.assertEqual(self.app.action_result["status"], "SUCCESS")
        tuple_res = json.loads(self.app.action_result["result"])
        self.assertTrue(tuple_res["success"])
        self.assertEqual(tuple_res["result"], "produced file")
        self.assertEqual(tuple_res["file_ids"], ["file_tuple_1"])

    @patch("shuffle_sdk.shuffle_sdk.requests.post")
    def test_integration_action_timeout_handling(self, mock_post):
        """Verify SHUFFLE_APP_SDK_TIMEOUT enforces execution timeout cleanly."""
        full_exec = {
            "execution_id": "exec-timeout",
            "workflow": {"id": "wf-1", "execution_org": {"id": "org-1"}, "branches": []},
            "results": [],
        }
        mock_post.side_effect = make_mock_post_for_execution(full_exec)
        action = {
            "id": "act-slow",
            "name": "slow_action",
            "parameters": [{"name": "delay", "value": "2.0", "variant": "STATIC_VALUE"}],
        }
        with patch.dict(os.environ, {"SHUFFLE_APP_SDK_TIMEOUT": "0"}, clear=False):
            self.app.execute_action(action)

        res_json = json.loads(self.app.action_result["result"])
        self.assertFalse(res_json["success"])
        self.assertIn("Timeout error", res_json["reason"])

    @patch("shuffle_sdk.shuffle_sdk.requests.post")
    def test_integration_standalone_cli_execution(self, mock_post):
        """Run SampleIntegrationApp via standalone CLI arguments (--standalone --action=greet name=World)."""
        mock_post.return_value = MagicMock(status_code=200, text="OK")
        cli_args = [
            "app.py",
            "--standalone",
            "--action=greet",
            "name=StandaloneUser",
            "greeting=Howdy",
        ]
        with patch.object(sys, "argv", cli_args):
            with patch.dict(os.environ, {"ACTION": "", "AUTHORIZATION": "", "EXECUTIONID": ""}, clear=False):
                with self.assertRaises(SystemExit):
                    SampleIntegrationApp.run()

    @patch("shuffle_sdk.shuffle_sdk.requests.post")
    def test_integration_cloud_object_run(self, mock_post):
        """Run SampleIntegrationApp via AppBase.run(action=dict_object) as used in Cloud Run / serverless."""
        full_exec = {
            "execution_id": "exec-cloud-1",
            "workflow": {"id": "wf-1", "execution_org": {"id": "org-1"}, "branches": []},
            "results": [],
        }
        mock_post.side_effect = make_mock_post_for_execution(full_exec)

        action_payload = {
            "id": "cloud-act-1",
            "name": "greet",
            "authorization": "cloud-auth",
            "execution_id": "exec-cloud-1",
            "url": "https://shuffler.io",
            "base_url": "https://shuffler.io",
            "parameters": [
                {"name": "name", "value": "CloudRunner", "variant": "STATIC_VALUE"},
            ],
        }
        SampleIntegrationApp.run(action=action_payload)
        self.assertEqual(mock_post.call_count, 2)
        sent_payload = mock_post.call_args_list[1][1]["json"]
        self.assertEqual(sent_payload["status"], "SUCCESS")
        self.assertEqual(sent_payload["result"], "Hello, CloudRunner!")

    @patch("waitress.serve")
    @patch("shuffle_sdk.shuffle_sdk.requests.post")
    def test_integration_webserver_microservice_mode(self, mock_post, mock_serve):
        """Start SampleIntegrationApp.run() in webserver mode and test /api/v1/health and /api/v1/run."""
        with patch.object(sdk_module, "runtime", "run"):
            with patch.dict(os.environ, {"SHUFFLE_APP_EXPOSED_PORT": "8080"}, clear=False):
                SampleIntegrationApp.run()

        self.assertTrue(mock_serve.called)
        flask_app = mock_serve.call_args[0][0]
        client = flask_app.test_client()

        # 1. GET /api/v1/health
        health_resp = client.get("/api/v1/health")
        self.assertEqual(health_resp.status_code, 200)
        self.assertEqual(health_resp.data.decode("utf-8"), "OK")

        # 2. POST /api/v1/run with valid action payload
        full_exec = {
            "execution_id": "exec-web-1",
            "workflow": {"id": "wf-1", "execution_org": {"id": "org-1"}, "branches": []},
            "results": [],
        }
        mock_post.side_effect = make_mock_post_for_execution(full_exec)

        run_payload = {
            "workflow_execution": full_exec,
            "action": {
                "id": "web-act-1",
                "name": "greet",
                "parameters": [
                    {"name": "name", "value": "Microservice", "variant": "STATIC_VALUE"}
                ],
            },
            "authorization": "web-auth",
            "execution_id": "exec-web-1",
            "url": "https://shuffler.io",
            "base_url": "https://shuffler.io",
        }
        run_resp = client.post(
            "/api/v1/run",
            data=json.dumps(run_payload),
            content_type="application/json",
        )
        self.assertEqual(run_resp.status_code, 200)
        run_json = run_resp.get_json()
        self.assertTrue(run_json["success"])
        self.assertEqual(run_json["reason"], "App successfully finished")

        # 3. POST /api/v1/run with invalid JSON payload
        bad_resp = client.post("/api/v1/run", data="not-json", content_type="application/json")
        self.assertFalse(bad_resp.get_json()["success"])


# =====================================================================
# 8. DEEP EDGE-CASE TESTS: CONDITIONAL PARSING, TYPE CASTING, & COMPLEX BRANCHES
# =====================================================================
class TestComplexParsingTypesAndConditionals(unittest.TestCase):
    """Deep unit & integration tests for conditional operators (larger/smaller than with string lists,
    list-vs-list, string length vs int), int/float/bool/string/AST parsing, missing vs extra parameters,
    parameter variants, inline cache lookups, and partial loop deduplication."""

    def setUp(self):
        self.app = create_test_app(cls=SampleIntegrationApp)

    def test_validate_condition_larger_and_smaller_than_with_string_lists_and_lengths(self):
        """Test all branches of 'larger than' / 'bigger than' / '>' / '>=' and 'smaller than' / 'less than' / '<' / '<=':
        - int vs int (including negative numbers and equal values)
        - JSON string list vs int (list item count compared against int)
        - JSON string list vs JSON string list (list item count compared against list item count)
        - plain string vs int (character length compared against int)
        - int vs plain string (int compared against character length)
        - non-digit non-list strings (returns False)
        """
        # 1. Integer strings vs Integer strings
        for op in ["larger than", "bigger than", ">", ">="]:
            self.assertTrue(self.app.validate_condition("10", op, "2"), f"Failed 10 {op} 2")
            self.assertFalse(self.app.validate_condition("2", op, "10"), f"Failed 2 {op} 10")
            self.assertFalse(self.app.validate_condition("5", op, "5"), f"Failed 5 {op} 5")

        for op in ["smaller than", "less than", "<", "<="]:
            self.assertTrue(self.app.validate_condition("2", op, "10"), f"Failed 2 {op} 10")
            self.assertFalse(self.app.validate_condition("10", op, "2"), f"Failed 10 {op} 2")
            self.assertFalse(self.app.validate_condition("5", op, "5"), f"Failed 5 {op} 5")

        # 2. String list (JSON array string) vs Integer string
        # len(["a", "b", "c"]) == 3 > 2 -> True; len(["only_one"]) == 1 (and char len 12) > 20 -> False
        self.assertTrue(self.app.validate_condition('["a", "b", "c"]', "larger than", "2"))
        self.assertTrue(self.app.validate_condition('["a", "b", "c"]', "bigger than", "0"))
        self.assertFalse(self.app.validate_condition('["only_one"]', "larger than", "20"))
        self.assertFalse(self.app.validate_condition("[]", "larger than", "5"))

        # len(["only_one"]) == 1 < 2 -> True; len(["a", "b", "c"]) == 3 < 2 -> False
        self.assertTrue(self.app.validate_condition('["only_one"]', "smaller than", "2"))
        self.assertTrue(self.app.validate_condition("[]", "less than", "1"))
        self.assertFalse(self.app.validate_condition('["a", "b", "c"]', "smaller than", "2"))

        # 3. String list (JSON array string) vs String list (JSON array string)
        # len(["a", "b", "c"]) == 3 vs len(["x"]) == 1
        self.assertTrue(self.app.validate_condition('["a", "b", "c"]', "larger than", '["x"]'))
        self.assertFalse(self.app.validate_condition('["x"]', "larger than", '["a", "b", "c"]'))
        self.assertTrue(self.app.validate_condition('["x"]', "smaller than", '["a", "b", "c"]'))
        self.assertFalse(self.app.validate_condition('["a", "b", "c"]', "smaller than", '["x"]'))

        # 4. Plain string (character length) vs Integer string
        # len("hello world") == 11 > 5 -> True; len("hi") == 2 > 5 -> False
        self.assertTrue(self.app.validate_condition("hello world", "larger than", "5"))
        self.assertFalse(self.app.validate_condition("hi", "larger than", "5"))
        self.assertTrue(self.app.validate_condition("hi", "smaller than", "5"))
        self.assertFalse(self.app.validate_condition("hello world", "smaller than", "5"))

        # 5. Integer string vs Plain string (character length)
        # 10 > len("hello") (5) -> True; 3 > len("hello") (5) -> False
        self.assertTrue(self.app.validate_condition("10", "larger than", "hello"))
        self.assertFalse(self.app.validate_condition("3", "larger than", "hello"))
        self.assertTrue(self.app.validate_condition("3", "smaller than", "hello"))
        self.assertFalse(self.app.validate_condition("10", "smaller than", "hello"))

        # 6. Two non-digit non-list strings -> returns False cleanly without raising
        self.assertFalse(self.app.validate_condition("apple", "larger than", "banana"))
        self.assertFalse(self.app.validate_condition("apple", "smaller than", "banana"))

    def test_validate_condition_empty_and_contains_any_of_edge_cases(self):
        """Test edge cases for is_empty / is empty and contains_any_of."""
        # is empty / is_empty treats "", "[]", "{}" as empty
        self.assertTrue(self.app.validate_condition("", "is empty", ""))
        self.assertTrue(self.app.validate_condition("[]", "is empty", ""))
        self.assertTrue(self.app.validate_condition("{}", "is_empty", ""))
        self.assertFalse(self.app.validate_condition('{"a": 1}', "is_empty", ""))
        self.assertFalse(self.app.validate_condition('["a"]', "is empty", ""))

        # contains_any_of with ", " delimiter vs "," delimiter vs empty element in list
        self.assertTrue(self.app.validate_condition("status: critical", "contains_any_of", "info, warn, critical"))
        self.assertTrue(self.app.validate_condition("status: critical", "contains_any_of", "info,warn,critical"))
        self.assertTrue(self.app.validate_condition("status: critical", "contains_any_of", "info,,critical,"))
        self.assertFalse(self.app.validate_condition("status: ok", "contains_any_of", "info,,critical,"))

    @patch("shuffle_sdk.shuffle_sdk.requests.post")
    def test_branch_conditions_with_string_list_larger_than_and_multi_branch_logic(self, mock_post):
        """Test check_branch_conditions inside execute_action:
        1. Branch condition with 'larger than' comparing a previous node's string list ($list_node.items) against '2'.
        2. Multiple branches pointing to the same destination node where Branch 1 fails and Branch 2 succeeds.
        3. Branch from a FAILURE parent node is skipped unless destination is the workflow start node.
        4. Branch with empty conditions list automatically passes.
        """
        # Case 1 & 2: Two branches into target-node:
        # Branch A fails ($list_node.items smaller than 2 -> False since len is 3)
        # Branch B succeeds ($list_node.items larger than 2 -> True since len is 3)
        full_exec = {
            "execution_id": "exec-branch-list",
            "start": "list-node-id",
            "workflow": {
                "id": "wf-1",
                "execution_org": {"id": "org-1"},
                "branches": [
                    {
                        "source_id": "list-node-id",
                        "destination_id": "target-node",
                        "conditions": [
                            {
                                "source": {"value": "$list_node.items", "variant": "STATIC_VALUE"},
                                "condition": {"value": "smaller than", "configuration": False},
                                "destination": {"value": "2", "variant": "STATIC_VALUE"},
                            }
                        ],
                    },
                    {
                        "source_id": "list-node-id",
                        "destination_id": "target-node",
                        "conditions": [
                            {
                                "source": {"value": "$list_node.items", "variant": "STATIC_VALUE"},
                                "condition": {"value": "larger than", "configuration": False},
                                "destination": {"value": "2", "variant": "STATIC_VALUE"},
                            }
                        ],
                    },
                ],
            },
            "results": [
                {
                    "action": {"id": "list-node-id", "label": "list_node"},
                    "status": "SUCCESS",
                    "result": json.dumps({"items": ["alpha", "beta", "gamma"]}),
                }
            ],
        }
        mock_post.side_effect = make_mock_post_for_execution(full_exec)
        action = {"id": "target-node", "name": "no_params_action", "parameters": []}
        self.app.execute_action(action)
        self.assertEqual(self.app.action_result["status"], "SUCCESS")
        self.assertEqual(self.app.action_result["result"], "ran_without_params")

        # Case 3: Parent node has status FAILURE -> target node is SKIPPED
        full_exec_parent_failed = json.loads(json.dumps(full_exec))
        full_exec_parent_failed["results"][0]["status"] = "FAILURE"
        mock_post.side_effect = make_mock_post_for_execution(full_exec_parent_failed)
        self.app.execute_action(action)
        self.assertEqual(self.app.action_result["status"], "SKIPPED")

        # Case 4: Parent node has status FAILURE, but target-node IS the workflow start node -> executes!
        full_exec_startnode = json.loads(json.dumps(full_exec_parent_failed))
        full_exec_startnode["start"] = "target-node"
        mock_post.side_effect = make_mock_post_for_execution(full_exec_startnode)
        self.app.execute_action(action)
        self.assertEqual(self.app.action_result["status"], "SUCCESS")

    @patch("shuffle_sdk.shuffle_sdk.requests.post")
    def test_int_float_bool_zero_scientific_and_python_dict_string_parsing(self, mock_post):
        """Verify variable resolution for int (including 0 and negative), float, scientific notation strings ('7e7'),
        booleans (True/False), Python single-quoted dict strings, and concatenated multi-JSON ('}{')."""
        full_exec = {
            "execution_id": "exec-types",
            "workflow": {"id": "wf-1", "execution_org": {"id": "org-1"}, "branches": []},
            "results": [
                {
                    "action": {"id": "n-json", "label": "typed_node"},
                    "status": "SUCCESS",
                    "result": json.dumps({
                        "pos_int": 42,
                        "zero_int": 0,
                        "neg_int": -99,
                        "float_num": 3.14159,
                        "sci_notation": "7e7",
                        "bool_t": True,
                        "bool_f": False,
                        "ast_list_field": "['first_obj', 'second_obj']",
                    }),
                },
                {
                    "action": {"id": "n-pydict", "label": "pydict_node"},
                    "status": "SUCCESS",
                    "result": "{'active': True, 'count': 77}",
                },
            ],
        }

        def run_expr(expr):
            mock_post.side_effect = make_mock_post_for_execution(full_exec)
            act = {
                "id": "act-t",
                "name": "echo_value",
                "parameters": [{"name": "value", "value": expr, "variant": "STATIC_VALUE"}],
            }
            self.app.execute_action(act)
            return self.app.action_result["result"]

        # Ints, zero, negative, float
        self.assertEqual(run_expr("$typed_node.pos_int"), "42")
        self.assertEqual(run_expr("$typed_node.zero_int"), "0")
        self.assertEqual(run_expr("$typed_node.neg_int"), "-99")
        self.assertEqual(run_expr("$typed_node.float_num"), "3.14159")

        # Scientific notation string '7e7' must stay '7e7' and not be cast to float 70000000.0
        self.assertEqual(run_expr("$typed_node.sci_notation"), "7e7")

        # Booleans True and False
        self.assertEqual(run_expr("$typed_node.bool_t").lower(), "true")
        self.assertEqual(run_expr("$typed_node.bool_f").lower(), "false")

        # Python dict string with single quotes and Python True
        self.assertEqual(run_expr("$pydict_node.active").lower(), "true")
        self.assertEqual(run_expr("$pydict_node.count"), "77")

        # Nested single-quoted Python list string "['first_obj', 'second_obj']" parsed via ast.literal_eval
        self.assertEqual(run_expr("$typed_node.ast_list_field.#0"), "first_obj")
        self.assertEqual(run_expr("$typed_node.ast_list_field.#1"), "second_obj")

    @patch("shuffle_sdk.shuffle_sdk.requests.post")
    def test_parameter_autocasting_json_ast_bytes_none_and_options(self, mock_post):
        """Test single-execution parameter type casting in execute_action:
        - JSON dict string -> dict
        - JSON list string (with skip_multicheck) -> list
        - Single-quoted Python literal string -> dict/list via ast.literal_eval
        - Invalid bracketed string -> remains str without crashing
        - None parameter value -> ''
        - Byte-string wrapper b'...' -> stripped to inner string
        - Parameter options with '||' -> extracts value after '||'
        """
        full_exec = {
            "execution_id": "exec-cast",
            "workflow": {"id": "wf-1", "execution_org": {"id": "org-1"}, "branches": []},
            "results": [],
        }

        def inspect_param(param_dict, skip_multicheck=False):
            mock_post.side_effect = make_mock_post_for_execution(full_exec)
            act = {
                "id": "act-inspect",
                "name": "inspect_type_and_value",
                "parameters": [param_dict],
            }
            if skip_multicheck:
                act["skip_multicheck"] = True
            self.app.execute_action(act)
            return json.loads(self.app.action_result["result"])

        # 1. Valid JSON object string -> cast to dict
        res_dict = inspect_param({"name": "data", "value": '{"k": 123, "nested": [1, 2]}', "variant": "STATIC_VALUE"})
        self.assertEqual(res_dict["type"], "dict")
        self.assertEqual(res_dict["value"], {"k": 123, "nested": [1, 2]})

        # 2. Valid JSON array string with skip_multicheck -> cast to list
        res_list = inspect_param(
            {"name": "data", "value": '[10, 20, 30]', "variant": "STATIC_VALUE"},
            skip_multicheck=True,
        )
        self.assertEqual(res_list["type"], "list")
        self.assertEqual(res_list["value"], [10, 20, 30])

        # 3. Single-quoted Python literal dict string -> cast to dict via ast.literal_eval
        res_ast = inspect_param({"name": "data", "value": "{'single_quoted': 456, 'arr': [7, 8]}", "variant": "STATIC_VALUE"})
        self.assertEqual(res_ast["type"], "dict")
        self.assertEqual(res_ast["value"], {"single_quoted": 456, "arr": [7, 8]})

        # 4. Malformed bracketed string -> stays str
        res_malformed = inspect_param({"name": "data", "value": "{not: valid: json_or_ast}", "variant": "STATIC_VALUE"})
        self.assertEqual(res_malformed["type"], "str")
        self.assertEqual(res_malformed["value"], "{not: valid: json_or_ast}")

        # 5. None parameter value -> caught cleanly by TypeError handler without crashing
        res_none = inspect_param({"name": "data", "value": None, "variant": "STATIC_VALUE"})
        self.assertFalse(res_none["success"])
        self.assertIn("Typeerror", res_none["reason"])

        # 6. Byte-string wrapper b'...' -> stripped to inner string
        res_bytes = inspect_param({"name": "data", "value": "b'decoded_bytes_text'", "variant": "STATIC_VALUE"})
        self.assertEqual(res_bytes["type"], "str")
        self.assertEqual(res_bytes["value"], "decoded_bytes_text")

        # 7. Parameter with options containing '||' delimiter -> extracts actual value after '||'
        res_options = inspect_param({
            "name": "data",
            "value": "Display Name||actual_option_value",
            "options": ["Display Name||actual_option_value"],
            "variant": "STATIC_VALUE",
        })
        self.assertEqual(res_options["value"], "actual_option_value")

    @patch("shuffle_sdk.shuffle_sdk.requests.post")
    def test_missing_required_param_vs_unexpected_extra_kwargs(self, mock_post):
        """Test TypeError handling when calling action methods:
        1a. Empty parameters=[] when action requires 'name' -> outer TypeError handler.
        1b. Non-empty parameters missing required 'name' -> inner TypeError handler ('old version of this action').
        2. Extra unexpected keyword arguments in single execution -> stripped automatically and action succeeds.
        """
        full_exec = {
            "execution_id": "exec-kwargs",
            "workflow": {"id": "wf-1", "execution_org": {"id": "org-1"}, "branches": []},
            "results": [],
        }

        # 1a. Empty parameters=[] when 'name' is required in greet()
        mock_post.side_effect = make_mock_post_for_execution(full_exec)
        act_missing_empty = {
            "id": "act-missing-empty",
            "name": "greet",
            "parameters": [],
        }
        self.app.execute_action(act_missing_empty)
        res_missing_empty = json.loads(self.app.action_result["result"])
        self.assertFalse(res_missing_empty["success"])
        self.assertIn("Typeerror", res_missing_empty["reason"])
        self.assertIn("missing 1 required positional argument", res_missing_empty["details"])

        # 1b. Non-empty parameters (passing optional 'greeting' but missing required 'name')
        mock_post.side_effect = make_mock_post_for_execution(full_exec)
        act_missing_partial = {
            "id": "act-missing-partial",
            "name": "greet",
            "parameters": [{"name": "greeting", "value": "Hi", "variant": "STATIC_VALUE"}],
        }
        self.app.execute_action(act_missing_partial)
        res_missing_partial = json.loads(self.app.action_result["result"])
        self.assertFalse(res_missing_partial["success"])
        self.assertIn("old version of this action", res_missing_partial["reason"])
        self.assertIn("missing 1 required positional argument", res_missing_partial["exception"])

        # 2. Extra unexpected keyword arguments in single execution are stripped in retry loop
        mock_post.side_effect = make_mock_post_for_execution(full_exec)
        act_extra = {
            "id": "act-extra",
            "name": "greet",
            "parameters": [
                {"name": "name", "value": "Alice", "variant": "STATIC_VALUE"},
                {"name": "unknown_param_1", "value": "val1", "variant": "STATIC_VALUE"},
                {"name": "unknown_param_2", "value": "val2", "variant": "STATIC_VALUE"},
            ],
        }
        self.app.execute_action(act_extra)
        self.assertEqual(self.app.action_result["status"], "SUCCESS")
        self.assertEqual(self.app.action_result["result"], "Hello, Alice!")

    @patch("shuffle_sdk.shuffle_sdk.requests.post")
    def test_parameter_variants_workflow_variable_action_result_and_inline_cache(self, mock_post):
        """Test WORKFLOW_VARIABLE, ACTION_RESULT variants, and inline $shuffle_cache.<key> resolution."""
        full_exec = {
            "execution_id": "exec-variants",
            "workflow": {
                "id": "wf-1",
                "execution_org": {"id": "org-1"},
                "branches": [],
                "workflow_variables": [{"name": "my_wf_var", "value": "wf_secret_123"}],
            },
            "results": [
                {
                    "action": {"id": "node-1", "label": "prev_step"},
                    "status": "SUCCESS",
                    "result": json.dumps({"nested": {"token": "tok_xyz"}}),
                }
            ],
            "execution_variables": [{"name": "fallback_exec_var", "value": "exec_val_456"}],
            "execution_argument": json.dumps({"trigger_field": "trig_789"}),
        }

        # 1. WORKFLOW_VARIABLE matching workflow_variables via action_field
        mock_post.side_effect = make_mock_post_for_execution(full_exec)
        self.app.execute_action({
            "id": "act-v1",
            "name": "echo_value",
            "parameters": [
                {"name": "value", "value": "", "action_field": "my_wf_var", "variant": "WORKFLOW_VARIABLE"}
            ],
        })
        self.assertEqual(self.app.action_result["result"], "wf_secret_123")

        # 2. WORKFLOW_VARIABLE falling back to execution_variables via action_field
        mock_post.side_effect = make_mock_post_for_execution(full_exec)
        self.app.execute_action({
            "id": "act-v2",
            "name": "echo_value",
            "parameters": [
                {"name": "value", "value": "", "action_field": "fallback_exec_var", "variant": "WORKFLOW_VARIABLE"}
            ],
        })
        self.assertEqual(self.app.action_result["result"], "exec_val_456")

        # 3. ACTION_RESULT from Execution Argument and from previous node with $.subpath
        mock_post.side_effect = make_mock_post_for_execution(full_exec)
        self.app.execute_action({
            "id": "act-v3",
            "name": "combine_three",
            "parameters": [
                {"name": "a", "value": "$.trigger_field", "action_field": "Execution Argument", "variant": "ACTION_RESULT"},
                {"name": "b", "value": "$.nested.token", "action_field": "prev_step", "variant": "ACTION_RESULT"},
            ],
        })
        self.assertEqual(self.app.action_result["result"], "trig_789:tok_xyz:default")

        # 4. Inline $shuffle_cache.<key>.value and $shuffle_cache.<key> resolution via get_cache
        cache_resp = MagicMock(status_code=200, json=lambda: {"success": True, "value": "cached_api_key_999"})
        mock_post.side_effect = make_mock_post_for_execution(full_exec, extra_responses=[cache_resp])
        self.app.execute_action({
            "id": "act-v4",
            "name": "echo_value",
            "parameters": [{"name": "value", "value": "Key=$shuffle_cache.api_key.value", "variant": "STATIC_VALUE"}],
        })
        self.assertEqual(self.app.action_result["result"], "Key=cached_api_key_999")

        cache_resp2 = MagicMock(status_code=200, json=lambda: {"success": True, "value": "cached_api_key_999"})
        mock_post.side_effect = make_mock_post_for_execution(full_exec, extra_responses=[cache_resp2])
        self.app.execute_action({
            "id": "act-v4-full",
            "name": "echo_value",
            "parameters": [{"name": "value", "value": "$shuffle_cache.api_key", "variant": "STATIC_VALUE"}],
        })
        self.assertEqual(json.loads(self.app.action_result["result"])["value"], "cached_api_key_999")

    @patch("shuffle_sdk.shuffle_sdk.requests.post")
    def test_increment_stats_int_float_and_string_parsing(self, mock_post):
        """Test increment_stats and increment_stat with int strings, float strings, non-numeric strings, and invalid JSON."""
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"success": True})

        # 1. Integer string '25' -> sent as int 25 in JSON body
        res_int = self.app.increment_stats("alerts_handled", "25")
        self.assertTrue(res_int["success"])
        sent_int_payload = mock_post.call_args[1]["json"]
        self.assertEqual(sent_int_payload["value"], 25)
        self.assertIsInstance(sent_int_payload["value"], int)

        # 2. Float string '3.75' -> sent as float 3.75 in JSON body
        res_float = self.app.increment_stats("time_saved", "3.75")
        self.assertTrue(res_float["success"])
        sent_float_payload = mock_post.call_args[1]["json"]
        self.assertEqual(sent_float_payload["value"], 3.75)
        self.assertIsInstance(sent_float_payload["value"], float)

        # 3. Non-numeric string 'custom_val' -> preserved as string
        res_str = self.app.increment_stat("custom_metric", "custom_val", org_id="custom-org-1")
        self.assertTrue(res_str["success"])
        sent_str_payload = mock_post.call_args[1]["json"]
        self.assertEqual(sent_str_payload["value"], "custom_val")
        sent_headers = mock_post.call_args[1]["headers"]
        self.assertEqual(sent_headers["Org-Id"], "custom-org-1")

        # 4. Backend returns non-JSON response -> returns {"success": False}
        bad_resp = MagicMock(status_code=500, text="Internal Server Error")
        bad_resp.json.side_effect = json.JSONDecodeError("err", "doc", 0)
        mock_post.return_value = bad_resp
        res_fail = self.app.increment_stats("metric", 1)
        self.assertFalse(res_fail["success"])

    @patch("shuffle_sdk.shuffle_sdk.requests.post")
    def test_validate_unique_fields_partial_deduplication_and_single_skip(self, mock_post):
        """Test validate_unique_fields:
        1. Partial deduplication in a 3-item loop where 1 item is already found -> executes only the 2 new items.
        2. Single execution where unique_toggled=True and value is found -> status SKIPPED.
        3. Hashing of int, float, bool, dict, and list parameter values.
        """
        # 1. Partial deduplication in multi-execution loop
        full_exec = {
            "execution_id": "exec-partial-uniq",
            "workflow": {"id": "wf-1", "execution_org": {"id": "org-1"}, "branches": []},
            "results": [
                {
                    "action": {"id": "n1", "label": "alerts"},
                    "status": "SUCCESS",
                    "result": json.dumps(["alert_1", "alert_dup", "alert_2"]),
                }
            ],
        }
        uniq_resp = MagicMock(status_code=200)
        uniq_resp.json.return_value = {
            "found": [hashlib.md5(b"alert_dup").hexdigest()]
        }
        mock_post.side_effect = make_mock_post_for_execution(full_exec, extra_responses=[uniq_resp])

        action_loop = {
            "id": "act-partial-uniq",
            "app_name": "sample_integration_app",
            "name": "echo_value",
            "parameters": [
                {"name": "value", "value": "$alerts.#", "variant": "STATIC_VALUE", "unique_toggled": True}
            ],
        }
        self.app.execute_action(action_loop)
        self.assertEqual(self.app.action_result["status"], "SUCCESS")
        self.assertEqual(json.loads(self.app.action_result["result"]), ["alert_1", "alert_2"])

        # 2. Single execution non-unique -> SKIPPED
        uniq_single_resp = MagicMock(status_code=200)
        uniq_single_resp.json.return_value = {
            "found": [hashlib.md5(b"already_seen").hexdigest()]
        }
        mock_post.side_effect = make_mock_post_for_execution(full_exec, extra_responses=[uniq_single_resp])
        action_single = {
            "id": "act-single-uniq",
            "app_name": "sample_integration_app",
            "name": "echo_value",
            "parameters": [
                {"name": "value", "value": "already_seen", "variant": "STATIC_VALUE", "unique_toggled": True}
            ],
        }
        sent_single = []
        orig_send = self.app.send_result

        def capture_send(ar, h, p):
            sent_single.append(json.loads(json.dumps(ar)))
            return orig_send(ar, h, p)

        with patch.object(sdk_module, "runtime", "run"), patch.object(
            self.app, "send_result", side_effect=capture_send
        ):
            self.app.execute_action(action_single)

        self.assertGreaterEqual(len(sent_single), 1)
        self.assertEqual(sent_single[0]["status"], "SKIPPED")
        self.assertIn("non-unique value", sent_single[0]["result"])

        # 3. Direct unit test of validate_unique_fields with int, float, bool, dict, list
        mock_post.side_effect = None
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"found": []})
        self.app.action = {
            "name": "echo_value",
            "app_name": "sample_integration_app",
            "parameters": [
                {"name": "p_int", "unique_toggled": True},
                {"name": "p_bool", "unique_toggled": True},
                {"name": "p_dict", "unique_toggled": True},
            ],
        }
        res_valid = self.app.validate_unique_fields({
            "p_int": 100,
            "p_bool": True,
            "p_dict": {"b": 2, "a": 1},
        })
        self.assertIsInstance(res_valid, list)
        self.assertEqual(len(res_valid), 1)
        self.assertEqual(res_valid[0]["p_int"], 100)

    @patch("shuffle_sdk.shuffle_sdk.requests.post")
    def test_json_in_json_multiline_and_quote_sanitization(self, mock_post):
        """When a parameter value is valid JSON containing a $node.field reference whose value has
        double quotes, newlines, and carriage returns, parse_params sanitizes the inner string
        so the outer JSON remains valid and parses cleanly into a dict."""
        full_exec = {
            "execution_id": "exec-json-in-json",
            "workflow": {"id": "wf-1", "execution_org": {"id": "org-1"}, "branches": []},
            "results": [
                {
                    "action": {"id": "n1", "label": "raw_source"},
                    "status": "SUCCESS",
                    "result": json.dumps({"raw_text": 'line1 "alert"\nline2\rline3'}),
                }
            ],
        }
        mock_post.side_effect = make_mock_post_for_execution(full_exec)
        act = {
            "id": "act-json-in-json",
            "name": "inspect_type_and_value",
            "parameters": [
                {
                    "name": "data",
                    "value": '{"message": "$raw_source.raw_text", "code": 200}',
                    "variant": "STATIC_VALUE",
                }
            ],
        }
        self.app.execute_action(act)
        self.assertEqual(self.app.action_result["status"], "SUCCESS")
        parsed = json.loads(self.app.action_result["result"])
        self.assertEqual(parsed["type"], "dict")
        self.assertEqual(parsed["value"]["code"], 200)
        self.assertEqual(parsed["value"]["message"], 'line1 "alert"\nline2\rline3')

    @patch("shuffle_sdk.shuffle_sdk.requests.post")
    def test_replace_params_from_workflow_actions_and_non_callable_attribute(self, mock_post):
        """Test execute_action(action) with SHUFFLE_AUTO_REMOVED overriding action parameters from
        full_execution['workflow']['actions'], and handling a non-callable attribute name."""
        full_exec = {
            "execution_id": "exec-replace-params",
            "workflow": {
                "id": "wf-1",
                "execution_org": {"id": "org-1"},
                "branches": [],
                "actions": [
                    {
                        "id": "act-replace-1",
                        "name": "greet",
                        "parameters": [
                            {"name": "name", "value": "ReplacedFromWorkflow", "variant": "STATIC_VALUE"},
                            {"name": "greeting", "value": "Welcome", "variant": "STATIC_VALUE"},
                        ],
                    }
                ],
            },
            "results": [],
        }
        mock_post.side_effect = make_mock_post_for_execution(full_exec)
        action = {
            "id": "act-replace-1",
            "name": "greet",
            "parameters": [{"name": "name", "value": "SHUFFLE_AUTO_REMOVED", "variant": "STATIC_VALUE"}],
        }
        self.app.execute_action(action)
        self.assertEqual(self.app.action_result["status"], "SUCCESS")
        self.assertEqual(self.app.action_result["result"], "Welcome, ReplacedFromWorkflow!")

        # Non-callable attribute on AppBase (e.g. 'app_name' is a string attribute, not a method)
        mock_post.side_effect = make_mock_post_for_execution(full_exec)
        non_callable_action = {
            "id": "act-non-callable",
            "name": "app_name",
            "parameters": [],
        }
        self.app.execute_action(non_callable_action)
        self.assertEqual(self.app.action_result["status"], "FAILURE")
        self.assertFalse(json.loads(self.app.action_result["result"])["success"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
