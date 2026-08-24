# server.py와 동일하게, src/ 를 import 루트로 잡아준다 (domain.xxx, application.xxx 형태로
# import할 수 있도록). 자세한 이유는 src/server.py 상단 주석 참고.

import pathlib
import sys

SRC_DIR = pathlib.Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))
