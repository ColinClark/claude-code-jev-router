import miniregex


def test_import():
    assert issubclass(miniregex.RegexError, Exception)
    assert callable(miniregex.compile)
