"""Problem bank.

Each problem carries three test tiers:
  visible  - shown to the coder and run on every "Run"
  hidden   - only run on submit (edge cases)
  stress   - only run on submit, large inputs with a time limit (efficiency)

Expected values are computed once at startup from a trusted reference solution,
so the sandbox never sees them: it only returns what the coder's function produced.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class TestCase:
    id: str
    args: list
    expected: Any = None
    tier: str = "visible"          # visible | hidden | stress
    time_limit: float = 2.0        # seconds for this single call
    note: str = ""                 # what this case checks (shown in reports, never the input)

    def public(self) -> dict:
        return {"id": self.id, "args": self.args, "expected": self.expected, "note": self.note}


@dataclass
class Problem:
    id: str
    title: str
    difficulty: str
    function_name: str
    statement: str
    starter_code: str
    reference: Callable
    compare: str                    # exact | unordered
    optimal_complexity: str
    expected_minutes: int
    hints: list[str]                # fallback hint ladder, rungs 1-4
    visible: list[TestCase] = field(default_factory=list)
    hidden: list[TestCase] = field(default_factory=list)
    stress: list[TestCase] = field(default_factory=list)

    def all_tests(self) -> list[TestCase]:
        return self.visible + self.hidden + self.stress

    def public(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "difficulty": self.difficulty,
            "function_name": self.function_name,
            "statement": self.statement,
            "starter_code": self.starter_code,
            "expected_minutes": self.expected_minutes,
            "examples": [t.public() for t in self.visible],
            "hidden_count": len(self.hidden),
            "stress_count": len(self.stress),
        }

    def summary(self) -> dict:
        return {"id": self.id, "title": self.title, "difficulty": self.difficulty}


# --------------------------------------------------------------------------- references

def _two_sum_ref(nums, target):
    seen = {}
    for i, x in enumerate(nums):
        if target - x in seen:
            return [seen[target - x], i]
        seen[x] = i
    return []


def _valid_parens_ref(s):
    pairs = {")": "(", "]": "[", "}": "{"}
    stack = []
    for ch in s:
        if ch in "([{":
            stack.append(ch)
        elif ch in pairs:
            if not stack or stack.pop() != pairs[ch]:
                return False
    return not stack


def _longest_unique_ref(s):
    last, start, best = {}, 0, 0
    for i, ch in enumerate(s):
        if ch in last and last[ch] >= start:
            start = last[ch] + 1
        last[ch] = i
        best = max(best, i - start + 1)
    return best


def _merge_intervals_ref(intervals):
    out = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


# --------------------------------------------------------------------------- bank

def _cycle_string(n: int, period: int, base: int = 0x4E00) -> str:
    return "".join(chr(base + (i % period)) for i in range(n))


def _build() -> dict[str, Problem]:
    problems = [
        Problem(
            id="two-sum",
            title="Two sum",
            difficulty="Easy",
            function_name="two_sum",
            statement=(
                "Given a list of integers `nums` and an integer `target`, return the indices "
                "of the two numbers that add up to `target`.\n\n"
                "Exactly one valid pair exists, and you may not use the same element twice. "
                "Return the two indices in any order.\n\n"
                "Aim for a solution faster than checking every pair."
            ),
            starter_code="def two_sum(nums, target):\n    # return [i, j]\n    pass\n",
            reference=_two_sum_ref,
            compare="unordered",
            optimal_complexity="O(n)",
            expected_minutes=10,
            hints=[
                "For each number, think about which other value it would need to reach the target.",
                "If you could instantly check whether `target - x` has appeared earlier, one pass "
                "over the list would be enough. Which data structure gives instant lookups?",
                "Outline: create an empty dict mapping value -> index. Walk the list with "
                "enumerate. If target - x is in the dict, return both indices. Otherwise store x.",
                "seen = {}\nfor i, x in enumerate(nums):\n    if target - x in seen: return [seen[target - x], i]",
            ],
            visible=[
                TestCase("v1", [[2, 7, 11, 15], 9], note="basic pair"),
                TestCase("v2", [[3, 2, 4], 6], note="pair not at the start"),
                TestCase("v3", [[3, 3], 6], note="duplicate values"),
            ],
            hidden=[
                TestCase("h1", [[-4, 1, 9, -2, 8], 6], note="negative numbers"),
                TestCase("h2", [[0, 5, 0], 0], note="zeros"),
                TestCase("h3", [[1, 2], 3], note="smallest input"),
                TestCase("h4", [[5, 75, 25, -10, 100], 15], note="negative partner"),
            ],
            stress=[
                TestCase("s1", [list(range(20000)), 39997], tier="stress", time_limit=1.5,
                         note="20k elements, pair at the end"),
                TestCase("s2", [list(range(0, 60000, 3)) + [1], 59998], tier="stress", time_limit=1.5,
                         note="20k elements, partner appended last"),
            ],
        ),
        Problem(
            id="valid-parentheses",
            title="Valid brackets",
            difficulty="Easy",
            function_name="valid_parentheses",
            statement=(
                "Given a string `s` containing only the characters `()[]{}`, return `True` if "
                "every bracket is closed by the same type of bracket in the correct order, "
                "and `False` otherwise.\n\n"
                "An empty string is valid."
            ),
            starter_code="def valid_parentheses(s):\n    pass\n",
            reference=_valid_parens_ref,
            compare="exact",
            optimal_complexity="O(n)",
            expected_minutes=10,
            hints=[
                "The most recently opened bracket must be the first one to close. "
                "What structure works in last-in, first-out order?",
                "Push opening brackets onto a stack. On a closing bracket, the top of the stack "
                "must be its matching opener. At the end, the stack must be empty.",
                "Outline: map each closer to its opener. Loop over characters; push openers; "
                "for closers, fail if the stack is empty or the popped value doesn't match. "
                "Return whether the stack is empty.",
                "pairs = {')': '(', ']': '[', '}': '{'}\nif not stack or stack.pop() != pairs[ch]:\n    return False",
            ],
            visible=[
                TestCase("v1", ["()[]{}"], note="simple pairs"),
                TestCase("v2", ["(]"], note="mismatched type"),
                TestCase("v3", ["{[()]}"], note="nested"),
            ],
            hidden=[
                TestCase("h1", [""], note="empty string"),
                TestCase("h2", ["(("], note="unclosed openers"),
                TestCase("h3", ["))"], note="closer with empty stack"),
                TestCase("h4", ["([)]"], note="interleaved"),
            ],
            stress=[
                TestCase("s1", ["(" * 50000 + ")" * 50000], tier="stress", time_limit=1.5,
                         note="100k deeply nested"),
                TestCase("s2", ["()[]{}" * 20000 + "("], tier="stress", time_limit=1.5,
                         note="120k with one unclosed at the end"),
            ],
        ),
        Problem(
            id="longest-unique-substring",
            title="Longest substring without repeats",
            difficulty="Medium",
            function_name="longest_unique_substring",
            statement=(
                "Given a string `s`, return the length of the longest substring that contains "
                "no repeated characters.\n\n"
                "For example, in `\"abcabcbb\"` the answer is `3` (`\"abc\"`)."
            ),
            starter_code="def longest_unique_substring(s):\n    pass\n",
            reference=_longest_unique_ref,
            compare="exact",
            optimal_complexity="O(n)",
            expected_minutes=20,
            hints=[
                "Think of a window over the string that only ever contains unique characters. "
                "What should happen to the window when a repeat arrives?",
                "Use a sliding window: extend the right edge one character at a time. When the new "
                "character is already inside the window, move the left edge just past its "
                "previous position. Track the best window length.",
                "Outline: dict last_seen = {}, start = 0, best = 0. For i, ch: if ch in last_seen "
                "and last_seen[ch] >= start, set start = last_seen[ch] + 1. Update last_seen[ch] = i "
                "and best = max(best, i - start + 1).",
                "if ch in last and last[ch] >= start:\n    start = last[ch] + 1\nbest = max(best, i - start + 1)",
            ],
            visible=[
                TestCase("v1", ["abcabcbb"], note="classic"),
                TestCase("v2", ["bbbbb"], note="all same"),
                TestCase("v3", ["pwwkew"], note="answer in the middle"),
            ],
            hidden=[
                TestCase("h1", [""], note="empty string"),
                TestCase("h2", ["abba"], note="left edge must not move backwards"),
                TestCase("h3", [" "], note="single space"),
                TestCase("h4", ["dvdf"], note="restart inside window"),
            ],
            stress=[
                TestCase("s1", [_cycle_string(100000, 2000)], tier="stress", time_limit=1.5,
                         note="100k chars, repeats every 2000"),
                TestCase("s2", [_cycle_string(60000, 5000)], tier="stress", time_limit=1.5,
                         note="60k chars, long unique runs"),
            ],
        ),
        Problem(
            id="merge-intervals",
            title="Merge intervals",
            difficulty="Medium",
            function_name="merge_intervals",
            statement=(
                "Given a list of intervals `[start, end]`, merge all overlapping intervals and "
                "return the merged list sorted by start.\n\n"
                "Intervals that touch, like `[1, 4]` and `[4, 5]`, count as overlapping."
            ),
            starter_code="def merge_intervals(intervals):\n    pass\n",
            reference=_merge_intervals_ref,
            compare="exact",
            optimal_complexity="O(n log n)",
            expected_minutes=20,
            hints=[
                "Overlaps are hard to spot in random order. Is there an order that puts every "
                "interval next to the ones it could merge with?",
                "Sort by start. Then walk through once: each interval either extends the last "
                "merged interval or starts a new one.",
                "Outline: sort intervals. result = []. For each [a, b]: if result and a <= "
                "result[-1][1], set result[-1][1] = max(result[-1][1], b); else append [a, b].",
                "if out and a <= out[-1][1]:\n    out[-1][1] = max(out[-1][1], b)\nelse: out.append([a, b])",
            ],
            visible=[
                TestCase("v1", [[[1, 3], [2, 6], [8, 10], [15, 18]]], note="basic overlap"),
                TestCase("v2", [[[1, 4], [4, 5]]], note="touching intervals"),
                TestCase("v3", [[[5, 6], [1, 2]]], note="unsorted input"),
            ],
            hidden=[
                TestCase("h1", [[]], note="empty list"),
                TestCase("h2", [[[1, 10], [2, 3], [4, 5]]], note="fully contained"),
                TestCase("h3", [[[1, 4], [0, 0]]], note="zero-length interval"),
                TestCase("h4", [[[2, 3], [4, 5], [6, 7], [1, 10]]], note="one swallows all"),
            ],
            stress=[
                TestCase("s1", [[[i * 2, i * 2 + 1] for i in range(30000, 0, -1)]], tier="stress",
                         time_limit=1.5, note="30k disjoint, reversed"),
                TestCase("s2", [[[i, i + 2] for i in range(40000)]], tier="stress", time_limit=1.5,
                         note="40k chained overlaps"),
            ],
        ),
    ]

    for p in problems:
        for tier in ("visible", "hidden", "stress"):   # the list a test sits in decides its tier
            for t in getattr(p, tier):
                t.tier = tier
        for t in p.all_tests():
            t.expected = p.reference(*[_clone(a) for a in t.args])
            if t.tier == "visible":
                t.time_limit = max(t.time_limit, 2.0)
    return {p.id: p for p in problems}


def _clone(x):
    import copy
    return copy.deepcopy(x)


PROBLEMS: dict[str, Problem] = _build()


def get_problem(problem_id: str) -> Problem | None:
    return PROBLEMS.get(problem_id)
