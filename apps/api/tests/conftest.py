# apps/api의 src.xxx import가 동작하려면 apps/api(=이 tests/의 부모)가 sys.path에
# 있어야 한다. uvicorn은 cwd=apps/api로 실행되어 자동으로 잡히지만, pytest는
# 보장되지 않으므로 명시적으로 추가한다.

import pathlib
import sys

APP_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_ROOT))
