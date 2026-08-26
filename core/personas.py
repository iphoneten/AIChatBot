"""角色人设：从 personas.json 加载，供用户 /role 切换。"""

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

_PERSONAS_FILE = Path(__file__).resolve().parent.parent / "personas.json"


class Persona(BaseModel):
    """单个角色人设。"""

    name: str
    description: str
    prompt: str


@lru_cache
def load_personas() -> dict[str, Persona]:
    """加载全部角色人设（进程内缓存）。"""
    raw: dict = json.loads(_PERSONAS_FILE.read_text(encoding="utf-8"))
    return {
        name: Persona(name=name, description=item["description"], prompt=item["prompt"])
        for name, item in raw.items()
    }


def get_persona(name: str) -> Persona | None:
    """按名称获取角色人设。"""
    return load_personas().get(name)


def list_personas() -> list[Persona]:
    """列出全部角色人设。"""
    return list(load_personas().values())
