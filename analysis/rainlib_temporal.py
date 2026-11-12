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

    Two quantities are computed with different, well-defined units:

    * **Precision is alert-based.** tp counts *prediction* timesteps that
      fall inside a tolerance window around some rain episode; fp counts
      prediction timesteps that fall outside every window.  So
      precision = tp / (tp + fp) is the fraction of raised alerts that
      actually landed near rain - "of the alerts we raised, how many were
      correct".  (Previously tp counted rainy timesteps while fp counted
      prediction timesteps, which inflated precision inside long rain
      spells - see #455.)

    * **Recall is episode-based.** Consecutive rainy timesteps are grouped
      into *episodes* (rain events).  An episode is *detected* when at least
      one prediction falls inside [start - lead_hours, end + lag_hours].
      recall = detected_episodes / total_episodes is the fraction of rain
      events the model caught, regardless of how many alerts each triggered.

    A prediction is considered a True Positive if:
    - The model predicts rain (pred >= threshold) within the window
      [episode_start - lead_hours, episode_end + lag_hours] around a
      rain episode.

    This accounts for the practical use case where predicting rain 
    3 hours early is still useful (and correct), not a false positive.
    
    Args:
        pred: Series of model predictions (e.g., humidity %)
        truth: Series of ground truth (1=rain, 0=no rain, NaN=unknown)
        threshold: Prediction threshold for classifying as "rain"
        lead_hours: Hours before an episode start that a prediction still counts as TP
        lag_hours: Hours after an episode end that a prediction still counts as TP
        drop_unknown: If True, drop NaN truth rows; if False, treat as no-rain
        end_lead_hours: (Future) Hours before rain end to detect end (not used yet)
        end_lag_hours: (Future) Hours after rain end tolerance (not used yet)
    
    Returns:
        Dict with: threshold, tp, fp, tn, fn, precision, recall, f1, f2, n,
        lead_hours, lag_hours
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
    
    # Group consecutive rainy timesteps into episodes: (start, end) inclusive.
    rain_flags = (y == 1).to_numpy()
    episodes = []  # list of (start_idx, end_idx)
    i = 0
    n = len(rain_flags)
    while i < n:
        if rain_flags[i]:
            j = i
            while j + 1 < n and rain_flags[j + 1]:
                j += 1
            episodes.append((df.index[i], df.index[j]))
            i = j + 1
        else:
            i += 1
    
    # Match predictions to episodes and detect episodes.  A prediction is
    # "matched" if it falls inside the window of at least one episode; an
    # episode is "detected" if at least one prediction falls in its window.
    matched_predictions = set()
    detected_episodes = 0
    
    for start, end in episodes:
        window_start = start - pd.Timedelta(hours=lead_hours)
        window_end = end + pd.Timedelta(hours=lag_hours)
        
        window_mask = (df.index >= window_start) & (df.index <= window_end)
        window_preds = df.index[window_mask & (yhat == 1)]
        
        if len(window_preds) > 0:
            detected_episodes += 1
            for pred_idx in window_preds:
                matched_predictions.add(pred_idx)
    
    all_predictions = set(df.index[yhat == 1])
    
    # TP/FP are alert (prediction) counts; FN is a missed-episode count.
    tp = len(matched_predictions)
    fp = len(all_predictions - matched_predictions)
    fn = len(episodes) - detected_episodes
    
    # True negatives in timesteps: no-rain timesteps minus false-positive
    # timesteps (every FP is itself a no-rain timestep).
    no_rain_timesteps = int((y == 0).sum())
    tn = no_rain_timesteps - fp
    
    # Precision is alert-based; recall is episode-based.
    precision = tp / (tp + fp) if (tp + fp) > 0 else float("nan")
    recall = detected_episodes / len(episodes) if len(episodes) > 0 else float("nan")
    
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
    
    # F-beta = (1 + b^2) * precision * recall / (b^2 * precision + recall)
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
