import pandas as pd
from agents.ml.model_trainer import SizingModel, FlashLoanModel
from agents.ml.feature_engineer import FEATURE_ORDER

def test_model_save_load_and_predict_consistency(tmp_path):
    X = pd.DataFrame([[0]*len(FEATURE_ORDER)], columns=FEATURE_ORDER)
    y_ret = pd.Series([0.01])
    y_risk = pd.Series([0.02])
    y_cls = pd.Series([1])
    sm = SizingModel(); sm.train(X, y_ret, y_risk)
    fm = FlashLoanModel(); fm.train(X, y_cls)
    from agents.ml.predictor import Predictor
    pr = Predictor()
    row = {k:0 for k in FEATURE_ORDER}
    out1 = pr.score_trade(row); out2 = pr.score_flash_loan(row)
    assert set(out1.keys()) == {"exp_ret","risk","conf"}
    assert set(out2.keys()) >= {"score","exp_profit","conf"}
