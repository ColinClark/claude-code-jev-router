"""Fuzz the number <-> text conversions that SQLite implements with its own algorithms
(sqlite3FpDecode for float rendering, sqlite3AtoF / sqlite3Atoi64 for parsing)."""

from __future__ import annotations

import math
import random
import struct

import pytest
from conftest import Differential


def _random_double(rng: random.Random) -> float:
    while True:
        k = rng.random()
        if k < 0.25:
            x = rng.uniform(-1e6, 1e6)
        elif k < 0.45:
            x = round(rng.uniform(-1000, 1000), rng.randint(0, 6))
        elif k < 0.7:
            x = struct.unpack("<d", struct.pack("<Q", rng.getrandbits(64)))[0]
        elif k < 0.85:
            x = rng.randint(-(10**17), 10**17) / 10 ** rng.randint(0, 20)
        else:
            x = float(rng.randint(-(2**60), 2**60)) + rng.choice([0.0, 0.5, 0.25])
        if math.isfinite(x):
            return x


@pytest.mark.parametrize("seed", range(3))
def test_float_rendering_fuzz(empty_pair: Differential, seed: int) -> None:
    rng = random.Random(100 + seed)
    for _ in range(150):
        lits = [repr(_random_double(rng)) for _ in range(8)]
        cols = ", ".join(f"CAST({lit} AS TEXT), {lit} || ''" for lit in lits)
        empty_pair.check(f"SELECT {cols}")


def _random_numeric_text(rng: random.Random) -> str:
    pieces = [
        " ", "  ", "\t", "+", "-", "0", "1", "7", "9", "42", "00", ".", ".5", "e", "E",
        "e5", "e-3", "e+2", "e400", "e-400", "x", "abc", "0x1A", "9223372036854775807",
        "9223372036854775808", "18446744073709551616", "12345678901234567890123",
        "3.14159", "1e308", "2.5e-310",
    ]  # fmt: skip
    return "".join(rng.choice(pieces) for _ in range(rng.randint(1, 4)))


@pytest.mark.parametrize("seed", range(3))
def test_text_to_number_fuzz(empty_pair: Differential, seed: int) -> None:
    rng = random.Random(200 + seed)
    empty_pair.run("CREATE TABLE conv (i INTEGER, r REAL, n NUMERIC, t TEXT, b)")
    for _ in range(120):
        s = _random_numeric_text(rng)
        lit = "'" + s.replace("'", "''") + "'"
        empty_pair.check(
            f"SELECT {lit} + 0, {lit} * 1.0, - {lit}, CAST({lit} AS INTEGER), "
            f"CAST({lit} AS REAL), CAST({lit} AS NUMERIC), {lit} = 5, {lit} < 10, "
            f"NOT {lit}, {lit} AND 1, {lit} % 7, {lit} | 0"
        )
        empty_pair.run(f"INSERT INTO conv VALUES ({lit}, {lit}, {lit}, {lit}, {lit})")
    empty_pair.check(
        "SELECT i, typeof(i), r, typeof(r), n, typeof(n), t, b FROM conv", ordered=False
    )
    empty_pair.check("SELECT SUM(t), TOTAL(t), AVG(t), MIN(i), MAX(i) FROM conv")
    empty_pair.check("SELECT COUNT(*) FROM conv WHERE i = t")
    empty_pair.check("SELECT COUNT(*) FROM conv WHERE n > '5'")


@pytest.mark.parametrize("seed", range(3))
def test_numeric_literal_fuzz(empty_pair: Differential, seed: int) -> None:
    rng = random.Random(300 + seed)
    for _ in range(150):
        lits = []
        for _ in range(8):
            digits = "".join(rng.choice("0123456789") for _ in range(rng.randint(1, 25)))
            k = rng.random()
            if k < 0.4:
                pos = rng.randint(0, len(digits))
                lit = digits[:pos] + "." + digits[pos:]
            elif k < 0.7:
                lit = digits[0] + "." + digits[1:] + "e" + str(rng.randint(-330, 320))
            else:
                lit = digits + "e" + str(rng.randint(-30, 30))
            lits.append(lit)
        empty_pair.check("SELECT " + ", ".join(lits))
