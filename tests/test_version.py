from importlib.metadata import version


def test_package_version():
    assert version("msw-io")
