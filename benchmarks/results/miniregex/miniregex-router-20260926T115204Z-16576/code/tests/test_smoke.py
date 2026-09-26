from miniregex import RegexError, compile


def test_imports():
    assert callable(compile)
    assert issubclass(RegexError, Exception)
