"""
Fasada zgodności: dawny moduł `src.database` re-eksportuje teraz API pakietu `src.finance`.

Nowy kod powinien importować bezpośrednio z modułów `src.finance.*` —
ta fasada istnieje, aby starsze skrypty i importy nadal działały.
"""

from src.finance.accounts import *  # noqa: F401,F403
from src.finance.analytics import *  # noqa: F401,F403
from src.finance.autosave import *  # noqa: F401,F403
from src.finance.data_io import *  # noqa: F401,F403
from src.finance.envelopes import *  # noqa: F401,F403
from src.finance.goals import *  # noqa: F401,F403
from src.finance.ledger import *  # noqa: F401,F403
from src.finance.recurring import *  # noqa: F401,F403
from src.finance.storage import *  # noqa: F401,F403
from src.finance.storage import DATA_DIR, PROJECT_ROOT, AUTH_DB  # noqa: F401  (jawnie dla czytelności)
