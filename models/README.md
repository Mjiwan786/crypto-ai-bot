# ML Model Artifacts

Model `.joblib` files are NOT committed to git.
They are trained locally and deployed via `git push + fly deploy`.

## Current Models

| Model | File | Purpose |
|-------|------|---------|
| Signal Scorer | `signal_scorer.joblib` | XGBoost binary classifier - predicts trade profitability |

## Training

```bash
conda activate crypto-bot
python -m trainer.train --synthetic --validate
```

## Versioning

Model version is embedded in the `.joblib` metadata.
Check with: `python -c "import joblib; m=joblib.load('models/signal_scorer.joblib'); print(m['training_metadata'])"`
