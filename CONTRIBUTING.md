# Contributing to Crypto AI Bot

Thank you for your interest in contributing to the Crypto AI Bot project! This document provides guidelines for contributing to the project.

## Getting Started

### Prerequisites

- Python 3.10.18
- Git
- Docker (optional, for testing)

### Development Setup

1. **Fork and clone the repository**
   ```bash
   git clone https://github.com/your-username/crypto-ai-bot.git
   cd crypto-ai-bot
   ```

2. **Create a conda environment**
   ```bash
   conda create -n crypto-bot python=3.10
   conda activate crypto-bot
   ```

3. **Install dependencies**
   ```bash
   pip install -e .
   pip install -r requirements.txt
   ```

4. **Run tests**
   ```bash
   pytest -q
   ```

## Development Guidelines

### Code Style

- Follow PEP 8 style guidelines
- Use type hints for all function parameters and return values
- Write docstrings for all public functions and classes
- Use meaningful variable and function names

### Testing

- Write tests for all new functionality
- Ensure all tests pass before submitting PR
- Aim for high test coverage
- Use descriptive test names

### Commit Messages

Use clear, descriptive commit messages:

```
feat: add new trading strategy
fix: resolve Redis connection timeout
docs: update API documentation
test: add unit tests for risk manager
```

### Pull Request Process

1. **Create a feature branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes**
   - Write code following project guidelines
   - Add tests for new functionality
   - Update documentation if needed

3. **Run quality checks**
   ```bash
   ruff check .
   mypy .
   pytest -q
   ```

4. **Submit a pull request**
   - Provide a clear description of changes
   - Reference any related issues
   - Ensure CI passes

## Project Structure

```
crypto-ai-bot/
├── agents/           # Trading agents and strategies
├── ai_engine/        # ML and AI components
├── config/           # Configuration management
├── monitoring/       # Monitoring and metrics
├── tests/            # Test suite
├── scripts/          # Utility scripts
└── docs/             # Documentation
```

## Areas for Contribution

### High Priority
- Additional trading strategies
- Performance optimizations
- Test coverage improvements
- Documentation enhancements

### Medium Priority
- New data sources
- Advanced risk management features
- UI/UX improvements
- Integration examples

### Low Priority
- Code refactoring
- Style improvements
- Minor bug fixes

## Questions?

- **General questions**: Open a GitHub issue
- **Security concerns**: Email security@crypto-ai-bot.com
- **Development help**: Check existing issues or start a discussion

## Code of Conduct

Please be respectful and constructive in all interactions. We welcome contributors from all backgrounds and experience levels.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
