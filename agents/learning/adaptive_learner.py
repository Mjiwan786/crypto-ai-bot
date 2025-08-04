# agents/learning/adaptive_learner.py
import os
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'  # Disable oneDNN warnings

import sys
import logging
import numpy as np
from collections import deque
from typing import Optional, Tuple
import random

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class TensorFlowManager:
    """Handles TensorFlow with graceful fallback"""
    
    def __init__(self):
        self.has_tf = False
        self.gpu_available = False
        self._initialize()
        
    def _initialize(self):
        """Attempt TensorFlow import with validation"""
        try:
            import tensorflow as tf
            self.tf = tf
            self.has_tf = True
            self.gpu_available = bool(tf.config.list_physical_devices('GPU'))
            logger.info(f"TensorFlow {tf.__version__} initialized | GPU: {self.gpu_available}")
        except ImportError as e:
            logger.warning(f"TensorFlow not available: {str(e)}")
            self.has_tf = False

class AdaptiveLearner:
    def __init__(self, base_model=None):
        self.tf = TensorFlowManager()
        self.model = None
        self.memory = deque(maxlen=10000)
        
        if self.tf.has_tf and base_model:
            self._initialize_model(base_model)

    def _initialize_model(self, base_model):
        """Safe model initialization"""
        try:
            self.model = self.tf.tf.keras.models.clone_model(base_model)
            self.model.compile(
                optimizer=self.tf.tf.keras.optimizers.Adam(0.001),
                loss='mse'
            )
        except Exception as e:
            logger.error(f"Model initialization failed: {str(e)}")
            self.tf.has_tf = False

    def update(self, X: np.ndarray, y: np.ndarray) -> bool:
        """Update model with new data"""
        if not self.tf.has_tf:
            return False
            
        try:
            self.memory.extend(zip(X, y))
            batch = random.sample(self.memory, min(512, len(self.memory)))
            X_batch, y_batch = zip(*batch)
            self.model.train_on_batch(np.array(X_batch), np.array(y_batch))
            return True
        except Exception as e:
            logger.error(f"Training failed: {str(e)}")
            return False

# Usage example
if __name__ == "__main__":
    # Test initialization
    learner = AdaptiveLearner()
    print(f"TF Available: {learner.tf.has_tf}")
    print(f"GPU Available: {learner.tf.gpu_available}")