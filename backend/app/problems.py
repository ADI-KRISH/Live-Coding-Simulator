"""Problem bank.

Each problem carries three test tiers:
  visible  - shown to the coder and run on every "Run"
  hidden   - only run on submit (edge cases)
  stress   - only run on submit, large inputs with a time limit (efficiency)

`difficulty` is beginner | intermediate | advanced. `topics` are ids from skills.TOPICS and
drive the per-topic skill profile. `scale(n)` builds a worst-case input of size n; the judge
times it at growing n to measure how the submitted code actually scales.

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
    topics: list[str] = field(default_factory=list)
    scale: Callable[[int], list] | None = None
    nested_ok: bool = False         # the optimal solution nests loops; don't flag loop depth
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
            "topics": self.topics,
            "function_name": self.function_name,
            "statement": self.statement,
            "starter_code": self.starter_code,
            "expected_minutes": self.expected_minutes,
            "examples": [t.public() for t in self.visible],
            "hidden_count": len(self.hidden),
            "stress_count": len(self.stress),
        }

    def summary(self) -> dict:
        return {"id": self.id, "title": self.title, "difficulty": self.difficulty, "topics": self.topics}


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


def _max_profit_ref(prices):
    best, low = 0, float("inf")
    for p in prices:
        low = min(low, p)
        best = max(best, p - low)
    return best


def _binary_search_ref(nums, target):
    lo, hi = 0, len(nums) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if nums[mid] == target:
            return mid
        if nums[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1


def _is_anagram_ref(s, t):
    if len(s) != len(t):
        return False
    counts = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    for ch in t:
        if counts.get(ch, 0) == 0:
            return False
        counts[ch] -= 1
    return True


def _max_area_ref(heights):
    lo, hi, best = 0, len(heights) - 1, 0
    while lo < hi:
        best = max(best, (hi - lo) * min(heights[lo], heights[hi]))
        if heights[lo] < heights[hi]:
            lo += 1
        else:
            hi -= 1
    return best


def _daily_temperatures_ref(temps):
    out, stack = [0] * len(temps), []
    for i, t in enumerate(temps):
        while stack and temps[stack[-1]] < t:
            j = stack.pop()
            out[j] = i - j
        stack.append(i)
    return out


def _count_islands_ref(grid):
    seen, count = set(), 0
    for r in range(len(grid)):
        for c in range(len(grid[0])):
            if grid[r][c] != 1 or (r, c) in seen:
                continue
            count += 1
            stack = [(r, c)]
            seen.add((r, c))
            while stack:
                y, x = stack.pop()
                for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                    if (0 <= ny < len(grid) and 0 <= nx < len(grid[0])
                            and grid[ny][nx] == 1 and (ny, nx) not in seen):
                        seen.add((ny, nx))
                        stack.append((ny, nx))
    return count


def _coin_change_ref(coins, amount):
    best = [0] + [amount + 1] * amount
    for a in range(1, amount + 1):
        for c in coins:
            if c <= a and best[a - c] + 1 < best[a]:
                best[a] = best[a - c] + 1
    return best[amount] if best[amount] <= amount else -1


def _lis_length_ref(nums):
    from bisect import bisect_left
    tails = []
    for x in nums:
        i = bisect_left(tails, x)
        if i == len(tails):
            tails.append(x)
        else:
            tails[i] = x
    return len(tails)


def _can_finish_ref(num_courses, prerequisites):
    after = [[] for _ in range(num_courses)]
    need = [0] * num_courses
    for course, pre in prerequisites:
        after[pre].append(course)
        need[course] += 1
    ready = [c for c in range(num_courses) if need[c] == 0]
    done = 0
    while ready:
        c = ready.pop()
        done += 1
        for nxt in after[c]:
            need[nxt] -= 1
            if need[nxt] == 0:
                ready.append(nxt)
    return done == num_courses


def _trap_water_ref(heights):
    lo, hi, left_max, right_max, water = 0, len(heights) - 1, 0, 0, 0
    while lo < hi:
        if heights[lo] < heights[hi]:
            left_max = max(left_max, heights[lo])
            water += left_max - heights[lo]
            lo += 1
        else:
            right_max = max(right_max, heights[hi])
            water += right_max - heights[hi]
            hi -= 1
    return water


def _max_sliding_window_ref(nums, k):
    from collections import deque
    window, out = deque(), []
    for i, x in enumerate(nums):
        while window and nums[window[-1]] <= x:
            window.pop()
        window.append(i)
        if window[0] <= i - k:
            window.popleft()
        if i >= k - 1:
            out.append(nums[window[0]])
    return out


# --------------------------------------------------------------------------- bank

def _cycle_string(n: int, period: int, base: int = 0x4E00) -> str:
    return "".join(chr(base + (i % period)) for i in range(n))


def _scatter(n: int, mod: int = 10007) -> list[int]:
    """Deterministic pseudo-random ints, so tests are reproducible."""
    return [(i * 7919) % mod for i in range(n)]


def _chain(n: int) -> list[list[int]]:
    """Course i needs course i-1, listed last-first so naive rescans resolve one per pass."""
    return [[i, i - 1] for i in range(n - 1, 0, -1)]


def _checkerboard(side: int) -> list[list[int]]:
    return [[(r + c) % 2 for c in range(side)] for r in range(side)]


def _build() -> dict[str, Problem]:
    problems = [
        Problem(
            id="two-sum",
            title="Two sum",
            difficulty="beginner",
            topics=["arrays", "hashmaps"],
            scale=lambda n: [list(range(n)), 2 * n - 3],
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
            difficulty="beginner",
            topics=["stacks", "strings"],
            scale=lambda n: ["(" * (n // 2) + ")" * (n // 2)],
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
            difficulty="intermediate",
            topics=["strings", "two-pointers", "hashmaps"],
            nested_ok=True,
            scale=lambda n: [_cycle_string(n, n // 2)],
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
            difficulty="intermediate",
            topics=["sorting", "arrays"],
            scale=lambda n: [[[i * 2, i * 2 + 1] for i in range(n, 0, -1)]],
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
        # ------------------------------------------------------------ more beginner
        Problem(
            id="best-time-to-trade",
            title="Best time to buy and sell",
            difficulty="beginner",
            topics=["arrays"],
            scale=lambda n: [list(range(n, 0, -1))],
            function_name="max_profit",
            statement=(
                "`prices[i]` is the price of a stock on day `i`. You may buy on one day and sell "
                "on a later day. Return the largest profit you can make.\n\n"
                "If no trade makes a profit, return `0`."
            ),
            starter_code="def max_profit(prices):\n    pass\n",
            reference=_max_profit_ref,
            compare="exact",
            optimal_complexity="O(n)",
            expected_minutes=10,
            hints=[
                "For any selling day, which earlier day would you most like to have bought on?",
                "Walk through the prices once, remembering the lowest price seen so far. On each "
                "day, the best sale is today's price minus that lowest price.",
                "Outline: lowest = infinity, best = 0. For each price: lowest = the smaller of "
                "lowest and price; best = the larger of best and price - lowest. Return best.",
                "low = min(low, p)\nbest = max(best, p - low)",
            ],
            visible=[
                TestCase("v1", [[7, 1, 5, 3, 6, 4]], note="buy low, sell later"),
                TestCase("v2", [[7, 6, 4, 3, 1]], note="prices only fall"),
                TestCase("v3", [[2, 4, 1]], note="lowest price comes after the best sale"),
            ],
            hidden=[
                TestCase("h1", [[]], note="empty list"),
                TestCase("h2", [[5]], note="single day"),
                TestCase("h3", [[3, 3, 3]], note="flat prices"),
                TestCase("h4", [[1, 2, 3, 4, 5]], note="prices only rise"),
            ],
            stress=[
                TestCase("s1", [list(range(20000, 0, -1))], tier="stress", time_limit=1.5,
                         note="20k falling prices"),
                TestCase("s2", [_scatter(30000)], tier="stress", time_limit=1.5,
                         note="30k scattered prices"),
            ],
        ),
        Problem(
            id="binary-search",
            title="Binary search",
            difficulty="beginner",
            topics=["binary-search", "arrays"],
            scale=lambda n: [list(range(0, 2 * n, 2)), 2 * n - 1],
            function_name="binary_search",
            statement=(
                "`nums` is a list of distinct integers sorted in increasing order. Return the "
                "index of `target` in `nums`, or `-1` if it is not there.\n\n"
                "The list can be very long, so aim for a solution that does not look at every element."
            ),
            starter_code="def binary_search(nums, target):\n    pass\n",
            reference=_binary_search_ref,
            compare="exact",
            optimal_complexity="O(log n)",
            expected_minutes=10,
            hints=[
                "The list is sorted. If you look at the middle element, what does it tell you "
                "about where the target can still be?",
                "Keep a low and a high index. Compare the middle element with the target and "
                "throw away the half that cannot contain it. Repeat until the range is empty.",
                "Outline: lo = 0, hi = last index. While lo <= hi: mid = middle. If the middle "
                "value is the target, return mid. If it is smaller, lo = mid + 1; otherwise "
                "hi = mid - 1. Return -1.",
                "mid = (lo + hi) // 2\nif nums[mid] < target: lo = mid + 1\nelse: hi = mid - 1",
            ],
            visible=[
                TestCase("v1", [[1, 3, 5, 7, 9], 7], note="target present"),
                TestCase("v2", [[1, 3, 5, 7, 9], 4], note="target missing"),
                TestCase("v3", [[2], 2], note="single element"),
            ],
            hidden=[
                TestCase("h1", [[], 1], note="empty list"),
                TestCase("h2", [[1, 3, 5, 7, 9], 1], note="first element"),
                TestCase("h3", [[1, 3, 5, 7, 9], 9], note="last element"),
                TestCase("h4", [[1, 3, 5, 7], 10], note="larger than everything"),
                TestCase("h5", [[4, 6, 8], 1], note="smaller than everything"),
            ],
            stress=[
                TestCase("s1", [list(range(0, 300000, 3)), 299997], tier="stress", time_limit=1.5,
                         note="100k elements, target at the end"),
                TestCase("s2", [list(range(0, 300000, 3)), 150001], tier="stress", time_limit=1.5,
                         note="100k elements, target missing"),
            ],
        ),
        Problem(
            id="valid-anagram",
            title="Valid anagram",
            difficulty="beginner",
            topics=["hashmaps", "strings"],
            scale=lambda n: [_cycle_string(n, 3000), _cycle_string(n, 3000)[::-1]],
            function_name="is_anagram",
            statement=(
                "Return `True` if string `t` is an anagram of string `s`: it uses exactly the "
                "same characters the same number of times, in any order.\n\n"
                "Upper and lower case are different characters."
            ),
            starter_code="def is_anagram(s, t):\n    pass\n",
            reference=_is_anagram_ref,
            compare="exact",
            optimal_complexity="O(n)",
            expected_minutes=10,
            hints=[
                "Order doesn't matter, only how many times each character appears. How could "
                "you record that?",
                "Count each character of `s` in a dictionary, then check that `t` uses up "
                "exactly those counts. Different lengths can never match.",
                "Outline: if the lengths differ, return False. Build a dict of character -> "
                "count from s. For each character in t: if its count is missing or zero, return "
                "False; otherwise lower it by one. Return True.",
                "counts = {}\nfor ch in s:\n    counts[ch] = counts.get(ch, 0) + 1",
            ],
            visible=[
                TestCase("v1", ["listen", "silent"], note="classic anagram"),
                TestCase("v2", ["rat", "car"], note="different letters"),
                TestCase("v3", ["aab", "abb"], note="same letters, different counts"),
            ],
            hidden=[
                TestCase("h1", ["", ""], note="empty strings"),
                TestCase("h2", ["a", "ab"], note="different lengths"),
                TestCase("h3", ["aacc", "ccac"], note="counts differ by one"),
                TestCase("h4", ["Tea", "eat"], note="case matters"),
            ],
            stress=[
                TestCase("s1", [_cycle_string(60000, 3000), _cycle_string(60000, 3000)[::-1]],
                         tier="stress", time_limit=1.5, note="60k characters, reversed"),
                TestCase("s2", [_cycle_string(60000, 3000), _cycle_string(59999, 3000) + "!"],
                         tier="stress", time_limit=1.5, note="60k characters, one differs"),
            ],
        ),
        # ------------------------------------------------------------ more intermediate
        Problem(
            id="container-with-most-water",
            title="Container with most water",
            difficulty="intermediate",
            topics=["two-pointers", "arrays"],
            scale=lambda n: [list(range(1, n + 1))],
            function_name="max_area",
            statement=(
                "`heights[i]` is the height of a vertical line at position `i`. Pick two lines; "
                "together with the x-axis they form a container that holds "
                "`distance between them * the shorter height` of water.\n\n"
                "Return the largest amount of water any pair can hold."
            ),
            starter_code="def max_area(heights):\n    pass\n",
            reference=_max_area_ref,
            compare="exact",
            optimal_complexity="O(n)",
            expected_minutes=20,
            hints=[
                "The widest container uses the two outermost lines. From there, which of the "
                "two lines is holding the area back?",
                "Start with one pointer at each end. The shorter line limits the area, so moving "
                "the taller one inward can never help. Move the shorter one and keep the best area.",
                "Outline: lo = 0, hi = last index, best = 0. While lo < hi: area = (hi - lo) * "
                "the shorter of the two heights; update best; move the pointer at the shorter "
                "line one step inward. Return best.",
                "if heights[lo] < heights[hi]:\n    lo += 1\nelse:\n    hi -= 1",
            ],
            visible=[
                TestCase("v1", [[1, 8, 6, 2, 5, 4, 8, 3, 7]], note="classic"),
                TestCase("v2", [[1, 1]], note="two lines"),
                TestCase("v3", [[4, 3, 2, 1, 4]], note="best pair is the outermost"),
            ],
            hidden=[
                TestCase("h1", [[1, 2, 1]], note="short outer lines"),
                TestCase("h2", [[2, 3, 4, 5, 18, 17, 6]], note="tall neighbours win"),
                TestCase("h3", [[0, 0]], note="zero heights"),
                TestCase("h4", [[1, 2]], note="uneven pair"),
            ],
            stress=[
                TestCase("s1", [list(range(1, 15001))], tier="stress", time_limit=1.5,
                         note="15k rising heights"),
                TestCase("s2", [[h + 1 for h in _scatter(20000, 1009)]], tier="stress", time_limit=1.5,
                         note="20k scattered heights"),
            ],
        ),
        Problem(
            id="daily-temperatures",
            title="Daily temperatures",
            difficulty="intermediate",
            topics=["stacks", "arrays"],
            nested_ok=True,
            scale=lambda n: [list(range(n + 100, 100, -1)) + [n + 200]],
            function_name="daily_temperatures",
            statement=(
                "Given a list of daily temperatures `temps`, return a list where entry `i` is "
                "the number of days you have to wait after day `i` for a strictly warmer day.\n\n"
                "If no warmer day ever comes, that entry is `0`."
            ),
            starter_code="def daily_temperatures(temps):\n    pass\n",
            reference=_daily_temperatures_ref,
            compare="exact",
            optimal_complexity="O(n)",
            expected_minutes=20,
            hints=[
                "Several days can be waiting for a warmer day at the same time. When a warm day "
                "arrives, which waiting days does it answer first?",
                "Keep a stack of the indices of days still waiting. When a new temperature is "
                "warmer than the day on top of the stack, that day has its answer: pop it and "
                "record the gap. Then push the new day.",
                "Outline: answer = zeros, stack = []. For each index i: while the stack is not "
                "empty and temps[top] < temps[i], pop j and set answer[j] = i - j. Push i. "
                "Return answer.",
                "while stack and temps[stack[-1]] < t:\n    j = stack.pop()\n    out[j] = i - j",
            ],
            visible=[
                TestCase("v1", [[73, 74, 75, 71, 69, 72, 76, 73]], note="classic"),
                TestCase("v2", [[30, 40, 50, 60]], note="always warmer tomorrow"),
                TestCase("v3", [[30, 60, 90]], note="short rising run"),
            ],
            hidden=[
                TestCase("h1", [[]], note="empty list"),
                TestCase("h2", [[50]], note="single day"),
                TestCase("h3", [[5, 4, 3, 2, 1]], note="never warmer"),
                TestCase("h4", [[70, 70, 71]], note="equal is not warmer"),
            ],
            stress=[
                TestCase("s1", [list(range(30000, 10000, -1)) + [40000]], tier="stress", time_limit=1.5,
                         note="20k cooling days, then one hot day"),
                TestCase("s2", [[50] * 20000], tier="stress", time_limit=1.5,
                         note="20k identical days"),
            ],
        ),
        Problem(
            id="number-of-islands",
            title="Number of islands",
            difficulty="intermediate",
            topics=["graphs"],
            nested_ok=True,
            scale=lambda n: [_checkerboard(int(n ** 0.5))],
            function_name="count_islands",
            statement=(
                "`grid` is a list of rows of `1` (land) and `0` (water). An island is a group of "
                "land cells connected up, down, left or right. Diagonal cells are not connected.\n\n"
                "Return the number of islands."
            ),
            starter_code="def count_islands(grid):\n    pass\n",
            reference=_count_islands_ref,
            compare="exact",
            optimal_complexity="O(rows * cols)",
            expected_minutes=25,
            hints=[
                "When you find a land cell, how can you make sure the rest of its island is "
                "never counted again?",
                "Scan every cell. Each time you reach land you have not visited, count one island "
                "and then visit everything connected to it (a flood fill) so it is marked as seen.",
                "Outline: count = 0, seen = empty set. For each cell: if it is land and not "
                "seen, add 1 to count, then explore from it with a stack or queue, marking each "
                "connected land cell as seen. Return count.",
                "for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):\n"
                "    if 0 <= ny < rows and 0 <= nx < cols and grid[ny][nx] == 1:",
            ],
            visible=[
                TestCase("v1", [[[1, 1, 0, 0], [1, 0, 0, 1], [0, 0, 1, 1]]], note="two islands"),
                TestCase("v2", [[[1, 0, 1], [0, 1, 0], [1, 0, 1]]], note="diagonals don't connect"),
                TestCase("v3", [[[0, 0], [0, 0]]], note="all water"),
            ],
            hidden=[
                TestCase("h1", [[]], note="empty grid"),
                TestCase("h2", [[[1]]], note="single cell"),
                TestCase("h3", [[[1, 0, 1, 1]]], note="single row"),
                TestCase("h4", [[[1, 1, 1], [1, 1, 1], [1, 1, 1]]], note="all land"),
                TestCase("h5", [[[1, 0, 1], [1, 0, 1], [1, 1, 1]]], note="U-shaped island"),
            ],
            stress=[
                TestCase("s1", [_checkerboard(300)], tier="stress", time_limit=1.5,
                         note="300 x 300 checkerboard"),
                TestCase("s2", [[[r % 2] * 300 for r in range(300)]], tier="stress", time_limit=1.5,
                         note="300 x 300 stripes"),
            ],
        ),
        Problem(
            id="coin-change",
            title="Coin change",
            difficulty="intermediate",
            topics=["dp"],
            nested_ok=True,
            scale=lambda n: [[7, 11, 13], n],
            function_name="coin_change",
            statement=(
                "Given coin values `coins` (you have as many of each as you like) and a target "
                "`amount`, return the fewest coins needed to make exactly `amount`.\n\n"
                "Return `-1` if the amount cannot be made. An amount of `0` needs `0` coins."
            ),
            starter_code="def coin_change(coins, amount):\n    pass\n",
            reference=_coin_change_ref,
            compare="exact",
            optimal_complexity="O(amount * coins)",
            expected_minutes=25,
            hints=[
                "Always taking the biggest coin can give the wrong answer. If you already knew "
                "the best answer for every smaller amount, could you work out this one?",
                "Build up from 0. The fewest coins for amount `a` is one more than the best "
                "answer for `a - c`, taking the best over every coin `c` that fits.",
                "Outline: best[0] = 0 and every other entry starts as 'impossible'. For a from 1 "
                "to amount: for each coin c <= a: best[a] = the smaller of best[a] and "
                "best[a - c] + 1. Return best[amount], or -1 if it is still impossible.",
                "for c in coins:\n    if c <= a:\n        best[a] = min(best[a], best[a - c] + 1)",
            ],
            visible=[
                TestCase("v1", [[1, 2, 5], 11], note="classic"),
                TestCase("v2", [[2], 3], note="impossible amount"),
                TestCase("v3", [[1, 3, 4], 6], note="biggest coin first is not best"),
            ],
            hidden=[
                TestCase("h1", [[1], 0], note="zero amount"),
                TestCase("h2", [[5], 5], note="one coin exactly"),
                TestCase("h3", [[2, 4], 7], note="odd amount, even coins"),
                TestCase("h4", [[9, 6, 5, 1], 11], note="greedy gives a worse answer"),
            ],
            stress=[
                TestCase("s1", [[7, 11, 13, 29], 9000], tier="stress", time_limit=1.5,
                         note="amount 9000, four coins"),
                TestCase("s2", [[2, 4, 6, 8], 9001], tier="stress", time_limit=1.5,
                         note="amount 9001, impossible"),
            ],
        ),
        # ------------------------------------------------------------ advanced
        Problem(
            id="longest-increasing-subsequence",
            title="Longest increasing subsequence",
            difficulty="advanced",
            topics=["dp", "binary-search"],
            nested_ok=True,
            scale=lambda n: [list(range(n))],
            function_name="lis_length",
            statement=(
                "Return the length of the longest strictly increasing subsequence of `nums`. "
                "A subsequence keeps the original order but may skip elements.\n\n"
                "The list can hold tens of thousands of numbers, so comparing every pair is too slow."
            ),
            starter_code="def lis_length(nums):\n    pass\n",
            reference=_lis_length_ref,
            compare="exact",
            optimal_complexity="O(n log n)",
            expected_minutes=30,
            hints=[
                "For each possible length, only one thing matters about the subsequences of that "
                "length: how small their last element can be.",
                "Keep a list `tails` where tails[k] is the smallest possible last value of an "
                "increasing subsequence of length k + 1. It stays sorted, so each new number can "
                "be placed with a binary search.",
                "Outline: tails = []. For each x: find the first position in tails whose value "
                "is >= x. If there is none, append x; otherwise replace that value with x. "
                "Return the length of tails.",
                "i = bisect_left(tails, x)\nif i == len(tails): tails.append(x)\nelse: tails[i] = x",
            ],
            visible=[
                TestCase("v1", [[10, 9, 2, 5, 3, 7, 101, 18]], note="classic"),
                TestCase("v2", [[0, 1, 0, 3, 2, 3]], note="repeats in between"),
                TestCase("v3", [[7, 7, 7, 7]], note="equal values don't count"),
            ],
            hidden=[
                TestCase("h1", [[]], note="empty list"),
                TestCase("h2", [[5]], note="single element"),
                TestCase("h3", [[5, 4, 3, 2, 1]], note="strictly falling"),
                TestCase("h4", [[1, 3, 6, 7, 9, 4, 10, 5, 6]], note="late smaller values"),
            ],
            stress=[
                TestCase("s1", [list(range(20000))], tier="stress", time_limit=1.5,
                         note="20k rising values"),
                TestCase("s2", [_scatter(20000, 20011)], tier="stress", time_limit=1.5,
                         note="20k scattered values"),
            ],
        ),
        Problem(
            id="course-schedule",
            title="Course schedule",
            difficulty="advanced",
            topics=["graphs"],
            nested_ok=True,
            scale=lambda n: [n, _chain(n)],
            function_name="can_finish",
            statement=(
                "There are `num_courses` courses numbered from `0`. Each pair `[a, b]` in "
                "`prerequisites` means you must finish course `b` before course `a`.\n\n"
                "Return `True` if it is possible to finish every course, and `False` otherwise."
            ),
            starter_code="def can_finish(num_courses, prerequisites):\n    pass\n",
            reference=_can_finish_ref,
            compare="exact",
            optimal_complexity="O(V + E)",
            expected_minutes=30,
            hints=[
                "Think of courses as nodes and prerequisites as arrows. What shape in that graph "
                "makes finishing impossible?",
                "It is possible exactly when the graph has no cycle. Repeatedly take any course "
                "with no unfinished prerequisites; if you run out before taking them all, "
                "there is a cycle.",
                "Outline: count the prerequisites of each course and list which courses each one "
                "unlocks. Put every course with a count of 0 in a queue. Pop a course, count it as "
                "done, lower the count of each course it unlocks and queue those that reach 0. "
                "Return whether done equals num_courses.",
                "for nxt in unlocks[course]:\n    need[nxt] -= 1\n    if need[nxt] == 0: ready.append(nxt)",
            ],
            visible=[
                TestCase("v1", [2, [[1, 0]]], note="one prerequisite"),
                TestCase("v2", [2, [[1, 0], [0, 1]]], note="two courses need each other"),
                TestCase("v3", [4, [[1, 0], [2, 0], [3, 1], [3, 2]]], note="diamond"),
            ],
            hidden=[
                TestCase("h1", [1, []], note="single course"),
                TestCase("h2", [3, []], note="no prerequisites"),
                TestCase("h3", [3, [[0, 1], [1, 2], [2, 0]]], note="cycle of three"),
                TestCase("h4", [5, [[1, 0], [2, 1], [3, 4], [4, 3]]], note="cycle in a separate group"),
                TestCase("h5", [1, [[0, 0]]], note="course requires itself"),
            ],
            stress=[
                TestCase("s1", [6000, _chain(6000)], tier="stress", time_limit=1.5,
                         note="6k courses in one long chain"),
                TestCase("s2", [6000, _chain(6000) + [[0, 5999]]], tier="stress", time_limit=1.5,
                         note="6k courses in one long cycle"),
            ],
        ),
        Problem(
            id="trapping-rain-water",
            title="Trapping rain water",
            difficulty="advanced",
            topics=["two-pointers", "arrays"],
            nested_ok=True,
            scale=lambda n: [_scatter(n, 1009)],
            function_name="trap_water",
            statement=(
                "`heights[i]` is the height of a wall of width 1 at position `i`. After rain, "
                "water collects in the dips between walls.\n\n"
                "Return the total units of water trapped."
            ),
            starter_code="def trap_water(heights):\n    pass\n",
            reference=_trap_water_ref,
            compare="exact",
            optimal_complexity="O(n)",
            expected_minutes=30,
            hints=[
                "Look at a single position. What decides how deep the water above it can be?",
                "The water above position i reaches the lower of the tallest wall to its left "
                "and the tallest wall to its right. Find those two values for every position "
                "without rescanning the list each time.",
                "Outline: one pointer at each end, with a running maximum for each side. Move "
                "the pointer at the lower wall inward: update that side's maximum, and add "
                "maximum - height to the total. Stop when the pointers meet.",
                "left_max = max(left_max, heights[lo])\nwater += left_max - heights[lo]\nlo += 1",
            ],
            visible=[
                TestCase("v1", [[0, 1, 0, 2, 1, 0, 1, 3, 2, 1, 2, 1]], note="classic"),
                TestCase("v2", [[4, 2, 0, 3, 2, 5]], note="one deep basin"),
                TestCase("v3", [[1, 2, 3]], note="stairs hold nothing"),
            ],
            hidden=[
                TestCase("h1", [[]], note="empty list"),
                TestCase("h2", [[5]], note="single wall"),
                TestCase("h3", [[3, 0, 3]], note="simple basin"),
                TestCase("h4", [[5, 4, 3, 2, 1]], note="falling stairs"),
                TestCase("h5", [[2, 0, 2, 0, 2]], note="two basins"),
            ],
            stress=[
                TestCase("s1", [_scatter(30000, 1009)], tier="stress", time_limit=1.5,
                         note="30k scattered walls"),
                TestCase("s2", [list(range(15000, 0, -1)) + list(range(1, 15001))], tier="stress",
                         time_limit=1.5, note="30k walls in a V shape"),
            ],
        ),
        Problem(
            id="sliding-window-maximum",
            title="Sliding window maximum",
            difficulty="advanced",
            topics=["stacks", "two-pointers"],
            nested_ok=True,
            scale=lambda n: [_scatter(n), n // 2],
            function_name="max_sliding_window",
            statement=(
                "A window of size `k` slides over `nums` from left to right, one step at a time. "
                "Return a list with the largest value in each window.\n\n"
                "You can assume `1 <= k <= len(nums)`. Both can be large, so finding each "
                "window's maximum from scratch is too slow."
            ),
            starter_code="def max_sliding_window(nums, k):\n    pass\n",
            reference=_max_sliding_window_ref,
            compare="exact",
            optimal_complexity="O(n)",
            expected_minutes=30,
            hints=[
                "When a new number enters the window, which older numbers can never be a "
                "maximum again?",
                "Keep a double-ended queue of indices whose values are in decreasing order. A new "
                "value removes every smaller value from the back; the front is always the "
                "current maximum, and it leaves once it falls out of the window.",
                "Outline: for each index i: pop from the back while that value <= nums[i]; "
                "append i; if the front index is outside the window, pop it from the front; "
                "once i >= k - 1, record nums[front].",
                "while window and nums[window[-1]] <= x:\n    window.pop()\nwindow.append(i)",
            ],
            visible=[
                TestCase("v1", [[1, 3, -1, -3, 5, 3, 6, 7], 3], note="classic"),
                TestCase("v2", [[1], 1], note="single element"),
                TestCase("v3", [[9, 8, 7, 6], 2], note="falling values"),
            ],
            hidden=[
                TestCase("h1", [[4, 2, 7, 1], 4], note="window covers the whole list"),
                TestCase("h2", [[4, 2, 7, 1], 1], note="window of one"),
                TestCase("h3", [[5, 5, 5, 5], 2], note="equal values"),
                TestCase("h4", [[-5, -2, -9, -4], 2], note="negative numbers"),
                TestCase("h5", [[9, 7, 5, 3, 1], 3], note="maximum leaves the window each step"),
            ],
            stress=[
                TestCase("s1", [list(range(40000, 0, -1)), 20000], tier="stress", time_limit=1.5,
                         note="40k falling values, window of 20k"),
                TestCase("s2", [_scatter(40000), 15000], tier="stress", time_limit=1.5,
                         note="40k scattered values, window of 15k"),
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
