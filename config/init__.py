# config/__init__.py
from pathlib import Path
import yaml
from pydantic import BaseModel

class ModularConfig:
    def __init__(self, config_dir="config"):
        self.base = self._load_yaml(Path(config_dir)/"base.yaml")
        self.ml = self._load_yaml(Path(config_dir)/"ml_models.yaml")
        self.risk = self._load_yaml(Path(config_dir)/"risk.yaml")
        self.validate_cross_references()
        
    def _load_yaml(self, path):
        with open(path) as f:
            return yaml.safe_load(f)
            
    def validate_cross_references(self):
        if self.ml["model_weights"]["sum"] != 1.0:
            raise ValueError("Model weights must sum to 1.0")