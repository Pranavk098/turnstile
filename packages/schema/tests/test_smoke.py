import turnstile_schema

def test_package_imports_and_declares_version():
    assert turnstile_schema.SCHEMA_VERSION == "1.0"
