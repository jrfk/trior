import pathlib, sys, trio, pytest
from trio_rust_poc import activate
activate(sys.argv[1])
root = pathlib.Path(trio.__file__).parent / '_core' / '_tests'
files = ['test_run.py','test_ki.py','test_instrumentation.py','test_guest_mode.py']
raise SystemExit(pytest.main(['-q', '-p', 'trio._tests.pytest_plugin', *[str(root/f) for f in files]]))
