"""Backtracking matcher nodes.

Each node implements ``match(ctx, pos, k)`` where ``ctx`` holds the text being
matched and the mutable group-span table, ``pos`` is the current offset into
the text, and ``k`` is the continuation to invoke with the offset reached
after this node matches. ``k`` returns ``True`` once the whole match (from the
top-level caller's perspective) has succeeded, in which case that ``True`` is
propagated straight back up without trying further alternatives -- this is
what gives leftmost-first (greedy, first-alternative-wins) semantics
identical to Python's `re`.
"""

from __future__ import annotations


class Context:
    __slots__ = ("text", "groups")

    def __init__(self, text, groups):
        self.text = text
        self.groups = groups


class Literal:
    __slots__ = ("char",)

    def __init__(self, char):
        self.char = char

    def match(self, ctx, pos, k):
        text = ctx.text
        if pos < len(text) and text[pos] == self.char:
            return k(pos + 1)
        return False


class AnyChar:
    __slots__ = ()

    def match(self, ctx, pos, k):
        text = ctx.text
        if pos < len(text) and text[pos] != "\n":
            return k(pos + 1)
        return False


class CharSet:
    __slots__ = ("items", "negate")

    def __init__(self, items, negate):
        self.items = items
        self.negate = negate

    def _base_match(self, ch):
        for item in self.items:
            if item[0] == "range":
                if item[1] <= ch <= item[2]:
                    return True
            else:
                if item[1](ch):
                    return True
        return False

    def match(self, ctx, pos, k):
        text = ctx.text
        if pos >= len(text):
            return False
        ch = text[pos]
        base = self._base_match(ch)
        ok = (not base) if self.negate else base
        if ok:
            return k(pos + 1)
        return False


class AnchorStart:
    __slots__ = ()

    def match(self, ctx, pos, k):
        if pos == 0:
            return k(pos)
        return False


class AnchorEnd:
    __slots__ = ()

    def match(self, ctx, pos, k):
        text = ctx.text
        if pos == len(text) or (pos == len(text) - 1 and text[pos] == "\n"):
            return k(pos)
        return False


class Empty:
    __slots__ = ()

    def match(self, ctx, pos, k):
        return k(pos)


class Concat:
    __slots__ = ("children",)

    def __init__(self, children):
        self.children = children

    def match(self, ctx, pos, k):
        children = self.children
        n = len(children)

        def helper(i, p):
            if i == n:
                return k(p)
            return children[i].match(ctx, p, lambda p2, i=i: helper(i + 1, p2))

        return helper(0, pos)


class Alt:
    __slots__ = ("children",)

    def __init__(self, children):
        self.children = children

    def match(self, ctx, pos, k):
        for child in self.children:
            if child.match(ctx, pos, k):
                return True
        return False


class Group:
    __slots__ = ("index", "child")

    def __init__(self, index, child):
        self.index = index
        self.child = child

    def match(self, ctx, pos, k):
        idx = self.index
        if idx is None:
            return self.child.match(ctx, pos, k)

        old = ctx.groups[idx]

        def k2(p2):
            ctx.groups[idx] = (pos, p2)
            if k(p2):
                return True
            ctx.groups[idx] = old
            return False

        result = self.child.match(ctx, pos, k2)
        if not result:
            ctx.groups[idx] = old
        return result


class Repeat:
    __slots__ = ("child", "min", "max", "lazy")

    def __init__(self, child, min_, max_, lazy):
        self.child = child
        self.min = min_
        self.max = max_
        self.lazy = lazy

    def match(self, ctx, pos, k):
        return self._match_count(ctx, pos, k, 0)

    def _match_count(self, ctx, pos, k, count):
        child = self.child
        mn, mx, lazy = self.min, self.max, self.lazy
        can_repeat = mx is None or count < mx

        def try_more():
            def k2(p2):
                if p2 == pos and count >= mn:
                    # Zero-width iteration: recursing again would loop
                    # forever without making progress. `re` still commits
                    # this iteration (its capture group updates) but treats
                    # it as the last one, so hand off straight to the outer
                    # continuation instead of trying to repeat again.
                    return k(p2)
                return self._match_count(ctx, p2, k, count + 1)

            return child.match(ctx, pos, k2)

        if lazy:
            if count >= mn and k(pos):
                return True
            if can_repeat and try_more():
                return True
            return False
        else:
            if can_repeat and try_more():
                return True
            if count >= mn:
                return k(pos)
            return False
