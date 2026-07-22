"""Temporal metrics for rain prediction with lead/lag windows.

This module provides confusion matrix calculation that accounts for 
prediction windows: a model can predict rain up to N hours before 
(lead time) or M hours after (lag time) the actual rain event and 
still be considered correct.
"""

import pandas as pd
import numpy as np
from typing import Optional


def confusion_with_windows(
    pred: pd.Series,
    truth: pd.Series,
    threshold: float = 50.0,
    lead_hours: int = 3,
    lag_hours: int = 1,
    drop_unknown: bool = True,
    end_lead_hours: Optional[int] = None,
    end_lag_hours: Optional[int] = None,
) -> dict:
    """Confusion matrix with temporal windows for prediction tolerance.
    
    A prediction is considered a True Positive if:
    - The model predicts rain (pred >= threshold) within a window around 
      an actual rain event
    - Window: [rain_time - lead_hours, rain_time + lag_hours]
    
    This accounts for the practical use case where predicting rain 
    3 hours early is still useful (and correct), not a false positive.
    
    Args:
        pred: Series of model predictions (e.g., humidity %)
        truth: Series of ground truth (1=rain, 0=no rain, NaN=unknown)
        threshold: Prediction threshold for classifying as "rain"
        lead_hours: Hours before rain that a prediction still counts as TP
        lag_hours: Hours after rain start that a prediction still counts as TP
        drop_unknown: If True, drop NaN truth rows; if False, treat as no-rain
        end_lead_hours: (Future) Hours before rain end to detect end (not used yet)
        end_lag_hours: (Future) Hours after rain end tolerance (not used yet)
    
    Returns:
        Dict with: threshold, tp, fp, tn, fn, precision, recall, f1, f2, n
    """
    df = pd.DataFrame({"pred": pred, "truth": truth})
    
    if drop_unknown:
        df = df.dropna()
    else:
        df = df.fillna({"truth": 0})
    
    if len(df) == 0:
        return {
            "threshold": threshold,
            "tp": 0, "fp": 0, "tn": 0, "fn": 0,
            "precision": float("nan"),
            "recall": float("nan"),
            "f1": float("nan"),
            "f2": float("nan"),
            "n": 0,
        }
    
    # Binary predictions and truth
    yhat = (df["pred"] >= threshold).astype(int)
    y = df["truth"].astype(int)
    
    # Find rain events (truth=1)
    rain_indices = df.index[y == 1]
    
    # Track which predictions and truth hours we've matched
    matched_predictions = set()
    matched_truth = set()
    
    # For each rain event, look for predictions in the window
    for rain_idx in rain_indices:
        # Define the window: [rain - lead, rain + lag]
        window_start = rain_idx - pd.Timedelta(hours=lead_hours)
        window_end = rain_idx + pd.Timedelta(hours=lag_hours)
        
        # Find predictions in this window
        window_mask = (df.index >= window_start) & (df.index <= window_end)
        window_preds = df.index[window_mask & (yhat == 1)]
        
        # If we found at least one prediction in the window, it's a TP
        if len(window_preds) > 0:
            matched_truth.add(rain_idx)
            # Mark all predictions in this window as matched (to avoid counting as FP)
            for pred_idx in window_preds:
                matched_predictions.add(pred_idx)
    
    # Calculate confusion matrix components
    tp = len(matched_truth)  # Rain events we successfully predicted
    fn = len(rain_indices) - tp  # Rain events we missed
    
    # False positives: predictions not matched to any rain event
    all_predictions = set(df.index[yhat == 1])
    fp = len(all_predictions - matched_predictions)
    
    # True negatives: hours with no rain and no prediction
    # (all other hours that aren't TP, FP, or FN)
    tn = len(df) - tp - fp - fn
    
    # Calculate metrics
    precision = tp / (tp + fp) if (tp + fp) > 0 else float("nan")
    recall = tp / (tp + fn) if (tp + fn) > 0 else float("nan")
    
    if precision != precision or recall != recall:  # NaN check
        f1 = float("nan")
        f2 = float("nan")
    elif (precision + recall) == 0:
        f1 = 0.0
        f2 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)
        # F2 score: weights recall 4x more than precision
        f2 = 5 * precision * recall / (4 * precision + recall)
    
    return {
        "threshold": threshold,
        "tp": int(tp),
        "fp": int(fp),
        "tn": int(tn),
        "fn": int(fn),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "f2": f2,
        "n": len(df),
        "lead_hours": lead_hours,
        "lag_hours": lag_hours,
    }


def sweep_threshold_temporal(
    pred: pd.Series,
    truth: pd.Series,
    lead_hours: int = 3,
    lag_hours: int = 1,
    thresholds=range(5, 100, 5),
) -> pd.DataFrame:
    """Compute temporal metrics across a range of thresholds.
    
    Args:
        pred: Series of model predictions
        truth: Series of ground truth
        lead_hours: Prediction window before rain (hours)
        lag_hours: Prediction window after rain start (hours)
        thresholds: Threshold values to sweep
    
    Returns:
        DataFrame indexed by threshold with metrics columns
    """
    results = []
    for t in thresholds:
        metrics = confusion_with_windows(
            pred, truth, threshold=t,
            lead_hours=lead_hours, lag_hours=lag_hours
        )
        results.append(metrics)
    
    return pd.DataFrame(results).set_index("threshold")


def recommend_threshold_temporal(
    pred: pd.Series,
    truth: pd.Series,
    beta: float = 2.0,
    lead_hours: int = 3,
    lag_hours: int = 1,
    min_precision: float = 0.0,
    thresholds=range(5, 100, 5),
) -> dict:
    """Recommend threshold using temporal metrics and F-beta optimization.
    
    Args:
        pred: Series of model predictions
        truth: Series of ground truth
        beta: F-beta parameter (2.0 = recall weighted 4x more than precision)
        lead_hours: Prediction window before rain
        lag_hours: Prediction window after rain start
        min_precision: Minimum acceptable precision (0-1)
        thresholds: Threshold values to consider
    
    Returns:
        Dict with: best_threshold, f_beta, precision, recall, f1, f2
    """
    sweep = sweep_threshold_temporal(
        pred, truth, lead_hours=lead_hours, lag_hours=lag_hours,
        thresholds=thresholds
    )
    
    # Filter by minimum precision
    candidates = sweep[sweep["precision"] >= min_precision]
    
    if len(candidates) == 0:
        return {
            "best_threshold": float("nan"),
            "f_beta": float("nan"),
            "precision": float("nan"),
            "recall": float("nan"),
            "f1": float("nan"),
            "f2": float("nan"),
        }
    
    # Calculate F-beta for each candidate
    p = candidates["precision"]
    r = candidates["recall"]
    b2 = beta * beta
    
    # F-beta = (1 + β²) · precision · recall / (β² · precision + recall)
    denom = (b2 * p) + r
    fbeta = (1 + b2) * p * r / denom
    fbeta = fbeta.fillna(0)  # Handle division by zero
    
    # Pick the threshold with highest F-beta
    best_idx = fbeta.idxmax()
    best_row = candidates.loc[best_idx]
    
    return {
        "best_threshold": best_idx,
        "f_beta": fbeta.loc[best_idx],
        "precision": best_row["precision"],
        "recall": best_row["recall"],
        "f1": best_row["f1"],
        "f2": best_row["f2"],
    }
