"""
Health API microservice for configuration and runtime health monitoring.

Provides JSON endpoints for Ops and Grafana to consume system health status
and configuration performance metrics.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder

# Import config managers
try:
    from config.loader import ConfigManager
except ImportError:
    try:
        from config.config_loader import ConfigManager
    except ImportError:
        ConfigManager = None

try:
    from config.agent_config_manager import AgentConfigManager
except ImportError:
    AgentConfigManager = None

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastAPI app
app = FastAPI(
    title="Crypto AI Bot Health API",
    description="Health monitoring and configuration metrics for crypto trading bot",
    version="1.0.0"
)


def safe_dump(obj: Any) -> Dict[str, Any]:
    """
    Safely serialize dataclasses and pydantic models to dict.
    
    Tries model_dump() for Pydantic v2, then dataclasses.asdict(),
    then falls back to jsonable_encoder.
    """
    try:
        # Try Pydantic v2 model_dump first
        if hasattr(obj, 'model_dump'):
            return obj.model_dump()
    except Exception:
        pass
    
    try:
        # Try dataclasses.asdict
        import dataclasses
        if dataclasses.is_dataclass(obj):
            return dataclasses.asdict(obj)
    except Exception:
        pass
    
    # Fallback to FastAPI's jsonable_encoder
    return jsonable_encoder(obj)


def get_config_manager() -> Optional[ConfigManager]:
    """Get ConfigManager instance, handling import failures gracefully."""
    if ConfigManager is None:
        return None
    
    try:
        return ConfigManager.get_instance("config/settings.yaml")
    except Exception as e:
        logger.warning(f"Failed to get ConfigManager: {e}")
        return None


def get_agent_config_manager() -> Optional[AgentConfigManager]:
    """Get AgentConfigManager instance, handling import failures gracefully."""
    if AgentConfigManager is None:
        return None
    
    try:
        return AgentConfigManager.get_instance()
    except Exception as e:
        logger.warning(f"Failed to get AgentConfigManager: {e}")
        return None


@app.get("/healthz")
async def health_check():
    """
    Basic health check endpoint.
    
    Returns status "ok" if both config managers can be imported and loaded.
    Returns "degraded" if there are issues but the service is running.
    """
    try:
        config_mgr = get_config_manager()
        agent_mgr = get_agent_config_manager()
        
        if config_mgr is None or agent_mgr is None:
            return {
                "status": "degraded",
                "ts": datetime.utcnow().isoformat() + "Z",
                "reason": "Config managers unavailable"
            }
        
        # Try to load config to verify it works
        try:
            config_mgr.get_config()
            agent_mgr.get_config()
        except Exception as e:
            logger.warning(f"Config load failed: {e}")
            return {
                "status": "degraded", 
                "ts": datetime.utcnow().isoformat() + "Z",
                "reason": f"Config load failed: {str(e)}"
            }
        
        return {
            "status": "ok",
            "ts": datetime.utcnow().isoformat() + "Z"
        }
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "degraded",
            "ts": datetime.utcnow().isoformat() + "Z", 
            "reason": f"Health check error: {str(e)}"
        }


@app.get("/config/health")
async def config_health():
    """
    Comprehensive configuration health endpoint.
    
    Returns merged health status from both config managers.
    """
    try:
        config_mgr = get_config_manager()
        agent_mgr = get_agent_config_manager()
        
        if config_mgr is None:
            raise HTTPException(status_code=503, detail="ConfigManager unavailable")
        
        if agent_mgr is None:
            raise HTTPException(status_code=503, detail="AgentConfigManager unavailable")
        
        # Get main config health
        main_health = safe_dump(config_mgr.health)
        
        # Get agent performance metrics
        agent_metrics = agent_mgr.get_performance_metrics()
        agent_health = {
            "avg_load_time": agent_metrics.avg_load_time,
            "avg_validation_time": agent_metrics.avg_validation_time,
            "cache_hit_ratio": agent_metrics.cache_hit_ratio,
            "cache_hits": agent_metrics.cache_hits,
            "cache_misses": agent_metrics.cache_misses,
            "last_update": agent_metrics.last_update.isoformat() + "Z"
        }
        
        return {
            "main": main_health,
            "agent": agent_health,
            "version": config_mgr.current_version,
            "updated_at": datetime.utcnow().isoformat() + "Z"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Config health check failed: {e}")
        raise HTTPException(status_code=500, detail=f"Config health check failed: {str(e)}")


@app.get("/config/perf")
async def config_performance():
    """
    Raw performance metrics endpoint.
    
    Returns separated performance metrics for both config managers.
    """
    try:
        config_mgr = get_config_manager()
        agent_mgr = get_agent_config_manager()
        
        if config_mgr is None:
            raise HTTPException(status_code=503, detail="ConfigManager unavailable")
        
        if agent_mgr is None:
            raise HTTPException(status_code=503, detail="AgentConfigManager unavailable")
        
        # Get main config health
        main_health = safe_dump(config_mgr.health)
        
        # Get agent performance metrics
        agent_metrics = agent_mgr.get_performance_metrics()
        agent_perf = safe_dump(agent_metrics)
        
        return {
            "main": main_health,
            "agent": agent_perf
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Config performance check failed: {e}")
        raise HTTPException(status_code=500, detail=f"Config performance check failed: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9400)
