"""korail2 가 설치되지 않은 환경(예: Python 3.12+)에서도 테스트가 돌도록 최소 스텁을 주입."""
import sys
import types

try:
    import korail2  # noqa: F401
except ImportError:
    m = types.ModuleType("korail2")

    class KorailError(Exception):
        def __init__(self, msg="", code=None):
            super().__init__(msg)
            self.code = code

    class NeedToLoginError(KorailError): pass
    class NoResultsError(KorailError): pass
    class SoldOutError(KorailError): pass

    m.KorailError, m.NeedToLoginError = KorailError, NeedToLoginError
    m.NoResultsError, m.SoldOutError = NoResultsError, SoldOutError
    sys.modules["korail2"] = m
