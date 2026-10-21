"""應用程式套件。

LiteLLM 在 ``LITELLM_MODE`` 為預設的 ``DEV`` 時，import 當下會對 cwd 的 ``.env`` 跑
``load_dotenv()``，把程序裡沒設的鍵補回來；``ENV_FILE`` 擋不住，臨時腳本 unset 掉的
``STORAGE_DATABASE_URL`` 會被補回正式應用庫。``.env`` 一律由 ``src.config.setup_env()`` 讀，
所以在任何 ``src`` 模組 import litellm 之前把它關掉。明確設了 ``LITELLM_MODE`` 的照用。
"""

import os

os.environ.setdefault("LITELLM_MODE", "PRODUCTION")
