from dataclasses import dataclass
from typing import Tuple, Union


type Uid = Tuple[int, int, int, int]


@dataclass
class PluginMetadata:
    id: Union[int, Uid]
    name: str
    vendor: str
    version: str
    vst_version: str
    subcategories: str
