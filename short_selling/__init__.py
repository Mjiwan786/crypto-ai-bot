"""
Short Selling Module

This module contains components for short-selling operations including
flash loan integration, timing models, and risk assessment.
"""

__version__ = '1.0.0'

# Only import what's actually available
__all__ = []

try:
    from .flash_loan_integrator import FlashLoanShortSeller
    __all__.append('FlashLoanShortSeller')
except ImportError:
    pass

try:
    from .flash_loan_integrator import (
        Opportunity, ScoredOpportunity, Simulation, LoanQuote,
        ExecutionPlan, ExecutionResult, RepayResult, MCPEvent,
        ExecutionMode, CircuitState
    )
    __all__.extend([
        'Opportunity', 'ScoredOpportunity', 'Simulation', 'LoanQuote',
        'ExecutionPlan', 'ExecutionResult', 'RepayResult', 'MCPEvent',
        'ExecutionMode', 'CircuitState'
    ])
except ImportError:
    pass

try:
    from .flash_loan_integrator import (
        FlashLoanException, LoanUnavailable, SlippageTooHigh,
        HealthFactorRisk, CircuitBreakerOpen, NetworkCongestion,
        SimulatorFailure, ExecutionTimeout
    )
    __all__.extend([
        'FlashLoanException', 'LoanUnavailable', 'SlippageTooHigh',
        'HealthFactorRisk', 'CircuitBreakerOpen', 'NetworkCongestion',
        'SimulatorFailure', 'ExecutionTimeout'
    ])
except ImportError:
    pass