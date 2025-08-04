# scripts/verify_tf.py
import sys
import logging
import subprocess
from importlib.util import find_spec

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_installation():
    """Comprehensive TensorFlow environment check"""
    logger.info("\n=== TensorFlow Environment Verification ===")
    logger.info(f"Python executable: {sys.executable}")
    logger.info(f"Python path: {sys.path}")
    
    # Check TensorFlow installation
    try:
        import tensorflow as tf
        logger.info(f"\n✅ TensorFlow {tf.__version__} installed in:\n{sys.prefix}")
        
        # Check GPU availability
        gpus = tf.config.list_physical_devices('GPU')
        logger.info(f"GPU Available: {bool(gpus)}")
        if gpus:
            for gpu in gpus:
                logger.info(f"GPU Device: {gpu}")
                
        # Verify basic functionality
        try:
            a = tf.constant([[1.0, 2.0], [3.0, 4.0]])
            b = tf.constant([[1.0, 1.0], [0.0, 1.0]])
            c = tf.matmul(a, b)
            logger.info("✅ Basic TensorFlow operations working")
            logger.info(f"Test matrix multiplication result:\n{c.numpy()}")
        except Exception as e:
            logger.error(f"❌ TensorFlow operations failed: {str(e)}")
            
        return True
    except ImportError as e:
        logger.error(f"❌ TensorFlow import failed: {str(e)}")
        
        # Suggest solutions
        logger.info("\n🛠️ Try these solutions:")
        logger.info("1. First activate your conda environment:")
        logger.info("   conda activate crypto-bot")
        logger.info("2. Then install/upgrade TensorFlow:")
        logger.info("   conda install tensorflow  # or")
        logger.info("   pip install --upgrade tensorflow")
        logger.info("3. Verify the installation:")
        logger.info("   python -c \"import tensorflow as tf; print(tf.__version__)\"")
        
        return False

if __name__ == "__main__":
    check_installation()