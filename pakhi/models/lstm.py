"""LSTM forecaster with temporal attention and MC Dropout.

A PyTorch-based sequence model for weather time-series forecasting.
Architecture: 2-layer Bidirectional LSTM → Bahdanau attention → FC head.

Uncertainty is estimated via Monte-Carlo Dropout (multiple stochastic
forward passes at inference time).

All ``torch`` imports are *lazy* — the rest of Pakhi works fine without
PyTorch installed.
"""

from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence

import numpy as np

from pakhi.models.base import BaseModel, ForecastResult, StandardScaler, compute_metrics

if TYPE_CHECKING:
    import torch

__all__ = [
    "AttentionLayer",
    "LSTMForecaster",
    "WeatherDataset",
]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy torch imports
# ---------------------------------------------------------------------------


def _lazy_torch():
    try:
        import torch
        import torch.nn as nn

        return torch, nn
    except ImportError:
        raise ImportError(
            "PyTorch is required for LSTMForecaster. Install it with: pip install pakhi[ml]"
        ) from None


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------


class WeatherDataset:
    """Simple sliding-window dataset for PyTorch ``DataLoader``.

    Parameters
    ----------
    X : array of shape ``(n_samples, n_features)``
        Feature matrix (assumed to be already sequenced / lagged).
    y : array of shape ``(n_samples, horizon)``
        Target values.
    seq_len : int
        Length of look-back window.
    """

    def __init__(
        self,
        X: np.ndarray,
        y: np.ndarray,
        seq_len: int = 168,
    ) -> None:
        torch, _ = _lazy_torch()
        self.seq_len = seq_len
        X_arr = np.asarray(X, dtype=np.float32)
        if X_arr.shape[0] > 0 and seq_len > 1:
            pad = np.repeat(X_arr[0:1], seq_len - 1, axis=0)
            X_arr = np.vstack([pad, X_arr])
        self.X = torch.tensor(X_arr)
        self.y = torch.tensor(np.asarray(y, dtype=np.float32))
        self.n_samples = self.y.shape[0]

    def __len__(self) -> int:
        return self.n_samples

    def __getitem__(self, idx: int):
        start = idx
        end = idx + self.seq_len
        x_seq = self.X[start:end]  # (seq_len, features)
        y_val = self.y[idx]  # predict from aligned step
        return x_seq, y_val


# ---------------------------------------------------------------------------
# Attention layer
# ---------------------------------------------------------------------------


class AttentionLayer:
    """Bahdanau-style additive attention over LSTM hidden states.

    This is a thin wrapper; actual implementation lives inside
    ``_LSTMNet`` so it can use ``torch.nn`` modules directly.
    """

    pass  # Implemented as part of _LSTMNet below.


# ---------------------------------------------------------------------------
# Internal nn.Module
# ---------------------------------------------------------------------------


def _build_net():
    """Construct the ``_LSTMNet`` class (lazy torch dependency)."""
    torch, nn = _lazy_torch()

    class Attention(nn.Module):
        def __init__(self, hidden_dim: int) -> None:
            super().__init__()
            self.W = nn.Linear(hidden_dim, hidden_dim)
            self.v = nn.Linear(hidden_dim, 1, bias=False)

        def forward(self, lstm_out: torch.Tensor) -> torch.Tensor:
            """lstm_out: (batch, seq, hidden) → context: (batch, hidden)"""
            energy = torch.tanh(self.W(lstm_out))
            scores = self.v(energy).squeeze(-1)  # (batch, seq)
            weights = torch.softmax(scores, dim=1)  # (batch, seq)
            context = torch.bmm(weights.unsqueeze(1), lstm_out).squeeze(1)
            return context

    class _LSTMNet(nn.Module):
        def __init__(
            self,
            input_dim: int,
            hidden_dim: int,
            n_layers: int,
            dropout: float,
            forecast_horizon: int,
            mc_dropout: float,
        ) -> None:
            super().__init__()
            self.lstm = nn.LSTM(
                input_size=input_dim,
                hidden_size=hidden_dim,
                num_layers=n_layers,
                batch_first=True,
                bidirectional=True,
                dropout=dropout if n_layers > 1 else 0.0,
            )
            self.attention = Attention(hidden_dim * 2)
            self.forecast_dropout = nn.Dropout(mc_dropout)
            self.fc = nn.Linear(hidden_dim * 2, forecast_horizon)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            """x: (batch, seq_len, input_dim) → (batch, forecast_horizon)"""
            lstm_out, _ = self.lstm(x)
            context = self.attention(lstm_out)
            context = self.forecast_dropout(context)
            return self.fc(context)

    return _LSTMNet


# ---------------------------------------------------------------------------
# Pinball loss
# ---------------------------------------------------------------------------


def _pinball_loss(
    predictions: torch.Tensor, targets: torch.Tensor, quantiles: list[float]
) -> torch.Tensor:
    """Quantile pinball loss averaged over all requested quantiles."""
    torch, _ = _lazy_torch()
    losses = []
    for q in quantiles:
        errors = targets - predictions
        loss_q = torch.max(q * errors, (q - 1.0) * errors)
        mask = ~torch.isnan(loss_q)
        if mask.any():
            losses.append(loss_q[mask].mean())
        else:
            losses.append(torch.tensor(0.0, device=predictions.device, requires_grad=True))
    if not losses:
        return torch.tensor(0.0, device=predictions.device, requires_grad=True)
    return torch.stack(losses).mean()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class LSTMForecaster(BaseModel):
    """BiLSTM forecaster with Bahdanau attention and MC Dropout.

    Parameters
    ----------
    input_dim : int
        Number of input features per time step.
    hidden_dim : int
        Hidden units per LSTM layer (doubled for bidirectional).
    n_layers : int
        Number of LSTM layers.
    dropout : float
        Dropout applied between LSTM layers.
    mc_dropout : float
        Dropout rate used at inference for MC sampling.
    forecast_horizon : int
        Number of future time steps to predict.
    seq_len : int
        Look-back window length.
    quantiles : sequence of float
        Quantile levels for pinball loss.
    lr : float
        Initial learning rate.
    weight_decay : float
        L2 regularisation.
    patience : int
        Early stopping patience (epochs).
    max_epochs : int
        Maximum training epochs.
    batch_size : int
        Mini-batch size.
    mc_samples : int
        Number of forward passes for MC Dropout inference.
    device : ``"cpu"`` or ``"cuda"``
        Compute device.
    """

    def __init__(
        self,
        input_dim: int = 50,
        hidden_dim: int = 128,
        n_layers: int = 2,
        dropout: float = 0.2,
        mc_dropout: float = 0.2,
        forecast_horizon: int = 1,
        seq_len: int = 168,
        quantiles: Sequence[float] = (0.1, 0.25, 0.5, 0.75, 0.9),
        lr: float = 1e-3,
        weight_decay: float = 1e-5,
        patience: int = 10,
        max_epochs: int = 100,
        batch_size: int = 64,
        mc_samples: int = 50,
        device: str | None = None,
    ) -> None:
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        self.n_layers = n_layers
        self.dropout = dropout
        self.mc_dropout = mc_dropout
        self.forecast_horizon = forecast_horizon
        self.seq_len = seq_len
        self.quantiles = list(quantiles)
        self.lr = lr
        self.weight_decay = weight_decay
        self.patience = patience
        self.max_epochs = max_epochs
        self.batch_size = batch_size
        self.mc_samples = mc_samples
        self._device_request = device

        self._net: Any = None
        self._x_scaler = StandardScaler()
        self._y_scaler = StandardScaler()
        self._fitted = False

    @property
    def device(self) -> str:
        """Resolve compute device lazily (first accessed after torch is available)."""
        if self._device_request is not None:
            return self._device_request
        torch, _ = _lazy_torch()
        return "cuda" if torch.cuda.is_available() else "cpu"

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _init_net(self) -> None:
        _torch, _nn = _lazy_torch()
        NetCls = _build_net()
        self._net = NetCls(
            input_dim=self.input_dim,
            hidden_dim=self.hidden_dim,
            n_layers=self.n_layers,
            dropout=self.dropout,
            forecast_horizon=self.forecast_horizon,
            mc_dropout=self.mc_dropout,
        )
        try:
            self._net = self._net.to(self.device)
        except RuntimeError as e:
            if "cuDNN" in str(e) or "CUDA" in str(e):
                import logging

                logging.getLogger(__name__).warning(
                    f"CUDA initialization failed ({e}), falling back to CPU."
                )
                self._device_request = "cpu"
                self._net = self._net.to("cpu")
            else:
                raise

    def _make_loader(self, X: np.ndarray, y: np.ndarray):
        torch, _ = _lazy_torch()
        ds = WeatherDataset(X, y, seq_len=self.seq_len)
        return torch.utils.data.DataLoader(
            ds, batch_size=self.batch_size, shuffle=True, drop_last=False
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        X_val: np.ndarray | None = None,
        y_val: np.ndarray | None = None,
    ) -> LSTMForecaster:
        """Train the BiLSTM model.

        Parameters
        ----------
        X : array of shape ``(n_samples, n_features)``
        y : array of shape ``(n_samples,)`` or ``(n_samples, horizon)``
        X_val, y_val : array, optional
            Validation data for early stopping.
        """
        torch, _nn = _lazy_torch()

        X = np.asarray(X, dtype=np.float32)
        y = np.asarray(y, dtype=np.float32)
        if y.ndim == 1:
            y = y.reshape(-1, 1)

        # Scale
        X_scaled = self._x_scaler.fit_transform(X)
        y_scaled = self._y_scaler.fit_transform(y)

        self.input_dim = X_scaled.shape[1]
        self.forecast_horizon = y_scaled.shape[1]
        self._init_net()

        train_loader = self._make_loader(X_scaled, y_scaled)

        optimizer = torch.optim.AdamW(
            self._net.parameters(), lr=self.lr, weight_decay=self.weight_decay
        )
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            optimizer, mode="min", factor=0.5, patience=max(3, self.patience // 3)
        )

        best_val_loss = float("inf")
        best_state = None
        epochs_no_improve = 0

        for epoch in range(1, self.max_epochs + 1):
            # -- train --
            self._net.train()
            train_loss = 0.0
            n_batches = 0
            for xb, yb in train_loader:
                xb = xb.to(self.device)
                yb = yb.to(self.device)
                optimizer.zero_grad()
                pred = self._net(xb)
                loss = _pinball_loss(pred, yb, self.quantiles)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self._net.parameters(), max_norm=1.0)
                optimizer.step()
                train_loss += loss.item()
                n_batches += 1

            avg_train = train_loss / max(n_batches, 1)

            # -- val --
            if X_val is not None and y_val is not None:
                val_loss = self._eval_loss(X_val, y_val, torch)
                scheduler.step(val_loss)
                if val_loss < best_val_loss:
                    best_val_loss = val_loss
                    best_state = copy.deepcopy(self._net.state_dict())
                    epochs_no_improve = 0
                else:
                    epochs_no_improve += 1
                if epochs_no_improve >= self.patience:
                    logger.info("Early stopping at epoch %d", epoch)
                    break
                if epoch % 10 == 0:
                    logger.info(
                        "Epoch %d/%d  train_loss=%.4f  val_loss=%.4f",
                        epoch,
                        self.max_epochs,
                        avg_train,
                        val_loss,
                    )
            else:
                if epoch % 10 == 0:
                    logger.info("Epoch %d/%d  train_loss=%.4f", epoch, self.max_epochs, avg_train)

        if best_state is not None:
            self._net.load_state_dict(best_state)

        self._fitted = True
        return self

    def _eval_loss(self, X_val: np.ndarray, y_val: np.ndarray, torch: Any) -> float:
        """Compute average pinball loss on a validation set."""
        self._net.eval()
        Xv = self._x_scaler.transform(np.asarray(X_val, dtype=np.float32))
        yv = self._y_scaler.transform(
            np.asarray(y_val, dtype=np.float32).reshape(-1, 1)
            if np.asarray(y_val).ndim == 1
            else np.asarray(y_val, dtype=np.float32)
        )
        loader = self._make_loader(Xv, yv)
        total = 0.0
        n = 0
        with torch.no_grad():
            for xb, yb in loader:
                xb, yb = xb.to(self.device), yb.to(self.device)
                pred = self._net(xb)
                total += _pinball_loss(pred, yb, self.quantiles).item()
                n += 1
        self._net.train()
        return total / max(n, 1)

    def predict(self, X: np.ndarray) -> ForecastResult:
        """Deterministic forecast (MC Dropout disabled)."""
        if not self._fitted:
            raise RuntimeError("Call fit() before predict().")
        torch, _ = _lazy_torch()
        X = np.asarray(X, dtype=np.float32)
        X_scaled = self._x_scaler.transform(X)

        self._net.eval()
        loader = self._make_loader(X_scaled, np.zeros((X_scaled.shape[0], self.forecast_horizon)))
        preds: list[np.ndarray] = []
        with torch.no_grad():
            for xb, _ in loader:
                xb = xb.to(self.device)
                out = self._net(xb)
                preds.append(out.cpu().numpy())

        raw = np.concatenate(preds, axis=0) if preds else np.zeros((0, self.forecast_horizon))
        det = self._y_scaler.inverse_transform(raw)
        return ForecastResult(
            deterministic=det,
            quantiles={},
            skill_scores={},
            metadata={"model": "lstm_bilstm_attention"},
        )

    def predict_proba(
        self,
        X: np.ndarray,
        quantiles: Sequence[float] = (0.1, 0.25, 0.5, 0.75, 0.9),
    ) -> ForecastResult:
        """Probabilistic forecast via MC Dropout.

        Performs ``self.mc_samples`` stochastic forward passes and
        computes quantiles from the predictive distribution.
        """
        if not self._fitted:
            raise RuntimeError("Call fit() before predict().")
        torch, _ = _lazy_torch()
        X = np.asarray(X, dtype=np.float32)
        X_scaled = self._x_scaler.transform(X)

        all_preds = []
        # Enable dropout at inference by switching to train mode.
        self._net.train()
        with torch.no_grad():
            for _ in range(self.mc_samples):
                loader = self._make_loader(
                    X_scaled, np.zeros((X_scaled.shape[0], self.forecast_horizon))
                )
                preds_i: list[np.ndarray] = []
                for xb, _ in loader:
                    xb = xb.to(self.device)
                    out = self._net(xb)
                    preds_i.append(out.cpu().numpy())
                if preds_i:
                    all_preds.append(np.concatenate(preds_i, axis=0))

        self._net.eval()

        if not all_preds:
            det = np.zeros((0, self.forecast_horizon))
            quantile_dict: dict[str, np.ndarray] = {}
        else:
            stack = np.stack(all_preds, axis=0)  # (mc_samples, n, horizon)
            det = self._y_scaler.inverse_transform(np.mean(stack, axis=0))
            quantile_dict = {}
            for q in quantiles:
                label = f"q{q}"
                raw_q = np.quantile(stack, q, axis=0)
                quantile_dict[label] = self._y_scaler.inverse_transform(raw_q)

        return ForecastResult(
            deterministic=det,
            quantiles=quantile_dict,
            skill_scores={},
            metadata={"model": "lstm_bilstm_attention", "mc_samples": self.mc_samples},
        )

    def score(
        self,
        X: np.ndarray,
        y: np.ndarray,
        metrics: Sequence[str] = ("rmse", "mae", "acc"),
    ) -> dict[str, float]:
        result = self.predict(X)
        return compute_metrics(y, result.deterministic, metrics=metrics)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str | Path) -> None:
        """Save model state dict and scalers to disk."""
        torch, _ = _lazy_torch()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(
            {
                "net_state": self._net.state_dict() if self._net else None,
                "x_scaler_mean": self._x_scaler.mean_,
                "x_scaler_std": self._x_scaler.std_,
                "y_scaler_mean": self._y_scaler.mean_,
                "y_scaler_std": self._y_scaler.std_,
                "config": {
                    "input_dim": self.input_dim,
                    "hidden_dim": self.hidden_dim,
                    "n_layers": self.n_layers,
                    "dropout": self.dropout,
                    "mc_dropout": self.mc_dropout,
                    "forecast_horizon": self.forecast_horizon,
                    "seq_len": self.seq_len,
                    "quantiles": self.quantiles,
                },
            },
            path,
        )
        logger.info("Model saved to %s", path)

    def load(self, path: str | Path) -> LSTMForecaster:
        """Load model state dict and scalers from disk."""
        torch, _ = _lazy_torch()
        ckpt = torch.load(path, map_location=self.device, weights_only=False)
        cfg = ckpt["config"]
        for k, v in cfg.items():
            setattr(self, k, v)
        self._x_scaler.mean_ = ckpt["x_scaler_mean"]
        self._x_scaler.std_ = ckpt["x_scaler_std"]
        self._y_scaler.mean_ = ckpt["y_scaler_mean"]
        self._y_scaler.std_ = ckpt["y_scaler_std"]
        if ckpt["net_state"] is not None:
            self._init_net()
            self._net.load_state_dict(ckpt["net_state"])
        self._fitted = True
        logger.info("Model loaded from %s", path)
        return self

    def export_onnx(self, path: str | Path) -> None:
        """Export the network to ONNX format for fast inference."""
        torch, _ = _lazy_torch()
        if self._net is None:
            raise RuntimeError("Model not fitted.")
        self._net.eval()
        dummy = torch.randn(1, self.seq_len, self.input_dim).to(self.device)
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.onnx.export(
            self._net,
            dummy,
            str(path),
            input_names=["input"],
            output_names=["output"],
            dynamic_axes={"input": {0: "batch"}, "output": {0: "batch"}},
        )
        logger.info("ONNX model exported to %s", path)

    def __repr__(self) -> str:
        status = "fitted" if self._fitted else "not fitted"
        dev = self._device_request or "auto"
        return (
            f"LSTMForecaster(input_dim={self.input_dim}, "
            f"hidden_dim={self.hidden_dim}, n_layers={self.n_layers}, "
            f"device='{dev}', status={status})"
        )
